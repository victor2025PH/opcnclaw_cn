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
_dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_dotenv_path, override=True)

# Ensure this module is registered under its canonical name even when run
# via `python -m src.server.main` (which sets __name__ to "__main__").
# Without this, relative imports (from ..main import backend) resolve to a
# separate module object whose globals never get updated by the lifespan.
if 'src.server.main' not in sys.modules:
    sys.modules['src.server.main'] = sys.modules[__name__]

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
    model_config = {"env_prefix": "OPENCLAW_", "env_file": ".env", "extra": "ignore"}

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

app = FastAPI(
    title="十三香小龙虾 AI",
    description="全双工 AI 语音助手 — 语音交互 / 桌面控制 / 微信自动化 / 工作流",
    version=_read_version(),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

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
    # 关键 API 不限速（健康检查、状态、配置）
    _NO_LIMIT = ("/api/ping", "/api/ai/status", "/api/setup/status", "/api/metrics",
                 "/api/client/info", "/api/system/network-status", "/api/daily-brief",
                 "/api/events/stream", "/api/pet/")
    if any(path.startswith(p) for p in _NO_LIMIT):
        return await call_next(request)
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


# ── PIN 码保护（敏感操作需要验证）──────────────────────────────────
_admin_pin: Optional[str] = os.environ.get("OPENCLAW_ADMIN_PIN")
_pin_sessions: dict = {}  # token → expire_ts

_PIN_PROTECTED_PREFIXES = (
    "/api/wechat/toggle", "/api/wechat/config", "/api/wechat/send",
    "/api/cowork/pause", "/api/cowork/resume", "/api/cowork/undo",
    "/api/restart", "/api/system/restart", "/api/system/clear-cache",
    "/api/mcp/rpc",
)

@app.post("/api/auth/pin")
async def auth_pin(request: Request):
    """验证 PIN 码，返回临时 token（有效期 24h）"""
    if not _admin_pin:
        return {"ok": True, "token": "no-pin-set", "message": "PIN 未设置，无需验证"}
    body = await request.json()
    pin = body.get("pin", "")
    if pin == _admin_pin:
        import secrets
        token = secrets.token_hex(16)
        _pin_sessions[token] = time.time() + 86400
        return {"ok": True, "token": token}
    return {"ok": False, "error": "PIN 码错误"}

@app.get("/api/auth/status")
async def auth_status():
    """检查是否需要 PIN 验证"""
    return {"pin_required": bool(_admin_pin), "pin_set": bool(_admin_pin)}


@app.get("/api/metrics")
async def system_metrics():
    """性能监控指标"""
    import psutil
    uptime = time.time() - _startup_progress["started_at"] if _startup_progress["started_at"] else 0
    metrics = {
        "uptime_s": round(uptime),
        "cpu_pct": psutil.cpu_percent(interval=0),
        "mem_pct": psutil.virtual_memory().percent,
        "mem_used_mb": psutil.virtual_memory().used // (1024**2),
    }
    # 数据库大小
    try:
        data_dir = _PROJECT_ROOT / "data"
        metrics["db_main_mb"] = round((data_dir / "main.db").stat().st_size / (1024**2), 1) if (data_dir / "main.db").exists() else 0
        metrics["db_wechat_mb"] = round((data_dir / "wechat.db").stat().st_size / (1024**2), 1) if (data_dir / "wechat.db").exists() else 0
    except Exception:
        pass
    # 消息统计
    try:
        conn = _db.get_conn("main")
        metrics["total_messages"] = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        metrics["total_fts_indexed"] = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    except Exception:
        pass
    # 微信统计
    try:
        from .wechat_autoreply import get_engine
        engine = get_engine()
        if engine:
            metrics["wechat_today_replied"] = getattr(engine, '_config', None) and 0
    except Exception:
        pass
    return metrics


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 格式 metrics 端点 — 供 Grafana/Prometheus 采集"""
    import psutil
    uptime = time.time() - _startup_progress["started_at"] if _startup_progress["started_at"] else 0
    lines = []

    # 系统指标
    lines.append(f"# HELP openclaw_uptime_seconds Server uptime in seconds")
    lines.append(f"# TYPE openclaw_uptime_seconds gauge")
    lines.append(f"openclaw_uptime_seconds {uptime:.0f}")

    lines.append(f"# HELP openclaw_cpu_percent CPU usage percentage")
    lines.append(f"# TYPE openclaw_cpu_percent gauge")
    lines.append(f'openclaw_cpu_percent {psutil.cpu_percent(interval=0):.1f}')

    mem = psutil.virtual_memory()
    lines.append(f"# HELP openclaw_memory_used_bytes Memory used in bytes")
    lines.append(f"# TYPE openclaw_memory_used_bytes gauge")
    lines.append(f"openclaw_memory_used_bytes {mem.used}")

    lines.append(f"# HELP openclaw_memory_percent Memory usage percentage")
    lines.append(f"# TYPE openclaw_memory_percent gauge")
    lines.append(f"openclaw_memory_percent {mem.percent:.1f}")

    # 数据库指标
    try:
        data_dir = _PROJECT_ROOT / "data"
        for db_name in ("main.db", "wechat.db"):
            db_path = data_dir / db_name
            if db_path.exists():
                size = db_path.stat().st_size
                safe_name = db_name.replace(".", "_")
                lines.append(f'openclaw_db_size_bytes{{db="{db_name}"}} {size}')
    except Exception:
        pass

    # 消息统计
    try:
        conn = _db.get_conn("main")
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        lines.append(f"# HELP openclaw_messages_total Total messages stored")
        lines.append(f"# TYPE openclaw_messages_total gauge")
        lines.append(f"openclaw_messages_total {total}")
    except Exception:
        pass

    # 意图融合统计
    try:
        from .intent_fusion import get_engine
        engine = get_engine()
        stats = engine._stats
        lines.append(f"# HELP openclaw_intent_signals_total Total signals received")
        lines.append(f"# TYPE openclaw_intent_signals_total counter")
        lines.append(f"openclaw_intent_signals_total {stats['signals_received']}")
        lines.append(f"openclaw_intent_fusions_total {stats['fusions_performed']}")
        lines.append(f"openclaw_intent_emergency_stops_total {stats['emergency_stops']}")
    except Exception:
        pass

    # EventBus 统计
    try:
        from .event_bus import get_bus
        ebus = get_bus()
        lines.append(f"# HELP openclaw_eventbus_subscribers Active event subscribers")
        lines.append(f"# TYPE openclaw_eventbus_subscribers gauge")
        lines.append(f"openclaw_eventbus_subscribers {ebus.subscriber_count}")
        ps = ebus.get_persist_stats()
        lines.append(f"openclaw_eventbus_persisted_total {ps['persisted_total']}")
    except Exception:
        pass

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.middleware("http")
async def pin_protection_middleware(request: Request, call_next):
    """敏感操作需要 PIN 验证"""
    if _admin_pin:
        path = request.url.path.rstrip("/")
        if any(path.startswith(p) for p in _PIN_PROTECTED_PREFIXES):
            token = request.headers.get("X-Admin-Token", "")
            if not token:
                token = request.query_params.get("_token", "")
            if token not in _pin_sessions or _pin_sessions.get(token, 0) < time.time():
                return Response(
                    content=json.dumps({"error": "需要 PIN 验证", "pin_required": True}),
                    status_code=401,
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
from .routers.intent import router as intent_router
from .routers.a2a import router as a2a_router
from .routers.users import router as users_router
from .routers.agents import router as agents_router
from .routers.pet import router as pet_router

app.include_router(voice_router)
app.include_router(desktop_router)
app.include_router(wechat_router)
app.include_router(workflow_router)
app.include_router(admin_router)
app.include_router(models_router)
app.include_router(mcp_router)
app.include_router(intent_router)
app.include_router(a2a_router)
app.include_router(users_router)
app.include_router(agents_router)
app.include_router(pet_router)


# ═══════════════════════════════════════════════════════════════════
# Startup / Shutdown (two-phase: fast → deferred)
# ═══════════════════════════════════════════════════════════════════

_startup_done = False

_startup_progress = {
    "phase": "init",        # init → db → models → ready
    "stt": "pending",       # pending → loading → ready → error
    "tts": "pending",
    "backend": "pending",
    "workflow": "pending",
    "ready": False,
    "started_at": 0,
    "message": "正在初始化...",
}

async def _startup(app: FastAPI):
    """Phase 1 (fast): DB + config. Phase 2 (background): models."""
    global _startup_done

    if _startup_done:
        return
    _startup_done = True
    _startup_progress["started_at"] = time.time()

    logger.info("Initializing OpenClaw Voice server...")

    # ── Phase 1: fast essentials (< 2s) ──────────────────────
    _startup_progress["phase"] = "db"
    _startup_progress["message"] = "初始化数据库..."

    _db.init_schemas()
    _db.migrate_from_old_dbs()

    try:
        mem_store.cleanup_oversized_messages()
    except Exception as e:
        logger.warning(f"DB cleanup failed (non-fatal): {e}")

    load_keys_from_env()
    if settings.require_auth:
        logger.info("🔐 Authentication ENABLED")
    else:
        logger.warning("⚠️ Authentication DISABLED (dev mode)")

    global desktop
    try:
        from .routers.desktop import desktop as _desk
        desktop = _desk
    except Exception:
        pass

    # 启动意图融合引擎（轻量，不阻塞）
    try:
        from .intent_fusion import get_engine
        get_engine()
        logger.info("✅ IntentFusion 引擎已启动")
    except Exception as e:
        logger.debug(f"IntentFusion 启动跳过: {e}")

    # 启动智能建议引擎
    try:
        from .smart_suggest import get_suggest_engine
        get_suggest_engine()
        logger.info("✅ SmartSuggest 引擎已启动")
    except Exception as e:
        logger.debug(f"SmartSuggest 启动跳过: {e}")

    # 定时任务调度器
    try:
        from .scheduler import get_scheduler
        get_scheduler().start()
        logger.info("✅ 定时任务调度器已启动")
    except Exception as e:
        logger.debug(f"调度器启动跳过: {e}")

    # iLink (微信 ClawBot) 自动恢复
    try:
        from .ilink_bot import get_ilink_bot
        bot = get_ilink_bot()
        if bot.is_connected:
            from .ilink_handler import handle_wechat_message
            bot.set_message_handler(handle_wechat_message)
            asyncio.create_task(bot.start_polling())
            logger.info("✅ 微信 ClawBot (iLink) 已自动恢复连接")
    except Exception as e:
        logger.debug(f"iLink 启动跳过: {e}")

    logger.info("✅ Phase 1 complete — server accepting requests")

    # ── Phase 2: heavy model loading (background) ─────────────
    asyncio.create_task(_startup_models_deferred(app))


async def _startup_models_deferred(app: FastAPI):
    """Background model loading — server already accepting requests.

    Load order optimized: backend first (fast, enables text chat immediately),
    then STT/TTS (slow, enables voice features).
    """
    global stt, tts, backend, vad

    _startup_progress["phase"] = "models"

    # 1. AI Backend first — fast (~1s), enables text chat immediately
    _startup_progress["backend"] = "loading"
    _startup_progress["message"] = "连接AI后端..."
    try:
        gateway_url = settings.openclaw_gateway_url or os.getenv("OPENCLAW_GATEWAY_URL")
        gateway_token = settings.openclaw_gateway_token or os.getenv("OPENCLAW_GATEWAY_TOKEN")
        zhipu_vision_key = os.getenv("ZHIPU_VISION_API_KEY") or os.getenv("ZHIPU_API_KEY")
        zhipu_vision_model = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")
        if zhipu_vision_key:
            logger.info(f"🖼️ Zhipu vision configured: {zhipu_vision_model}")

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

        app.state.ai_backend = backend
        _startup_progress["backend"] = "ready"
    except Exception as e:
        _startup_progress["backend"] = "error"
        logger.error(f"Backend init failed: {e}")

    # 2. STT — heavy model load, uses thread pool to avoid blocking event loop
    _startup_progress["stt"] = "loading"
    _startup_progress["message"] = "加载语音识别模型..."
    try:
        logger.info(f"Loading STT model: {settings.stt_model}")
        stt = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: WhisperSTT(
                model_name=settings.stt_model,
                device=settings.stt_device,
                language=settings.stt_language,
            )
        )
        _startup_progress["stt"] = "ready"
        logger.info(f"STT language: {settings.stt_language or 'auto'}")
    except Exception as e:
        _startup_progress["stt"] = "error"
        logger.error(f"STT load failed: {e}")

    # 3. TTS — heavy model load
    _startup_progress["tts"] = "loading"
    _startup_progress["message"] = "加载语音合成模型..."
    try:
        logger.info(f"Loading TTS model: {settings.tts_model}")
        tts = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ChatterboxTTS(voice_sample=settings.tts_voice)
        )
        _startup_progress["tts"] = "ready"
    except Exception as e:
        _startup_progress["tts"] = "error"
        logger.error(f"TTS load failed: {e}")

    vad = VoiceActivityDetector()

    # Workflow + Ollama 并行启动
    _startup_progress["workflow"] = "loading"
    _startup_progress["message"] = "启动工作流引擎..."

    async def _start_workflow():
        if _WORKFLOW_AVAILABLE:
            try:
                wf_engine = get_wf_engine()
                await wf_engine.start(ai_backend=backend, tts_engine=tts)
                logger.info("⚡ Workflow engine started")
                _startup_progress["workflow"] = "ready"
            except Exception as e:
                logger.warning(f"Workflow engine startup failed: {e}")
                _startup_progress["workflow"] = "error"
        else:
            _startup_progress["workflow"] = "ready"

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

    async def _preload_ocr():
        """预加载 OCR 引擎（首次约 40s，之后 <1s）"""
        try:
            if desktop:
                await asyncio.get_event_loop().run_in_executor(None, desktop._get_ocr)
                logger.info("✅ OCR 引擎预加载完成")
        except Exception as e:
            logger.debug(f"OCR 预加载跳过: {e}")

    await asyncio.gather(_start_workflow(), _detect_ollama(), _preload_ocr())

    # ── Mark startup complete ──
    _startup_progress["phase"] = "ready"
    _startup_progress["ready"] = True
    _startup_progress["message"] = "就绪"
    elapsed = time.time() - _startup_progress["started_at"]
    logger.info(f"✅ Phase 2 complete — all models loaded ({elapsed:.1f}s total)")

    # ── 微信监控（不再自动启动，需要用户手动开启）──
    # 之前这里会自动开启 reply_all=True 导致重启后乱发消息
    # 现在改为：只初始化引擎，不自动开启回复
    if sys.platform == "win32" and _wechat_autoreply_available:
        async def _init_wechat_engine():
            await asyncio.sleep(5)
            try:
                from .wechat_monitor import _wechat_is_running
                if _wechat_is_running():
                    # 只初始化，不开启自动回复
                    _, engine = init_wechat_v2(ai_backend=backend, desktop=desktop)
                    if engine:
                        # 默认关闭自动回复，用户需要在设置中手动开启
                        engine.update_config({"enabled": False, "reply_all": False})
                        logger.info("ℹ️ 微信引擎已初始化（自动回复默认关闭，需手动开启）")
                else:
                    logger.info("ℹ️ 微信未运行")
            except Exception as e:
                logger.debug(f"微信引擎初始化跳过: {e}")
        asyncio.create_task(_init_wechat_engine())

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

                # 2b. Clean expired data (events 90d, audit 30d)
                try:
                    import time as _t
                    conn_main = _db.get_conn("main")
                    conn_wechat = _db.get_conn("wechat")
                    # audit_log: 30 days
                    cutoff_30d = _t.time() - 30 * 86400
                    conn_main.execute("DELETE FROM audit_log WHERE timestamp < ? AND timestamp > 0", (cutoff_30d,))
                    conn_main.commit()
                    # events (main): 90 days
                    cutoff_90d = _t.time() - 90 * 86400
                    conn_main.execute("DELETE FROM events WHERE timestamp < ? AND timestamp > 0", (cutoff_90d,))
                    conn_main.commit()
                    # events (wechat): 90 days
                    conn_wechat.execute("DELETE FROM events WHERE timestamp < ? AND timestamp > 0", (cutoff_90d,))
                    conn_wechat.commit()
                    logger.info("  ✅ Expired data cleaned (audit 30d, events 90d)")
                except Exception as _ce:
                    logger.debug(f"  Data cleanup: {_ce}")

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
    return FileResponse("src/client/app.html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/pet")
@app.get("/pet/")
async def pet_page():
    """Tauri 桌宠窗口：动画 + 字幕/状态（与主界面 BroadcastChannel 联动）"""
    return FileResponse(
        "src/client/pet.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    return FileResponse("src/client/setup.html")


@app.get("/purge")
@app.get("/purge/")
async def purge_cache():
    """Force-clear all browser caches using Clear-Site-Data header + JS cleanup, then redirect to /app"""
    return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="utf-8"><title>清除缓存</title></head>
<body style="font-family:sans-serif;text-align:center;padding:80px 20px;background:#0a0a14;color:#e8e8f0">
<h2>正在清除浏览器缓存...</h2>
<p id="s">请稍候</p>
<script>
(async()=>{
  const s=document.getElementById('s');
  try{
    if('serviceWorker' in navigator){
      const regs=await navigator.serviceWorker.getRegistrations();
      for(const r of regs){await r.unregister();}
      s.textContent='已清除 '+regs.length+' 个 Service Worker';
    }
    const keys=await caches.keys();
    for(const k of keys){await caches.delete(k);}
    try{localStorage.clear()}catch(e){}
    try{sessionStorage.clear()}catch(e){}
    s.textContent='缓存已清除，正在跳转...';
    setTimeout(()=>{window.location.href='/app?_t='+Date.now();},1000);
  }catch(e){
    s.textContent='清除失败: '+e.message;
  }
})();
</script></body></html>""", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Clear-Site-Data": '"cache", "storage"',
    })


@app.get("/error")
@app.get("/error/")
async def error_page():
    return FileResponse("src/client/error.html")


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


# ── System API (供 Cursor 前端用) ──────────────────────────────────

@app.post("/api/system/restart")
async def system_restart(request: Request):
    """重启服务（需要确认参数防止误触发）"""
    try:
        body = await request.json()
        if not body.get("confirm"):
            return {"ok": False, "error": "需要 confirm:true 参数"}
    except Exception:
        pass
    return await restart()


@app.post("/api/system/clear-cache")
async def system_clear_cache():
    """清除各类缓存"""
    cleared = []
    try:
        # FTS jieba 缓存
        from .memory_search import _FTS5_AVAILABLE, _JIEBA_FTS_AVAILABLE
        import src.server.memory_search as ms
        ms._FTS5_AVAILABLE = None
        ms._JIEBA_FTS_AVAILABLE = None
        cleared.append("fts")
    except Exception:
        pass
    try:
        # OCR 缓存
        if desktop and hasattr(desktop, '_ocr_cache'):
            desktop._ocr_cache = []
            desktop._ocr_cache_ts = 0.0
            cleared.append("ocr")
    except Exception:
        pass
    try:
        # Vision AI 缓存
        from .wechat.moments_reader import MomentsReader
        MomentsReader._vision_cache.clear()
        cleared.append("vision")
    except Exception:
        pass
    return {"ok": True, "cleared": cleared}


@app.get("/api/system/logs")
async def system_logs(lines: int = 30):
    """读取服务器日志尾部"""
    import subprocess
    try:
        log_file = _PROJECT_ROOT / "logs" / "server.log"
        if log_file.exists():
            result = subprocess.run(
                ["tail", "-n", str(min(lines, 200)), str(log_file)],
                capture_output=True, text=True, timeout=3
            )
            return {"lines": result.stdout.strip().split("\n")}
        # 回退：从 loguru 获取最近日志
        return {"lines": ["日志文件未找到，请检查 logs/server.log"]}
    except Exception as e:
        return {"lines": [f"读取日志失败: {e}"]}


# ── Cowork API (协作调度) ──────────────────────────────────────────

@app.get("/api/cowork/status")
async def cowork_status():
    """协作状态：人类活动 + AI 状态 + 任务队列"""
    from .cowork_bus import get_bus
    from .action_journal import get_journal
    bus = get_bus()
    status = bus.get_status()
    status["journal_count"] = len(get_journal()._entries)
    # 附加详细人类状态
    try:
        from .human_detector import get_human_state
        status["human"] = get_human_state().to_dict()
    except Exception:
        pass
    return status


@app.get("/api/cowork/human-status")
async def cowork_human_status():
    """详细人类活动状态"""
    from .human_detector import get_human_state
    return get_human_state().to_dict()


@app.get("/api/cowork/journal")
async def cowork_journal(limit: int = 20):
    """最近 AI 操作日志"""
    from .action_journal import get_journal
    return {"entries": get_journal().get_recent(limit)}


@app.get("/api/cowork/journal/{entry_id}/thumbnails")
async def cowork_journal_thumbs(entry_id: str):
    """获取操作前后截图"""
    from .action_journal import get_journal
    return get_journal().get_entry_thumbnails(entry_id)


@app.post("/api/cowork/undo")
async def cowork_undo():
    """撤销最后一步 AI 操作"""
    from .action_journal import get_journal
    result = get_journal().undo_last()
    if result:
        return {"ok": True, "undone": result.get("desc", "?")}
    return {"ok": False, "error": "无可撤销的操作"}


@app.post("/api/cowork/pause")
async def cowork_pause():
    """暂停 AI 桌面操作"""
    from .cowork_bus import get_bus
    get_bus().pause()
    return {"ok": True, "status": "paused"}


@app.post("/api/cowork/resume")
async def cowork_resume():
    """恢复 AI 桌面操作"""
    from .cowork_bus import get_bus
    get_bus().resume()
    return {"ok": True, "status": "running"}


@app.post("/api/cowork/task")
async def cowork_add_task(request: Request):
    """添加后台任务"""
    from .cowork_bus import get_bus
    data = await request.json()
    bus = get_bus()
    task = bus.add_task(
        task_id=data.get("id", f"task_{int(time.time())}"),
        description=data.get("description", ""),
        target_window=data.get("target_window", ""),
        priority=data.get("priority", 5),
    )
    return {"ok": True, "task": task.to_dict()}
@app.post("/api/config/auto-open-qr")
async def set_auto_open_qr(request: Request):
    """Toggle auto_open_qr in config.ini from the QR page."""
    body = await request.json()
    enabled = body.get("enabled", True)
    cfg_path = str(_PROJECT_ROOT / "config.ini")
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path, encoding="utf-8")
    if not cfg.has_section("system"):
        cfg.add_section("system")
    cfg.set("system", "auto_open_qr", str(enabled).lower())
    with open(cfg_path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return {"ok": True, "auto_open_qr": enabled}


@app.get("/api/config/auto-open-qr")
async def get_auto_open_qr():
    """Read auto_open_qr setting."""
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read(str(_PROJECT_ROOT / "config.ini"), encoding="utf-8")
        val = cfg.get("system", "auto_open_qr", fallback="true").lower() == "true"
        return {"auto_open_qr": val}
    except Exception:
        return {"auto_open_qr": True}


@app.get("/chat")
@app.get("/chat/")
async def chat_page():
    # 统一使用 app.html（chat.html 是旧版，不再维护）
    return FileResponse("src/client/app.html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    return FileResponse("src/client/setup.html")


@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "ts": time.time()}


@app.get("/api/startup-status")
async def startup_status():
    """Report model loading progress for frontend loading screen."""
    elapsed = time.time() - _startup_progress["started_at"] if _startup_progress["started_at"] else 0
    return {
        "ok": True,
        "ready": _startup_progress["ready"],
        "phase": _startup_progress["phase"],
        "message": _startup_progress["message"],
        "elapsed": round(elapsed, 1),
        "components": {
            "stt": _startup_progress["stt"],
            "tts": _startup_progress["tts"],
            "backend": _startup_progress["backend"],
            "workflow": _startup_progress["workflow"],
        },
    }


@app.get("/api/system/health")
async def system_health():
    """Lightweight system health snapshot for the QR dashboard."""
    import psutil
    uptime = time.time() - _startup_progress["started_at"] if _startup_progress["started_at"] else 0
    cpu = psutil.cpu_percent(interval=0)
    mem = psutil.virtual_memory()
    gpu_info = None
    try:
        import subprocess as _sp
        import shutil as _shutil
        if _shutil.which("nvidia-smi"):
            r = _sp.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1,
            )
            if r.returncode == 0:
                parts = r.stdout.strip().split(",")
                if len(parts) >= 3:
                    gpu_info = {"util": int(parts[0].strip()), "mem_used": int(parts[1].strip()), "mem_total": int(parts[2].strip())}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        pass
    except Exception:
        pass
    return {
        "uptime": round(uptime),
        "cpu": round(cpu),
        "mem_used": mem.used // (1024**2),
        "mem_total": mem.total // (1024**2),
        "mem_pct": round(mem.percent),
        "gpu": gpu_info,
        "components": {
            "stt": _startup_progress.get("stt", "unknown"),
            "tts": _startup_progress.get("tts", "unknown"),
            "backend": _startup_progress.get("backend", "unknown"),
            "workflow": _startup_progress.get("workflow", "unknown"),
        },
        "ready": _startup_progress.get("ready", False),
    }


@app.get("/api/system/diagnose")
async def system_diagnose():
    """Run quick connectivity checks on all subsystems."""
    results = {}

    # AI check
    try:
        from src.router.config import RouterConfig
        rc = RouterConfig()
        active = None
        for p in rc.all_providers_meta():
            if p.get("has_key"):
                active = p
                break
        if active:
            results["ai"] = {"ok": True, "provider": active.get("name", "?"), "status": active.get("status", "?")}
        else:
            results["ai"] = {"ok": False, "error": "未配置 AI 平台"}
    except Exception as e:
        results["ai"] = {"ok": False, "error": str(e)}

    # TTS check
    results["tts"] = {"ok": _startup_progress.get("tts") == "ready", "status": _startup_progress.get("tts", "unknown")}

    # STT check
    results["stt"] = {"ok": _startup_progress.get("stt") == "ready", "status": _startup_progress.get("stt", "unknown")}

    # WeChat check (Windows only)
    try:
        if sys.platform == "win32":
            from .wechat_monitor import _wechat_is_running
            running = _wechat_is_running()
            results["wechat"] = {"ok": running, "status": "运行中" if running else "未运行"}
        else:
            results["wechat"] = {"ok": False, "status": "仅支持 Windows"}
    except Exception:
        results["wechat"] = {"ok": False, "status": "模块不可用"}

    # Network check
    try:
        import socket
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
        lan_ips = [ip for ip in ips if not ip.startswith("127.")]
        results["network"] = {"ok": len(lan_ips) > 0, "ips": lan_ips}
    except Exception:
        results["network"] = {"ok": False, "ips": []}

    return results


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
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/i18n/{name:path}")
async def serve_i18n_json(name: str):
    """Serve locale bundles from src/client/i18n/ (P3 client i18n)."""
    if not name.endswith(".json"):
        return Response(content="Not found", status_code=404)
    fpath = Path("src/client/i18n") / name
    if not fpath.exists() or not fpath.is_file():
        return Response(content="Not found", status_code=404)
    return FileResponse(
        str(fpath),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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


# ── 微信 ClawBot (iLink) API ──
@app.get("/api/ilink/status")
async def ilink_status():
    """iLink 连接状态"""
    try:
        from .ilink_bot import get_ilink_bot
        return get_ilink_bot().get_status()
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.post("/api/ilink/login")
async def ilink_login():
    """获取 iLink 登录二维码"""
    try:
        from .ilink_bot import get_ilink_bot
        bot = get_ilink_bot()
        qr = await bot.get_login_qrcode()
        return {"ok": True, **qr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/ilink/qrcode-status")
async def ilink_qrcode_status(qrcode_id: str):
    """检查二维码扫描状态"""
    try:
        from .ilink_bot import get_ilink_bot
        bot = get_ilink_bot()
        result = await bot.check_qrcode_status(qrcode_id)
        if result.get("connected"):
            # 绑定成功，启动消息轮询
            from .ilink_handler import handle_wechat_message
            bot.set_message_handler(handle_wechat_message)
            asyncio.create_task(bot.start_polling())
        return result
    except Exception as e:
        return {"connected": False, "error": str(e)}


@app.post("/api/ilink/disconnect")
async def ilink_disconnect():
    """断开 iLink 连接"""
    try:
        from .ilink_bot import get_ilink_bot
        get_ilink_bot().disconnect()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/ilink/start")
async def ilink_start():
    """手动启动 iLink 轮询（已有 token 时）"""
    try:
        from .ilink_bot import get_ilink_bot
        from .ilink_handler import handle_wechat_message
        bot = get_ilink_bot()
        if not bot.is_connected:
            return {"ok": False, "error": "未绑定微信，请先扫码登录"}
        bot.set_message_handler(handle_wechat_message)
        asyncio.create_task(bot.start_polling())
        return {"ok": True, "message": "iLink 轮询已启动"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 定时任务 API ──
@app.get("/api/scheduler/status")
async def api_scheduler_status():
    """定时任务状态"""
    try:
        from .scheduler import get_scheduler
        s = get_scheduler()
        return {
            "running": s._running,
            "tasks": [{"name": t["name"], "hour": t["hour"], "minute": t["minute"],
                       "weekday": t["weekday"], "last_run": t["last_run"]} for t in s._tasks],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/scheduler/trigger/{task_name}")
async def api_trigger_task(task_name: str):
    """手动触发定时任务"""
    try:
        from .scheduler import get_scheduler
        s = get_scheduler()
        for t in s._tasks:
            if task_name in t["name"]:
                result = t["func"]()
                if hasattr(result, '__await__'):
                    await result
                return {"ok": True, "name": t["name"]}
        return {"ok": False, "error": "任务不存在"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 护城河数据导出/导入 API ──
@app.get("/api/moat/export")
async def api_moat_export():
    """导出护城河数据（JSON）"""
    try:
        from .data_export import export_moat_data
        return export_moat_data()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/moat/export-zip")
async def api_moat_export_zip():
    """导出护城河数据（ZIP，含项目文件）"""
    try:
        from .data_export import export_moat_zip
        content = export_moat_zip()
        filename = f"moat_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}),
                        status_code=500, media_type="application/json")


@app.post("/api/moat/import")
async def api_moat_import(request: Request):
    """导入护城河数据"""
    try:
        body = await request.json()
        from .data_export import import_moat_data
        result = import_moat_data(body)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 护城河分数 API ──
@app.get("/api/moat-score")
async def api_moat_score():
    """护城河综合分数"""
    try:
        from .moat_score import calculate_moat_score
        return calculate_moat_score()
    except Exception as e:
        return {"total": 0, "max": 100, "percentage": 0, "level": "未知", "error": str(e)}


# ── Agent 进化 API ──
@app.get("/api/agents/evolution")
async def api_agent_evolution():
    """Agent 专长进化统计"""
    try:
        from .agent_evolution import get_evolution_stats
        return {"stats": get_evolution_stats()}
    except Exception as e:
        return {"error": str(e)}


# ── 用户画像 API（护城河：越用越懂老板）──
@app.get("/api/user/profile")
async def api_get_user_profile():
    """获取用户画像"""
    try:
        from .user_profile_ai import get_user_profile
        return get_user_profile()
    except Exception as e:
        return {"error": str(e)}


@app.put("/api/user/profile")
async def api_update_user_profile(request: Request):
    """手动更新用户画像"""
    try:
        from .user_profile_ai import get_user_profile, save_user_profile
        body = await request.json()
        profile = get_user_profile()
        # 只更新允许的字段
        allowed = {"company", "industry", "products", "target_users", "brand_tone",
                    "writing_style", "forbidden_words", "common_terms", "competitor_names",
                    "budget_range", "team_size"}
        for k, v in body.items():
            if k in allowed:
                profile[k] = v
        save_user_profile(profile)
        return {"ok": True, "profile": profile}
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}),
                        status_code=500, media_type="application/json")


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


@app.get("/project")
@app.get("/project/")
@app.get("/projects")
async def project_page():
    return FileResponse("src/client/project.html")


@app.get("/remote")
@app.get("/remote/")
async def remote_page():
    return FileResponse("src/client/remote.html")


@app.get("/demo")
@app.get("/demo/")
async def demo_page():
    return FileResponse("src/client/demo.html")


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


@app.get("/api/system/update-check")
async def system_update_check_alias():
    """Alias for QR / legacy clients (same payload as /api/update/check)."""
    return await check_update()


@app.get("/api/system/network-status")
async def network_status():
    """网络状态（在线/本地/离线）"""
    from .offline_manager import get_offline_manager
    return get_offline_manager().get_status()


# ── IoT 智能家居 API ─────────────────────────────────────────

@app.get("/api/iot/devices")
async def iot_devices():
    """IoT 设备列表"""
    from .iot_bridge import get_iot_bridge
    bridge = get_iot_bridge()
    devices = await bridge.get_devices()
    return {"devices": [d.to_dict() for d in devices], "configured": bridge.is_configured}


@app.post("/api/iot/control")
async def iot_control(request: Request):
    """控制 IoT 设备"""
    from .iot_bridge import get_iot_bridge
    body = await request.json()
    entity_id = body.get("entity_id", "")
    action = body.get("action", "toggle")
    value = body.get("value", {})

    # 支持按名称查找
    bridge = get_iot_bridge()
    if not entity_id and body.get("name"):
        dev = bridge.get_device_by_name(body["name"])
        if dev:
            entity_id = dev.id

    if not entity_id:
        return {"error": "请指定 entity_id 或 name"}
    result = await bridge.control(entity_id, action, value)
    return result


@app.post("/api/iot/config")
async def iot_config(request: Request):
    """保存 HomeAssistant 配置"""
    from .iot_bridge import get_iot_bridge
    body = await request.json()
    bridge = get_iot_bridge()
    bridge.configure(body.get("url", ""), body.get("token", ""))
    # 保存到 config.ini
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini", encoding="utf-8")
        if not cfg.has_section("iot"):
            cfg.add_section("iot")
        cfg.set("iot", "homeassistant_url", body.get("url", ""))
        cfg.set("iot", "homeassistant_token", body.get("token", ""))
        with open("config.ini", "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception:
        pass
    return {"ok": True}


# ── Web Push API ─────────────────────────────────────────────

_push_subscriptions: dict = {}  # client_id → subscription JSON

@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """注册 Web Push 订阅"""
    body = await request.json()
    sub = body.get("subscription")
    if not sub:
        return {"ok": False, "error": "缺少 subscription"}
    # 用 endpoint 的 hash 作为 ID
    import hashlib
    endpoint = sub.get("endpoint", "")
    client_id = hashlib.md5(endpoint.encode()).hexdigest()[:12]
    _push_subscriptions[client_id] = {
        "subscription": sub,
        "created_at": time.time(),
        "types": body.get("types", ["wechat", "system", "workflow"]),
    }
    logger.info(f"[Push] 新订阅: {client_id}")
    return {"ok": True, "client_id": client_id}


@app.get("/api/push/status")
async def push_status():
    """推送订阅状态"""
    return {
        "subscriptions": len(_push_subscriptions),
        "clients": list(_push_subscriptions.keys()),
    }


@app.post("/api/push/test")
async def push_test():
    """发送测试推送"""
    sent = 0
    for cid, info in _push_subscriptions.items():
        try:
            from pywebpush import webpush
            webpush(
                subscription_info=info["subscription"],
                data=json.dumps({"title": "十三香小龙虾", "body": "推送测试成功！", "icon": "/icon.png"}),
                vapid_private_key="",  # 需要配置
                vapid_claims={"sub": "mailto:admin@openclaw.ai"},
            )
            sent += 1
        except Exception as e:
            logger.debug(f"[Push] 发送失败 {cid}: {e}")
    return {"ok": True, "sent": sent, "total": len(_push_subscriptions)}


# ── 文件传输 API ─────────────────────────────────────────────

from fastapi import UploadFile, File as FastAPIFile

@app.post("/api/files/upload")
async def file_upload(file: UploadFile = FastAPIFile(...)):
    """手机上传文件到电脑"""
    from .file_transfer import get_transfer_manager
    content = await file.read()
    try:
        record = get_transfer_manager().upload(file.filename or "unnamed", content)
        return {"ok": True, "file": record.to_dict()}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/files/list")
async def file_list():
    """文件传输历史"""
    from .file_transfer import get_transfer_manager
    return {"files": get_transfer_manager().list_records()}


@app.get("/api/files/{file_id}/download")
async def file_download(file_id: str):
    """下载文件"""
    from .file_transfer import get_transfer_manager
    path = get_transfer_manager().get_file_path(file_id)
    if not path:
        return Response(content="文件不存在", status_code=404)
    return FileResponse(str(path), filename=path.name)


@app.post("/api/files/push")
async def file_push(request: Request):
    """电脑推送文件到手机"""
    from .file_transfer import get_transfer_manager
    body = await request.json()
    source = body.get("path", "")
    if not source:
        return {"ok": False, "error": "缺少 path"}
    record = get_transfer_manager().push(source)
    if record:
        return {"ok": True, "file": record.to_dict()}
    return {"ok": False, "error": "文件不存在"}


@app.delete("/api/files/{file_id}")
async def file_delete(file_id: str):
    """删除传输文件"""
    from .file_transfer import get_transfer_manager
    ok = get_transfer_manager().delete(file_id)
    return {"ok": ok}


# ── 远程剪贴板 API ───────────────────────────────────────────

@app.post("/api/remote/clipboard")
async def clipboard_sync(request: Request):
    """剪贴板双向同步"""
    body = await request.json()
    action = body.get("action", "get")  # get / set

    if action == "set":
        # 手机 → 电脑剪贴板
        text = body.get("text", "")
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"ok": True, "action": "set"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        # 电脑剪贴板 → 手机
        try:
            import pyperclip
            text = pyperclip.paste()
            return {"ok": True, "text": text[:10000]}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ── AI 状态检查 + 快速配置 + 设备识别 ─────────────────────

@app.get("/api/ai/status")
async def ai_status():
    """AI 配置状态——前端用来决定是否显示配置引导"""
    import os
    configured = False
    platform_name = ""
    platform_id = ""

    try:
        from src.router.config import RouterConfig
        rc = RouterConfig()
        for p in rc.all_providers_meta():
            pid = p["id"]
            key = rc.get_provider_key(pid)
            if key and len(key) > 5:
                configured = True
                platform_name = p.get("name_short", p.get("name", pid))
                platform_id = pid
                break
    except Exception:
        pass

    # 也检查环境变量
    if not configured:
        for env_key, name in [("ZHIPU_API_KEY", "智谱"), ("DEEPSEEK_API_KEY", "DeepSeek")]:
            if os.environ.get(env_key, ""):
                configured = True
                platform_name = name
                break

    return {
        "configured": configured,
        "platform": platform_name,
        "platform_id": platform_id,
        "can_chat": backend is not None,
    }


@app.post("/api/ai/quick-setup")
async def ai_quick_setup(request: Request):
    """一键配置 AI（输入 API Key 自动识别平台）"""
    import os
    body = await request.json()
    api_key = body.get("api_key", "").strip()
    if not api_key or len(api_key) < 5:
        return {"ok": False, "error": "API Key 不能为空"}

    # 自动识别平台
    platform = "unknown"
    env_key = ""
    if "." in api_key and len(api_key.split(".")) == 2:
        platform = "智谱 GLM-4-Flash（免费）"
        env_key = "ZHIPU_API_KEY"
    elif api_key.startswith("sk-"):
        # 可能是 DeepSeek 或 OpenAI
        if len(api_key) > 40:
            platform = "OpenAI"
            env_key = "OPENAI_API_KEY"
        else:
            platform = "DeepSeek"
            env_key = "DEEPSEEK_API_KEY"
    else:
        # 默认当智谱处理
        platform = "智谱 GLM-4-Flash"
        env_key = "ZHIPU_API_KEY"

    # 保存到 .env
    try:
        os.environ[env_key] = api_key
        env_path = Path(".env")
        lines = env_path.read_text(encoding="utf-8").split("\n") if env_path.exists() else []
        # 替换或追加
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_key}="):
                lines[i] = f"{env_key}={api_key}"
                found = True
                break
        if not found:
            lines.append(f"{env_key}={api_key}")
        env_path.write_text("\n".join(lines), encoding="utf-8")

        os.environ["OPENCLAW_SETUP_DONE"] = "true"
        return {"ok": True, "platform": platform, "message": f"已配置 {platform}，可以开始使用了！"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/client/info")
async def client_info(request: Request):
    """识别客户端类型（设备/浏览器/网络）"""
    ua = request.headers.get("user-agent", "")
    host = request.client.host if request.client else ""

    is_mobile = any(k in ua.lower() for k in ["mobile", "android", "iphone", "ipad"])
    is_tauri = "tauri" in ua.lower()

    return {
        "device": "mobile" if is_mobile else "desktop",
        "client": "tauri" if is_tauri else "browser",
        "network": "local" if host in ("127.0.0.1", "::1") else ("lan" if host.startswith(("192.168.", "10.", "172.")) else "remote"),
        "user_agent": ua[:100],
    }


# ── 项目工作空间 API ─────────────────────────────────────────

@app.get("/api/projects")
async def list_projects_api():
    """项目列表"""
    from .project_workspace import list_projects
    return {"projects": list_projects()}

@app.get("/api/projects/{project_id}")
async def get_project_api(project_id: str):
    """项目详情"""
    from .project_workspace import get_project
    p = get_project(project_id)
    if not p:
        return {"error": "项目不存在"}
    return {"project": p.to_dict(), "files": p.list_files()}

@app.get("/api/projects/{project_id}/files/{filename}")
async def get_project_file(project_id: str, filename: str):
    """读取项目文件"""
    from .project_workspace import get_project
    p = get_project(project_id)
    if not p:
        return Response(content="项目不存在", status_code=404)
    content = p.get_file(filename)
    if content is None:
        return Response(content="文件不存在", status_code=404)
    # 判断文件类型
    if filename.endswith('.md'):
        return Response(content=content, media_type="text/markdown; charset=utf-8")
    elif filename.endswith('.html'):
        return Response(content=content, media_type="text/html; charset=utf-8")
    elif filename.endswith('.csv'):
        return Response(content=content, media_type="text/csv; charset=utf-8")
    return Response(content=content, media_type="text/plain; charset=utf-8")

@app.get("/report/{project_id}")
async def share_report(project_id: str):
    """公开分享报告页面（无需登录）"""
    from .project_workspace import get_project, list_projects
    # 先尝试精确匹配
    p = get_project(project_id)
    if not p:
        # 尝试模糊匹配（URL 可能只传了部分 ID）
        for proj in list_projects():
            if project_id in proj.get("project_id", ""):
                p = get_project(proj["project_id"])
                break
    if not p:
        return HTMLResponse("<h1>报告不存在</h1><p>该项目报告可能已被删除。</p>", status_code=404)
    # 找 HTML 报告文件
    for f in p.list_files():
        if f.get("filename", "").endswith(".html"):
            content = p.get_file(f["filename"])
            if content:
                return HTMLResponse(content)
    # 降级：用 README.md 生成简单页面
    readme = p.get_file("README.md")
    if readme:
        import re
        body = readme
        body = re.sub(r'^### (.*$)', r'<h3>\1</h3>', body, flags=re.M)
        body = re.sub(r'^## (.*$)', r'<h2>\1</h2>', body, flags=re.M)
        body = re.sub(r'^# (.*$)', r'<h1>\1</h1>', body, flags=re.M)
        body = re.sub(r'^\- (.*$)', r'<li>\1</li>', body, flags=re.M)
        body = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', body)
        body = body.replace('\n\n', '</p><p>').replace('\n', '<br>')
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{p.name} — 十三香小龙虾 AI 工作队</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,sans-serif;background:#0b0d14;color:#eee;max-width:800px;margin:0 auto;padding:20px 16px}}
h1,h2,h3{{margin:20px 0 10px;color:#fff}}p{{margin:8px 0;line-height:1.7;color:#ccc}}li{{margin:4px 0;color:#ccc}}strong{{color:#fff}}
.header{{background:linear-gradient(135deg,#6c63ff,#8b5cf6);padding:30px 20px;text-align:center;border-radius:12px;margin-bottom:20px}}
.header h1{{font-size:22px;margin-bottom:6px}}.header p{{opacity:.8;font-size:13px}}
.footer{{text-align:center;padding:24px;color:#555;font-size:11px;margin-top:30px}}</style></head><body>
<div class="header"><h1>{p.name}</h1><p>{p.task[:80]}</p></div>
<div>{body}</div>
<div class="footer">由十三香小龙虾 AI 工作队自动生成</div></body></html>"""
        return HTMLResponse(html)
    return HTMLResponse("<h1>暂无报告内容</h1>", status_code=404)


@app.get("/api/projects/{project_id}/share-url")
async def get_share_url(project_id: str, request: Request):
    """获取项目分享链接"""
    host = request.headers.get("host", "localhost:8766")
    scheme = "https" if "443" in host else "http"
    url = f"{scheme}://{host}/report/{project_id}"
    return {"url": url, "project_id": project_id}


@app.get("/api/projects/{project_id}/download")
async def download_project(project_id: str):
    """下载项目（ZIP 打包）"""
    from .project_workspace import get_project
    import zipfile, io
    p = get_project(project_id)
    if not p:
        return Response(content="项目不存在", status_code=404)
    # 创建 ZIP
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in p.dir.iterdir():
            if f.is_file():
                zf.write(f, f.name)
    buffer.seek(0)
    return Response(
        content=buffer.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{project_id}.zip"'},
    )


# ── 集群 API ─────────────────────────────────────────────────

@app.get("/api/cluster/nodes")
async def cluster_nodes():
    """集群节点列表"""
    from .cluster import get_cluster
    return {"nodes": get_cluster().get_nodes()}

@app.post("/api/cluster/nodes/add")
async def cluster_add_node(request: Request):
    """添加集群节点"""
    from .cluster import get_cluster
    body = await request.json()
    node = get_cluster().add_node(body.get("host", ""), body.get("port", 8766), body.get("name", ""))
    return {"ok": True, "node": node.to_dict()}

@app.get("/api/cluster/status")
async def cluster_status():
    """集群状态"""
    from .cluster import get_cluster
    return get_cluster().get_status()

@app.post("/api/cluster/discover")
async def cluster_discover():
    """启动局域网自动发现"""
    from .cluster import get_cluster
    get_cluster().start_discovery()
    return {"ok": True, "message": "局域网发现已启动"}

@app.post("/api/cluster/task")
async def cluster_receive_task(request: Request):
    """Worker：接收 Master 分发的任务"""
    from .agent_team import Agent, AgentRole, SubTask
    body = await request.json()
    rd = body.get("agent_role", {})
    role = AgentRole(id=rd.get("id","w"), name=rd.get("name","Worker"),
                     avatar="🤖", description="", system_prompt=rd.get("system_prompt","你是AI助手。"))
    agent = Agent(role)
    task = SubTask(agent_id=role.id, description=body.get("task_description",""))
    async def _ai(messages, model=""):
        return await backend.chat_simple(messages) if backend else "AI未就绪"
    result = await agent.execute(task, body.get("context",{}), _ai)
    return {"ok": True, "result": result, "status": task.status}


# ── 每日早报 API ─────────────────────────────────────────────

@app.get("/api/daily-brief")
async def daily_brief():
    """每日早报：天气+未读消息+今日待办"""
    import datetime
    now = datetime.datetime.now()
    brief = {
        "time": now.strftime("%Y-%m-%d %H:%M"),
        "greeting": "早上好" if now.hour < 12 else ("下午好" if now.hour < 18 else "晚上好"),
        "sections": [],
    }

    # 天气（使用 tools 中的 get_weather）
    try:
        from .tools import get_weather
        weather = await get_weather("Beijing")
        brief["sections"].append({
            "icon": "🌤",
            "title": "天气",
            "content": f"{weather.get('city','')}: {weather.get('description','')}, {weather.get('temperature','')}°C",
        })
    except Exception:
        brief["sections"].append({"icon": "🌤", "title": "天气", "content": "获取失败"})

    # 未读微信消息
    try:
        from .wechat_monitor import WeChatMonitor
        monitor = WeChatMonitor()
        sessions = monitor.get_unread_sessions()
        unread_count = len(sessions) if sessions else 0
        brief["sections"].append({
            "icon": "💬",
            "title": "微信",
            "content": f"{unread_count} 条未读消息" if unread_count else "无未读消息",
        })
    except Exception:
        brief["sections"].append({"icon": "💬", "title": "微信", "content": "未连接"})

    # 团队历史
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        today = now.strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM team_history WHERE created_at > ?",
            (now.timestamp() - 86400,)
        ).fetchone()[0]
        brief["sections"].append({
            "icon": "👥",
            "title": "团队",
            "content": f"过去24小时完成 {count} 个团队任务" if count else "暂无团队任务",
        })
    except Exception:
        pass

    # 系统状态
    try:
        import psutil
        brief["sections"].append({
            "icon": "📊",
            "title": "系统",
            "content": f"CPU {psutil.cpu_percent()}%, 内存 {psutil.virtual_memory().percent}%",
        })
    except Exception:
        pass

    return brief


@app.get("/api/remote/status")
async def remote_status():
    """远程连接状态"""
    return {
        "desktop_available": desktop is not None,
        "screen_size": f"{desktop._screen_w}x{desktop._screen_h}" if desktop else "N/A",
    }


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

    # 直接传 app 实例（非字符串），避免两个 server 各自 import 导致 startup 执行两次
    https_config = uvicorn.Config(
        app,
        host=settings.host, port=port,
        ssl_keyfile=server_key, ssl_certfile=server_crt,
        reload=False, log_level="info",
    )
    http_config = uvicorn.Config(
        app,
        host=settings.host, port=http_port,
        reload=False, log_level="warning",
    )

    async def serve_both():
        https_server = uvicorn.Server(https_config)
        http_server = uvicorn.Server(http_config)

        async def _open_browser():
            if os.environ.get("OPENCLAW_DESKTOP") == "1":
                return
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read(str(_PROJECT_ROOT / "config.ini"), encoding="utf-8")
                if cfg.get("system", "auto_open_qr", fallback="true").lower() == "false":
                    logger.info("🌐 auto_open_qr=false, skipping browser open")
                    return
            except Exception:
                pass
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
