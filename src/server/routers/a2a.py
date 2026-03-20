# -*- coding: utf-8 -*-
"""A2A (Agent-to-Agent) 协议 API 路由

端点：
  - GET  /.well-known/agent.json   — Agent Card 发现
  - GET  /api/a2a/card             — Agent Card (别名)
  - POST /api/a2a/task             — 创建任务
  - GET  /api/a2a/task/{id}        — 查询任务状态
  - POST /api/a2a/task/{id}/cancel — 取消任务
  - POST /api/a2a/task/{id}/message — 向任务发送消息
  - GET  /api/a2a/tasks            — 任务列表
  - POST /api/a2a/webhook          — 注册 Webhook
  - GET  /api/a2a/skills           — 可用技能列表
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from src.server.a2a import get_a2a_server, get_agent_card

router = APIRouter(tags=["a2a"])


# ── 请求模型 ─────────────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    source_agent: str = Field(..., description="发起方 Agent ID")
    intent: str = Field(..., description="任务意图/技能ID: wechat_send, screenshot, desktop_control 等")
    params: Optional[Dict] = Field(default=None, description="任务参数")
    priority: int = Field(5, ge=1, le=10, description="优先级 1(最高)-10(最低)")
    metadata: Optional[Dict] = Field(default=None, description="元数据")


class SendMessageRequest(BaseModel):
    role: str = Field("user", description="消息角色: user/agent/system")
    content: str = Field(..., description="消息内容")
    parts: Optional[List[Dict]] = Field(default=None, description="多模态部分")


class WebhookRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    url: str = Field(..., description="Webhook 回调 URL")


# ── Agent Card ───────────────────────────────────────────────

@router.get("/.well-known/agent.json")
async def well_known_agent_card():
    """Agent Card 标准发现端点（Google A2A 规范）"""
    return get_agent_card()


@router.get("/api/a2a/card")
async def agent_card():
    """Agent Card（便捷别名）"""
    return get_agent_card()


# ── 任务管理 ─────────────────────────────────────────────────

@router.post("/api/a2a/task")
async def create_task(req: CreateTaskRequest):
    """创建 A2A 任务。

    外部 Agent 通过此接口委派任务给十三香小龙虾。
    任务会自动匹配技能处理器，桌面操作类任务进入 CoworkBus 队列。
    """
    server = get_a2a_server()
    task = await server.create_task(
        source_agent=req.source_agent,
        intent=req.intent,
        params=req.params or {},
        priority=req.priority,
        metadata=req.metadata or {},
    )
    return {"ok": True, "task": task.to_dict()}


@router.get("/api/a2a/task/{task_id}")
async def get_task(task_id: str):
    """查询任务状态和结果"""
    server = get_a2a_server()
    task = server.get_task(task_id)
    if not task:
        return {"ok": False, "error": "task_not_found"}
    return {"ok": True, "task": task.to_dict()}


@router.post("/api/a2a/task/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    server = get_a2a_server()
    ok = server.cancel_task(task_id)
    return {"ok": ok}


@router.post("/api/a2a/task/{task_id}/message")
async def send_task_message(task_id: str, req: SendMessageRequest):
    """向任务发送消息（用于 input-required 状态的回复）"""
    server = get_a2a_server()
    ok = server.send_message(task_id, req.role, req.content, req.parts)
    return {"ok": ok}


@router.get("/api/a2a/tasks")
async def list_tasks(source_agent: str = "", state: str = "", limit: int = 20):
    """任务列表（可按来源和状态过滤）"""
    server = get_a2a_server()
    tasks = server.list_tasks(source_agent=source_agent, state=state, limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


# ── Webhook ──────────────────────────────────────────────────

@router.post("/api/a2a/webhook")
async def register_webhook(req: WebhookRequest):
    """注册 Webhook 回调 URL，任务状态变化时自动通知。"""
    server = get_a2a_server()
    server.register_webhook(req.agent_id, req.url)
    return {"ok": True, "agent_id": req.agent_id}


# ── 技能列表 ─────────────────────────────────────────────────

@router.get("/api/a2a/skills")
async def list_skills():
    """列出所有可用技能及其描述"""
    card = get_agent_card()
    return {"skills": card.get("skills", []), "count": len(card.get("skills", []))}
