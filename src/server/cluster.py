# -*- coding: utf-8 -*-
"""
多机集群 — Master/Worker 分布式协作

架构：
  - Master: 拆解任务 + 分发到 Worker + 收集结果
  - Worker: 接收任务 + 本地执行 + 汇报结果
  - 通信: HTTP API（复用已有 A2A 协议）

节点发现：
  - 手动添加（IP:Port）
  - 局域网 UDP 广播（自动发现）
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from loguru import logger


DISCOVERY_PORT = 8770
DISCOVERY_MAGIC = b"OPENCLAW_HELLO"
HEARTBEAT_INTERVAL = 30.0
NODE_TIMEOUT = 90.0


@dataclass
class ClusterNode:
    """集群节点"""
    id: str
    host: str
    port: int = 8766
    name: str = ""
    status: str = "online"       # online / offline / busy
    last_heartbeat: float = 0.0
    tasks_running: int = 0
    tasks_completed: int = 0
    agent_count: int = 0
    capabilities: List[str] = field(default_factory=list)  # desktop / wechat / gpu

    def to_dict(self) -> dict:
        return {
            "id": self.id, "host": self.host, "port": self.port,
            "name": self.name or f"{self.host}:{self.port}",
            "status": self.status, "tasks_running": self.tasks_running,
            "tasks_completed": self.tasks_completed, "agent_count": self.agent_count,
            "last_heartbeat": round(self.last_heartbeat, 1),
            "capabilities": self.capabilities,
        }

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < NODE_TIMEOUT


class ClusterManager:
    """集群管理器（Master 角色）"""

    def __init__(self):
        self._nodes: Dict[str, ClusterNode] = {}
        self._self_id = f"node_{socket.gethostname()}"
        self._discovery_running = False
        self._heartbeat_running = False

    @property
    def node_count(self) -> int:
        return len([n for n in self._nodes.values() if n.is_alive])

    def add_node(self, host: str, port: int = 8766, name: str = "") -> ClusterNode:
        """手动添加节点"""
        node_id = f"{host}:{port}"
        node = ClusterNode(
            id=node_id, host=host, port=port, name=name,
            last_heartbeat=time.time(),
        )
        self._nodes[node_id] = node
        logger.info(f"[Cluster] 添加节点: {node_id}")
        return node

    def remove_node(self, node_id: str) -> bool:
        return self._nodes.pop(node_id, None) is not None

    def get_nodes(self) -> List[dict]:
        # 更新状态
        for n in self._nodes.values():
            if not n.is_alive:
                n.status = "offline"
        return [n.to_dict() for n in self._nodes.values()]

    def get_status(self) -> dict:
        alive = [n for n in self._nodes.values() if n.is_alive]
        return {
            "master_id": self._self_id,
            "total_nodes": len(self._nodes),
            "online_nodes": len(alive),
            "total_capacity": sum(n.agent_count for n in alive),
            "total_tasks_running": sum(n.tasks_running for n in alive),
        }

    async def distribute_task(self, task_desc: str, agent_role: dict,
                              context: dict) -> Optional[dict]:
        """将任务分发到最空闲的 Worker"""
        alive = [n for n in self._nodes.values() if n.is_alive and n.status != "busy"]
        if not alive:
            return None

        # 选择最空闲的节点
        target = min(alive, key=lambda n: n.tasks_running)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{target.url}/api/cluster/task",
                    json={
                        "task_description": task_desc,
                        "agent_role": agent_role,
                        "context": context,
                        "master_id": self._self_id,
                    },
                )
                if r.status_code == 200:
                    target.tasks_running += 1
                    return {"node": target.id, "response": r.json()}
        except Exception as e:
            logger.warning(f"[Cluster] 分发到 {target.id} 失败: {e}")
            target.status = "offline"

        return None

    async def collect_result(self, node_id: str, task_id: str, result: str, status: str):
        """收集 Worker 的任务结果"""
        node = self._nodes.get(node_id)
        if node:
            node.tasks_running = max(0, node.tasks_running - 1)
            node.tasks_completed += 1
            logger.info(f"[Cluster] 收到结果: {node_id} task={task_id} status={status}")

    # ── 局域网发现 ────────────────────────────────────────────

    def start_discovery(self):
        """启动 UDP 广播发现"""
        if self._discovery_running:
            return
        self._discovery_running = True
        threading.Thread(target=self._discovery_listener, daemon=True, name="ClusterDiscovery").start()
        threading.Thread(target=self._discovery_broadcaster, daemon=True, name="ClusterBroadcast").start()
        logger.info("[Cluster] 局域网发现已启动")

    def _discovery_broadcaster(self):
        """定期广播自己的存在"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = DISCOVERY_MAGIC + json.dumps({
            "id": self._self_id,
            "port": 8766,
            "name": socket.gethostname(),
        }).encode()

        while self._discovery_running:
            try:
                sock.sendto(msg, ('<broadcast>', DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)

    def _discovery_listener(self):
        """监听其他节点的广播"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('', DISCOVERY_PORT))
        except Exception as e:
            logger.warning(f"[Cluster] UDP 绑定失败: {e}")
            return

        sock.settimeout(5.0)
        while self._discovery_running:
            try:
                data, addr = sock.recvfrom(1024)
                if data.startswith(DISCOVERY_MAGIC):
                    info = json.loads(data[len(DISCOVERY_MAGIC):])
                    node_id = info.get("id", "")
                    if node_id and node_id != self._self_id:
                        host = addr[0]
                        port = info.get("port", 8766)
                        nid = f"{host}:{port}"
                        if nid not in self._nodes:
                            self.add_node(host, port, info.get("name", ""))
                            logger.info(f"[Cluster] 发现节点: {nid}")
                        else:
                            self._nodes[nid].last_heartbeat = time.time()
                            self._nodes[nid].status = "online"
            except socket.timeout:
                continue
            except Exception:
                continue

    def stop_discovery(self):
        self._discovery_running = False


# ── 全局单例 ──────────────────────────────────────────────────

_cluster: Optional[ClusterManager] = None

def get_cluster() -> ClusterManager:
    global _cluster
    if _cluster is None:
        _cluster = ClusterManager()
    return _cluster
