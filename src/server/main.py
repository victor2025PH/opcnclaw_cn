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
app = FastAPI(title="OpenClaw Voice", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# ═══════════════════════════════════════════════════════════════════
# Global Instances
# ═══════════════════════════════════════════════════════════════════

stt: Optional[WhisperSTT] = None
tts: Optional[ChatterboxTTS] = None
backend: Optional[AIBackend] = None
vad: Optional[VoiceActivityDetector] = None


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

@app.on_event("startup")
async def startup():
    """Initialize models on server start."""
    global stt, tts, backend, vad

    logger.info("Initializing OpenClaw Voice server...")

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

    if gateway_url and gateway_token:
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

    if _WORKFLOW_AVAILABLE:
        try:
            wf_engine = get_wf_engine()
            await wf_engine.start(ai_backend=backend, tts_engine=tts)
            logger.info("⚡ Workflow engine started")
        except Exception as e:
            logger.warning(f"Workflow engine startup failed: {e}")

    # Ollama auto-detect
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

    logger.info("✅ OpenClaw Voice server ready!")


@app.on_event("shutdown")
async def shutdown():
    if _WORKFLOW_AVAILABLE:
        try:
            await get_wf_engine().stop()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Page Serving & Core Endpoints (shared between both Cursors)
# ═══════════════════════════════════════════════════════════════════

@app.get("/app")
@app.get("/app/")
async def app_page():
    return FileResponse("src/client/app.html")


@app.get("/setup")
@app.get("/setup/")
async def setup_page():
    return FileResponse("src/client/setup.html")


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
        "gateway_url": gateway_url, "token": gateway_token,
    }


@app.get("/chat")
@app.get("/chat/")
async def chat_page():
    return FileResponse("src/client/chat.html")


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
        from fastapi.responses import RedirectResponse
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


@app.get("/")
@app.get("/voice")
@app.get("/voice/")
async def index():
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
