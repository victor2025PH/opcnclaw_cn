# -*- coding: utf-8 -*-
"""Agent 团队 API 路由"""

from __future__ import annotations
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional

from src.server.agent_team import create_team, get_team, list_teams
from src.server.agent_templates import list_templates, list_roles

router = APIRouter(prefix="/api/agents", tags=["agent-team"])


class CreateTeamRequest(BaseModel):
    template_id: str = Field(..., description="团队模板 ID")


class ExecuteRequest(BaseModel):
    task: str = Field(..., description="用户需求描述")


@router.get("/templates")
async def get_templates():
    """列出所有团队模板"""
    return {"templates": list_templates()}


@router.get("/roles")
async def get_roles():
    """列出所有 Agent 角色"""
    return {"roles": list_roles()}


@router.post("/team/create")
async def create_agent_team(req: CreateTeamRequest):
    """一键创建团队"""
    try:
        # 获取 AI 调用函数
        async def _ai_call(messages, model=""):
            try:
                from src.server.backend import AIBackend
                backend = AIBackend(backend_type="router")
                result = await backend.chat_simple(
                    messages[-1]["content"] if messages else "",
                    system=messages[0]["content"] if messages and messages[0]["role"] == "system" else "",
                )
                return result
            except Exception as e:
                return f"AI 调用失败: {e}"

        team = create_team(req.template_id, _ai_call)
        return {"ok": True, "team": team.get_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/team/{team_id}/execute")
async def execute_team_task(team_id: str, req: ExecuteRequest):
    """让团队执行任务"""
    team = get_team(team_id)
    if not team:
        return {"ok": False, "error": "团队不存在"}

    # 异步执行（不阻塞请求）
    import asyncio
    asyncio.create_task(team.execute(req.task))
    return {"ok": True, "status": "executing", "team_id": team_id}


@router.get("/team/{team_id}/status")
async def get_team_status(team_id: str):
    """查询团队执行状态"""
    team = get_team(team_id)
    if not team:
        return {"ok": False, "error": "团队不存在"}
    return {"ok": True, **team.get_status()}


@router.get("/team/{team_id}/messages")
async def get_team_messages(team_id: str):
    """Agent 间消息流"""
    team = get_team(team_id)
    if not team:
        return {"messages": []}
    return {"messages": [m.to_dict() for m in team.messages]}


@router.get("/team/{team_id}/result")
async def get_team_result(team_id: str):
    """获取最终结果"""
    team = get_team(team_id)
    if not team:
        return {"result": "", "status": "not_found"}
    return {"result": team.final_result, "status": team.status}


@router.post("/team/{team_id}/stop")
async def stop_team(team_id: str):
    """停止团队执行"""
    team = get_team(team_id)
    if not team:
        return {"ok": False}
    team.status = "error"
    return {"ok": True}


@router.get("/teams")
async def get_all_teams():
    """列出所有团队"""
    return {"teams": list_teams()}
