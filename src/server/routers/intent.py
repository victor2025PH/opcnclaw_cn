# -*- coding: utf-8 -*-
"""意图融合 API 路由

端点：
  - POST /api/intent/signal      — 接收前端多模态信号
  - POST /api/intent/batch       — 批量推送信号（减少 HTTP 开销）
  - POST /api/intent/emergency   — 紧急停止
  - GET  /api/intent/state       — 当前融合状态
  - GET  /api/intent/history     — 融合历史
  - GET  /api/intent/config      — 引擎配置
  - PUT  /api/intent/config      — 修改引擎配置
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from src.server.intent_fusion import (
    get_engine, push_signal, Signal, SignalPriority,
    INTENT_CATEGORIES, CHANNEL_PRIORITY,
)

router = APIRouter(prefix="/api/intent", tags=["intent-fusion"])


# ── 请求模型 ─────────────────────────────────────────────────

class SignalRequest(BaseModel):
    """单条信号"""
    channel: str = Field(..., description="信号通道: gaze/expression/voice/touch/desktop")
    name: str = Field(..., description="信号名: nod/smile_hold/yes/click 等")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="置信度 0-1")
    params: Optional[Dict] = Field(default=None, description="附加参数")
    priority: int = Field(0, description="覆盖优先级 (0=使用通道默认)")


class BatchSignalRequest(BaseModel):
    """批量信号"""
    signals: List[SignalRequest]


class ConfigUpdateRequest(BaseModel):
    """引擎配置更新"""
    window_ms: Optional[int] = Field(None, ge=100, le=2000, description="融合窗口毫秒")
    min_confidence: Optional[float] = Field(None, ge=0.1, le=0.9, description="最低置信度")
    emergency_threshold: Optional[float] = Field(None, ge=0.3, le=1.0, description="紧急停止阈值")


# ── 端点 ─────────────────────────────────────────────────────

@router.post("/signal")
async def receive_signal(req: SignalRequest):
    """接收一条多模态信号，推入融合引擎。

    前端 expression-system.js / gaze-tracker.js 调用此接口上报信号。
    紧急停止信号会立即处理，不等融合窗口。
    """
    push_signal(
        channel=req.channel,
        name=req.name,
        confidence=req.confidence,
        params=req.params or {},
        priority=req.priority,
    )
    return {"ok": True, "intent": req.name}


@router.post("/batch")
async def receive_batch(req: BatchSignalRequest):
    """批量推送信号（减少 HTTP 开销，适合前端定时批量上报）"""
    engine = get_engine()
    for sig in req.signals:
        engine.push_raw(
            channel=sig.channel,
            name=sig.name,
            confidence=sig.confidence,
            params=sig.params or {},
            priority=sig.priority,
        )
    return {"ok": True, "count": len(req.signals)}


@router.post("/emergency")
async def emergency_stop():
    """紧急停止 — 立即暂停所有 AI 桌面操作。

    等价于推送一条最高优先级的 stop 信号。
    会同时触发 CoworkBus.pause()。
    """
    push_signal(
        channel="voice",
        name="emergency_stop",
        confidence=1.0,
        priority=SignalPriority.EMERGENCY,
    )
    return {"ok": True, "action": "emergency_stop"}


@router.get("/state")
async def get_state():
    """当前融合引擎状态。

    返回：运行状态、当前融合意图、活跃信号列表、统计数据。
    前端 intent-panel.js 每 2 秒轮询此接口。
    """
    engine = get_engine()
    return engine.get_state()


@router.get("/history")
async def get_history(limit: int = 20):
    """最近 N 条融合结果。"""
    engine = get_engine()
    history = engine.get_history(limit)
    return {"history": history, "count": len(history)}


@router.get("/config")
async def get_config():
    """引擎配置（可在线调整）"""
    engine = get_engine()
    return {
        "window_ms": engine.WINDOW_MS,
        "min_confidence": engine.MIN_CONFIDENCE,
        "emergency_threshold": engine.EMERGENCY_THRESHOLD,
        "signal_ttl": engine.SIGNAL_TTL,
        "channels": {k: int(v) for k, v in CHANNEL_PRIORITY.items()},
        "intents": {k: sorted(v) for k, v in INTENT_CATEGORIES.items()},
    }


@router.put("/config")
async def update_config(req: ConfigUpdateRequest):
    """在线调整引擎参数（无需重启）"""
    engine = get_engine()
    changed = {}

    if req.window_ms is not None:
        engine.WINDOW_MS = req.window_ms
        changed["window_ms"] = req.window_ms

    if req.min_confidence is not None:
        engine.MIN_CONFIDENCE = req.min_confidence
        changed["min_confidence"] = req.min_confidence

    if req.emergency_threshold is not None:
        engine.EMERGENCY_THRESHOLD = req.emergency_threshold
        changed["emergency_threshold"] = req.emergency_threshold

    return {"ok": True, "changed": changed}
