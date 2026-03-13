"""
OpenClaw Voice Server

WebSocket server that handles:
- Audio input from browser
- Speech-to-Text via Whisper
- AI backend communication
- Text-to-Speech via ElevenLabs
- Audio streaming back to browser
"""

import asyncio
import base64
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from starlette.responses import StreamingResponse

from .stt import WhisperSTT
from .tts import ChatterboxTTS
from .backend import AIBackend
from .vad import VoiceActivityDetector
from .auth import token_manager, load_keys_from_env, APIKey
from .text_utils import clean_for_speech
from .certs import ensure_certs, generate_mobileconfig, get_lan_ips
from .desktop import DesktopStreamer
from .desktop_skills import list_skills, get_skill, get_skills_prompt_section
from . import memory as mem_store

# 工作流引擎
try:
    from .workflow import get_engine as get_wf_engine, store as wf_store
    from .workflow.nodes import get_available_nodes as wf_available_nodes
    _WORKFLOW_AVAILABLE = True
except ImportError:
    _WORKFLOW_AVAILABLE = False

# 微信自动回复（可选，仅 Windows）
_wechat_monitor = None
_wechat_engine = None
_wechat_adapter = None  # v2.0 三轨融合适配器
try:
    if sys.platform == "win32":
        from .wechat_autoreply import (
            init_wechat_autoreply, init_wechat_v2,
            get_monitor, get_engine, get_adapter,
        )
        _wechat_autoreply_available = True
    else:
        _wechat_autoreply_available = False
except ImportError:
    _wechat_autoreply_available = False

# IM 桥接（可选）
try:
    import sys as _sys
    from pathlib import Path as _Path
    _ROOT = str(_Path(__file__).parent.parent.parent)
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)
    from src.bridge.manager import get_bridge_manager as _get_bridge_mgr
    _bridge_manager = _get_bridge_mgr()
    _IM_BRIDGE_AVAILABLE = True
except Exception:
    _bridge_manager = None
    _IM_BRIDGE_AVAILABLE = False


class Settings(BaseSettings):
    """Server configuration."""
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8765
    
    # Auth
    require_auth: bool = False  # Set True for production
    master_key: Optional[str] = None  # Admin key for full access
    
    # STT
    stt_model: str = "base"  # tiny, base, small, medium, large-v3-turbo
    stt_device: str = "auto"  # auto, cpu, cuda, mps
    stt_language: Optional[str] = "zh"  # zh=中文, en=英文, None=自动检测(易出韩文)
    
    # TTS
    tts_model: str = "chatterbox"
    tts_voice: Optional[str] = None  # Path to voice sample for cloning
    
    # AI Backend
    backend_type: str = "openai"  # openai, openclaw, custom
    backend_url: str = "https://api.openai.com/v1"
    backend_model: str = "gpt-4o-mini"
    openai_api_key: Optional[str] = None
    
    # OpenClaw Gateway (auto-detected from OPENCLAW_GATEWAY_URL + TOKEN)
    openclaw_gateway_url: Optional[str] = None
    openclaw_gateway_token: Optional[str] = None
    
    # HTTP port for QR-scan quick chat (no cert needed)
    http_port: int = 0  # 0 = port+1 (auto), set OPENCLAW_HTTP_PORT to disable with -1

    # Audio
    sample_rate: int = 16000
    
    class Config:
        env_prefix = "OPENCLAW_"
        env_file = ".env"
        extra = "ignore"


settings = Settings()
app = FastAPI(title="OpenClaw Voice", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """API 速率限制中间件"""
    path = request.url.path
    if path.startswith("/api/"):
        try:
            from .rate_limiter import check_rate_limit
            allowed, info = check_rate_limit(request)
            if not allowed:
                return Response(
                    content=json.dumps({"error": "Rate limit exceeded", "retry_after": info.get("reset", 60)}),
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "Retry-After": str(int(info.get("reset", 60))),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Limit": str(info.get("limit", 120)),
                    },
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining"] = str(info.get("remaining", 0))
            response.headers["X-RateLimit-Limit"] = str(info.get("limit", 120))
            return response
        except Exception:
            pass
    return await call_next(request)


# Global instances (initialized on startup)
stt: Optional[WhisperSTT] = None
tts: Optional[ChatterboxTTS] = None
backend: Optional[AIBackend] = None
vad: Optional[VoiceActivityDetector] = None


@app.on_event("startup")
async def startup():
    """Initialize models on server start."""
    global stt, tts, backend, vad
    
    logger.info("Initializing OpenClaw Voice server...")
    
    # Load API keys
    load_keys_from_env()
    if settings.require_auth:
        logger.info("🔐 Authentication ENABLED")
    else:
        logger.warning("⚠️ Authentication DISABLED (dev mode)")
    
    # Initialize STT (language=None for auto-detection, supports Chinese/English/etc.)
    logger.info(f"Loading STT model: {settings.stt_model}")
    stt = WhisperSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        language=settings.stt_language,
    )
    logger.info(f"STT 语言: {settings.stt_language or '自动检测'}")
    
    # Initialize TTS
    logger.info(f"Loading TTS model: {settings.tts_model}")
    tts = ChatterboxTTS(
        voice_sample=settings.tts_voice,
    )
    
    # Initialize AI backend
    # Auto-detect OpenClaw gateway
    gateway_url = settings.openclaw_gateway_url or os.getenv("OPENCLAW_GATEWAY_URL")
    gateway_token = settings.openclaw_gateway_token or os.getenv("OPENCLAW_GATEWAY_TOKEN")
    
    # 智谱视觉模型配置（可选）
    zhipu_vision_key = os.getenv("ZHIPU_VISION_API_KEY") or os.getenv("ZHIPU_API_KEY")
    zhipu_vision_model = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
    if zhipu_vision_key:
        logger.info(f"🖼️ 智谱视觉模型已配置: {zhipu_vision_model}")
    else:
        logger.info("ℹ️ 未配置 ZHIPU_VISION_API_KEY，视觉请求将降级到主模型")

    if gateway_url and gateway_token:
        # Use OpenClaw gateway (connects to Aria!)
        logger.info(f"🦞 Connecting to OpenClaw gateway: {gateway_url}")
        backend = AIBackend(
            backend_type="openai",  # Gateway speaks OpenAI API
            url=f"{gateway_url}/v1",
            model="openclaw:voice",  # Maps to 'voice' agent in config
            api_key=gateway_token,
            system_prompt=(
                "This conversation is happening via real-time voice chat. "
                "Keep responses concise and conversational — a few sentences "
                "at most unless the topic genuinely needs depth. "
                "No markdown, bullet points, code blocks, or special formatting."
            ),
            vision_api_key=zhipu_vision_key,
            vision_model=zhipu_vision_model,
        )
    else:
        # Fallback to direct OpenAI
        logger.info(f"Connecting to backend: {settings.backend_type}")
        backend = AIBackend(
            backend_type=settings.backend_type,
            url=settings.backend_url,
            model=settings.backend_model,
            api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY"),
            vision_api_key=zhipu_vision_key,
            vision_model=zhipu_vision_model,
        )
    
    # Initialize VAD
    logger.info("Loading VAD model")
    vad = VoiceActivityDetector()

    # Store backend reference for lazy API access
    app.state.ai_backend = backend

    # Initialize Workflow Engine
    if _WORKFLOW_AVAILABLE:
        try:
            wf_engine = get_wf_engine()
            await wf_engine.start(
                ai_backend=backend,
                tts_engine=tts,
            )
            logger.info("⚡ 工作流引擎已启动")
        except Exception as e:
            logger.warning(f"工作流引擎启动失败: {e}")

    # Ollama 自动检测
    try:
        from .ollama_bridge import OllamaBridge
        _ollama = OllamaBridge()
        health = await _ollama.check_health()
        if health.available:
            from src.router.config import RouterConfig
            cfg = RouterConfig()
            _ollama.auto_enable_in_router(cfg)
            models = [m.name for m in health.models]
            logger.info(f"🦙 Ollama 已检测 (v{health.version}) 模型: {models}")
        else:
            logger.info("ℹ️ Ollama 未运行，跳过本地模型")
        app.state.ollama_bridge = _ollama
    except Exception as e:
        logger.debug(f"Ollama 检测跳过: {e}")
        app.state.ollama_bridge = None

    # 启动账号健康心跳定时器
    async def _health_heartbeat_loop():
        import asyncio
        while True:
            try:
                from .wechat.account_health import get_health_monitor
                await get_health_monitor().check_all_heartbeats()
            except Exception:
                pass
            await asyncio.sleep(60)
    asyncio.create_task(_health_heartbeat_loop())

    # 异常检测定时器（每小时采样+检查）
    async def _anomaly_check_loop():
        import asyncio
        while True:
            await asyncio.sleep(3600)
            try:
                from .anomaly_detector import get_detector
                from .wechat.account_health import get_health_monitor
                detector = get_detector()
                for m in get_health_monitor().get_all_status():
                    detector.record_hourly(m["account_id"],
                        send_rate=m["send_rate_per_hour"],
                        error_rate=m["error_rate_per_hour"])
                    detector.check(m["account_id"],
                        current_send=m["send_rate_per_hour"],
                        current_error=m["error_rate_per_hour"])
            except Exception:
                pass
    asyncio.create_task(_anomaly_check_loop())

    # 日报定时器（每天 18:00 自动生成）
    async def _daily_report_loop():
        import asyncio
        from datetime import datetime
        while True:
            now = datetime.now()
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if now >= target:
                from datetime import timedelta
                target += timedelta(days=1)
            wait_secs = (target - now).total_seconds()
            await asyncio.sleep(wait_secs)
            try:
                from .daily_report import generate_and_cache
                ai_call = backend.chat_simple if backend else None
                await generate_and_cache(ai_call)
            except Exception:
                pass
    asyncio.create_task(_daily_report_loop())

    logger.info("✅ OpenClaw Voice server ready!")


@app.on_event("shutdown")
async def shutdown():
    if _WORKFLOW_AVAILABLE:
        try:
            await get_wf_engine().stop()
        except Exception:
            pass


@app.get("/app")
@app.get("/app/")
async def app_page():
    """Serve the integrated AI assistant page."""
    return FileResponse("src/client/app.html")


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    """iOS certificate setup & instructions page."""
    return FileResponse("src/client/setup.html")


@app.get("/ca.crt")
async def serve_ca_cert():
    """Download the CA certificate (DER format for iOS)."""
    ca_path = Path("certs/ca.crt")
    if not ca_path.exists():
        return Response(content="Certificates not generated. Restart server with HTTPS.",
                        status_code=404)
    return FileResponse(
        str(ca_path),
        media_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": "attachment; filename=OpenClaw-CA.crt"},
    )


@app.get("/ca.mobileconfig")
async def serve_mobileconfig():
    """Download iOS configuration profile with the CA certificate."""
    ca_path = Path("certs/ca.crt")
    if not ca_path.exists():
        return Response(content="Certificates not generated. Restart server with HTTPS.",
                        status_code=404)
    profile_xml = generate_mobileconfig(str(ca_path))
    return Response(
        content=profile_xml,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": "attachment; filename=OpenClaw-CA.mobileconfig"},
    )


@app.post("/api/tts")
async def tts_api(request: Request):
    """Convert text to speech audio and return as streaming response."""
    body = await request.json()
    text = body.get("text", "").strip()
    if not text or not tts:
        return Response(content="", status_code=400)

    async def audio_stream():
        async for chunk in tts.synthesize_stream(text):
            b64 = base64.b64encode(chunk).decode()
            yield f"data: {json.dumps({'audio': b64, 'format': tts.audio_format})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        audio_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/voice")
async def voice_http(request: Request):
    """HTTP-based voice: receive audio → STT → AI → TTS, all via SSE.
    Fallback for when WebSocket (wss://) fails on iOS with self-signed certs."""
    body = await request.json()
    audio_b64 = body.get("audio", "")
    image_b64: Optional[str] = body.get("image")  # optional camera frame

    if not audio_b64:
        return Response(content=json.dumps({"error": "No audio data"}), status_code=400)

    audio_bytes = base64.b64decode(audio_b64)
    audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
    logger.info(f"HTTP voice: {len(audio_np)} samples, max={np.abs(audio_np).max():.4f}")

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

    async def voice_stream():
        # 1. STT
        transcript = await stt.transcribe(audio_np)
        yield f"data: {json.dumps({'type': 'transcript', 'text': transcript})}\n\n"
        if image_b64:
            yield f"data: {json.dumps({'type': 'vision_used', 'value': True})}\n\n"

        if not transcript.strip():
            yield f"data: {json.dumps({'type': 'done', 'empty': True})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # 2. AI response (streaming)
        full_response = ""
        sentence_buffer = ""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                sys_prompt = "你是 OpenClaw AI 助手，用中文简洁回答。"
                if image_b64:
                    sys_prompt += "\n\n用户发送了摄像头画面，请结合图像内容来回答，说明你看到了什么。"
                user_content = transcript if not image_b64 else [
                    {"type": "text", "text": transcript},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "low",
                    }},
                ]
                async with client.stream(
                    "POST",
                    f"{gateway_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "model": "deepseek-chat",
                        "stream": True,
                    },
                    headers={
                        "Authorization": f"Bearer {gateway_token}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                            delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                full_response += delta
                                sentence_buffer += delta
                                yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"

                                # TTS sentence by sentence
                                seps = ['。', '！', '？', '；', '.\n', '!\n', '?\n', '\n\n']
                                while any(sep in sentence_buffer for sep in seps):
                                    earliest = len(sentence_buffer)
                                    for sep in seps:
                                        idx = sentence_buffer.find(sep)
                                        if idx != -1 and idx < earliest:
                                            earliest = idx + len(sep)
                                    if earliest < len(sentence_buffer):
                                        sentence = sentence_buffer[:earliest].strip()
                                        sentence_buffer = sentence_buffer[earliest:]
                                        speech = clean_for_speech(sentence)
                                        if speech:
                                            async for audio_chunk in tts.synthesize_stream(speech):
                                                yield f"data: {json.dumps({'type': 'audio', 'data': base64.b64encode(audio_chunk).decode(), 'format': tts.audio_format})}\n\n"
                        except json.JSONDecodeError:
                            continue

            # TTS remaining text
            remaining = clean_for_speech(sentence_buffer.strip())
            if remaining:
                async for audio_chunk in tts.synthesize_stream(remaining):
                    yield f"data: {json.dumps({'type': 'audio', 'data': base64.b64encode(audio_chunk).decode(), 'format': tts.audio_format})}\n\n"

        except Exception as e:
            logger.error(f"HTTP voice AI error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'text': full_response})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        voice_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
async def chat_completions_proxy(request: Request):
    """Proxy chat completions to OpenClaw Gateway with SSE streaming."""
    body = await request.json()

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

    if "stream" not in body:
        body["stream"] = True

    async def event_stream():
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{gateway_url}/v1/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {gateway_token}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield f"{line}\n\n"
            except Exception as e:
                logger.error(f"Chat proxy error: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class VisionRequest(BaseModel):
    text: str
    image_b64: Optional[str] = None

@app.post("/api/vision")
async def vision_chat(req: VisionRequest):
    """Text + optional camera image → streaming AI response (SSE).
    Routes through Zhipu GLM-4V when image present and vision key configured."""
    if not backend:
        return Response("Server initializing", status_code=503)

    async def event_stream():
        try:
            async for chunk in backend.chat_stream(req.text, image_b64=req.image_b64):
                data = json.dumps({
                    "choices": [{"delta": {"content": chunk}, "finish_reason": None}]
                })
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Vision chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 文件上传到本地电脑 ──────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("OPENCLAW_UPLOAD_DIR", str(Path.home() / "Downloads" / "OpenClawUploads")))

@app.get("/api/upload/dir")
async def get_upload_dir():
    """返回当前上传目录路径。"""
    return {"dir": str(UPLOAD_DIR)}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), subdir: str = Form("")):
    """将文件保存到电脑本地目录（默认 ~/Downloads/OpenClawUploads）。"""
    try:
        save_dir = UPLOAD_DIR / subdir if subdir else UPLOAD_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        # 防止路径穿越攻击
        safe_name = Path(file.filename).name
        if not safe_name:
            safe_name = f"upload_{int(os.times().elapsed * 1000)}"

        # 如果同名文件已存在，自动加序号
        dest = save_dir / safe_name
        if dest.exists():
            stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
            counter = 1
            while dest.exists():
                dest = save_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        content = await file.read()
        dest.write_bytes(content)

        size_kb = len(content) / 1024
        logger.info(f"📁 文件已保存: {dest} ({size_kb:.1f} KB)")

        return {
            "ok": True,
            "filename": dest.name,
            "path": str(dest),
            "size": len(content),
            "dir": str(save_dir),
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return {"ok": False, "error": str(e)}


DESKTOP_AI_SYSTEM_PROMPT = """你是桌面 AI 助手，可以看到并控制用户的 Windows 电脑屏幕。

当前屏幕上识别到的文字和位置（x,y 是归一化坐标 0~1，左上角为 0,0，右下角为 1,1）：
{screen_text}

你可以使用以下动作来控制电脑。把动作放在 [ACTIONS] 和 [/ACTIONS] 标记之间，格式为 JSON 数组：

可用动作：
- {{"action":"find_and_click","text":"微信"}} — 在屏幕上找到包含该文字的位置并点击（最推荐，不受窗口位置影响）
- {{"action":"find_and_double_click","text":"微信"}} — 找到文字并双击
- {{"action":"click","x":0.5,"y":0.5}} — 点击指定坐标
- {{"action":"double_click","x":0.5,"y":0.5}} — 双击指定坐标
- {{"action":"type","text":"你好"}} — 输入文字（支持中文）
- {{"action":"key","key":"enter"}} — 按键（enter/tab/esc/backspace/delete/up/down/left/right 等）
- {{"action":"hotkey","keys":["ctrl","a"]}} — 组合键
- {{"action":"scroll","dy":3}} — 滚动（正数向上，负数向下）
- {{"action":"wait","ms":1000}} — 等待指定毫秒

回复规则：
1. 先简要描述你在屏幕上看到了什么
2. 说明你打算执行什么操作
3. 在 [ACTIONS]...[/ACTIONS] 中给出动作序列
4. 如果需要多步操作（如先打开应用再操作），每次只执行当前步骤的动作，说明接下来还需要什么
5. 如果找不到目标，说明原因并建议用户怎么做
6. 用中文回复
{skills_section}"""


def _format_ocr_for_ai(items: list[dict], max_items: int = 80) -> str:
    """Format OCR results into a readable screen description for the AI."""
    if not items:
        return "  （屏幕上未识别到文字）"
    display = items[:max_items]
    lines = []
    for it in display:
        lines.append(f"  [{it['text']}] at ({it['x']:.2f}, {it['y']:.2f})")
    if len(items) > max_items:
        lines.append(f"  ...还有 {len(items) - max_items} 项未显示")
    return "\n".join(lines)


def _parse_actions(text: str) -> list[dict]:
    """Extract actions JSON from AI response text between [ACTIONS]...[/ACTIONS]."""
    pattern = r'\[ACTIONS\]\s*(.*?)\s*\[/ACTIONS\]'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        try:
            cleaned = match.group(1).strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'```$', '', cleaned).strip()
            return json.loads(cleaned)
        except Exception:
            return []


@app.post("/api/desktop-cmd")
async def desktop_ai_command(request: Request):
    """AI-driven desktop control: screenshot → OCR → AI plan → execute → respond."""
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    body = await request.json()
    command = body.get("command", "").strip()
    history = body.get("history", [])
    max_rounds = min(int(body.get("max_rounds", 3)), 5)

    if not command:
        return Response(content=json.dumps({"error": "No command"}), status_code=400)

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    loop = asyncio.get_running_loop()

    async def run_rounds():
        round_history = list(history[-6:])

        for round_num in range(1, max_rounds + 1):
            # 1. Screenshot + OCR
            yield f"data: {json.dumps({'type': 'status', 'text': f'正在分析屏幕... (第{round_num}轮)'})}\n\n"

            ocr_items = await loop.run_in_executor(None, desktop.ocr_screen)
            screen_desc = _format_ocr_for_ai(ocr_items)

            # 2. Build messages
            skills_section = get_skills_prompt_section()
            system_msg = DESKTOP_AI_SYSTEM_PROMPT.format(
                screen_text=screen_desc,
                skills_section=skills_section
            )
            messages = [{"role": "system", "content": system_msg}]
            messages.extend(round_history)

            if round_num == 1:
                messages.append({"role": "user", "content": command})
            else:
                messages.append({"role": "user", "content":
                    f"动作已执行完成。执行日志：\n{exec_log_text}\n\n"
                    f"屏幕已更新。请查看新的屏幕内容，判断操作是否成功，是否需要继续。"
                    f"如果任务已完成，不需要输出 [ACTIONS] 块。"
                })

            # 3. Call AI (collect full response)
            full_response = ""
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{gateway_url}/v1/chat/completions",
                        json={"messages": messages, "model": "deepseek-chat", "stream": True},
                        headers={
                            "Authorization": f"Bearer {gateway_token}",
                            "Content-Type": "application/json",
                        },
                    ) as resp:
                        async for line in resp.aiter_lines():
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                parsed = json.loads(data)
                                delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    full_response += delta
                                    yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.error(f"Desktop AI error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                break

            # 4. Parse actions
            actions = _parse_actions(full_response)
            if not actions:
                yield f"data: {json.dumps({'type': 'done', 'round': round_num})}\n\n"
                break

            # 5. Execute actions
            yield f"data: {json.dumps({'type': 'executing', 'actions': actions})}\n\n"
            exec_log = await loop.run_in_executor(None, desktop.execute_actions, actions)
            exec_log_text = "\n".join(exec_log)
            yield f"data: {json.dumps({'type': 'exec_result', 'log': exec_log})}\n\n"

            # Save to round history for multi-round
            round_history.append({"role": "assistant", "content": full_response})

            # Wait for screen to update after actions
            await asyncio.sleep(0.8)

            # Take a post-action screenshot
            screenshot_b64 = await loop.run_in_executor(None, desktop.capture_screenshot_b64)
            yield f"data: {json.dumps({'type': 'screenshot', 'data': screenshot_b64})}\n\n"

            if round_num >= max_rounds:
                yield f"data: {json.dumps({'type': 'done', 'round': round_num, 'reason': 'max_rounds'})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_rounds(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/desktop-skills")
async def desktop_skills_list():
    """Return available desktop skill packs."""
    return {"skills": list_skills()}


@app.post("/api/desktop-skill/{skill_id}")
async def execute_desktop_skill(skill_id: str):
    """Execute a desktop skill pack by ID."""
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    skill = get_skill(skill_id)
    if not skill:
        return Response(content=json.dumps({"error": f"Skill '{skill_id}' not found"}), status_code=404)

    loop = asyncio.get_running_loop()

    async def run_skill():
        yield f"data: {json.dumps({'type': 'skill_start', 'id': skill_id, 'name': skill.name_zh})}\n\n"

        try:
            result = await loop.run_in_executor(None, skill.execute, desktop)

            for step in result.steps:
                yield f"data: {json.dumps({'type': 'skill_step', 'desc': step.description, 'status': step.status, 'detail': step.detail})}\n\n"

            payload = {
                'type': 'skill_done',
                'success': result.success,
                'message': result.message,
            }
            if result.screenshot_b64:
                payload['screenshot'] = result.screenshot_b64
            yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            logger.error(f"Skill {skill_id} error: {e}")
            yield f"data: {json.dumps({'type': 'skill_error', 'message': str(e)})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_skill(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/desktop-skill/send_wechat_message")
async def send_wechat_message_api(request: Request):
    """
    向微信联系人发送消息（双重 OCR 验证，绝不依赖坐标）。
    Body: { "contact": "张三", "message": "你好" }
    """
    if not desktop:
        return Response(content=json.dumps({"error": "Desktop not available"}), status_code=503)

    body = await request.json()
    contact = (body.get("contact") or "").strip()
    message = (body.get("message") or "").strip()

    if not contact:
        return Response(content=json.dumps({"error": "缺少 contact 参数（联系人名字）"}), status_code=400)
    if not message:
        return Response(content=json.dumps({"error": "缺少 message 参数（消息内容）"}), status_code=400)

    from .desktop_skills import execute_send_wechat_message

    loop = asyncio.get_running_loop()

    async def run_send():
        yield f"data: {json.dumps({'type': 'skill_start', 'id': 'send_wechat_message', 'contact': contact})}\n\n"
        try:
            result = await loop.run_in_executor(
                None, execute_send_wechat_message, desktop, contact, message
            )
            for step in result.steps:
                yield f"data: {json.dumps({'type': 'skill_step', 'desc': step.description, 'status': step.status, 'detail': step.detail})}\n\n"

            payload = {
                "type": "skill_done",
                "success": result.success,
                "message": result.message,
            }
            if result.screenshot_b64:
                payload["screenshot"] = result.screenshot_b64
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error(f"send_wechat_message error: {e}")
            yield f"data: {json.dumps({'type': 'skill_error', 'message': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        run_send(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/server-info")
async def server_info():
    """Return server connection info for QR code generation."""
    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    try:
        hostname = socket.gethostname()
        local_ips = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        local_ips = ["127.0.0.1"]

    http_port = settings.http_port if settings.http_port > 0 else settings.port + 1

    return {
        "host": hostname,
        "ips": local_ips,
        "port": settings.port,
        "http_port": http_port,
        "gateway_url": gateway_url,
        "token": gateway_token,
    }


@app.get("/chat")
@app.get("/chat/")
async def chat_page():
    """Quick chat page — works over plain HTTP, no cert needed. QR-scan friendly."""
    return FileResponse("src/client/chat.html")


@app.get("/qr")
@app.get("/qr/")
async def qr_page():
    """QR code display page for the computer screen."""
    return FileResponse("src/client/qr.html")


@app.get("/api/qr")
async def generate_qr_image(url: str, size: int = 240):
    """Generate a QR code PNG image server-side (no CDN dependency)."""
    import io
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=max(4, size // 40),
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        # Fallback: redirect to external service
        from fastapi.responses import RedirectResponse
        safe_url = url.replace("&", "%26")
        return RedirectResponse(
            url=f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={safe_url}"
        )


@app.get("/manifest.json")
async def pwa_manifest():
    """Serve PWA manifest for home-screen installation."""
    return FileResponse(
        "src/client/manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/sw.js")
async def service_worker():
    """Serve Service Worker script (must be at root scope)."""
    return FileResponse(
        "src/client/sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )

@app.get("/")
@app.get("/voice")
@app.get("/voice/")
async def index():
    """Serve the demo page."""
    return FileResponse("src/client/index.html")


@app.post("/api/keys")
async def create_api_key(
    name: str,
    tier: str = "free",
    master_key: Optional[str] = None,
):
    """
    Create a new API key (requires master key).
    
    curl -X POST "http://localhost:8765/api/keys?name=myapp&tier=pro" \
         -H "x-master-key: YOUR_MASTER_KEY"
    """
    # Verify master key
    if settings.require_auth:
        if not master_key and not settings.master_key:
            return {"error": "Master key required"}
        
        provided_key = master_key or ""
        if provided_key != settings.master_key:
            # Also check if it's a valid master-tier key
            key = token_manager.validate_key(provided_key)
            if not key or key.tier != "enterprise":
                return {"error": "Invalid master key"}
    
    from .auth import PRICING_TIERS
    
    if tier not in PRICING_TIERS:
        return {"error": f"Invalid tier. Options: {list(PRICING_TIERS.keys())}"}
    
    tier_config = PRICING_TIERS[tier]
    
    plaintext_key, api_key = token_manager.generate_key(
        name=name,
        tier=tier,
        rate_limit=tier_config["rate_limit"],
        monthly_minutes=tier_config["monthly_minutes"],
    )
    
    return {
        "api_key": plaintext_key,  # Only shown once!
        "key_id": api_key.key_id,
        "name": api_key.name,
        "tier": api_key.tier,
        "monthly_minutes": api_key.monthly_minutes,
        "rate_limit": api_key.rate_limit_per_minute,
    }


@app.get("/api/history")
async def get_history(session: str = "default", limit: int = 50):
    """Return conversation history for a session."""
    try:
        msgs = mem_store.get_history_raw(session, limit=limit)
        return {"session": session, "messages": msgs, "count": len(msgs)}
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        return {"session": session, "messages": [], "count": 0, "error": str(e)}

@app.delete("/api/history")
async def clear_history(session: str = "default"):
    """Clear conversation history for a session."""
    try:
        deleted = mem_store.clear_history(session)
        # Also clear in-memory cache in the backend
        if backend:
            backend.clear_history()
        return {"ok": True, "deleted": deleted, "session": session}
    except Exception as e:
        logger.error(f"History clear error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/history/sessions")
async def list_history_sessions():
    """List all sessions with message counts."""
    try:
        sessions = mem_store.list_sessions()
        return {"sessions": sessions}
    except Exception as e:
        return {"sessions": [], "error": str(e)}

class STTModelRequest(BaseModel):
    model: str  # tiny / base / small / medium / large-v3-turbo

@app.post("/api/stt-model")
async def switch_stt_model(req: STTModelRequest):
    """Hot-switch the Whisper STT model (reloads the model immediately)."""
    global stt
    VALID_MODELS = {"tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"}
    if req.model not in VALID_MODELS:
        return {"ok": False, "error": f"Invalid model. Valid: {sorted(VALID_MODELS)}"}
    try:
        logger.info(f"Switching STT model: {stt.model_name} → {req.model}")
        new_stt = WhisperSTT(
            model_name=req.model,
            device=settings.stt_device,
            language=settings.stt_language,
        )
        stt = new_stt
        logger.info(f"✅ STT model switched to: {req.model}")
        return {"ok": True, "model": req.model, "backend": stt._backend}
    except Exception as e:
        logger.error(f"STT model switch failed: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/stt-model")
async def get_stt_model():
    """Return current STT model info."""
    if not stt:
        return {"model": None, "backend": None}
    return {"model": stt.model_name, "backend": stt._backend}

@app.get("/api/skills")
async def get_skills_catalog():
    """返回所有技能的分类列表（供技能中心 UI 使用）"""
    import json as _json
    from pathlib import Path as _Path
    skills_dir = _Path(__file__).parent.parent.parent / "skills"
    categories = []
    for meta_file in sorted(skills_dir.rglob("_meta.json")):
        try:
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            categories.append({
                "id": meta.get("category", ""),
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "skills": meta.get("skills", []),
            })
        except Exception:
            pass
    total = sum(len(c["skills"]) for c in categories)
    return {"categories": categories, "total": total}


@app.post("/api/stats/record")
async def record_skill_stat(data: dict):
    """记录技能调用统计"""
    try:
        from src.server.stats import record_usage
        record_usage(
            skill_id=data.get("skill_id", ""),
            session_id=data.get("session_id"),
            user_input=data.get("input", ""),
            success=data.get("success", True),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/stats/skills")
async def get_skill_stats():
    """获取技能使用统计（热度排行）"""
    try:
        from src.server.stats import get_skill_stats as _get_stats, get_recent_skills, get_summary
        return {
            "top": _get_stats(20),
            "recent": get_recent_skills(5),
            "summary": get_summary(),
        }
    except Exception as e:
        return {"top": [], "recent": [], "summary": {}, "error": str(e)}


@app.get("/api/update/check")
async def check_update():
    """检查是否有新版本"""
    try:
        from src.server.updater import get_updater
        updater = get_updater()
        info = await updater.check_for_updates()
        return {
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "has_update": info.has_update,
            "changelog": info.changelog,
            "changed_files_count": len(info.changed_files),
            "needs_restart": info.needs_restart,
            "error": info.error,
        }
    except Exception as e:
        return {"has_update": False, "error": str(e)}


@app.post("/api/update/apply")
async def apply_update():
    """执行更新（增量下载并替换变更文件）"""
    try:
        from src.server.updater import get_updater
        updater = get_updater()
        info = await updater.check_for_updates()
        if not info.has_update:
            return {"ok": False, "message": "没有可用的更新"}
        ok, msg = await updater.apply_update(info)
        return {"ok": ok, "message": msg, "needs_restart": info.needs_restart}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ══════════════════════════════════════════════════════════════════
# 微信自动回复 API
# ══════════════════════════════════════════════════════════════════

def _ensure_wechat_engine():
    """懒加载：首次调用时初始化 v2.0 三轨融合系统"""
    global _wechat_monitor, _wechat_engine, _wechat_adapter
    if not _wechat_autoreply_available:
        return None, None
    if _wechat_engine is None:
        try:
            result = init_wechat_v2(
                ai_backend=backend,
                desktop=desktop,
            )
            if isinstance(result, tuple) and len(result) == 2:
                _wechat_adapter, _wechat_engine = result
                _wechat_monitor = get_monitor()
            else:
                _wechat_monitor, _wechat_engine = init_wechat_autoreply(
                    ai_backend=backend, desktop=desktop,
                )
            logger.info("✅ 微信自动回复引擎初始化完成")
        except Exception as e:
            logger.error(f"微信自动回复初始化失败: {e}")
            return None, None
    return _wechat_monitor, _wechat_engine


@app.get("/api/wechat/status")
async def wechat_autoreply_status():
    """获取微信自动回复状态、统计、待审核列表（含三轨信息）"""
    if not _wechat_autoreply_available:
        return {"available": False, "reason": "仅支持 Windows 平台"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"available": False, "reason": "引擎初始化失败"}
    monitor = get_monitor()
    adapter = get_adapter() if _wechat_autoreply_available else None
    stats = engine.get_stats()
    stats["available"] = True
    stats["monitor_running"] = monitor.is_running if monitor else False
    stats["monitor_mode"] = monitor.get_mode() if monitor else "none"
    stats["monitor_stats"] = monitor.stats if monitor else {}
    # v2.0 三轨信息
    if adapter:
        adapter_status = adapter.get_status()
        stats["v2"] = {
            "active_track": adapter_status.get("active_track", "none"),
            "adapter_running": adapter_status.get("running", False),
            "tracks": adapter_status.get("tracks", {}),
            "anti_risk": adapter_status.get("anti_risk", {}),
        }
    return stats


@app.post("/api/wechat/toggle")
async def wechat_autoreply_toggle(request: Request):
    """
    开启 / 关闭自动回复总开关，或启动/停止监控器。
    Body: { "enabled": true/false }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    enabled = body.get("enabled", False)
    monitor, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎初始化失败"}), status_code=500)

    engine.update_config({"enabled": enabled})

    # v2.0 适配器
    adapter = get_adapter() if _wechat_autoreply_available else None
    if enabled:
        if adapter and not adapter.is_running:
            import threading
            threading.Thread(target=adapter.start, daemon=True).start()
            logger.info("v2.0 三轨适配器已启动")
        elif monitor and not monitor.is_running:
            monitor.start()
            logger.info("微信监控器已启动")
    else:
        if adapter and adapter.is_running:
            adapter.stop()
        if monitor and monitor.is_running:
            monitor.stop()
            logger.info("微信监控器已停止")

    return {"ok": True, "enabled": enabled}


@app.post("/api/wechat/config")
async def wechat_autoreply_config(request: Request):
    """
    更新全局配置。
    Body 字段（均可选）:
      manual_review, quiet_start, quiet_end,
      min_reply_delay, max_reply_delay,
      global_persona, keyword_blacklist
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    ok = engine.update_config(body)
    return {"ok": ok}


@app.post("/api/wechat/contacts")
async def wechat_add_contact(request: Request):
    """
    添加联系人到白名单。
    Body: { "name": "张三", "daily_limit": 20, "is_group": false, "persona": "" }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return Response(content=json.dumps({"error": "缺少 name"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    rule = engine.add_contact(
        name=name,
        daily_limit=body.get("daily_limit", 20),
        is_group=body.get("is_group", False),
        group_reply_only_at_me=body.get("group_reply_only_at_me", True),
        persona=body.get("persona", ""),
    )
    # v2.0: 自动加入 wxauto 后台监听
    adapter = get_adapter() if _wechat_autoreply_available else None
    if adapter:
        adapter.add_listen([name])
    return {"ok": True, "contact": name, "daily_limit": rule.daily_limit}


@app.delete("/api/wechat/contacts/{name}")
async def wechat_remove_contact(name: str):
    """从白名单移除联系人"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.remove_contact(name) if engine else False
    return {"ok": ok}


@app.patch("/api/wechat/contacts/{name}")
async def wechat_toggle_contact(name: str, request: Request):
    """启用 / 禁用某联系人的自动回复"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    enabled = body.get("enabled", True)
    _, engine = _ensure_wechat_engine()
    ok = engine.toggle_contact(name, enabled) if engine else False
    return {"ok": ok}


@app.get("/api/wechat/reviews")
async def wechat_pending_reviews():
    """获取待人工审核的回复列表"""
    if not _wechat_autoreply_available:
        return {"reviews": []}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"reviews": []}
    return {"reviews": engine.get_pending_reviews()}


@app.post("/api/wechat/reviews/{reply_id}/approve")
async def wechat_approve_reply(reply_id: str):
    """批准一条待审核回复（发送）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.approve_reply(reply_id) if engine else False
    return {"ok": ok}


@app.post("/api/wechat/reviews/{reply_id}/reject")
async def wechat_reject_reply(reply_id: str):
    """拒绝一条待审核回复（不发送）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.reject_reply(reply_id) if engine else False
    return {"ok": ok}


@app.get("/api/wechat/escalations")
async def wechat_escalations():
    """获取待处理的升级列表（AI 判断需要人工介入的消息）"""
    if not _wechat_autoreply_available:
        return {"error": "不支持"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"items": []}
    return {"items": engine.get_escalations()}


@app.post("/api/wechat/escalations/{eid}")
async def wechat_handle_escalation(eid: str, request: Request):
    """
    处理升级项。
    Body: { "action": "send_draft" | "send_custom" | "dismiss", "reply": "..." }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    body = await request.json()
    action = body.get("action", "dismiss")
    reply = body.get("reply", "")
    ok = engine.handle_escalation(eid, action, reply)
    return {"ok": ok}


@app.get("/api/wechat/smart-stats")
async def wechat_smart_stats():
    """获取智能回复引擎统计"""
    if not _wechat_autoreply_available:
        return {"error": "不支持"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {}
    stats = engine.get_stats()
    return {
        "smart_mode": stats.get("smart_mode", False),
        "smart_engine": stats.get("smart_engine", {}),
    }


@app.get("/api/wechat/reviews/stream")
async def wechat_review_stream():
    """SSE 实时推送新的待审核回复（前端用于实时通知）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)

    queue: asyncio.Queue = asyncio.Queue()

    def on_review(pr):
        asyncio.run_coroutine_threadsafe(
            queue.put({
                "id": pr.id,
                "contact": pr.contact,
                "incoming": pr.incoming_msg,
                "reply": pr.ai_reply,
            }),
            asyncio.get_event_loop()
        )

    engine.on_review_needed(on_review)

    async def event_stream():
        yield "data: {\"type\": \"connected\"}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps({'type': 'review', **item}, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/wechat/monitor-stats")
async def wechat_monitor_stats():
    """获取监控器运行统计（含 v2.0 三轨信息）"""
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    monitor, engine = _ensure_wechat_engine()
    adapter = get_adapter() if _wechat_autoreply_available else None
    stats = {}
    if monitor:
        stats = {
            **monitor.stats,
            "is_running": monitor.is_running,
            "mode": monitor.get_mode(),
        }
    if adapter:
        adapter_st = adapter.get_status()
        stats["v2_active_track"] = adapter_st.get("active_track", "none")
        stats["v2_running"] = adapter_st.get("running", False)
        stats["v2_tracks"] = adapter_st.get("tracks", {})
        stats["v2_scans"] = adapter_st.get("stats", {}).get("scans", 0)
        stats["v2_messages"] = adapter_st.get("stats", {}).get("messages_detected", 0)
    return {"available": True, "stats": stats}


@app.post("/api/wechat/test-read")
async def wechat_test_read():
    """
    手动触发一次读取（不触发回复）。
    优先使用 v2.0 三轨适配器，降级到旧版 monitor.manual_scan。
    """
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    _ensure_wechat_engine()
    adapter = get_adapter() if _wechat_autoreply_available else None
    monitor = get_monitor() if _wechat_autoreply_available else None
    try:
        if adapter:
            result = await asyncio.get_event_loop().run_in_executor(
                None, adapter.manual_scan
            )
            return {"ok": True, "version": "v2", "result": result}
        elif monitor:
            result = await asyncio.get_event_loop().run_in_executor(
                None, monitor.manual_scan
            )
            return {"ok": True, "version": "v1", "result": result}
        else:
            return {"ok": False, "error": "无可用监控器"}
    except Exception as e:
        logger.error(f"wechat test-read error: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/wechat/uia-debug")
async def wechat_uia_debug(max_depth: int = 5):
    """
    导出微信窗口完整 UIA 控件树（诊断工具）。
    max_depth: 控件树最大深度（默认5，建议不超过7）
    """
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    monitor, _ = _ensure_wechat_engine()
    if not monitor:
        return {"error": "监控器未初始化"}
    try:
        depth = max(1, min(max_depth, 8))
        tree = await asyncio.get_event_loop().run_in_executor(
            None, lambda: monitor.dump_uia_tree(max_depth=depth)
        )
        return {"ok": True, "node_count": len(tree), "tree": tree}
    except Exception as e:
        logger.error(f"wechat uia-debug error: {e}")
        return {"ok": False, "error": str(e)}


# ── 朋友圈 API ─────────────────────────────────────────────────────────────────

_chain_tracker = None
_content_calendar = None


def _get_chain_tracker():
    global _chain_tracker
    if _chain_tracker is None:
        from .wechat.moments_tracker import CommentChainTracker
        ai_call = None
        if hasattr(app.state, 'ai_backend') and app.state.ai_backend:
            ai_call = app.state.ai_backend.chat_simple
        _chain_tracker = CommentChainTracker(ai_call=ai_call)
    return _chain_tracker


def _get_content_calendar():
    global _content_calendar
    if _content_calendar is None:
        from .wechat.moments_tracker import ContentCalendar
        ai_call = None
        if hasattr(app.state, 'ai_backend') and app.state.ai_backend:
            ai_call = app.state.ai_backend.chat_simple
        _content_calendar = ContentCalendar(ai_call=ai_call)
    return _content_calendar


@app.post("/api/moments/browse")
async def moments_browse(request: Request):
    """浏览朋友圈并用 AI 分析"""
    data = await request.json() if request.headers.get("content-type") else {}
    max_posts = data.get("max_posts", 5)

    try:
        from .wechat.moments_reader import MomentsReader
        from .wechat.moments_ai import MomentsAIEngine

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        reader = MomentsReader(ai_backend=backend, wxauto_reader=wxauto_r)
        page = await reader.browse(max_posts)

        posts_data = []
        if page.posts and backend:
            ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
            for post in page.posts:
                analysis = await ai_engine.analyze_post(post)
                posts_data.append({
                    "author": post.author,
                    "text": post.text,
                    "image_desc": post.image_desc,
                    "time": post.time_str,
                    "analysis": analysis.to_dict(),
                })

        return {"ok": True, "posts": posts_data, "source": page.source}
    except Exception as e:
        logger.error(f"moments browse error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/moments/interact")
async def moments_interact(request: Request):
    """对一条朋友圈执行互动（点赞/评论）"""
    data = await request.json()
    action = data.get("action", "like")  # like / comment
    author = data.get("author", "")
    post_text = data.get("post_text", "")
    comment = data.get("comment", "")

    if not author:
        return {"error": "缺少 author"}

    try:
        from .wechat.moments_reader import MomentPost
        from .wechat.moments_actor import MomentsActor
        from .wechat.moments_guard import MomentsGuard

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        actor = MomentsActor(wxauto_reader=wxauto_r, guard=MomentsGuard())
        post = MomentPost(author=author, text=post_text)

        if action == "like":
            ok = await actor.like_post(post)
        elif action == "comment":
            if not comment and backend:
                from .wechat.moments_ai import MomentsAIEngine
                ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
                analysis = await ai_engine.analyze_post(post)
                comment = analysis.comment_text
            ok = await actor.comment_post(post, comment) if comment else False
        else:
            return {"error": f"未知操作: {action}"}

        return {"ok": ok, "action": action, "author": author, "comment": comment}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/moments/publish")
async def moments_publish(request: Request):
    """发布朋友圈"""
    data = await request.json()
    text = data.get("text", "")
    media_files = data.get("media_files", [])
    privacy = data.get("privacy", "all")
    generate = data.get("generate", False)
    topic = data.get("topic", "")

    try:
        from .wechat.moments_actor import MomentsActor
        from .wechat.moments_guard import MomentsGuard

        if generate and backend:
            from .wechat.moments_ai import MomentsAIEngine
            ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
            drafts = await ai_engine.generate_moment_text(
                topic=topic or text, mood=data.get("mood", "平常"),
            )
            if drafts:
                text = drafts[0]["text"]

        if not text:
            return {"error": "缺少文案"}

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        actor = MomentsActor(wxauto_reader=wxauto_r, guard=MomentsGuard())
        ok = await actor.publish_moment(text, media_files, privacy)
        return {"ok": ok, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/moments/generate-text")
async def moments_generate_text(request: Request):
    """AI 生成朋友圈文案（3个选项）"""
    data = await request.json()
    if not backend:
        return {"error": "AI 后端未初始化"}

    try:
        from .wechat.moments_ai import MomentsAIEngine
        ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
        drafts = await ai_engine.generate_moment_text(
            topic=data.get("topic", ""),
            style=data.get("style", "日常"),
            mood=data.get("mood", "平常"),
            scene=data.get("scene", ""),
            extra=data.get("extra", ""),
        )
        return {"ok": True, "drafts": drafts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/moments/stats")
async def moments_stats():
    """朋友圈互动统计"""
    try:
        from .wechat.moments_guard import MomentsGuard
        from .wechat.contact_profile import get_stats as profile_stats
        guard = MomentsGuard()
        chain_stats = {}
        try:
            chain_stats = _get_chain_tracker().get_chain_stats()
        except Exception:
            pass
        return {
            "ok": True,
            "guard": guard.get_stats(),
            "profiles": profile_stats(),
            "chain": chain_stats,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/moments/chain/stats")
async def chain_stats():
    """评论链跟进统计"""
    try:
        return {"ok": True, **_get_chain_tracker().get_chain_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/moments/chain/recent")
async def chain_recent():
    """最近评论链记录"""
    try:
        return {"ok": True, "chains": _get_chain_tracker().get_recent_chains()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/moments/calendar")
async def calendar_list(status: str = ""):
    """获取内容日历"""
    try:
        cal = _get_content_calendar()
        return {"ok": True, "entries": cal.get_entries(status)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/moments/calendar/generate")
async def calendar_generate(request: Request):
    """AI 生成 30 天内容日历"""
    try:
        data = await request.json()
        cal = _get_content_calendar()
        entries = await cal.generate_month_plan(
            user_profile=data.get("user_profile", ""),
            interests=data.get("interests", ""),
            style=data.get("style", "自然日常"),
            posts_per_week=data.get("posts_per_week", 3),
        )
        return {"ok": True, "entries": [e.to_dict() for e in entries]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/moments/calendar/{date}/{action}")
async def calendar_action(date: str, action: str):
    """日历条目操作：approve/skip"""
    try:
        cal = _get_content_calendar()
        if action == "approve":
            cal.approve_entry(date)
        elif action == "skip":
            cal.skip_entry(date)
        else:
            return {"ok": False, "error": f"未知操作: {action}"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/contacts/profiles")
async def contacts_profiles(min_intimacy: float = 0):
    """获取联系人社交画像列表"""
    try:
        from .wechat.contact_profile import list_profiles
        profiles = list_profiles(min_intimacy)
        return {"ok": True, "profiles": [p.to_dict() for p in profiles]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/contacts/profiles/{name}")
async def update_contact_profile(name: str, request: Request):
    """更新联系人画像"""
    data = await request.json()
    try:
        from .wechat.contact_profile import get_profile, save_profile
        profile = get_profile(name)
        if "relationship" in data:
            profile.relationship = data["relationship"]
        if "intimacy" in data:
            profile.intimacy = max(0, min(100, float(data["intimacy"])))
        if "comment_style" in data:
            profile.comment_style = data["comment_style"]
        if "interests" in data:
            profile.interests = data["interests"]
        if "notes" in data:
            profile.notes = data["notes"]
        save_profile(profile)
        return {"ok": True, "profile": profile.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 工作流 API ──────────────────────────────────────────────────────────────────

@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    """Serve the admin dashboard."""
    admin_path = Path(__file__).parent.parent / "client" / "admin.html"
    if admin_path.exists():
        return FileResponse(str(admin_path))
    return Response(content="Admin page not found", status_code=404)


@app.get("/admin-manifest.json")
async def admin_manifest():
    p = Path(__file__).parent.parent / "client" / "admin-manifest.json"
    return FileResponse(str(p), media_type="application/manifest+json") if p.exists() else Response("", 404)


@app.get("/admin-sw.js")
async def admin_sw():
    p = Path(__file__).parent.parent / "client" / "admin-sw.js"
    return FileResponse(str(p), media_type="application/javascript") if p.exists() else Response("", 404)


@app.get("/api/workflow/status")
async def workflow_status():
    if not _WORKFLOW_AVAILABLE:
        return {"available": False}
    engine = get_wf_engine()
    return {"available": True, **engine.get_status()}


@app.get("/api/workflow/nodes")
async def workflow_node_types():
    if not _WORKFLOW_AVAILABLE:
        return {"nodes": []}
    return {"nodes": wf_available_nodes()}


@app.get("/api/workflow/list")
async def workflow_list(category: str = ""):
    if not _WORKFLOW_AVAILABLE:
        return {"workflows": []}
    wfs = wf_store.list_workflows(category=category or None)
    return {"workflows": [w.to_dict() for w in wfs]}


@app.get("/api/workflow/{wf_id}")
async def workflow_get(wf_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    wf = wf_store.get_workflow(wf_id)
    if not wf:
        return {"error": f"工作流 {wf_id} 不存在"}
    return {"workflow": wf.to_dict()}


@app.post("/api/workflow/save")
async def workflow_save(request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json()
    try:
        from .workflow.models import Workflow
        wf = Workflow.from_dict(data)
        wf.updated_at = __import__("time").time()
        wf_store.save_workflow(wf)
        get_wf_engine().reload_listeners()
        return {"ok": True, "id": wf.id}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/workflow/{wf_id}")
async def workflow_delete(wf_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ok = wf_store.delete_workflow(wf_id)
    if ok:
        get_wf_engine().reload_listeners()
    return {"ok": ok}


@app.post("/api/workflow/{wf_id}/toggle")
async def workflow_toggle(wf_id: str, request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json()
    enabled = data.get("enabled", False)
    ok = wf_store.toggle_workflow(wf_id, enabled)
    if ok:
        get_wf_engine().reload_listeners()
    return {"ok": ok}


@app.post("/api/workflow/{wf_id}/execute")
async def workflow_execute(wf_id: str, request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json() if request.headers.get("content-type") else {}
    engine = get_wf_engine()

    if engine.wechat_adapter is None and _wechat_adapter:
        engine.wechat_adapter = _wechat_adapter
    if engine.wechat_engine is None and _wechat_engine:
        engine.wechat_engine = _wechat_engine

    ex = await engine.execute(wf_id, trigger_type="manual", event_data=data)
    try:
        from . import audit_log
        audit_log.log("workflow_run", target=wf_id, detail=f"status={ex.status.value}")
    except Exception:
        pass
    return {"ok": ex.status.value == "success", "execution": ex.to_dict()}


@app.get("/api/workflow/executions")
async def workflow_executions(
    workflow_id: str = "",
    limit: int = 50,
    offset: int = 0,
):
    if not _WORKFLOW_AVAILABLE:
        return {"executions": [], "total": 0}
    execs = wf_store.list_executions(
        workflow_id=workflow_id or None, limit=limit, offset=offset
    )
    total = wf_store.count_executions(workflow_id=workflow_id or None)
    return {
        "executions": [e.to_dict() for e in execs],
        "total": total,
    }


@app.get("/api/workflow/executions/{ex_id}")
async def workflow_execution_detail(ex_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ex = wf_store.get_execution(ex_id)
    if not ex:
        return {"error": "执行记录不存在"}
    return {"execution": ex.to_dict()}


@app.post("/api/workflow/executions/{ex_id}/cancel")
async def workflow_execution_cancel(ex_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ok = get_wf_engine().cancel_execution(ex_id)
    return {"ok": ok}


@app.get("/api/usage")
async def get_usage(api_key: str):
    """
    Get usage stats for an API key.
    
    curl "http://localhost:8765/api/usage?api_key=ocv_xxx"
    """
    key = token_manager.validate_key(api_key)
    if not key:
        return {"error": "Invalid API key"}
    
    return token_manager.get_usage(key)


@app.websocket("/ws")
@app.websocket("/voice/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle voice WebSocket connections."""
    # Check for API key in query params or headers
    api_key_str = websocket.query_params.get("api_key") or \
                  websocket.headers.get("x-api-key")
    
    api_key: Optional[APIKey] = None
    
    if settings.require_auth:
        if not api_key_str:
            await websocket.close(code=4001, reason="API key required")
            return
        
        api_key = token_manager.validate_key(api_key_str)
        if not api_key:
            await websocket.close(code=4002, reason="Invalid API key")
            return
        
        if not token_manager.check_rate_limit(api_key):
            await websocket.close(code=4003, reason="Rate limit exceeded")
            return
        
        logger.info(f"Client connected: {api_key.name} (tier={api_key.tier})")
    else:
        # Dev mode - allow all
        if api_key_str:
            api_key = token_manager.validate_key(api_key_str)
        logger.info("Client connected (auth disabled)")
    
    await websocket.accept()
    
    audio_buffer = []
    is_listening = False
    session_start = None
    pending_image: Optional[str] = None  # camera frame waiting for stop_listening

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg["type"] == "image_frame":
                # Client sends camera frame just before stop_listening
                pending_image = msg.get("data")
                logger.debug(f"Image frame queued ({len(pending_image or '') // 1024}KB b64)")

            elif msg["type"] == "start_listening":
                is_listening = True
                audio_buffer = []
                await websocket.send_json({"type": "listening_started"})
                logger.debug("Started listening")
                
            elif msg["type"] == "stop_listening":
                is_listening = False
                
                if audio_buffer:
                    # Combine audio chunks
                    audio_data = np.concatenate(audio_buffer)
                    
                    # Stream transcription — send partial results as segments arrive
                    logger.debug("Transcribing audio (streaming)...")
                    transcript_parts = []
                    async for partial in stt.transcribe_stream(audio_data):
                        transcript_parts.append(partial)
                        # Send each segment to the client in real-time
                        await websocket.send_json({
                            "type": "transcript",
                            "text": partial,
                            "partial": True,
                            "accumulated": " ".join(transcript_parts),
                        })

                    transcript = " ".join(transcript_parts).strip()

                    # Send final complete transcript
                    await websocket.send_json({
                        "type": "transcript",
                        "text": transcript,
                        "final": True,
                    })
                    logger.info(f"Transcript: {transcript}")
                    
                    if not transcript.strip():
                        await websocket.send_json({
                            "type": "response_complete",
                            "text": "",
                            "empty_transcript": True,
                        })
                    
                    if transcript.strip():
                        # Stream AI response with progressive TTS
                        has_image = bool(pending_image)
                        logger.debug(f"Streaming AI response (vision={has_image})...")

                        full_response = ""
                        sentence_buffer = ""
                        audio_chunks = []

                        # Send vision indicator to client
                        if has_image:
                            await websocket.send_json({"type": "vision_used", "value": True})

                        # Stream response and synthesize sentences as they complete
                        async for chunk in backend.chat_stream(transcript, image_b64=pending_image):
                            full_response += chunk
                            sentence_buffer += chunk
                            
                            # Send text chunk for progressive display
                            await websocket.send_json({
                                "type": "response_chunk",
                                "text": chunk,
                            })
                            
                            # Check for sentence boundaries (English + Chinese punctuation)
                            SENTENCE_SEPS = ['. ', '! ', '? ', '.\n', '!\n', '?\n',
                                             '。', '！', '？', '；', '\n\n']
                            while any(sep in sentence_buffer for sep in SENTENCE_SEPS):
                                earliest_idx = len(sentence_buffer)
                                for sep in SENTENCE_SEPS:
                                    idx = sentence_buffer.find(sep)
                                    if idx != -1 and idx < earliest_idx:
                                        earliest_idx = idx + len(sep)
                                
                                if earliest_idx < len(sentence_buffer):
                                    sentence = sentence_buffer[:earliest_idx].strip()
                                    sentence_buffer = sentence_buffer[earliest_idx:]
                                    
                                    if sentence:
                                        # Clean and synthesize this sentence
                                        speech_text = clean_for_speech(sentence)
                                        if speech_text:
                                            logger.debug(f"Synthesizing: {speech_text[:50]}...")
                                            async for audio_chunk in tts.synthesize_stream(speech_text):
                                                audio_b64 = base64.b64encode(audio_chunk).decode()
                                                await websocket.send_json({
                                                    "type": "audio_chunk",
                                                    "data": audio_b64,
                                                    "sample_rate": 24000,
                                                    "format": tts.audio_format,
                                                })
                                else:
                                    break
                        
                        # Handle any remaining text
                        if sentence_buffer.strip():
                            speech_text = clean_for_speech(sentence_buffer.strip())
                            if speech_text:
                                async for audio_chunk in tts.synthesize_stream(speech_text):
                                    audio_b64 = base64.b64encode(audio_chunk).decode()
                                    await websocket.send_json({
                                        "type": "audio_chunk",
                                        "data": audio_b64,
                                        "sample_rate": 24000,
                                        "format": tts.audio_format,
                                    })
                        
                        # Signal end of response
                        await websocket.send_json({
                            "type": "response_complete",
                            "text": full_response,
                        })
                        logger.info(f"Response complete: {full_response[:100]}...")

                        # 异步推送到 IM 平台（不阻塞语音回复）
                        if _IM_BRIDGE_AVAILABLE and _bridge_manager and full_response:
                            asyncio.create_task(
                                _bridge_manager.broadcast(
                                    f"用户：{transcript}\n\nAI：{full_response[:200]}",
                                    title="语音对话记录"
                                )
                            )
                
                pending_image = None  # consumed
                audio_buffer = []
                await websocket.send_json({"type": "listening_stopped"})
                logger.debug("Stopped listening")
                
            elif msg["type"] == "audio" and is_listening:
                audio_bytes = base64.b64decode(msg["data"])
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                audio_buffer.append(audio_np)

                if len(audio_buffer) == 1:
                    logger.debug(f"Audio: first chunk {len(audio_np)} samples, "
                                 f"max={np.abs(audio_np).max():.4f}, "
                                 f"rms={np.sqrt(np.mean(audio_np**2)):.4f}")
                
                # VAD check - notify client if speech detected
                if vad and len(audio_np) > 0:
                    has_speech = vad.is_speech(audio_np)
                    await websocket.send_json({
                        "type": "vad_status",
                        "speech_detected": has_speech,
                    })
                
            elif msg["type"] == "monitor_audio":
                # Wake-word monitoring: transcribe a short chunk, check for wake word
                audio_bytes = base64.b64decode(msg["data"])
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                max_amp = float(np.abs(audio_np).max()) if len(audio_np) > 0 else 0.0
                if max_amp > 0.005:  # skip silent chunks
                    try:
                        transcript = await stt.transcribe(audio_np)
                        if transcript.strip():
                            lower = transcript.lower()
                            wake_words = [
                                '你好', '小龙', '龙虾', '唤醒', '开始', '在吗',
                                'hey claw', 'hey cloud', 'hello', 'hi claw',
                            ]
                            has_wake = any(w in lower for w in wake_words)
                            await websocket.send_json({
                                "type": "monitor_transcript",
                                "text": transcript,
                                "has_wake_word": has_wake,
                            })
                            logger.debug(f"Monitor: '{transcript}' wake={has_wake}")
                    except Exception as e:
                        logger.warning(f"Monitor STT error: {e}")

            elif msg["type"] == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


# ── Remote Desktop ──
desktop: Optional[DesktopStreamer] = None

try:
    desktop = DesktopStreamer()
except Exception as e:
    logger.warning(f"Desktop streamer unavailable: {e}")


@app.websocket("/ws/desktop")
async def desktop_ws(websocket: WebSocket):
    """Stream desktop frames and receive mouse/keyboard commands."""
    if not desktop:
        await websocket.close(code=4010, reason="Desktop streaming unavailable")
        return

    await websocket.accept()
    logger.info("Desktop client connected")

    streaming = True
    fps = desktop.fps

    async def send_frames():
        loop = asyncio.get_running_loop()
        frame_count = 0
        while streaming:
            try:
                data, w, h = await loop.run_in_executor(
                    None, desktop.capture_frame
                )
                await websocket.send_json({
                    "type": "frame",
                    "data": data,
                    "w": w,
                    "h": h,
                    "sw": desktop.screen_size[0],
                    "sh": desktop.screen_size[1],
                })
                frame_count += 1
                if frame_count == 1:
                    logger.info(f"Desktop: first frame sent ({len(data)//1024}KB {w}x{h})")
                await asyncio.sleep(1.0 / fps)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Desktop frame error: {e}")
                await asyncio.sleep(0.5)

    frame_task = asyncio.create_task(send_frames())

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "set_fps":
                fps = max(1, min(30, int(msg.get("fps", 10))))
                desktop.fps = fps
            else:
                await asyncio.get_event_loop().run_in_executor(
                    None, desktop.handle_command, msg
                )
    except WebSocketDisconnect:
        logger.info("Desktop client disconnected")
    except Exception as e:
        logger.error(f"Desktop WS error: {e}")
    finally:
        streaming = False
        frame_task.cancel()


# Serve static files for client
client_dir = Path(__file__).parent.parent / "client"
if client_dir.exists():
    app.mount("/static", StaticFiles(directory=str(client_dir)), name="static")


def _ensure_firewall_rules(http_port: int, https_port: int):
    """Add Windows Firewall inbound rules for HTTP/HTTPS ports (best-effort)."""
    import platform, subprocess
    if platform.system() != "Windows":
        return
    for port, name in [(http_port, "OpenClaw-HTTP"), (https_port, "OpenClaw-HTTPS")]:
        try:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name={name}-{port}", "protocol=TCP", "dir=in",
                 f"localport={port}", "action=allow", "enable=yes"],
                capture_output=True, check=False, timeout=5,
            )
        except Exception:
            pass


# ── SSE 实时推送 ───────────────────────────────────────────────────────────────

@app.get("/api/events/stream")
async def sse_stream(request: Request):
    """Server-Sent Events 端点 — Admin 面板实时更新"""
    from .event_bus import get_bus

    async def event_generator():
        try:
            async for event in get_bus().subscribe():
                data = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: {event['type']}\ndata: {data}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/events/recent")
async def sse_recent(limit: int = 20, event_type: str = ""):
    """最近事件历史"""
    from .event_bus import get_bus
    return {"ok": True, "events": get_bus().recent_events(limit, event_type)}


# ── 统一收件箱 API ────────────────────────────────────────────────────────────

@app.get("/api/inbox")
async def inbox_query(account_id: str = "", contact: str = "", unread: bool = False, limit: int = 50, offset: int = 0):
    from .wechat.unified_inbox import query_inbox
    msgs = query_inbox(account_id, contact, unread_only=unread, limit=limit, offset=offset)
    return {"ok": True, "messages": msgs}


@app.get("/api/inbox/stats")
async def inbox_stats(account_id: str = ""):
    from .wechat.unified_inbox import get_inbox_stats
    return {"ok": True, **get_inbox_stats(account_id)}


@app.get("/api/inbox/conversations")
async def inbox_conversations(account_id: str = "", limit: int = 30):
    from .wechat.unified_inbox import get_conversations
    return {"ok": True, "conversations": get_conversations(account_id, limit)}


@app.post("/api/inbox/read")
async def inbox_mark_read(request: Request):
    data = await request.json()
    from .wechat.unified_inbox import mark_read
    mark_read(
        msg_ids=data.get("msg_ids"),
        account_id=data.get("account_id", ""),
        contact=data.get("contact", ""),
    )
    return {"ok": True}


@app.post("/api/inbox/star/{msg_id}")
async def inbox_star(msg_id: int):
    from .wechat.unified_inbox import toggle_star
    starred = toggle_star(msg_id)
    return {"ok": True, "starred": starred}


# ── 转发规则 API ──────────────────────────────────────────────────────────────

@app.get("/api/forward-rules")
async def forward_rules_list():
    from .wechat.unified_inbox import list_forward_rules
    return {"ok": True, "rules": [r.to_dict() for r in list_forward_rules()]}


@app.post("/api/forward-rules")
async def forward_rules_save(request: Request):
    data = await request.json()
    from .wechat.unified_inbox import ForwardRule, save_forward_rule
    rule = ForwardRule(
        id=data.get("id", ""),
        name=data.get("name", "新规则"),
        enabled=data.get("enabled", True),
        src_account=data.get("src_account", ""),
        src_contact=data.get("src_contact", ""),
        dst_account=data.get("dst_account", ""),
        dst_contact=data.get("dst_contact", ""),
        keyword_filter=data.get("keyword_filter", ""),
        transform=data.get("transform", "plain"),
    )
    save_forward_rule(rule)
    return {"ok": True, "id": rule.id}


@app.delete("/api/forward-rules/{rule_id}")
async def forward_rules_delete(rule_id: str):
    from .wechat.unified_inbox import delete_forward_rule
    delete_forward_rule(rule_id)
    return {"ok": True}


# ── 朋友圈协作 API ───────────────────────────────────────────────────────────

@app.get("/api/moments-coop/status")
async def moments_coop_status():
    from .wechat.moments_coordinator import get_coordinator
    return {"ok": True, **get_coordinator().get_status()}


@app.post("/api/moments-coop/browse")
async def moments_coop_browse(request: Request):
    data = await request.json()
    from .wechat.moments_coordinator import get_coordinator
    coord = get_coordinator()
    tasks = await coord.schedule_browse(
        account_ids=data.get("account_ids", []),
        max_posts=data.get("max_posts", 5),
        auto_interact=data.get("auto_interact", True),
    )
    return {"ok": True, "tasks": len(tasks)}


@app.post("/api/moments-coop/publish")
async def moments_coop_publish(request: Request):
    data = await request.json()
    from .wechat.moments_coordinator import get_coordinator
    coord = get_coordinator()
    tasks = await coord.schedule_coop_publish(
        account_ids=data.get("account_ids", []),
        topic=data.get("topic", ""),
        text=data.get("text", ""),
        stagger_minutes=data.get("stagger_minutes", 30),
    )
    return {"ok": True, "tasks": len(tasks)}


# ── 账号健康度 API ───────────────────────────────────────────────────────────

@app.get("/api/health/overview")
async def health_overview():
    from .wechat.account_health import get_health_monitor
    return {"ok": True, **get_health_monitor().get_overview()}


@app.get("/api/health/accounts")
async def health_accounts():
    from .wechat.account_health import get_health_monitor
    return {"ok": True, "accounts": get_health_monitor().get_all_status()}


@app.get("/api/health/{account_id}")
async def health_account(account_id: str):
    from .wechat.account_health import get_health_monitor
    return {"ok": True, **get_health_monitor().get_status(account_id)}


@app.post("/api/health/check")
async def health_check():
    """手动触发心跳检查"""
    from .wechat.account_health import get_health_monitor
    await get_health_monitor().check_all_heartbeats()
    return {"ok": True, "accounts": get_health_monitor().get_all_status()}


# ── 话题跟踪 API ─────────────────────────────────────────────────────────────

@app.get("/api/topics")
async def topics_status(session: str = "default"):
    from .topic_tracker import get_tracker
    return {"ok": True, **get_tracker(session).get_status()}


# ── 通知聚合 API ─────────────────────────────────────────────────────────────

@app.get("/api/notifications/digest")
async def notif_digest(min_priority: int = 0, limit: int = 20):
    from .notification_aggregator import get_aggregator
    return {"ok": True, "groups": get_aggregator().get_digest(min_priority, limit)}


@app.get("/api/notifications/summary")
async def notif_summary():
    from .notification_aggregator import get_aggregator
    return {"ok": True, **get_aggregator().get_unread_summary()}


@app.post("/api/notifications/clear")
async def notif_clear(request: Request):
    data = await request.json()
    from .notification_aggregator import get_aggregator
    get_aggregator().clear_group(data.get("account_id", ""), data.get("contact", ""))
    return {"ok": True}


@app.post("/api/notifications/summarize")
async def notif_ai_summarize():
    """用 AI 为高优先级分组生成摘要"""
    from .notification_aggregator import get_aggregator
    agg = get_aggregator()
    if backend:
        await agg.generate_summaries(ai_call=backend.chat_simple)
    return {"ok": True, "groups": agg.get_digest(limit=10)}


# ── 意图预测 API ─────────────────────────────────────────────────────────────

@app.get("/api/intent")
async def intent_status(session: str = "default"):
    from .intent_predictor import get_predictor
    return {"ok": True, **get_predictor(session).get_status()}


# ── 联系人融合 API ───────────────────────────────────────────────────────────

@app.get("/api/contacts/discover-matches")
async def contacts_discover():
    from .wechat.contact_fusion import auto_discover_matches
    return {"ok": True, "matches": auto_discover_matches()}


@app.post("/api/contacts/fuse")
async def contacts_fuse(request: Request):
    data = await request.json()
    from .wechat.contact_fusion import create_fused_contact
    fc = create_fused_contact(
        display_name=data.get("display_name", ""),
        account_contacts=data.get("account_contacts", []),
        relationship=data.get("relationship", "normal"),
    )
    return {"ok": True, "id": fc.id}


@app.get("/api/contacts/fused")
async def contacts_fused_list():
    from .wechat.contact_fusion import list_fused_contacts
    return {"ok": True, "contacts": [c.to_dict() for c in list_fused_contacts()]}


@app.get("/api/contacts/fused/{fused_id}")
async def contacts_fused_detail(fused_id: str):
    from .wechat.contact_fusion import get_360_view
    return {"ok": True, **get_360_view(fused_id)}


@app.post("/api/contacts/fused/{fused_id}/merge")
async def contacts_fuse_merge(fused_id: str, request: Request):
    data = await request.json()
    from .wechat.contact_fusion import merge_contacts
    ok = merge_contacts(fused_id, data.get("account_id", ""), data.get("name", ""))
    return {"ok": ok}


@app.delete("/api/contacts/fused/{fused_id}")
async def contacts_fuse_delete(fused_id: str):
    from .wechat.contact_fusion import delete_fused_contact
    delete_fused_contact(fused_id)
    return {"ok": True}


# ── 工作流模板 API ───────────────────────────────────────────────────────────

@app.get("/api/templates")
async def templates_list(category: str = ""):
    from .workflow.template_store import list_templates, get_template_categories
    return {"ok": True, "templates": list_templates(category), "categories": get_template_categories()}


@app.get("/api/templates/{tpl_id}")
async def templates_detail(tpl_id: str):
    from .workflow.template_store import get_template
    tpl = get_template(tpl_id)
    return {"ok": True, "template": tpl} if tpl else {"ok": False, "error": "模板不存在"}


@app.post("/api/templates/{tpl_id}/install")
async def templates_install(tpl_id: str, request: Request):
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    from .workflow.template_store import install_template
    wf_id = install_template(tpl_id, custom_name=data.get("name", ""))
    if wf_id:
        return {"ok": True, "workflow_id": wf_id}
    return {"ok": False, "error": "安装失败"}


@app.get("/api/workflows/{wf_id}/export")
async def workflow_export(wf_id: str):
    from .workflow.template_store import export_workflow
    data = export_workflow(wf_id)
    if data:
        return {"ok": True, "workflow": data}
    return {"ok": False, "error": "工作流不存在"}


@app.post("/api/workflows/import")
async def workflow_import(request: Request):
    data = await request.json()
    from .workflow.template_store import import_workflow
    wf_data = data.get("workflow", data)
    wf_id = import_workflow(wf_data, custom_name=data.get("name", ""))
    if wf_id:
        return {"ok": True, "workflow_id": wf_id}
    return {"ok": False, "error": "导入失败"}


# ── 日报系统 API ─────────────────────────────────────────────────────────────

@app.post("/api/daily-report")
async def daily_report_generate():
    from .daily_report import generate_and_cache
    ai_call = backend.chat_simple if backend else None
    report = await generate_and_cache(ai_call)
    return {"ok": True, **report.to_dict()}


@app.get("/api/daily-report")
async def daily_report_get():
    from .daily_report import get_last_report, generate_and_cache
    report = get_last_report()
    if not report:
        ai_call = backend.chat_simple if backend else None
        report = await generate_and_cache(ai_call)
    return {"ok": True, **report.to_dict()}


@app.get("/api/daily-report/text")
async def daily_report_text():
    from .daily_report import get_last_report
    report = get_last_report()
    if not report:
        return {"ok": False, "text": "暂无日报，请先生成"}
    return {"ok": True, "text": report.to_text()}


# ── 异常检测 API ─────────────────────────────────────────────────────────────

@app.get("/api/anomaly/status")
async def anomaly_status():
    from .anomaly_detector import get_detector
    return {"ok": True, **get_detector().get_status()}


@app.get("/api/anomaly/alerts")
async def anomaly_alerts(limit: int = 20):
    from .anomaly_detector import get_detector
    return {"ok": True, "alerts": get_detector().get_recent_alerts(limit)}


@app.post("/api/anomaly/reset/{account_id}")
async def anomaly_reset(account_id: str):
    from .anomaly_detector import get_detector
    get_detector().reset_circuit_breaker(account_id)
    return {"ok": True}


@app.post("/api/anomaly/check")
async def anomaly_check_now():
    """手动触发异常检查"""
    from .anomaly_detector import get_detector
    from .wechat.account_health import get_health_monitor
    detector = get_detector()
    all_alerts = []
    for m in get_health_monitor().get_all_status():
        alerts = detector.check(
            m["account_id"],
            current_send=m["send_rate_per_hour"],
            current_error=m["error_rate_per_hour"],
        )
        all_alerts.extend(alerts)
    return {"ok": True, "alerts": [a.to_dict() for a in all_alerts]}


# ── 知识库 API ───────────────────────────────────────────────────────────────

@app.get("/api/knowledge")
async def knowledge_list():
    from .knowledge_base import list_documents, get_stats
    return {"ok": True, "documents": list_documents(), **get_stats()}


@app.post("/api/knowledge/import")
async def knowledge_import(request: Request):
    data = await request.json()
    from .knowledge_base import import_document
    doc_id = import_document(
        title=data.get("title", "未命名文档"),
        content=data.get("content", ""),
        source=data.get("source", ""),
        chunk_size=data.get("chunk_size", 500),
    )
    return {"ok": True, "doc_id": doc_id}


@app.post("/api/knowledge/search")
async def knowledge_search(request: Request):
    data = await request.json()
    from .knowledge_base import search
    results = search(data.get("query", ""), top_k=data.get("top_k", 5))
    return {"ok": True, "results": results}


@app.delete("/api/knowledge/{doc_id}")
async def knowledge_delete(doc_id: str):
    from .knowledge_base import delete_document
    delete_document(doc_id)
    return {"ok": True}


# ── 情感分析 API ─────────────────────────────────────────────────────────────

@app.get("/api/sentiment/overview")
async def sentiment_overview():
    from .sentiment_analyzer import get_overview
    return {"ok": True, **get_overview()}


@app.get("/api/sentiment/trend")
async def sentiment_trend(hours: int = 24, account_id: str = ""):
    from .sentiment_analyzer import get_trend
    return {"ok": True, "trend": get_trend(hours, account_id)}


@app.get("/api/sentiment/contact/{contact}")
async def sentiment_contact(contact: str):
    from .sentiment_analyzer import get_contact_sentiment
    return {"ok": True, **get_contact_sentiment(contact)}


# ── 群聊管理 API ─────────────────────────────────────────────────────────────

@app.get("/api/groups")
async def groups_list():
    from .wechat.group_manager import get_group_manager
    return {"ok": True, "groups": get_group_manager().get_all_groups()}


@app.get("/api/groups/{group_name}")
async def group_stats(group_name: str):
    from .wechat.group_manager import get_group_manager
    stats = get_group_manager().get_group_stats(group_name)
    return {"ok": True, **(stats or {})}


@app.get("/api/groups/{group_name}/important")
async def group_important(group_name: str, limit: int = 20):
    from .wechat.group_manager import get_group_manager
    msgs = get_group_manager().get_important_messages(group_name, limit)
    return {"ok": True, "messages": msgs}


@app.post("/api/groups/{group_name}/summary")
async def group_summary(group_name: str):
    from .wechat.group_manager import get_group_manager
    ai_call = backend.chat_simple if backend else None
    summary = await get_group_manager().generate_summary(group_name, ai_call)
    return {"ok": True, "summary": summary}


# ── 工作流可视化编辑器 API ───────────────────────────────────────────────────

@app.get("/api/workflow-editor/node-types")
async def wf_editor_node_types():
    from .workflow.visual_editor import node_type_info
    return {"ok": True, "types": node_type_info()}


@app.post("/api/workflow-editor/visualize")
async def wf_editor_visualize(request: Request):
    data = await request.json()
    from .workflow.visual_editor import workflow_to_visual
    return {"ok": True, **workflow_to_visual(data)}


@app.post("/api/workflow-editor/validate")
async def wf_editor_validate(request: Request):
    data = await request.json()
    from .workflow.visual_editor import validate_workflow
    errors = validate_workflow(data)
    return {"ok": len(errors) == 0, "errors": errors}


@app.post("/api/workflow-editor/dry-run")
async def wf_editor_dry_run(request: Request):
    data = await request.json()
    from .workflow.visual_editor import dry_run
    steps = dry_run(data)
    return {"ok": True, "steps": steps}


# ── 插件系统 API ─────────────────────────────────────────────────────────────

@app.get("/api/plugins")
async def plugins_list():
    from .plugin_system import get_plugin_manager
    pm = get_plugin_manager()
    return {"ok": True, "plugins": pm.list_plugins(), **pm.get_stats()}


@app.post("/api/plugins/{plugin_id}/enable")
async def plugin_enable(plugin_id: str):
    from .plugin_system import get_plugin_manager
    ok = get_plugin_manager().enable(plugin_id)
    try:
        from . import audit_log
        audit_log.log("plugin_toggle", target=plugin_id, detail="enable")
    except Exception:
        pass
    return {"ok": ok}


@app.post("/api/plugins/{plugin_id}/disable")
async def plugin_disable(plugin_id: str):
    from .plugin_system import get_plugin_manager
    ok = get_plugin_manager().disable(plugin_id)
    try:
        from . import audit_log
        audit_log.log("plugin_toggle", target=plugin_id, detail="disable")
    except Exception:
        pass
    return {"ok": ok}


@app.get("/api/plugins/{plugin_id}")
async def plugin_detail(plugin_id: str):
    from .plugin_system import get_plugin_manager
    info = get_plugin_manager().get_plugin(plugin_id)
    return {"ok": bool(info), **(info or {})}


# ── 上下文压缩 API ───────────────────────────────────────────────────────────

@app.get("/api/compressor/stats")
async def compressor_stats():
    from .context_compressor import get_compressor
    return {"ok": True, **get_compressor().get_stats()}


# ── WebSocket 实时推送（双通道） ────────────────────────────────────────────

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """WebSocket 事件推送 — 替代 SSE，支持客户端过滤"""
    from .event_bus import get_bus
    await websocket.accept()

    client_id = id(websocket)
    bus = get_bus()
    queue = bus.register_ws(client_id)
    logger.info(f"WebSocket 事件客户端连接 #{client_id}")

    try:
        send_task = asyncio.create_task(_ws_event_sender(websocket, queue))
        recv_task = asyncio.create_task(_ws_event_receiver(websocket, bus, client_id))
        done, pending = await asyncio.wait(
            {send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS events error: {e}")
    finally:
        bus.unregister_ws(client_id)
        logger.info(f"WebSocket 事件客户端断开 #{client_id}")


async def _ws_event_sender(websocket: WebSocket, queue: asyncio.Queue):
    while True:
        event = await queue.get()
        await websocket.send_json(event)


async def _ws_event_receiver(websocket: WebSocket, bus, client_id: int):
    """接收客户端指令：subscribe/unsubscribe 事件类型过滤"""
    while True:
        try:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            cmd = msg.get("cmd", "")
            if cmd == "subscribe":
                types = set(msg.get("types", []))
                bus.update_ws_filters(client_id, types if types else None)
            elif cmd == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
        except (WebSocketDisconnect, Exception):
            break


# ── 对话记忆搜索 API ──────────────────────────────────────────────────────────

@app.get("/api/memory/search")
async def memory_search(
    q: str = "", session: str = "", role: str = "",
    start: str = "", end: str = "", limit: int = 50, offset: int = 0,
):
    from .memory_search import search
    return {"ok": True, **search(q, session, role, start, end, limit, offset)}


@app.get("/api/memory/sessions")
async def memory_sessions():
    from .memory_search import get_sessions
    return {"ok": True, "sessions": get_sessions()}


@app.get("/api/memory/stats")
async def memory_stats():
    from .memory_search import get_stats
    return {"ok": True, **get_stats()}


# ── 系统健康检查 API ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    from .health_check import get_health_checker
    checker = get_health_checker()
    results = await checker.run_all()
    return {"ok": True, **checker.get_summary()}


@app.post("/api/health/recheck")
async def health_recheck():
    from .health_check import get_health_checker
    checker = get_health_checker()
    await checker.run_all(force=True)
    return {"ok": True, **checker.get_summary()}


# ── 国际化 API ────────────────────────────────────────────────────────────────

@app.get("/api/i18n/translations")
async def i18n_translations(lang: str = ""):
    from .i18n import get_all_translations, get_language
    return {"ok": True, "lang": lang or get_language(), "translations": get_all_translations(lang)}


@app.post("/api/i18n/language")
async def i18n_set_language(request: Request):
    data = await request.json()
    from .i18n import set_language, get_language
    set_language(data.get("lang", "zh"))
    return {"ok": True, "lang": get_language()}


@app.get("/api/i18n/languages")
async def i18n_languages():
    from .i18n import get_supported_languages
    return {"ok": True, "languages": get_supported_languages()}


# ── 审计日志 API ──────────────────────────────────────────────────────────────

@app.get("/api/audit/logs")
async def audit_logs(
    action: str = "", actor: str = "", severity: str = "",
    limit: int = 50, offset: int = 0,
):
    from . import audit_log
    return {"ok": True, **audit_log.query(action, actor, severity, limit=limit, offset=offset)}


@app.get("/api/audit/stats")
async def audit_stats():
    from . import audit_log
    return {"ok": True, **audit_log.get_stats()}


# ── 速率限制 API ──────────────────────────────────────────────────────────────

@app.get("/api/ratelimit/stats")
async def ratelimit_stats():
    from .rate_limiter import get_limiter
    return {"ok": True, **get_limiter().get_stats()}


# ── 事件总线统计 API ──────────────────────────────────────────────────────────

@app.get("/api/events/stats")
async def events_stats():
    from .event_bus import get_bus
    bus = get_bus()
    return {"ok": True, "subscribers": bus.subscriber_count, "ws_clients": bus.ws_count, **bus.get_persist_stats()}


# ── 大屏数据 API ─────────────────────────────────────────────────────────────

@app.get("/api/dashboard/realtime")
async def dashboard_realtime():
    """大屏实时数据聚合端点"""
    result = {}
    try:
        from .wechat.unified_inbox import get_inbox_stats
        result["inbox"] = get_inbox_stats()
    except Exception:
        result["inbox"] = {}
    try:
        from .wechat.account_health import get_health_monitor
        result["health"] = get_health_monitor().get_overview()
        result["accounts"] = get_health_monitor().get_all_status()
    except Exception:
        result["health"] = {}
    try:
        from .workflow.store import get_stats as wf_stats
        result["workflows"] = wf_stats()
    except Exception:
        result["workflows"] = {}
    try:
        from .notification_aggregator import get_aggregator
        result["notifications"] = get_aggregator().get_unread_summary()
    except Exception:
        result["notifications"] = {}
    try:
        from .anomaly_detector import get_detector
        result["anomaly"] = {
            "breakers": get_detector()._circuit_breakers,
            "recent_alerts": len(get_detector()._alerts),
        }
    except Exception:
        result["anomaly"] = {}
    try:
        from .knowledge_base import get_stats as kb_stats
        result["knowledge"] = kb_stats()
    except Exception:
        result["knowledge"] = {}
    return {"ok": True, **result}


# ── 数据导出 API ──────────────────────────────────────────────────────────────

@app.get("/api/export/analytics")
async def export_analytics(days: int = 30):
    from .data_export import export_analytics_csv
    content = export_analytics_csv(days)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=analytics_{days}d.csv"},
    )


@app.get("/api/export/contacts")
async def export_contacts():
    from .data_export import export_contacts_csv
    content = export_contacts_csv()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@app.get("/api/export/workflows")
async def export_workflows():
    from .data_export import export_workflows_json
    content = export_workflows_json()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=workflows.json"},
    )


@app.get("/api/export/conversations")
async def export_conversations(session: str = "default"):
    from .data_export import export_conversations_json
    content = export_conversations_json(session)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=conversations_{session}.json"},
    )


@app.get("/api/export/messages")
async def export_messages(
    source: str = "memory", session: str = "", contact: str = "",
    account_id: str = "", start: str = "", end: str = "",
    fmt: str = "csv", sentiment: bool = False,
):
    """导出消息报表：CSV / HTML / JSON"""
    from .message_export import export_conversations as do_export
    result = do_export(source, session, contact, account_id, start, end, fmt, sentiment)
    return Response(
        content=result["content"],
        media_type=result["mime"],
        headers={"Content-Disposition": f"attachment; filename={result['filename']}"},
    )


@app.get("/api/export/rules")
async def export_rules():
    from .data_export import export_rules_json
    content = export_rules_json()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=msg_rules.json"},
    )


@app.get("/api/export/report")
async def export_report(days: int = 30):
    from .data_export import export_full_report_json
    content = export_full_report_json(days)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=full_report.json"},
    )


# ── 统一日历 API ──────────────────────────────────────────────────────────────

@app.get("/api/calendar")
async def calendar_events(year: int = 0, month: int = 0):
    """
    聚合所有定时任务到统一日历视图。
    来源：工作流定时/周期触发、朋友圈内容日历、群发计划。
    """
    import calendar as cal_mod
    from datetime import datetime, timedelta

    now = datetime.now()
    y = year or now.year
    m = month or now.month
    _, days_in_month = cal_mod.monthrange(y, m)

    events = []

    # 1. 工作流定时任务
    try:
        from .workflow.store import store
        from .workflow.models import TriggerType
        all_wf = store.list_workflows()
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        for wf in all_wf:
            if not wf.enabled:
                continue
            t = wf.trigger
            if t.type == TriggerType.SCHEDULE and t.time:
                for d in range(1, days_in_month + 1):
                    dt = datetime(y, m, d)
                    weekday = day_names[dt.weekday()]
                    if t.days and weekday not in t.days:
                        continue
                    events.append({
                        "date": f"{y}-{m:02d}-{d:02d}",
                        "time": t.time,
                        "title": wf.name,
                        "icon": wf.icon or "🔄",
                        "type": "workflow",
                        "id": wf.id,
                    })
            elif t.type == TriggerType.INTERVAL and t.seconds > 0:
                events.append({
                    "date": f"{y}-{m:02d}-01",
                    "time": "",
                    "title": f"{wf.name} (每{t.seconds//60}分钟)",
                    "icon": wf.icon or "🔄",
                    "type": "interval",
                    "id": wf.id,
                })
    except Exception:
        pass

    # 2. 朋友圈内容日历
    try:
        from .wechat.moments_tracker import ContentCalendar
        calendar = ContentCalendar()
        for entry in calendar.list_entries(y, m):
            events.append({
                "date": entry.get("date", ""),
                "time": entry.get("time", "12:00"),
                "title": entry.get("topic", "朋友圈发布"),
                "icon": "📢",
                "type": "moment",
                "id": entry.get("id", ""),
            })
    except Exception:
        pass

    # 3. 执行历史热力数据
    heatmap = {}
    try:
        from .workflow.store import store as wf_store_inst
        execs = wf_store_inst.list_executions(limit=500)
        for ex in execs:
            if ex.started_at:
                from datetime import datetime as _dt
                d = _dt.fromtimestamp(ex.started_at)
                if d.year == y and d.month == m:
                    key = f"{y}-{m:02d}-{d.day:02d}"
                    heatmap[key] = heatmap.get(key, 0) + 1
    except Exception:
        pass

    return {"ok": True, "year": y, "month": m, "events": events, "heatmap": heatmap}


# ── 多账号并行管理 API ────────────────────────────────────────────────────────

@app.get("/api/accounts")
async def accounts_list():
    from .wechat.account_manager import list_accounts, ensure_default_account
    ensure_default_account()
    return {"ok": True, "accounts": [a.to_dict() for a in list_accounts()]}


@app.post("/api/accounts")
async def accounts_save(request: Request):
    data = await request.json()
    from .wechat.account_manager import WeChatAccount, save_account
    acct = WeChatAccount(
        id=data.get("id", ""),
        name=data.get("name", "新账号"),
        wx_name=data.get("wx_name", ""),
        notes=data.get("notes", ""),
        autoreply_config=data.get("autoreply_config", {}),
        moments_config=data.get("moments_config", {}),
    )
    save_account(acct)
    return {"ok": True, "id": acct.id}


@app.get("/api/accounts/discover")
async def accounts_discover():
    """扫描当前系统中所有运行的微信窗口"""
    from .wechat.account_manager import discover_instances
    instances = discover_instances()
    return {"ok": True, "instances": [
        {"hwnd": i.hwnd, "pid": i.pid, "title": i.title,
         "wx_name": i.wx_name, "bound_account_id": i.bound_account_id}
        for i in instances
    ]}


@app.post("/api/accounts/{acct_id}/bind")
async def accounts_bind(acct_id: str, request: Request):
    """将账号绑定到指定的微信窗口句柄"""
    data = await request.json()
    hwnd = data.get("hwnd", 0)
    if not hwnd:
        return {"ok": False, "error": "请指定窗口句柄 hwnd"}
    from .wechat.account_manager import bind_account
    ok = bind_account(acct_id, hwnd)
    return {"ok": ok}


@app.post("/api/accounts/auto-bind")
async def accounts_auto_bind():
    """自动发现并绑定所有微信窗口"""
    from .wechat.account_manager import auto_bind_all
    result = auto_bind_all()
    return {"ok": True, "bound": result}


@app.post("/api/accounts/{acct_id}/disconnect")
async def accounts_disconnect(acct_id: str):
    """断开账号的微信连接"""
    from .wechat.account_manager import disconnect_account
    disconnect_account(acct_id)
    return {"ok": True}


@app.delete("/api/accounts/{acct_id}")
async def accounts_delete(acct_id: str):
    from .wechat.account_manager import delete_account
    delete_account(acct_id)
    return {"ok": True}


@app.get("/api/accounts/connected")
async def accounts_connected():
    """返回所有已连接的账号"""
    from .wechat.account_manager import get_all_connected
    return {"ok": True, "connected": get_all_connected()}


# ── 长期记忆 API ──────────────────────────────────────────────────────────────

@app.get("/api/memory/stats")
async def memory_stats(session: str = "default"):
    try:
        from .long_memory import get_memory_stats
        return {"ok": True, **get_memory_stats(session)}
    except ImportError:
        return {"ok": False, "error": "long_memory module not available"}


@app.post("/api/memory/compress")
async def memory_compress(request: Request):
    """手动触发记忆压缩"""
    data = await request.json()
    session = data.get("session", "default")
    try:
        from .long_memory import compress_old_messages
        backend = getattr(app.state, "ai_backend", None)
        ai_call = backend.chat_simple if backend else None
        count = await compress_old_messages(session, ai_call=ai_call)
        return {"ok": True, "compressed": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/memory/search")
async def memory_search(q: str, session: str = "default"):
    """检索相关记忆"""
    try:
        from .long_memory import retrieve_relevant
        segments = retrieve_relevant(session, q, top_k=5)
        return {"ok": True, "results": [
            {"summary": s.summary, "keywords": s.keywords, "relevance": round(s.relevance, 3)}
            for s in segments
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 系统监控 API ──────────────────────────────────────────────────────────────

@app.get("/api/router/status")
async def router_status():
    """AI Router 状态"""
    try:
        backend = getattr(app.state, "ai_backend", None)
        router = getattr(backend, "_router", None) if backend else None
        if not router:
            return {"ok": True, "providers": []}
        providers = []
        for p in getattr(router, "_providers", []):
            providers.append({
                "id": getattr(p, "id", "?"),
                "name": getattr(p, "name", getattr(p, "id", "?")),
                "model": getattr(p, "model", ""),
                "available": getattr(p, "available", True),
                "requests": getattr(p, "_request_count", 0),
                "avg_latency": round(getattr(p, "_avg_latency", 0)),
                "quota_remaining": getattr(p, "_remaining_quota_pct", 100),
            })
        return {"ok": True, "providers": providers}
    except Exception as e:
        return {"ok": False, "providers": [], "error": str(e)}


@app.get("/api/system/stats")
async def system_stats():
    """系统资源统计"""
    import time as _time
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_mb = round(process.memory_info().rss / 1024 / 1024, 1)
        cpu_pct = process.cpu_percent(interval=0)
        return {
            "ok": True,
            "memory_mb": mem_mb,
            "cpu_percent": cpu_pct,
            "threads": process.num_threads(),
            "uptime_seconds": round(_time.time() - process.create_time()),
        }
    except ImportError:
        return {"ok": True, "memory_mb": "N/A", "cpu_percent": 0, "threads": 0, "uptime_seconds": 0}


# ── 消息路由规则 API ──────────────────────────────────────────────────────────

@app.get("/api/msg-rules")
async def msg_rules_list():
    """列出所有消息路由规则"""
    from .wechat.msg_router import list_rules
    rules = list_rules()
    return {"ok": True, "rules": [r.to_dict() for r in rules]}


@app.post("/api/msg-rules")
async def msg_rules_save(request: Request):
    """创建/更新消息路由规则"""
    data = await request.json()
    from .wechat.msg_router import RoutingRule, save_rule
    rule = RoutingRule(
        id=data.get("id", ""),
        name=data.get("name", "新规则"),
        enabled=data.get("enabled", True),
        priority=data.get("priority", 50),
        match_type=data.get("match_type", "keyword"),
        match_pattern=data.get("match_pattern", ""),
        match_contacts=data.get("match_contacts", ""),
        action_type=data.get("action_type", "notify"),
        action_target=data.get("action_target", ""),
        action_params=data.get("action_params", {}),
        cooldown_seconds=data.get("cooldown_seconds", 60),
    )
    save_rule(rule)
    return {"ok": True, "id": rule.id}


@app.delete("/api/msg-rules/{rule_id}")
async def msg_rules_delete(rule_id: str):
    """删除消息路由规则"""
    from .wechat.msg_router import delete_rule
    delete_rule(rule_id)
    return {"ok": True}


@app.get("/api/msg-rules/stats")
async def msg_rules_stats():
    """消息路由统计"""
    from .wechat.msg_router import MessageRouter
    router = MessageRouter()
    return {"ok": True, **router.get_stats()}


@app.post("/api/msg-rules/suggest")
async def msg_rules_suggest():
    """AI 分析消息历史，建议新路由规则"""
    try:
        backend = getattr(app.state, "ai_backend", None)
        ai_call = backend.chat_simple if backend else None
        if not ai_call:
            return {"ok": False, "error": "AI backend not available"}
        from .wechat.msg_router import suggest_rules
        suggestions = await suggest_rules(ai_call)
        return {"ok": True, "suggestions": suggestions}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Ollama API ─────────────────────────────────────────────────────────────────

@app.get("/api/ollama/status")
async def ollama_status():
    """Ollama 状态"""
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        return {"available": False, "error": "bridge not initialized"}
    return {"ok": True, **bridge.get_status()}


@app.post("/api/ollama/check")
async def ollama_check():
    """重新检测 Ollama"""
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        from .ollama_bridge import OllamaBridge
        bridge = OllamaBridge()
        app.state.ollama_bridge = bridge
    health = await bridge.check_health()
    if health.available:
        try:
            from src.router.config import RouterConfig
            bridge.auto_enable_in_router(RouterConfig())
        except Exception:
            pass
    return {"ok": True, **bridge.get_status()}


@app.post("/api/ollama/pull")
async def ollama_pull(request: Request):
    """拉取模型"""
    data = await request.json()
    model = data.get("model", "qwen2.5:7b")
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge or not bridge.is_available:
        return {"ok": False, "error": "Ollama not available"}
    success = await bridge.pull_model(model)
    return {"ok": success}


@app.post("/api/ollama/benchmark")
async def ollama_benchmark(request: Request):
    """基准测试"""
    data = await request.json() if request.headers.get("content-type") else {}
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge or not bridge.is_available:
        return {"ok": False, "error": "Ollama not available"}
    result = await bridge.benchmark(data.get("model", ""))
    return {"ok": True, **result}


@app.delete("/api/ollama/models/{name}")
async def ollama_delete_model(name: str):
    """删除模型"""
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        return {"ok": False}
    success = await bridge.delete_model(name)
    return {"ok": success}


# ── 素材库 API ─────────────────────────────────────────────────────────────────

@app.get("/api/media/list")
async def media_list(category: str = "", tag: str = "", limit: int = 50):
    """列出素材"""
    from .wechat.media_library import list_media, get_stats, get_categories
    return {
        "ok": True,
        "media": list_media(category=category, tag=tag, limit=limit),
        "stats": get_stats(),
        "categories": get_categories(),
    }


@app.post("/api/media/import")
async def media_import(request: Request):
    """导入素材"""
    data = await request.json()
    path = data.get("path", "")
    category = data.get("category", "")
    from .wechat.media_library import import_file, import_directory
    if Path(path).is_dir():
        results = import_directory(path, category)
    else:
        r = import_file(path, category)
        results = [r] if r else []
    return {"ok": True, "imported": len(results), "results": results}


@app.post("/api/media/match")
async def media_match(request: Request):
    """根据文案匹配配图"""
    data = await request.json()
    text = data.get("text", "")
    count = data.get("count", 3)
    from .wechat.media_library import match_images
    images = match_images(text, count=count, category_hint=data.get("category", ""))
    return {"ok": True, "images": images}


@app.post("/api/media/analyze/{media_id}")
async def media_analyze(media_id: str):
    """AI 分析素材"""
    ai = getattr(app.state, "ai_backend", None)
    if not ai:
        return {"ok": False, "error": "AI backend not available"}

    async def vision_call(b64, prompt):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]
        if hasattr(ai, '_vision_client') and ai._vision_client:
            resp = await ai._vision_client.chat.completions.create(
                model=ai._vision_model, messages=messages, max_tokens=300
            )
            return resp.choices[0].message.content
        return ""

    from .wechat.media_library import analyze_media
    result = await analyze_media(media_id, vision_call)
    return {"ok": bool(result), "analysis": result}


@app.delete("/api/media/{media_id}")
async def media_delete(media_id: str):
    from .wechat.media_library import delete_media
    return {"ok": delete_media(media_id)}


# ── 数据分析 API ───────────────────────────────────────────────────────────────

@app.get("/api/analytics/overview")
async def analytics_overview(days: int = 30):
    from .wechat.moments_analytics import get_overview
    return {"ok": True, **get_overview(days)}


@app.get("/api/analytics/hourly")
async def analytics_hourly(days: int = 30):
    from .wechat.moments_analytics import get_hourly_distribution
    return {"ok": True, "distribution": get_hourly_distribution(days)}


@app.get("/api/analytics/top-contacts")
async def analytics_top_contacts(days: int = 30, limit: int = 10):
    from .wechat.moments_analytics import get_top_contacts
    return {"ok": True, "contacts": get_top_contacts(days, limit)}


@app.get("/api/analytics/content-performance")
async def analytics_content_perf(days: int = 30):
    from .wechat.moments_analytics import get_content_performance
    return {"ok": True, "performance": get_content_performance(days)}


@app.get("/api/analytics/best-times")
async def analytics_best_times(days: int = 30):
    from .wechat.moments_analytics import get_best_posting_times
    return {"ok": True, **get_best_posting_times(days)}


@app.get("/api/analytics/weekly-trend")
async def analytics_weekly_trend(weeks: int = 8):
    from .wechat.moments_analytics import get_weekly_trend
    return {"ok": True, "trend": get_weekly_trend(weeks)}


@app.post("/api/analytics/strategy-report")
async def analytics_strategy_report(days: int = 30):
    ai = getattr(app.state, "ai_backend", None)
    ai_call = ai.chat_simple if ai else None
    from .wechat.moments_analytics import generate_strategy_report
    report = await generate_strategy_report(ai_call, days)
    return {"ok": True, "report": report}


# ── 群发 API ───────────────────────────────────────────────────────────────────

@app.get("/api/broadcast/templates")
async def broadcast_templates():
    from .wechat.broadcast import list_templates, ensure_builtin_templates
    ensure_builtin_templates()
    return {"ok": True, "templates": list_templates()}


@app.post("/api/broadcast/templates")
async def broadcast_save_template(request: Request):
    data = await request.json()
    from .wechat.broadcast import MessageTemplate, save_template
    tpl = MessageTemplate(
        name=data.get("name", ""),
        content=data.get("content", ""),
        variables=data.get("variables", []),
        category=data.get("category", ""),
    )
    save_template(tpl)
    return {"ok": True, "template": tpl.to_dict()}


@app.delete("/api/broadcast/templates/{tid}")
async def broadcast_delete_template(tid: str):
    from .wechat.broadcast import delete_template
    return {"ok": delete_template(tid)}


@app.post("/api/broadcast/filter-audience")
async def broadcast_filter_audience(request: Request):
    data = await request.json()
    from .wechat.broadcast import filter_audience
    audience = filter_audience(
        min_intimacy=data.get("min_intimacy", 0),
        max_intimacy=data.get("max_intimacy", 100),
        relationship=data.get("relationship", ""),
        interests=data.get("interests"),
        exclude=data.get("exclude"),
    )
    return {"ok": True, "audience": audience, "count": len(audience)}


@app.post("/api/broadcast/send")
async def broadcast_send(request: Request):
    data = await request.json()
    from .wechat.broadcast import BroadcastCampaign, BroadcastEngine

    campaign = BroadcastCampaign(
        name=data.get("name", "群发任务"),
        message=data.get("message", ""),
        targets=data.get("targets", []),
        personalize=data.get("personalize", False),
    )

    ai = getattr(app.state, "ai_backend", None)
    ai_call = ai.chat_simple if ai else None

    async def send_fn(contact: str, msg: str) -> bool:
        try:
            from .wechat.wxauto_reader import WxAutoReader
            reader = WxAutoReader()
            if reader._wx:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: reader._wx.SendMsg(msg, contact)
                )
                return True
        except Exception as e:
            logger.warning(f"Broadcast send failed: {contact}: {e}")
        return False

    from .event_bus import publish as pub_event

    def progress_cb(current, total, contact, sent, failed):
        pub_event("broadcast_progress", {
            "current": current, "total": total,
            "contact": contact, "sent": sent, "failed": failed,
        })

    engine = BroadcastEngine(send_fn=send_fn, ai_call=ai_call)
    result = await engine.execute_campaign(campaign, progress_cb=progress_cb)
    pub_event("broadcast_complete", result)
    try:
        from . import audit_log
        audit_log.log("broadcast_send", target=campaign.name,
                      detail=f"targets={len(campaign.targets)}, sent={result.get('sent',0)}")
    except Exception:
        pass
    return {"ok": True, **result}


@app.get("/api/broadcast/campaigns")
async def broadcast_campaigns():
    from .wechat.broadcast import BroadcastEngine
    engine = BroadcastEngine()
    return {"ok": True, "campaigns": engine.get_campaigns()}


@app.get("/api/broadcast/stats")
async def broadcast_stats():
    from .wechat.broadcast import BroadcastEngine
    engine = BroadcastEngine()
    return {"ok": True, **engine.get_daily_stats()}


if __name__ == "__main__":
    import asyncio
    import uvicorn

    ca_crt, server_crt, server_key = ensure_certs("certs")
    lan_ips = get_lan_ips()
    port = settings.port
    http_port = settings.http_port if settings.http_port > 0 else port + 1

    _ensure_firewall_rules(http_port, port)

    logger.info("=" * 60)
    logger.info("  OpenClaw Voice — 双端服务器")
    logger.info("=" * 60)
    for ip in lan_ips:
        if ip != "127.0.0.1":
            logger.info(f"  📱 扫码聊天(HTTP): http://{ip}:{http_port}/chat")
            logger.info(f"  🖥️  二维码展示:     http://{ip}:{http_port}/qr")
            logger.info(f"  🔐 完整版(HTTPS):  https://{ip}:{port}/app")
            logger.info(f"  📋 证书安装:        https://{ip}:{port}/setup")
    logger.info(f"  💻 本地完整版:     https://localhost:{port}/app")
    logger.info("=" * 60)

    https_config = uvicorn.Config(
        "src.server.main:app",
        host=settings.host,
        port=port,
        ssl_keyfile=server_key,
        ssl_certfile=server_crt,
        reload=False,
        log_level="info",
    )
    http_config = uvicorn.Config(
        "src.server.main:app",
        host=settings.host,
        port=http_port,
        reload=False,
        log_level="warning",  # quieter for the secondary server
    )

    async def serve_both():
        https_server = uvicorn.Server(https_config)
        http_server = uvicorn.Server(http_config)

        async def _open_browser():
            """Wait for HTTP server to start, then open QR page in browser."""
            await asyncio.sleep(2.0)
            import webbrowser
            qr_url = f"http://localhost:{http_port}/qr"
            logger.info(f"🌐 自动打开浏览器: {qr_url}")
            webbrowser.open(qr_url)

        await asyncio.gather(
            https_server.serve(),
            http_server.serve(),
            _open_browser(),
        )

    asyncio.run(serve_both())
