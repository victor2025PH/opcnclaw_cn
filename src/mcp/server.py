# -*- coding: utf-8 -*-
"""
MCP Server — 让外部 AI 客户端调用十三香小龙虾的能力

协议: JSON-RPC 2.0 (MCP 2024-11-05)
传输: stdio (子进程模式) + HTTP (FastAPI 集成)

暴露工具:
  - 16 个桌面控制工具 (desktop_*)
  - 微信工具 (wechat_read, wechat_send, wechat_moments)
  - 系统工具 (cowork_status, action_journal)
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ShisanXiang"
SERVER_VERSION = "3.8.0"


class MCPTool:
    """MCP 工具定义"""
    def __init__(self, name: str, description: str, input_schema: dict,
                 handler: Callable):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPServer:
    """MCP Server 核心协议处理"""

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._initialized = False
        self._request_id = 0

    def register_tool(self, tool: MCPTool):
        self._tools[tool.name] = tool

    def register_tools(self, tools: List[MCPTool]):
        for t in tools:
            self._tools[t.name] = t

    def handle_request(self, request: dict) -> dict:
        """处理 JSON-RPC 请求"""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                return self._handle_initialize(req_id, params)
            elif method == "initialized":
                return None  # 通知，不需要响应
            elif method == "tools/list":
                return self._handle_tools_list(req_id)
            elif method == "tools/call":
                return self._handle_tools_call(req_id, params)
            elif method == "ping":
                return self._make_response(req_id, {})
            else:
                return self._make_error(req_id, -32601, f"Method not found: {method}")
        except Exception as e:
            return self._make_error(req_id, -32603, str(e))

    def _handle_initialize(self, req_id, params: dict) -> dict:
        self._initialized = True
        client_info = params.get("clientInfo", {})
        logger.info(f"[MCP Server] 客户端连接: {client_info.get('name', '?')} v{client_info.get('version', '?')}")
        return self._make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        })

    def _handle_tools_list(self, req_id) -> dict:
        tools = [t.to_dict() for t in self._tools.values()]
        return self._make_response(req_id, {"tools": tools})

    def _handle_tools_call(self, req_id, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(name)
        if not tool:
            return self._make_error(req_id, -32602, f"Tool not found: {name}")

        try:
            result = tool.handler(**arguments)
            # 标准 MCP 工具响应格式
            if isinstance(result, dict) and "content" in result:
                return self._make_response(req_id, result)
            # 自动包装
            return self._make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            })
        except Exception as e:
            return self._make_response(req_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })

    @staticmethod
    def _make_response(req_id, result) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _make_error(req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def create_server() -> MCPServer:
    """创建并注册所有工具的 MCP Server"""
    server = MCPServer()

    # 1. 注册桌面工具
    try:
        from src.server.mcp_desktop_tools import get_mcp_tools
        for tool_def in get_mcp_tools():
            server.register_tool(MCPTool(
                name=tool_def["name"],
                description=tool_def["description"],
                input_schema=tool_def.get("inputSchema", {}),
                handler=tool_def["handler"],
            ))
    except Exception as e:
        logger.debug(f"[MCP Server] 桌面工具注册失败: {e}")

    # 2. 注册微信工具
    _register_wechat_tools(server)

    # 3. 注册系统工具
    _register_system_tools(server)

    logger.info(f"[MCP Server] 就绪: {len(server._tools)} 个工具")
    return server


def _register_wechat_tools(server: MCPServer):
    """注册微信相关 MCP 工具"""
    def wechat_send(contact: str = "", text: str = "") -> dict:
        try:
            from src.server.wechat_autoreply import get_adapter
            adapter = get_adapter()
            if adapter:
                ok = adapter.send_message(contact, text)
                return {"sent": ok, "contact": contact}
            return {"sent": False, "error": "adapter not available"}
        except Exception as e:
            return {"sent": False, "error": str(e)}

    def wechat_read(limit: int = 5) -> dict:
        try:
            from src.server.wechat_autoreply import get_adapter
            adapter = get_adapter()
            if adapter:
                msgs = adapter.get_new_messages()
                return {"messages": [{"contact": m.contact, "content": m.content, "type": m.msg_type} for m in msgs[:limit]]}
            return {"messages": []}
        except Exception as e:
            return {"messages": [], "error": str(e)}

    def wechat_status() -> dict:
        try:
            from src.server.wechat_monitor import _wechat_is_running
            return {"running": _wechat_is_running()}
        except Exception:
            return {"running": False}

    server.register_tools([
        MCPTool("wechat_send", "发送微信消息给指定联系人", {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "联系人名称"},
                "text": {"type": "string", "description": "消息内容"},
            },
            "required": ["contact", "text"],
        }, wechat_send),
        MCPTool("wechat_read", "读取最近微信消息", {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多读取条数", "default": 5},
            },
        }, wechat_read),
        MCPTool("wechat_status", "检查微信是否在运行", {
            "type": "object", "properties": {},
        }, wechat_status),
    ])


def _register_system_tools(server: MCPServer):
    """注册系统工具"""
    def cowork_status() -> dict:
        try:
            from src.server.cowork_bus import get_bus
            return get_bus().get_status()
        except Exception as e:
            return {"error": str(e)}

    def action_journal(limit: int = 10) -> dict:
        try:
            from src.server.action_journal import get_journal
            return {"entries": get_journal().get_recent(limit)}
        except Exception as e:
            return {"entries": [], "error": str(e)}

    server.register_tools([
        MCPTool("cowork_status", "获取人机协作状态（用户活跃度、AI状态）", {
            "type": "object", "properties": {},
        }, cowork_status),
        MCPTool("action_journal", "获取AI最近的桌面操作日志", {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数", "default": 10},
            },
        }, action_journal),
    ])


# ── stdio 模式入口 ──

def run_stdio():
    """以 stdio 模式运行 MCP Server（供 Claude Desktop / Cursor 等调用）"""
    server = create_server()
    logger.info(f"[MCP Server] stdio 模式启动, {len(server._tools)} 工具就绪")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = server.handle_request(request)
            if response:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            error = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            sys.stdout.write(json.dumps(error) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio()
