# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) server / tool / skill management routes.

Exposes:
  - /api/mcp/servers          — list registered MCP servers
  - /api/mcp/servers/add      — register a new MCP server
  - /api/mcp/servers/{id}     — remove a server
  - /api/mcp/connect/{id}     — connect to a server + discover tools
  - /api/mcp/tools            — list all discovered tools across servers
  - /api/mcp/tool/call        — invoke a tool on a server
  - /api/mcp/skills           — list user-created prompt skills
  - /api/mcp/skills/generate  — generate a new skill from description
  - /api/mcp/skills/{id}      — delete a user skill
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel
from typing import Dict, List, Optional

from src.mcp.client import MCPClient, MCPServer
from src.mcp.skill_generator import generate_skill, delete_skill, list_user_skills

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_client = MCPClient()
_client.load_config()


# ── Pydantic request models ──

class AddServerRequest(BaseModel):
    id: str
    name: str
    transport: str = "stdio"
    command: str = ""
    url: str = ""
    enabled: bool = True


class CallToolRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: Optional[Dict] = None


class GenerateSkillRequest(BaseModel):
    description: str
    name: Optional[str] = None
    trigger_words: Optional[List[str]] = None


# ── Server management ──

@router.get("/servers")
async def list_servers():
    """List all registered MCP servers and their status."""
    servers = []
    for sid, srv in _client._servers.items():
        servers.append({
            "id": sid,
            "name": srv.name,
            "transport": srv.transport,
            "command": srv.command,
            "url": srv.url,
            "enabled": srv.enabled,
            "tools_count": len(srv.tools),
            "connected": srv._process is not None if srv.transport == "stdio" else bool(srv.tools),
        })
    return {"servers": servers, "count": len(servers)}


@router.post("/servers/add")
async def add_server(req: AddServerRequest):
    """Register a new MCP server."""
    srv = MCPServer(
        id=req.id,
        name=req.name,
        transport=req.transport,
        command=req.command,
        url=req.url,
        enabled=req.enabled,
    )
    _client.register_server(srv)
    _client.save_config()
    return {"ok": True, "server_id": req.id}


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str):
    """Unregister and disconnect an MCP server."""
    _client.unregister_server(server_id)
    _client.save_config()
    return {"ok": True, "server_id": server_id}


@router.post("/connect/{server_id}")
async def connect_server(server_id: str):
    """Connect to an MCP server and discover its tools."""
    ok = await _client.connect(server_id)
    srv = _client._servers.get(server_id)
    tools_count = len(srv.tools) if srv else 0
    return {"ok": ok, "server_id": server_id, "tools_discovered": tools_count}


# ── Tool discovery & invocation ──

@router.get("/tools")
async def list_tools():
    """List all tools across all connected servers."""
    tools = _client.get_all_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "server_id": t.server_id,
                "parameters": t.parameters,
            }
            for t in tools
        ],
        "count": len(tools),
    }


@router.post("/tool/call")
async def call_tool(req: CallToolRequest):
    """Invoke a tool on a specific MCP server."""
    result = await _client.call_tool(req.server_id, req.tool_name, req.arguments)
    return {"result": result}


# ── User skill management ──

@router.get("/skills")
async def list_skills():
    """List all user-created prompt skills."""
    skills = list_user_skills()
    return {"skills": skills, "count": len(skills)}


@router.post("/skills/generate")
async def gen_skill(req: GenerateSkillRequest):
    """Generate a new prompt-based skill from a natural language description."""
    try:
        skill = generate_skill(
            description=req.description,
            name=req.name,
            trigger_words=req.trigger_words,
        )
        return {"ok": True, "skill": skill}
    except Exception as e:
        logger.error(f"Skill generation failed: {e}")
        return {"ok": False, "error": str(e)}


@router.delete("/skills/{skill_id}")
async def del_skill(skill_id: str):
    """Delete a user-created skill by ID."""
    ok = delete_skill(skill_id)
    return {"ok": ok, "skill_id": skill_id}


# ── MCP Server (HTTP 模式) ──────────────────────────────────────────

_mcp_server = None

def _get_mcp_server():
    global _mcp_server
    if _mcp_server is None:
        from src.mcp.server import create_server
        _mcp_server = create_server()
    return _mcp_server


@router.post("/rpc")
async def mcp_rpc(request: Request):
    """MCP Server HTTP 入口 — 接收 JSON-RPC 请求"""
    body = await request.json()
    server = _get_mcp_server()
    response = server.handle_request(body)
    if response:
        return response
    return {"ok": True}


@router.get("/server-info")
async def mcp_server_info():
    """MCP Server 信息 — 供客户端发现"""
    server = _get_mcp_server()
    return {
        "name": "ShisanXiang",
        "version": "4.1.0",
        "protocol": "2024-11-05",
        "tools_count": len(server._tools),
        "tools": [t.to_dict() for t in server._tools.values()],
        "transports": ["http", "stdio"],
        "http_endpoint": "/api/mcp/rpc",
        "stdio_command": "python -m src.mcp.server",
    }
