"""
OpenClaw Voice Server

Modular FastAPI application with route handlers split into:
  routers/voice.py    — STT/TTS/WebSocket voice pipeline
  routers/desktop.py  — Desktop control, file upload, remote streaming
  routers/wechat.py   — WeChat auto-reply, Moments, contacts, broadcast, media
  routers/workflow.py  — Workflow engine, templates, visual editor, calendar
  routers/admin.py    — Events, health, i18n, audit, export, monitoring, Ollama
"""

import asyncio
import base64
import json
import os
import re
import socket
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from loguru import logger
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from starlette.responses import StreamingResponse

from .stt import WhisperSTT
from .tts import ChatterboxTTS
from .backend import AIBackend
from .vad import VoiceActivityDetector
from .auth import token_manager, load_keys_from_env, APIKey, ip_limiter, key_limiter
from .text_utils import clean_for_speech
from .certs import ensure_certs, generate_mobileconfig, get_lan_ips
from .desktop import DesktopStreamer
from .desktop_skills import list_skills, get_skill, get_skills_prompt_section
from . import db as _db
from . import memory as mem_store

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PROVIDERS_JSON = _PROJECT_ROOT / "src" / "router" / "providers.json"

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
_wechat_adapter = None
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


# ═══════════════════════════════════════════════════════════════════
# Settings & App Creation
# ═══════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8765
    require_auth: bool = False
    master_key: Optional[str] = None
    stt_model: str = "base"
    stt_device: str = "auto"
    stt_language: Optional[str] = "zh"
    tts_model: str = "chatterbox"
    tts_voice: Optional[str] = None
    backend_type: str = "openai"
    backend_url: str = "https://api.openai.com/v1"
    backend_model: str = "gpt-4o-mini"
    openai_api_key: Optional[str] = None
    openclaw_gateway_url: Optional[str] = None
    openclaw_gateway_token: Optional[str] = None
    http_port: int = 0
    sample_rate: int = 16000

    class Config:
        env_prefix = "OPENCLAW_"
        env_file = ".env"
        extra = "ignore"


settings = Settings()

def _read_version():
    vf = _PROJECT_ROOT / "version.txt"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "3.2.0"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup + shutdown in one place."""
    await _startup(app)
    yield
    await _shutdown()

app = FastAPI(title="OpenClaw Voice", version=_read_version(), lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """Ensure all unhandled errors return JSON instead of HTML error pages."""
    logger.error(f"Unhandled exception on {request.url.path}: {exc}")
    return Response(
        content=json.dumps({"ok": False, "error": f"服务器内部错误: {str(exc)[:200]}"}),
        status_code=500,
        media_type="application/json",
    )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """API rate limiting middleware"""
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


_PROTECTED_WRITE_PATHS = {
    "/api/restart", "/api/update/apply", "/api/history",
    "/api/setup/save-key", "/api/setup/finish", "/api/stt/save-key",
    "/api/keys", "/api/wechat/toggle",
}

@app.middleware("http")
async def write_protection_middleware(request: Request, call_next):
    if request.method in ("DELETE", "POST", "PUT", "PATCH"):
        path = request.url.path.rstrip("/")
        if path in _PROTECTED_WRITE_PATHS or path.startswith("/api/wechat/"):
            client_ip = request.client.host if request.client else ""
            is_local = client_ip in ("127.0.0.1", "::1", "localhost") or \
                       client_ip.startswith("192.168.") or \
                       client_ip.startswith("10.") or \
                       client_ip.startswith("172.")
            if not is_local and not settings.require_auth:
                return Response(
                    content=json.dumps({"error": "Access denied: non-LAN request blocked"}),
                    status_code=403,
                    media_type="application/json",
                )
    return await call_next(request)


# ═══════════════════════════════════════════════════════════════════
# Global Instances
# ═══════════════════════════════════════════════════════════════════

stt: Optional[WhisperSTT] = None
tts: Optional[ChatterboxTTS] = None
backend: Optional[AIBackend] = None
vad: Optional[VoiceActivityDetector] = None
desktop: Optional[DesktopStreamer] = None


# ═══════════════════════════════════════════════════════════════════
# Include Routers
# ═══════════════════════════════════════════════════════════════════

from .routers.voice import router as voice_router
from .routers.desktop import router as desktop_router
from .routers.wechat import router as wechat_router
from .routers.workflow import router as workflow_router
from .routers.admin import router as admin_router
from .routers.models import router as models_router
from .routers.mcp import router as mcp_router

app.include_router(voice_router)
app.include_router(desktop_router)
app.include_router(wechat_router)
app.include_router(workflow_router)
app.include_router(admin_router)
app.include_router(models_router)
app.include_router(mcp_router)


# ═══════════════════════════════════════════════════════════════════
# Startup / Shutdown
# ═══════════════════════════════════════════════════════════════════

async def _startup(app: FastAPI):
    """Initialize models on server start."""
    global stt, tts, backend, vad

    logger.info("Initializing OpenClaw Voice server...")

    # 初始化统一数据库（合并 13 个独立 SQLite → 2 个）
    _db.init_schemas()
    _db.migrate_from_old_dbs()

    # 清理过大消息（需在 schema 初始化后执行）
    try:
        mem_store.cleanup_oversized_messages()
    except Exception as e:
        logger.warning(f"DB cleanup failed (non-fatal): {e}")

    load_keys_from_env()
    if settings.require_auth:
        logger.info("🔐 Authentication ENABLED")
    else:
        logger.warning("⚠️ Authentication DISABLED (dev mode)")

    logger.info(f"Loading STT model: {settings.stt_model}")
    stt = WhisperSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        language=settings.stt_language,
    )
    logger.info(f"STT language: {settings.stt_language or 'auto'}")

    logger.info(f"Loading TTS model: {settings.tts_model}")
    tts = ChatterboxTTS(voice_sample=settings.tts_voice)

    gateway_url = settings.openclaw_gateway_url or os.getenv("OPENCLAW_GATEWAY_URL")
    gateway_token = settings.openclaw_gateway_token or os.getenv("OPENCLAW_GATEWAY_TOKEN")
    zhipu_vision_key = os.getenv("ZHIPU_VISION_API_KEY") or os.getenv("ZHIPU_API_KEY")
    zhipu_vision_model = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
    if zhipu_vision_key:
        logger.info(f"🖼️ Zhipu vision configured: {zhipu_vision_model}")

    # Gateway health check: async，不阻塞 event loop
    use_gateway = False
    if gateway_url and gateway_token:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(
                    f"{gateway_url}/v1/models",
                    headers={"Authorization": f"Bearer {gateway_token}"},
                )
                if r.status_code < 500:
                    use_gateway = True
                    logger.info(f"🦞 OpenClaw Gateway reachable: {gateway_url}")
        except Exception:
            logger.warning(f"⚠️ OpenClaw Gateway unreachable ({gateway_url}), falling back to direct API")

    # Fallback: use Zhipu API key directly via Router
    zhipu_key = os.getenv("ZHIPU_API_KEY")
    fallback_url = "https://open.bigmodel.cn/api/paas/v4"
    fallback_model = "glm-4-flash"

    if use_gateway:
        logger.info(f"🦞 Connecting to OpenClaw gateway: {gateway_url}")
        backend = AIBackend(
            backend_type="openai",
            url=f"{gateway_url}/v1",
            model="openclaw:voice",
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
    elif zhipu_key:
        logger.info(f"🔗 Direct connect to Zhipu GLM-4-Flash (free, unlimited)")
        backend = AIBackend(
            backend_type="openai",
            url=fallback_url,
            model=fallback_model,
            api_key=zhipu_key,
            system_prompt=(
                "你是十三香小龙虾，一个智能语音助手。回答简洁口语化，1-2句话为主，"
                "除非用户明确要求详细说明。用中文回答。"
            ),
            vision_api_key=zhipu_vision_key,
            vision_model=zhipu_vision_model,
        )
    else:
        logger.info(f"Connecting to backend: {settings.backend_type}")
        backend = AIBackend(
            backend_type=settings.backend_type,
            url=settings.backend_url,
            model=settings.backend_model,
            api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY"),
            vision_api_key=zhipu_vision_key,
            vision_model=zhipu_vision_model,
        )

    logger.info("Loading VAD model")
    vad = VoiceActivityDetector()
    app.state.ai_backend = backend

    # Expose desktop streamer from routers/desktop.py for wechat module
    global desktop
    try:
        from .routers.desktop import desktop as _desk
        desktop = _desk
    except Exception:
        pass

    # Workflow + Ollama 并行启动（互不依赖，节省 1-3 秒）
    async def _start_workflow():
        if _WORKFLOW_AVAILABLE:
            try:
                wf_engine = get_wf_engine()
                await wf_engine.start(ai_backend=backend, tts_engine=tts)
                logger.info("⚡ Workflow engine started")
            except Exception as e:
                logger.warning(f"Workflow engine startup failed: {e}")

    async def _detect_ollama():
        try:
            from .ollama_bridge import OllamaBridge
            _ollama = OllamaBridge()
            health = await _ollama.check_health()
            if health.available:
                from src.router.config import RouterConfig
                cfg = RouterConfig()
                _ollama.auto_enable_in_router(cfg)
                models = [m.name for m in health.models]
                logger.info(f"🦙 Ollama detected (v{health.version}) models: {models}")
            else:
                logger.info("ℹ️ Ollama not running, skipping local models")
            app.state.ollama_bridge = _ollama
        except Exception as e:
            logger.debug(f"Ollama detection skipped: {e}")
            app.state.ollama_bridge = None

    await asyncio.gather(_start_workflow(), _detect_ollama())

    # Background tasks: account health heartbeat
    async def _health_heartbeat_loop():
        while True:
            try:
                from .wechat.account_health import get_health_monitor
                await get_health_monitor().check_all_heartbeats()
            except Exception:
                pass
            await asyncio.sleep(60)
    asyncio.create_task(_health_heartbeat_loop())

    # Anomaly detection hourly check
    async def _anomaly_check_loop():
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

    # Daily report at 18:00
    async def _daily_report_loop():
        from datetime import datetime, timedelta
        while True:
            now = datetime.now()
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                from .daily_report import generate_and_cache
                ai_call = backend.chat_simple if backend else None
                await generate_and_cache(ai_call)
            except Exception:
                pass
    asyncio.create_task(_daily_report_loop())

    # Database auto-maintenance at 03:00 daily
    async def _db_maintenance_loop():
        from datetime import datetime, timedelta
        while True:
            now = datetime.now()
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                logger.info("🗄️ Starting daily database maintenance...")

                # 1. Compress old messages into long-term memory
                from .long_memory import compress_old_messages
                ai_call = backend.chat_simple if backend else None
                if ai_call:
                    await compress_old_messages("default", ai_call)
                    logger.info("  ✅ Message compression done")

                # 2. Clean old workflow executions (>30 days)
                from .workflow.store import cleanup_old_executions
                cleanup_old_executions(days=30)
                logger.info("  ✅ Old workflow executions cleaned")

                # 3. VACUUM core databases (via unified db module)
                _db.vacuum_all()
                logger.info("  ✅ Database VACUUM done")

                # 4. Backup databases (via unified db module)
                _db.backup()
                data_dir = _PROJECT_ROOT / "data"
                backup_dir = data_dir / "backup"
                # Remove backups older than 7 days
                cutoff = datetime.now() - timedelta(days=7)
                for old in backup_dir.glob("*.db"):
                    try:
                        from datetime import datetime as _dt
                        date_part = old.stem.rsplit("_", 1)[-1]
                        if len(date_part) == 8 and _dt.strptime(date_part, "%Y%m%d") < cutoff:
                            old.unlink()
                    except Exception:
                        pass
                logger.info("  ✅ Database backup done")

                logger.info("🗄️ Daily database maintenance complete")
            except Exception as e:
                logger.warning(f"Database maintenance error: {e}")
    asyncio.create_task(_db_maintenance_loop())

    # 内存缓存定期清理（速率限制器 + 过期会话）
    async def _cache_cleanup_loop():
        while True:
            await asyncio.sleep(120)  # 每 2 分钟
            try:
                ip_limiter.cleanup(max_idle=300)
                key_limiter.cleanup(max_idle=300)
            except Exception:
                pass
    asyncio.create_task(_cache_cleanup_loop())

    logger.info("✅ OpenClaw Voice server ready!")


async def _shutdown():
    if _WORKFLOW_AVAILABLE:
        try:
            await get_wf_engine().stop()
        except Exception:
            pass
    _db.close_all()


# ═══════════════════════════════════════════════════════════════════
# Page Serving & Core Endpoints (shared between both Cursors)
# ═══════════════════════════════════════════════════════════════════

_MOBILE_HTTP_CLEANER = HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenClaw Voice</title>
<style>body{background:#0a0a14;color:#e8e8f0;font-family:-apple-system,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
.box{padding:40px 20px}.spin{animation:r 1s linear infinite;font-size:32px;display:inline-block}
@keyframes r{to{transform:rotate(360deg)}}</style></head>
<body><div class="box"><div class="spin">&#9881;</div>
<p>正在优化连接，请稍候...</p></div>
<script>
(async()=>{
if('serviceWorker' in navigator){
const regs=await navigator.serviceWorker.getRegistrations();
await Promise.all(regs.map(r=>r.unregister()));
}
const keys=await caches.keys();
await Promise.all(keys.map(k=>caches.delete(k)));
try{localStorage.clear()}catch(e){}
location.replace('/chat');
})();
</script></body></html>""", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/app")
@app.get("/app/")
async def app_page(request: Request):
    if _is_mobile(request):
        return RedirectResponse("/chat#more")
    return FileResponse("src/client/app.html")


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    return FileResponse("src/client/setup.html")


@app.get("/cert")
@app.get("/cert/")
async def cert_page():
    return RedirectResponse("/chat#voice", status_code=302)


@app.get("/ca.crt")
async def serve_ca_cert():
    ca_path = Path("certs/ca.crt")
    if not ca_path.exists():
        return Response(content="Certificates not generated.", status_code=404)
    return FileResponse(
        str(ca_path),
        media_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": "attachment; filename=OpenClaw-CA.crt"},
    )


@app.get("/ca.mobileconfig")
async def serve_mobileconfig():
    ca_path = Path("certs/ca.crt")
    if not ca_path.exists():
        return Response(content="Certificates not generated.", status_code=404)
    profile_xml = generate_mobileconfig(str(ca_path))
    return Response(
        content=profile_xml,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": "attachment; filename=OpenClaw-CA.mobileconfig"},
    )


@app.get("/api/server-info")
async def server_info():
    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    try:
        hostname = socket.gethostname()
        local_ips = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        local_ips = ["127.0.0.1"]
    http_port = settings.http_port if settings.http_port > 0 else settings.port + 1
    return {
        "host": hostname, "ips": local_ips,
        "port": settings.port, "http_port": http_port,
        "gateway_url": gateway_url,
        "version": _read_version(),
    }


@app.get("/chat")
@app.get("/chat/")
async def chat_page():
    return FileResponse("src/client/chat.html")


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    return FileResponse("src/client/setup.html")


@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "ts": time.time()}


@app.post("/api/stt/wake-check")
async def stt_wake_check(file: UploadFile = File(...)):
    """Transcribe an audio chunk and check for wake words."""
    global stt
    if not stt or stt.backend_name == "mock":
        return {"text": "", "wake": False}
    try:
        audio_bytes = await file.read()
        audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
        if len(audio_np) == 0 or float(np.abs(audio_np).max()) < 0.005:
            return {"text": "", "wake": False}
        result = await stt.transcribe(audio_np)
        text = result.text.strip() if result.text else ""
        if not text:
            return {"text": "", "wake": False}
        lower = text.lower()
        wake_words = ['你好', '小龙', '龙虾', '唤醒', '开始', '在吗',
                       'hey claw', 'hey cloud', 'hello', 'hi claw']
        has_wake = any(w in lower for w in wake_words)
        return {"text": text, "wake": has_wake}
    except Exception as e:
        logger.warning(f"Wake check error: {e}")
        return {"text": "", "wake": False}


@app.post("/api/stt/transcribe")
async def stt_transcribe(file: UploadFile = File(...)):
    """Transcribe uploaded audio using cloud STT."""
    global stt
    if not stt or stt.backend_name == "mock":
        return {"text": "", "error": "STT not configured"}
    try:
        audio_bytes = await file.read()
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio_np) < 1600:
            return {"text": ""}
        result = await stt.transcribe(audio_np)
        text = result.text.strip() if result.text else ""
        return {"text": text}
    except Exception as e:
        logger.warning(f"STT transcribe error: {e}")
        return {"text": "", "error": str(e)}


@app.get("/api/stt/status")
async def stt_status():
    """Return current STT backend info."""
    global stt
    backend = stt.backend_name if stt else "none"
    is_cloud = stt.is_cloud if stt else False
    ready = backend not in ("mock", "none")
    return {
        "backend": backend,
        "ready": ready,
        "is_cloud": is_cloud,
    }


@app.post("/api/stt/save-key")
async def stt_save_key(request: Request):
    """Save a cloud STT API key, write to .env, and hot-reload the STT engine."""
    global stt
    data = await request.json()
    provider = data.get("provider", "")
    api_key = data.get("api_key", "").strip()

    env_map = {
        "zhipu": "ZHIPU_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_map.get(provider)
    if not env_var or not api_key:
        return {"ok": False, "error": "参数无效"}

    env_path = str(_PROJECT_ROOT / ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(env_var + "=") or stripped.startswith(f"# {env_var}="):
            lines[i] = f"{env_var}={api_key}\n"
            found = True
            break
    if not found:
        lines.append(f"\n{env_var}={api_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    os.environ[env_var] = api_key

    try:
        new_stt = WhisperSTT(
            model_name=settings.stt_model,
            device=settings.stt_device,
            language=settings.stt_language,
        )
        if new_stt.backend_name in ("mock", "none"):
            return {"ok": False, "error": "Key 保存成功但 STT 引擎未能启动，请检查 Key 是否正确"}
        stt = new_stt
        logger.info(f"STT hot-reloaded: {stt.backend_name}")
        return {"ok": True, "backend": stt.backend_name}
    except Exception as e:
        logger.error(f"STT reload failed: {e}")
        return {"ok": False, "error": f"STT 重载失败: {e}"}


@app.get("/api/setup/status")
async def setup_status():
    """Check whether setup has been completed and a provider is configured."""
    setup_done = os.environ.get("OPENCLAW_SETUP_DONE", "").lower() == "true"
    configured_provider = None
    try:
        from src.router.config import RouterConfig
        rc = RouterConfig()
        for p in rc.all_providers_meta():
            pid = p["id"]
            key = rc.get_provider_key(pid)
            if key and len(key) > 5:
                configured_provider = p.get("name_short", p.get("name", pid))
                break
    except Exception:
        pass
    # 零配置检测：即使没有显式 setup_done，有 provider 就算完成
    has_provider = configured_provider is not None
    effective_complete = setup_done or has_provider
    return {
        "complete": effective_complete,
        "setup_done": setup_done,
        "has_provider": has_provider,
        "provider_name": configured_provider,
        # 给前端提示：可以直接用，无需 setup
        "can_chat": backend is not None and (backend._client is not None or backend._router is not None),
    }


@app.get("/api/providers")
async def get_providers():
    """Return available AI platform list from providers.json + active provider info"""
    try:
        with open(_PROVIDERS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        configured_provider = None
        try:
            from src.router.config import RouterConfig
            rc = RouterConfig()
            for p in rc.all_providers_meta():
                pid = p["id"]
                key = rc.get_provider_key(pid)
                if key and len(key) > 5:
                    configured_provider = p.get("name_short", p.get("name", pid))
                    break
        except Exception:
            pass
        data["active_provider"] = configured_provider
        return data
    except Exception as e:
        logger.warning(f"get_providers: {e}")
        return {"providers": [], "error": str(e)}


@app.post("/api/setup/verify-key")
async def setup_verify_key(request: Request):
    """Verify an API key by making a test call."""
    try:
        try:
            data = await request.json()
        except Exception:
            return {"ok": False, "error": "请求体无效"}
        provider_id = data.get("provider_id")
        api_key = (data.get("api_key") or "").strip()
        if not provider_id or not api_key:
            return {"ok": False, "error": "缺少必要参数"}

        try:
            with open(_PROVIDERS_JSON, encoding="utf-8") as f:
                pdata = json.load(f)
        except FileNotFoundError:
            logger.error(f"providers.json not found: {_PROVIDERS_JSON}")
            return {"ok": False, "error": "服务配置缺失，请重新安装或检查安装目录"}
        except Exception as e:
            return {"ok": False, "error": f"读取配置失败: {e}"}

        provider = next((p for p in pdata.get("providers", []) if p["id"] == provider_id), None)
        if not provider:
            return {"ok": False, "error": "未知的平台"}

        try:
            from openai import AsyncOpenAI
        except ImportError:
            return {"ok": False, "error": "服务端缺少 openai 库，请运行: pip install openai"}

        client = AsyncOpenAI(api_key=api_key, base_url=provider["base_url"], timeout=20)
        resp = await client.chat.completions.create(
            model=provider["default_model"],
            messages=[{"role": "user", "content": "你好"}],
            max_tokens=10,
        )
        if resp.choices and resp.choices[0].message.content:
            return {"ok": True, "reply": resp.choices[0].message.content}
        return {"ok": False, "error": "API 返回为空"}
    except Exception as e:
        err = str(e)[:200]
        logger.warning(f"verify-key error: {e}")
        return {"ok": False, "error": err}


@app.post("/api/setup/save-key")
async def setup_save_key(request: Request):
    """Save provider API key to .env file"""
    data = await request.json()
    provider_id = data.get("provider_id")
    api_key = data.get("api_key", "").strip()
    if not provider_id or not api_key:
        return {"ok": False}

    try:
        with open(_PROVIDERS_JSON, encoding="utf-8") as f:
            pdata = json.load(f)
    except Exception:
        return {"ok": False}
    provider = next((p for p in pdata.get("providers", []) if p["id"] == provider_id), None)
    if not provider:
        return {"ok": False}

    env_var = provider.get("key_env", "")
    if not env_var:
        return {"ok": False}

    env_path = str(_PROJECT_ROOT / ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(env_var + "=") or line.strip().startswith(f"# {env_var}="):
            lines[i] = f"{env_var}={api_key}\n"
            found = True
            break
    if not found:
        lines.append(f"\n{env_var}={api_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    os.environ[env_var] = api_key
    return {"ok": True}


@app.post("/api/setup/save-voice")
async def setup_save_voice(request: Request):
    """Save selected TTS voice"""
    data = await request.json()
    voice_id = data.get("voice_id", "zh-CN-XiaoxiaoNeural")
    os.environ["EDGE_TTS_VOICE"] = voice_id

    env_path = str(_PROJECT_ROOT / ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("EDGE_TTS_VOICE=") or line.strip().startswith("# EDGE_TTS_VOICE="):
            lines[i] = f"EDGE_TTS_VOICE={voice_id}\n"
            found = True
            break
    if not found:
        lines.append(f"\nEDGE_TTS_VOICE={voice_id}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return {"ok": True}


@app.post("/api/setup/finish")
async def setup_finish(request: Request):
    """Mark setup as complete, save environment preference"""
    data = await request.json()
    environment = data.get("environment", "family")

    env_path = str(_PROJECT_ROOT / ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    found_env = False
    found_setup = False
    for i, line in enumerate(lines):
        if line.strip().startswith("OPENCLAW_ENVIRONMENT="):
            lines[i] = f"OPENCLAW_ENVIRONMENT={environment}\n"
            found_env = True
        if line.strip().startswith("OPENCLAW_SETUP_DONE="):
            lines[i] = "OPENCLAW_SETUP_DONE=true\n"
            found_setup = True

    if not found_env:
        lines.append(f"\nOPENCLAW_ENVIRONMENT={environment}\n")
    if not found_setup:
        lines.append("OPENCLAW_SETUP_DONE=true\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    os.environ["OPENCLAW_ENVIRONMENT"] = environment
    os.environ["OPENCLAW_SETUP_DONE"] = "true"
    return {"ok": True}


@app.get("/js/{filename:path}")
async def serve_js_module(filename: str):
    """Serve client-side JS modules from src/client/js/"""
    fpath = Path("src/client/js") / filename
    if not fpath.exists() or not fpath.suffix == ".js":
        return Response(content="Not found", status_code=404)
    return FileResponse(str(fpath), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


# ── Accessibility Config API ──
@app.get("/api/access/config")
async def get_access_config():
    from src.server.access_config import load_config
    return load_config()


@app.put("/api/access/config")
async def update_access_config(request: Request):
    from src.server.access_config import load_config, save_config
    body = await request.json()
    config = load_config()
    config.update(body)
    save_config(config)
    return config


@app.post("/api/access/config/reset")
async def reset_access_config():
    from src.server.access_config import _default_config, save_config
    config = _default_config()
    save_config(config)
    return config


@app.get("/api/access/presets")
async def list_access_presets():
    from src.server.access_config import get_presets
    return get_presets()


@app.post("/api/access/preset/{name}")
async def apply_access_preset(name: str):
    from src.server.access_config import apply_preset
    try:
        return apply_preset(name)
    except ValueError as e:
        return Response(content=json.dumps({"error": str(e)}), status_code=404,
                        media_type="application/json")


# ── Local Voice Commands API ──
@app.post("/api/local-command")
async def local_voice_command(request: Request):
    """Match spoken text against local commands (zero network, no LLM)."""
    from src.server.local_voice_commands import get_engine
    body = await request.json()
    text = body.get("text", "")
    engine = get_engine()
    result = engine.match(text)
    if result:
        return {
            "matched": True,
            "action": result.action,
            "params": result.params,
            "phrase": result.matched_phrase,
            "confidence": result.confidence,
        }
    return {"matched": False}


@app.get("/api/local-commands")
async def list_local_commands():
    """List all available local voice commands."""
    from src.server.local_voice_commands import get_engine
    return get_engine().get_all_commands()


@app.post("/api/local-command/custom")
async def add_custom_command(request: Request):
    """Add a user-defined local voice command."""
    from src.server.local_voice_commands import get_engine
    body = await request.json()
    phrase = body.get("phrase", "").strip()
    action_config = body.get("config", {})
    if not phrase or not action_config.get("action"):
        return Response(content=json.dumps({"error": "phrase and config.action required"}),
                        status_code=400, media_type="application/json")
    get_engine().add_custom_command(phrase, action_config)
    return {"ok": True, "phrase": phrase}


# ── Local Mode API ──
@app.get("/api/mode")
async def get_mode():
    """Get current operating mode (full or local)."""
    mode = os.environ.get("OPENCLAW_MODE", "full")
    return {"mode": mode, "ai_available": mode == "full"}


@app.post("/api/mode")
async def set_mode(request: Request):
    """Switch between full mode (with AI) and local mode (offline)."""
    body = await request.json()
    mode = body.get("mode", "full")
    if mode not in ("full", "local"):
        return Response(content=json.dumps({"error": "mode must be 'full' or 'local'"}),
                        status_code=400, media_type="application/json")
    os.environ["OPENCLAW_MODE"] = mode
    logger.info(f"Mode switched to: {mode}")
    return {"mode": mode, "ai_available": mode == "full"}


# ═══════════════════════════════════════════════════════════════════
# Intent Fusion + Workflow + MCP Desktop Tools API
# ═══════════════════════════════════════════════════════════════════

from .intent_router import get_intent_router, IntentCategory
from .workflow_recorder import get_workflow_recorder
from .mcp_desktop_tools import get_mcp_desktop_tools, execute_mcp_desktop_tool


@app.post("/api/intent")
async def resolve_intent(request: Request):
    """Resolve a fused intent from the frontend IntentFusionEngine."""
    body = await request.json()
    action = body.get("action", "")
    params = body.get("params", {})
    source = body.get("source", "")
    confidence = body.get("confidence", 1.0)

    router = get_intent_router()
    result = router.route(action, params, source, confidence)

    # Auto-execute desktop direct actions
    if result.category == IntentCategory.DESKTOP_DIRECT and desktop:
        try:
            cmd = result.params
            cmd_type = cmd.pop("type", "")
            if cmd_type == "mouse_click":
                x, y = cmd.get("x"), cmd.get("y")
                button = cmd.get("button", "left")
                if x is not None and y is not None:
                    # Convert 0-1 to screen coords if needed
                    import pyautogui
                    sw, sh = pyautogui.size()
                    px = int(float(x) * sw) if isinstance(x, float) and x <= 1 else int(x)
                    py = int(float(y) * sh) if isinstance(y, float) and y <= 1 else int(y)
                    desktop.mouse_click(px, py, button=button)
                else:
                    import pyautogui
                    pyautogui.click(button=button)
            elif cmd_type == "mouse_scroll":
                import pyautogui
                pyautogui.scroll(cmd.get("dy", -3))
            elif cmd_type == "hotkey":
                import pyautogui
                keys = cmd.get("keys", [])
                if keys:
                    pyautogui.hotkey(*keys)
            elif cmd_type == "screenshot":
                desktop.capture_screen_base64()
            result.params["executed"] = True
        except Exception as e:
            logger.error(f"Intent execution failed: {e}")
            result.params["executed"] = False
            result.params["error"] = str(e)

    return result.to_dict()


@app.get("/api/intent/context")
async def get_intent_context():
    """Get current intent routing context (history + screen)."""
    router = get_intent_router()
    return router.get_context()


@app.get("/api/intent/history")
async def get_intent_history(n: int = 20):
    """Get recent intent history."""
    router = get_intent_router()
    return {"history": router.history.recent(n)}


# ── Workflow Recording API ──

@app.get("/api/workflows")
async def list_workflows():
    """List all saved workflows."""
    recorder = get_workflow_recorder()
    return {"workflows": recorder.list_workflows()}


@app.post("/api/workflows")
async def create_workflow(request: Request):
    """Create a workflow from recorded actions."""
    body = await request.json()
    recorder = get_workflow_recorder()
    wf = recorder.create_from_recording(
        recorded_actions=body.get("actions", []),
        name=body.get("name", "Untitled"),
        description=body.get("description", ""),
        tags=body.get("tags", []),
    )
    return {"workflow": wf.to_dict()}


@app.get("/api/workflows/{wf_id}")
async def get_workflow(wf_id: str):
    """Get workflow details."""
    recorder = get_workflow_recorder()
    wf = recorder.get_workflow(wf_id)
    if not wf:
        return Response(content='{"error":"not found"}', status_code=404,
                        media_type="application/json")
    return {"workflow": wf.to_dict()}


@app.delete("/api/workflows/{wf_id}")
async def delete_workflow(wf_id: str):
    """Delete a workflow."""
    recorder = get_workflow_recorder()
    ok = recorder.delete_workflow(wf_id)
    return {"deleted": ok}


@app.post("/api/workflows/{wf_id}/replay")
async def replay_workflow(wf_id: str, request: Request):
    """Replay a workflow."""
    body = await request.json() if (await request.body()) else {}
    speed = body.get("speed", 1.0)

    recorder = get_workflow_recorder()

    async def executor(action, params):
        # Route each step through the intent router
        router = get_intent_router()
        result = router.route(action, params)
        if result.category == IntentCategory.DESKTOP_DIRECT and desktop:
            cmd = dict(result.params)
            cmd_type = cmd.pop("type", "")
            if cmd_type == "hotkey":
                import pyautogui
                pyautogui.hotkey(*cmd.get("keys", []))
            elif cmd_type == "mouse_click":
                import pyautogui
                pyautogui.click(button=cmd.get("button", "left"))
            elif cmd_type == "mouse_scroll":
                import pyautogui
                pyautogui.scroll(cmd.get("dy", -3))
        return {"routed": result.to_dict()}

    result = await recorder.replay(wf_id, executor, speed=speed)
    return result


# ── MCP Desktop Tools API ──

@app.get("/api/mcp/desktop-tools")
async def list_mcp_desktop_tools():
    """List all desktop MCP tools."""
    return {"tools": get_mcp_desktop_tools()}


@app.post("/api/mcp/desktop-tool/call")
async def call_mcp_desktop_tool(request: Request):
    """Call a desktop MCP tool directly."""
    body = await request.json()
    tool_name = body.get("tool_name", "")
    arguments = body.get("arguments", {})
    result = await execute_mcp_desktop_tool(tool_name, arguments, desktop)
    return result


@app.get("/qr")
@app.get("/qr/")
async def qr_page():
    return FileResponse("src/client/qr.html")


@app.get("/api/qr")
async def generate_qr_image(url: str, size: int = 240):
    import io
    try:
        import qrcode
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=max(4, size // 40), border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/png",
                        headers={"Cache-Control": "no-cache"})
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        safe_url = url.replace("&", "%26")
        return RedirectResponse(url=f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={safe_url}")


@app.get("/manifest.json")
async def pwa_manifest():
    return FileResponse("src/client/manifest.json", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse("src/client/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


def _is_mobile(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    return any(k in ua for k in ("iphone", "android", "mobile", "ipod", "ipad", "windows phone"))


@app.get("/")
async def index(request: Request):
    """智能首页路由：有 AI 配置 → 直接进聊天，无配置 → 引导设置"""
    if _is_mobile(request):
        return RedirectResponse("/chat")
    # 检查是否有可用的 AI 提供商
    has_provider = backend is not None and (backend._client or backend._router)
    if has_provider:
        return RedirectResponse("/app")
    return FileResponse("src/client/setup.html")


@app.get("/voice")
@app.get("/voice/")
async def voice_page():
    return FileResponse("src/client/index.html")


@app.post("/api/keys")
async def create_api_key(name: str, tier: str = "free", master_key: Optional[str] = None):
    if settings.require_auth:
        if not master_key and not settings.master_key:
            return {"error": "Master key required"}
        provided_key = master_key or ""
        if provided_key != settings.master_key:
            key = token_manager.validate_key(provided_key)
            if not key or key.tier != "enterprise":
                return {"error": "Invalid master key"}
    from .auth import PRICING_TIERS
    if tier not in PRICING_TIERS:
        return {"error": f"Invalid tier. Options: {list(PRICING_TIERS.keys())}"}
    tier_config = PRICING_TIERS[tier]
    plaintext_key, api_key = token_manager.generate_key(
        name=name, tier=tier,
        rate_limit=tier_config["rate_limit"],
        monthly_minutes=tier_config["monthly_minutes"],
    )
    return {
        "api_key": plaintext_key, "key_id": api_key.key_id,
        "name": api_key.name, "tier": api_key.tier,
        "monthly_minutes": api_key.monthly_minutes,
        "rate_limit": api_key.rate_limit_per_minute,
    }


@app.get("/api/update/check")
async def check_update():
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
    try:
        from src.server.updater import get_updater
        updater = get_updater()
        info = await updater.check_for_updates()
        if not info.has_update:
            return {"ok": False, "message": "No update available"}
        ok, msg = await updater.apply_update(info)
        return {"ok": ok, "message": msg, "needs_restart": info.needs_restart}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/api/restart")
async def restart_server():
    """Gracefully restart the server process after an update."""
    import sys as _sys
    import asyncio as _aio

    async def _delayed_restart():
        await _aio.sleep(1)
        logger.info("Restarting server via os.execv...")
        os.execv(_sys.executable, [_sys.executable] + _sys.argv)

    _aio.get_event_loop().create_task(_delayed_restart())
    return {"ok": True, "message": "Restarting in 1 second..."}


# ═══════════════════════════════════════════════════════════════════
# Server Boot
# ═══════════════════════════════════════════════════════════════════

def _ensure_firewall_rules(http_port: int, https_port: int):
    import platform, subprocess
    if platform.system() != "Windows":
        return
    for port, name in [(http_port, "OpenClaw-HTTP"), (https_port, "OpenClaw-HTTPS")]:
        try:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name={name}", "dir=in", "action=allow", "protocol=TCP",
                 f"localport={port}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass


if __name__ == "__main__":
    import asyncio
    import uvicorn

    ca_crt, server_crt, server_key = ensure_certs("certs")
    lan_ips = get_lan_ips()
    port = settings.port
    http_port = settings.http_port if settings.http_port > 0 else port + 1

    _ensure_firewall_rules(http_port, port)

    logger.info("=" * 60)
    logger.info("  OpenClaw Voice — Dual Server")
    logger.info("=" * 60)
    for ip in lan_ips:
        if ip != "127.0.0.1":
            logger.info(f"  📱 Chat(HTTP):   http://{ip}:{http_port}/chat")
            logger.info(f"  🖥️  QR:           http://{ip}:{http_port}/qr")
            logger.info(f"  🔐 Full(HTTPS):  https://{ip}:{port}/app")
            logger.info(f"  📋 Certs:         https://{ip}:{port}/setup")
    logger.info(f"  💻 Local:         https://localhost:{port}/app")
    logger.info("=" * 60)

    https_config = uvicorn.Config(
        "src.server.main:app",
        host=settings.host, port=port,
        ssl_keyfile=server_key, ssl_certfile=server_crt,
        reload=False, log_level="info",
    )
    http_config = uvicorn.Config(
        "src.server.main:app",
        host=settings.host, port=http_port,
        reload=False, log_level="warning",
    )

    async def serve_both():
        https_server = uvicorn.Server(https_config)
        http_server = uvicorn.Server(http_config)

        async def _open_browser():
            await asyncio.sleep(2.0)
            import webbrowser
            qr_url = f"http://localhost:{http_port}/qr"
            logger.info(f"🌐 Opening browser: {qr_url}")
            webbrowser.open(qr_url)

        await asyncio.gather(
            https_server.serve(),
            http_server.serve(),
            _open_browser(),
        )

    asyncio.run(serve_both())
