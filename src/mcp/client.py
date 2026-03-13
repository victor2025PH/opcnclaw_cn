"""
MCP Client — connects to MCP servers over stdio / HTTP / SSE.

Provides a unified interface to call tools exposed by any MCP-compliant
server, enabling access to 470,000+ community skills.
"""

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

MCP_DIR = Path("data/mcp_servers")
MCP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MCPTool:
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    server_id: str = ""


@dataclass
class MCPServer:
    id: str
    name: str
    transport: str = "stdio"
    command: str = ""
    url: str = ""
    tools: List[MCPTool] = field(default_factory=list)
    enabled: bool = True
    _process: Optional[subprocess.Popen] = field(
        default=None, repr=False)


class MCPClient:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    # ------------------------------------------------------------------
    #  Server lifecycle
    # ------------------------------------------------------------------

    def register_server(self, server: MCPServer):
        self._servers[server.id] = server
        logger.info(f"MCP server registered: {server.id} ({server.transport})")

    def unregister_server(self, server_id: str):
        srv = self._servers.pop(server_id, None)
        if srv and srv._process:
            srv._process.terminate()
        logger.info(f"MCP server unregistered: {server_id}")

    async def connect(self, server_id: str) -> bool:
        srv = self._servers.get(server_id)
        if not srv or not srv.enabled:
            return False

        if srv.transport == "stdio":
            return await self._connect_stdio(srv)
        if srv.transport in ("http", "sse"):
            return await self._connect_http(srv)
        logger.warning(f"Unknown transport: {srv.transport}")
        return False

    async def _connect_stdio(self, srv: MCPServer) -> bool:
        try:
            proc = subprocess.Popen(
                srv.command.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(MCP_DIR / srv.id) if (MCP_DIR / srv.id).exists()
                else None,
            )
            srv._process = proc

            init_msg = {
                "jsonrpc": "2.0", "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "OpenClaw", "version": "3.0"},
                },
            }
            resp = await self._stdio_request(proc, init_msg)
            if resp and "result" in resp:
                await self._discover_tools_stdio(srv)
                logger.info(
                    f"MCP stdio connected: {srv.id} "
                    f"({len(srv.tools)} tools)")
                return True
        except Exception as e:
            logger.error(f"MCP stdio connect failed ({srv.id}): {e}")
        return False

    async def _connect_http(self, srv: MCPServer) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    srv.url,
                    json={
                        "jsonrpc": "2.0", "id": self._next_id(),
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "OpenClaw", "version": "3.0"},
                        },
                    },
                )
                data = resp.json()
                if "result" in data:
                    await self._discover_tools_http(srv)
                    logger.info(
                        f"MCP HTTP connected: {srv.id} "
                        f"({len(srv.tools)} tools)")
                    return True
        except Exception as e:
            logger.error(f"MCP HTTP connect failed ({srv.id}): {e}")
        return False

    # ------------------------------------------------------------------
    #  Tool discovery
    # ------------------------------------------------------------------

    async def _discover_tools_stdio(self, srv: MCPServer):
        msg = {
            "jsonrpc": "2.0", "id": self._next_id(),
            "method": "tools/list", "params": {},
        }
        resp = await self._stdio_request(srv._process, msg)
        if resp and "result" in resp:
            srv.tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {}),
                    server_id=srv.id,
                )
                for t in resp["result"].get("tools", [])
            ]

    async def _discover_tools_http(self, srv: MCPServer):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    srv.url,
                    json={
                        "jsonrpc": "2.0", "id": self._next_id(),
                        "method": "tools/list", "params": {},
                    },
                )
                data = resp.json()
                if "result" in data:
                    srv.tools = [
                        MCPTool(
                            name=t["name"],
                            description=t.get("description", ""),
                            parameters=t.get("inputSchema", {}),
                            server_id=srv.id,
                        )
                        for t in data["result"].get("tools", [])
                    ]
        except Exception as e:
            logger.error(f"Tool discovery failed ({srv.id}): {e}")

    # ------------------------------------------------------------------
    #  Tool invocation
    # ------------------------------------------------------------------

    async def call_tool(
        self, server_id: str, tool_name: str,
        arguments: Optional[Dict] = None,
    ) -> Dict:
        srv = self._servers.get(server_id)
        if not srv:
            return {"error": f"Server {server_id} not found"}

        msg = {
            "jsonrpc": "2.0", "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

        if srv.transport == "stdio" and srv._process:
            resp = await self._stdio_request(srv._process, msg)
            return resp.get("result", resp) if resp else {"error": "no response"}
        if srv.transport in ("http", "sse"):
            return await self._http_request(srv, msg)

        return {"error": f"Server {server_id} not connected"}

    def get_all_tools(self) -> List[MCPTool]:
        tools = []
        for srv in self._servers.values():
            if srv.enabled:
                tools.extend(srv.tools)
        return tools

    def find_tool(self, name: str) -> Optional[MCPTool]:
        for srv in self._servers.values():
            if srv.enabled:
                for t in srv.tools:
                    if t.name == name:
                        return t
        return None

    # ------------------------------------------------------------------
    #  Transport helpers
    # ------------------------------------------------------------------

    async def _stdio_request(
        self, proc: subprocess.Popen, msg: dict
    ) -> Optional[dict]:
        loop = asyncio.get_event_loop()

        def _io():
            try:
                line = json.dumps(msg) + "\n"
                proc.stdin.write(line.encode())
                proc.stdin.flush()
                resp_line = proc.stdout.readline()
                if resp_line:
                    return json.loads(resp_line)
            except Exception as e:
                logger.debug(f"stdio I/O error: {e}")
            return None

        return await loop.run_in_executor(None, _io)

    async def _http_request(self, srv: MCPServer, msg: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(srv.url, json=msg)
                return resp.json()
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    #  Persistence
    # ------------------------------------------------------------------

    def save_config(self):
        cfg = {}
        for sid, srv in self._servers.items():
            cfg[sid] = {
                "name": srv.name, "transport": srv.transport,
                "command": srv.command, "url": srv.url,
                "enabled": srv.enabled,
            }
        path = MCP_DIR / "servers.json"
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    def load_config(self):
        path = MCP_DIR / "servers.json"
        if not path.exists():
            return
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            for sid, data in cfg.items():
                self.register_server(MCPServer(
                    id=sid, name=data["name"],
                    transport=data.get("transport", "stdio"),
                    command=data.get("command", ""),
                    url=data.get("url", ""),
                    enabled=data.get("enabled", True),
                ))
        except Exception as e:
            logger.warning(f"MCP config load failed: {e}")
