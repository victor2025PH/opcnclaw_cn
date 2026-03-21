# -*- coding: utf-8 -*-
"""
A2A (Agent-to-Agent) 协议支持

实现 Google A2A 标准兼容的 Agent 间通信协议：
  - Agent Card 发现（/.well-known/agent.json）
  - 任务生命周期管理（创建→处理→完成/失败）
  - 异步结果通知（EventBus + Webhook）
  - 与 CoworkBus 集成（桌面任务走调度器）

协议设计：
  参考 Google A2A Spec，简化为适合本项目的子集：
  - AgentCard: 描述能力、支持的技能
  - Task: 任务对象（submitted → working → completed/failed）
  - Artifact: 任务产出物（文本/截图/文件）
  - Message: Agent 间通信消息

使用场景：
  1. Claude Desktop/Cursor 通过 A2A 委派桌面操作任务
  2. 多个十三香实例间互相协作
  3. 自定义 Agent 调用十三香的桌面/微信能力
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


# ── 数据模型 ──────────────────────────────────────────────────────

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class Artifact:
    """任务产出物"""
    name: str
    type: str = "text"  # text / image / file / json
    data: Any = None
    uri: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "data": self.data if self.type != "image" else f"[image:{len(str(self.data or ''))}bytes]",
            "uri": self.uri,
            "timestamp": round(self.timestamp, 1),
        }


@dataclass
class A2AMessage:
    """Agent 间消息"""
    role: str = "agent"  # agent / user / system
    content: str = ""
    parts: List[Dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "parts": self.parts,
            "timestamp": round(self.timestamp, 1),
        }


@dataclass
class A2ATask:
    """A2A 任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_agent: str = ""          # 发起方 Agent ID
    intent: str = ""                # 任务意图
    state: TaskState = TaskState.SUBMITTED
    params: Dict = field(default_factory=dict)
    artifacts: List[Artifact] = field(default_factory=list)
    messages: List[A2AMessage] = field(default_factory=list)
    priority: int = 5               # 1(最高) - 10(最低)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    error: str = ""
    metadata: Dict = field(default_factory=dict)
    # 内部字段
    _executor: Optional[Callable] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_agent": self.source_agent,
            "intent": self.intent,
            "state": self.state.value,
            "params": self.params,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "messages": [m.to_dict() for m in self.messages[-10:]],
            "priority": self.priority,
            "created_at": round(self.created_at, 1),
            "updated_at": round(self.updated_at, 1),
            "completed_at": round(self.completed_at, 1) if self.completed_at else None,
            "error": self.error,
            "metadata": self.metadata,
        }

    def add_message(self, role: str, content: str, parts: list = None):
        self.messages.append(A2AMessage(role=role, content=content, parts=parts or []))
        self.updated_at = time.time()

    def add_artifact(self, name: str, type: str = "text", data: Any = None, uri: str = ""):
        self.artifacts.append(Artifact(name=name, type=type, data=data, uri=uri))
        self.updated_at = time.time()


# ── Agent Card ────────────────────────────────────────────────────

def get_agent_card() -> dict:
    """
    Agent Card — 描述本 Agent 的能力。

    遵循 Google A2A AgentCard 格式：
      name, description, url, capabilities, skills
    """
    try:
        from pathlib import Path
        version_file = Path(__file__).resolve().parent.parent.parent / "version.txt"
        version = version_file.read_text().strip() if version_file.exists() else "4.0.0"
    except Exception:
        version = "4.0.0"

    return {
        "name": "ShisanXiang",
        "description": "十三香小龙虾 — 自托管全双工 AI 语音助手，桌面控制/微信自动化/人机协作",
        "url": "http://localhost:8766",
        "version": version,
        "protocol": "a2a/1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": True,
            "stateTransitionHistory": True,
        },
        "skills": [
            {
                "id": "desktop_control",
                "name": "桌面控制",
                "description": "AI 看着屏幕操作电脑（截图+OCR+鼠标键盘自动化）",
                "inputModes": ["text", "image"],
                "outputModes": ["text", "image"],
            },
            {
                "id": "wechat_send",
                "name": "微信发消息",
                "description": "向指定联系人发送微信消息",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            {
                "id": "wechat_read",
                "name": "微信读消息",
                "description": "读取指定联系人的最新消息",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            {
                "id": "screenshot",
                "name": "截屏",
                "description": "截取当前屏幕并返回图片",
                "inputModes": ["text"],
                "outputModes": ["image"],
            },
            {
                "id": "ocr",
                "name": "OCR 识别",
                "description": "截屏 + OCR 文字识别",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            {
                "id": "voice",
                "name": "语音合成",
                "description": "将文本转为语音播放",
                "inputModes": ["text"],
                "outputModes": ["audio"],
            },
        ],
        "authentication": {
            "schemes": ["pin"],
            "description": "使用 PIN 码获取 Bearer Token",
        },
    }


# ── A2A Server ────────────────────────────────────────────────────

class A2AServer:
    """
    A2A 服务端 — 管理任务生命周期

    外部 Agent 通过 HTTP API 创建任务，
    本 Server 调度执行并返回结果。
    """

    MAX_TASKS = 100
    TASK_TTL = 3600  # 1小时后清理完成的任务

    def __init__(self):
        self._tasks: Dict[str, A2ATask] = {}
        self._skill_handlers: Dict[str, Callable] = {}
        self._webhooks: Dict[str, str] = {}  # agent_id → webhook_url

    def register_skill(self, skill_id: str, handler: Callable):
        """注册技能处理函数"""
        self._skill_handlers[skill_id] = handler
        logger.debug(f"[A2A] 注册技能: {skill_id}")

    def register_webhook(self, agent_id: str, url: str):
        """注册 Agent 的 Webhook 回调 URL"""
        self._webhooks[agent_id] = url

    async def create_task(self, source_agent: str, intent: str,
                          params: dict = None, priority: int = 5,
                          metadata: dict = None) -> A2ATask:
        """创建新任务"""
        task = A2ATask(
            source_agent=source_agent,
            intent=intent,
            params=params or {},
            priority=priority,
            metadata=metadata or {},
        )
        task.add_message("system", f"任务已创建: {intent}")

        self._tasks[task.id] = task
        self._cleanup_old_tasks()

        logger.info(f"[A2A] 新任务: {task.id} 意图={intent} 来源={source_agent}")

        # 发布事件
        self._publish_event("a2a:task_created", task)

        # 尝试自动执行
        await self._auto_execute(task)

        return task

    async def _auto_execute(self, task: A2ATask):
        """自动分派到技能处理器或 CoworkBus"""
        handler = self._skill_handlers.get(task.intent)

        if handler:
            # 有直接处理器 → 异步执行
            task.state = TaskState.WORKING
            task.add_message("system", "技能匹配，开始执行")
            self._publish_event("a2a:task_working", task)

            try:
                # 超时保护：技能执行最多 60 秒
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(handler(task), timeout=60.0)
                else:
                    result = handler(task)

                if isinstance(result, dict):
                    for k, v in result.items():
                        task.add_artifact(k, "text" if isinstance(v, str) else "json", v)

                task.state = TaskState.COMPLETED
                task.completed_at = time.time()
                task.add_message("agent", "任务完成")
                self._publish_event("a2a:task_completed", task)

            except asyncio.TimeoutError:
                task.state = TaskState.FAILED
                task.error = "技能执行超时 (60s)"
                task.completed_at = time.time()
                task.add_message("system", "执行超时")
                self._publish_event("a2a:task_failed", task)
                logger.warning(f"[A2A] 任务 {task.id} 超时: {task.intent}")

            except Exception as e:
                task.state = TaskState.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                task.add_message("system", f"执行失败: {e}")
                self._publish_event("a2a:task_failed", task)
                logger.error(f"[A2A] 任务 {task.id} 失败: {e}")
        else:
            # 无处理器 → 检查是否需要桌面操作 → CoworkBus
            desktop_intents = {"desktop_control", "screenshot", "ocr", "click", "type"}
            if task.intent in desktop_intents:
                await self._delegate_to_cowork(task)
            else:
                task.add_message("system", f"无可用的技能处理器: {task.intent}")
                task.state = TaskState.FAILED
                task.error = f"unknown_skill: {task.intent}"
                task.completed_at = time.time()
                self._publish_event("a2a:task_failed", task)

    async def _delegate_to_cowork(self, task: A2ATask):
        """委派到 CoworkBus 调度执行"""
        try:
            from .cowork_bus import get_bus
            bus = get_bus()

            def _execute():
                # 桌面操作类任务
                try:
                    from .desktop import execute_actions
                    actions = task.params.get("actions", [])
                    if actions:
                        result = execute_actions(actions)
                        task.add_artifact("result", "json", result)
                    task.state = TaskState.COMPLETED
                    task.completed_at = time.time()
                    task.add_message("agent", "桌面操作完成")
                    self._publish_event("a2a:task_completed", task)
                    return "done"
                except Exception as e:
                    task.state = TaskState.FAILED
                    task.error = str(e)
                    task.completed_at = time.time()
                    self._publish_event("a2a:task_failed", task)
                    return f"error: {e}"

            bus.add_task(
                task_id=f"a2a_{task.id}",
                description=f"A2A: {task.intent}",
                target_window=task.params.get("target_window", ""),
                priority=task.priority,
                executor=_execute,
            )
            task.state = TaskState.WORKING
            task.add_message("system", "已加入 CoworkBus 队列")
            self._publish_event("a2a:task_working", task)

        except Exception as e:
            task.state = TaskState.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            self._publish_event("a2a:task_failed", task)

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.state in (TaskState.SUBMITTED, TaskState.WORKING, TaskState.INPUT_REQUIRED):
            task.state = TaskState.CANCELED
            task.completed_at = time.time()
            task.add_message("system", "任务已取消")
            self._publish_event("a2a:task_canceled", task)
            return True
        return False

    def list_tasks(self, source_agent: str = "", state: str = "",
                   limit: int = 20) -> List[dict]:
        tasks = list(self._tasks.values())
        if source_agent:
            tasks = [t for t in tasks if t.source_agent == source_agent]
        if state:
            tasks = [t for t in tasks if t.state.value == state]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def send_message(self, task_id: str, role: str, content: str,
                     parts: list = None) -> bool:
        """向任务添加消息（用于 input-required 状态的用户回复）"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.add_message(role, content, parts)

        # 如果任务在等待输入，恢复执行
        if task.state == TaskState.INPUT_REQUIRED:
            task.state = TaskState.WORKING
            self._publish_event("a2a:task_resumed", task)

        return True

    def _publish_event(self, event_type: str, task: A2ATask):
        """通过 EventBus 发布 A2A 事件"""
        try:
            from .event_bus import publish
            publish(event_type, {
                "task_id": task.id,
                "intent": task.intent,
                "state": task.state.value,
                "source_agent": task.source_agent,
            })
        except Exception:
            pass

        # Webhook 通知
        webhook = self._webhooks.get(task.source_agent)
        if webhook:
            self._send_webhook(webhook, task)

    def _send_webhook(self, url: str, task: A2ATask):
        """异步发送 Webhook 通知"""
        try:
            import httpx
            # 在后台线程中发送，不阻塞
            import threading
            def _send():
                try:
                    with httpx.Client(timeout=5.0) as client:
                        client.post(url, json={
                            "event": "task_update",
                            "task": task.to_dict(),
                        })
                except Exception as e:
                    logger.debug(f"[A2A] Webhook 发送失败: {e}")
            threading.Thread(target=_send, daemon=True).start()
        except ImportError:
            pass

    def _cleanup_old_tasks(self):
        """清理过期任务"""
        if len(self._tasks) <= self.MAX_TASKS:
            return
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if t.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED)
            and (now - t.completed_at) > self.TASK_TTL
        ]
        for tid in expired:
            del self._tasks[tid]


# ── 全局单例 ──────────────────────────────────────────────────────

_server: Optional[A2AServer] = None


def get_a2a_server() -> A2AServer:
    """获取全局 A2A 服务器单例"""
    global _server
    if _server is None:
        _server = A2AServer()
        _register_builtin_skills(_server)
    return _server


def _register_builtin_skills(server: A2AServer):
    """注册内置技能处理器"""

    async def _wechat_send(task: A2ATask) -> dict:
        """微信发消息"""
        contact = task.params.get("contact", "")
        message = task.params.get("message", "")
        if not contact or not message:
            task.state = TaskState.INPUT_REQUIRED
            task.add_message("system", "缺少参数: contact 和 message")
            return {}
        try:
            from .wechat_monitor import WeChatMonitor
            monitor = WeChatMonitor()
            ok = monitor.send_message(contact, message)
            return {"sent": ok, "contact": contact}
        except Exception as e:
            return {"error": str(e)}

    async def _wechat_read(task: A2ATask) -> dict:
        """微信读消息"""
        contact = task.params.get("contact", "")
        try:
            from .wechat_monitor import WeChatMonitor
            monitor = WeChatMonitor()
            messages = monitor.get_current_chat_messages()
            return {"messages": messages[:20], "contact": contact}
        except Exception as e:
            return {"error": str(e)}

    async def _screenshot(task: A2ATask) -> dict:
        """截屏"""
        try:
            from .routers.desktop import desktop
            if not desktop:
                return {"error": "桌面控制不可用"}
            b64 = desktop.capture_screenshot_b64()
            task.add_artifact("screenshot", "image", b64[:100] + "...")
            items = desktop.ocr_screen()
            text = " | ".join(i["text"] for i in items[:30])
            return {"ocr_text": text[:1000], "elements_count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    async def _ocr(task: A2ATask) -> dict:
        """OCR 识别"""
        try:
            from .routers.desktop import desktop
            if not desktop:
                return {"error": "桌面控制不可用"}
            items = desktop.ocr_screen(force=True)
            return {"text": " | ".join(i["text"] for i in items[:50]),
                    "elements": items[:30]}
        except Exception as e:
            return {"error": str(e)}

    async def _voice(task: A2ATask) -> dict:
        """语音合成"""
        text = task.params.get("text", "")
        if not text:
            return {"error": "缺少 text 参数"}
        try:
            from .tts_engine import speak
            await speak(text)
            return {"spoken": True, "text": text}
        except Exception as e:
            return {"error": str(e)}

    server.register_skill("wechat_send", _wechat_send)
    server.register_skill("wechat_read", _wechat_read)
    server.register_skill("screenshot", _screenshot)
    server.register_skill("ocr", _ocr)
    server.register_skill("voice", _voice)
