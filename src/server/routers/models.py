# -*- coding: utf-8 -*-
"""Model management, health check, and system info routes.

Exposes:
  - /api/models          — list available models + install status
  - /api/models/install  — install a model by ID
  - /api/models/uninstall — uninstall a model by ID
  - /api/models/summary  — installed model summary
  - /api/system/gpu      — GPU info
  - /api/system/disk     — disk space
  - /api/system/health   — startup health check results
  - /api/s2s/status      — Speech-to-Speech engine status
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import Response
from loguru import logger
from starlette.responses import StreamingResponse

from ..model_downloader import (
    get_models, install_model, uninstall_model,
    check_installed, get_gpu_info, get_disk_space,
    get_installed_summary, get_install_mode,
)
from ..health import HealthChecker

router = APIRouter()

_health_checker = HealthChecker()

_s2s_engine = None
_s2s_init_attempted = False


def _get_s2s():
    """Lazy-init S2S — only attempt once to avoid blocking startup."""
    global _s2s_engine, _s2s_init_attempted
    if _s2s_init_attempted:
        return _s2s_engine
    _s2s_init_attempted = True
    try:
        from ..s2s import SpeechToSpeech
        _s2s_engine = SpeechToSpeech()
        if _s2s_engine.available:
            logger.info(f"S2S engine loaded: {_s2s_engine.backend_name}")
        else:
            logger.info("S2S engine: no backend available (GPU < 8GB or deps missing)")
    except Exception as e:
        logger.info(f"S2S engine not available: {e}")
    return _s2s_engine


# ── Model listing ──

@router.get("/api/models")
async def list_models():
    """List all available models with install status."""
    models = get_models()
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "size_mb": m.size_mb,
                "category": m.category,
                "requires_gpu": m.requires_gpu,
                "min_vram_gb": m.min_vram_gb,
                "installed": m.installed,
            }
            for m in models
        ],
        "mode": get_install_mode(),
    }


@router.get("/api/models/summary")
async def models_summary():
    """Installed model summary (count, size, mode)."""
    return get_installed_summary()


# ── Model install / uninstall (SSE progress) ──

@router.post("/api/models/{model_id}/install")
async def install_model_api(model_id: str):
    """Install a model, streaming progress via SSE."""
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue = asyncio.Queue()

    def on_progress(msg: str, pct: int):
        loop.call_soon_threadsafe(progress_queue.put_nowait, (msg, pct))

    async def stream():
        task = loop.run_in_executor(
            None, lambda: install_model(model_id, on_progress=on_progress)
        )
        while True:
            done = task.done()
            try:
                msg, pct = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield f"data: {json.dumps({'type': 'progress', 'message': msg, 'percent': pct})}\n\n"
                if pct == 100 or pct == -1:
                    break
            except asyncio.TimeoutError:
                if done:
                    break

        success = await task
        yield f"data: {json.dumps({'type': 'done', 'success': success})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/models/{model_id}/uninstall")
async def uninstall_model_api(model_id: str):
    """Uninstall a model by ID."""
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, uninstall_model, model_id)
    return {"ok": ok, "model_id": model_id}


@router.get("/api/models/{model_id}/check")
async def check_model_installed(model_id: str):
    """Runtime check whether a model's packages are actually importable."""
    loop = asyncio.get_running_loop()
    installed = await loop.run_in_executor(None, check_installed, model_id)
    return {"model_id": model_id, "installed": installed}


# ── System info ──

@router.get("/api/system/gpu")
async def gpu_info():
    """GPU availability and VRAM."""
    return get_gpu_info()


@router.get("/api/system/disk")
async def disk_info():
    """Disk space on the working drive."""
    return get_disk_space()


@router.get("/api/system/health")
async def health_check():
    """Run all health checks and return a summary."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _health_checker.summary)
    return result


# ── Speech-to-Speech status ──

@router.get("/api/s2s/status")
async def s2s_status():
    """Return S2S engine availability and backend info."""
    engine = _get_s2s()
    if engine and engine.available:
        return {
            "available": True,
            "backend": engine.backend_name,
            "gpu": engine.get_gpu_info(),
        }
    return {"available": False, "backend": "none"}
