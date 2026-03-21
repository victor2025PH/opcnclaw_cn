# -*- coding: utf-8 -*-
"""Agent 团队 API 路由"""

from __future__ import annotations
import json
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional, List

from src.server.agent_team import create_team, get_team, list_teams
from src.server.agent_templates import list_templates, list_roles
from src.server.agent_skills import get_skills_for_role, list_all_skills, get_stats as skills_stats
from src.server.agent_custom import get_custom_role_manager

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
        # 获取 AI 调用函数（复用全局 backend）
        async def _ai_call(messages, model=""):
            try:
                # 尝试获取已初始化的全局 backend
                from src.server.main import backend as _global_backend
                if _global_backend:
                    return await _global_backend.chat_simple(messages)

                # 降级：创建临时 backend
                from src.server.backend import AIBackend
                _temp = AIBackend(backend_type="router")
                return await _temp.chat_simple(messages)
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


@router.post("/team/{team_id}/agent/{agent_id}/chat")
async def chat_with_agent(team_id: str, agent_id: str, request: Request):
    """与团队中的单个 Agent 对话"""
    team = get_team(team_id)
    if not team:
        return {"ok": False, "error": "团队不存在"}
    agent = team.agents.get(agent_id)
    if not agent:
        return {"ok": False, "error": f"Agent {agent_id} 不存在"}

    body = await request.json()
    user_msg = body.get("message", "")
    if not user_msg:
        return {"ok": False, "error": "缺少 message"}

    try:
        # 构建带上下文的 prompt
        messages = [
            {"role": "system", "content": agent.role.system_prompt},
            {"role": "user", "content": user_msg},
        ]
        # 加入之前的工作成果作为上下文
        if agent.current_task and agent.current_task.result:
            messages.insert(1, {
                "role": "assistant",
                "content": f"我之前的工作成果：\n{agent.current_task.result[:800]}"
            })

        async def _ai(msgs, model=""):
            try:
                from src.server.main import backend as _b
                if _b:
                    return await _b.chat_simple(msgs)
                return "AI 未就绪"
            except Exception as e:
                return str(e)

        reply = await _ai(messages)
        # 更新 Agent 的工作成果
        if agent.current_task:
            agent.current_task.result = reply

        return {"ok": True, "agent_id": agent_id, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/team/{team_id}/stop")
async def stop_team(team_id: str):
    """停止团队执行"""
    team = get_team(team_id)
    if not team:
        return {"ok": False}
    team.status = "error"
    return {"ok": True}


@router.get("/skills")
async def get_all_skills():
    """所有专属技能列表"""
    return {"skills": list_all_skills(), **skills_stats()}


@router.get("/roles/{role_id}/skills")
async def get_role_skills(role_id: str):
    """角色专属技能"""
    return {"role_id": role_id, "skills": get_skills_for_role(role_id)}


# ── 自定义角色 ───────────────────────────────────────────────

class CreateRoleRequest(BaseModel):
    id: str = Field(..., description="角色ID（英文）")
    name: str = Field(..., description="角色名称")
    avatar: str = Field("🤖", description="头像emoji")
    description: str = Field("", description="角色描述")
    system_prompt: str = Field(..., description="系统提示词")
    preferred_model: str = Field("", description="优先AI模型")
    tools: list = Field(default_factory=list, description="工具权限")


@router.post("/roles/create")
async def create_custom_role(req: CreateRoleRequest):
    """创建自定义角色"""
    try:
        mgr = get_custom_role_manager()
        role = mgr.create(
            id=req.id, name=req.name, avatar=req.avatar,
            description=req.description, system_prompt=req.system_prompt,
            preferred_model=req.preferred_model, tools=req.tools,
        )
        return {"ok": True, "role": role.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.put("/roles/{role_id}")
async def update_custom_role(role_id: str, request: Request):
    """编辑自定义角色"""
    body = await request.json()
    mgr = get_custom_role_manager()
    ok = mgr.update(role_id, **body)
    return {"ok": ok}


@router.delete("/roles/{role_id}")
async def delete_custom_role(role_id: str):
    """删除自定义角色"""
    mgr = get_custom_role_manager()
    ok = mgr.delete(role_id)
    return {"ok": ok}


@router.get("/roles/custom")
async def list_custom_roles():
    """列出所有自定义角色"""
    mgr = get_custom_role_manager()
    return {"roles": mgr.list_roles()}


@router.get("/roles/export")
async def export_roles():
    """导出自定义角色（JSON）"""
    mgr = get_custom_role_manager()
    return {"data": mgr.export_all()}


@router.post("/roles/import")
async def import_roles(request: Request):
    """导入角色（JSON）"""
    body = await request.json()
    mgr = get_custom_role_manager()
    count = mgr.import_roles(json.dumps(body.get("roles", [])))
    return {"ok": True, "imported": count}


@router.post("/team/custom")
async def create_custom_team(request: Request):
    """自定义团队（指定角色ID列表）"""
    body = await request.json()
    role_ids = body.get("roles", [])
    name = body.get("name", "自定义团队")

    if not role_ids:
        return {"ok": False, "error": "请指定角色列表"}

    try:
        from src.server.agent_templates import build_agents
        from src.server.agent_team import AgentTeam, _teams
        import time as _time

        agents = build_agents(role_ids)
        if not agents:
            return {"ok": False, "error": "无效的角色ID"}

        team_id = f"team_{int(_time.time() * 1000) % 100000}"
        team = AgentTeam(team_id=team_id, name=name, agents=agents)

        async def _ai_call(messages, model=""):
            try:
                from src.server.main import backend as _b
                if _b:
                    return await _b.chat_simple(messages)
                return "AI 未就绪"
            except Exception as e:
                return f"AI 错误: {e}"

        team.set_ai_call(_ai_call)
        _teams[team_id] = team
        return {"ok": True, "team": team.get_status()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/teams")
async def get_all_teams():
    """列出所有团队"""
    return {"teams": list_teams()}
