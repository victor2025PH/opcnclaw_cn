# -*- coding: utf-8 -*-
"""
工作流核心数据模型

Workflow DSL 设计：
  - Workflow: 包含触发器 + 节点列表
  - Node: 可插拔动作单元，输出写入上下文供下游节点引用
  - Trigger: schedule / interval / event / manual
  - Execution: 一次工作流运行的完整记录
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TriggerType(str, Enum):
    SCHEDULE = "schedule"      # 指定时间 (HH:MM + weekdays)
    INTERVAL = "interval"      # 固定间隔 (seconds)
    EVENT = "event"            # 事件驱动 (wechat_message / voice_command / api_call)
    MANUAL = "manual"          # 手动触发


class NodeType(str, Enum):
    LLM_GENERATE = "llm_generate"
    LLM_CLASSIFY = "llm_classify"
    TEMPLATE = "template"
    TTS_SPEAK = "tts_speak"
    WECHAT_SEND = "wechat_send"
    WECHAT_READ = "wechat_read"
    WECHAT_AUTOREPLY = "wechat_autoreply"
    DELAY = "delay"
    CONDITION = "condition"
    HTTP_REQUEST = "http_request"
    NOTIFY = "notify"
    SYSTEM_INFO = "system_info"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SKILL_EXECUTE = "skill_execute"
    PYTHON_EVAL = "python_eval"
    LOOP = "loop"
    PARALLEL = "parallel"


class ExecStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class Trigger:
    type: TriggerType = TriggerType.MANUAL
    time: str = ""              # HH:MM for schedule
    days: List[str] = field(default_factory=list)  # mon/tue/.../sun, empty=every day
    seconds: int = 0            # for interval
    event: str = ""             # for event trigger
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "type": self.type.value if isinstance(self.type, TriggerType) else self.type,
            "time": self.time,
            "days": self.days,
            "seconds": self.seconds,
            "event": self.event,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        return cls(
            type=TriggerType(d.get("type", "manual")),
            time=d.get("time", ""),
            days=d.get("days", []),
            seconds=d.get("seconds", 0),
            event=d.get("event", ""),
            enabled=d.get("enabled", True),
        )


@dataclass
class NodeDef:
    """工作流节点定义"""
    id: str
    type: str                     # NodeType value
    label: str = ""               # 显示名称
    params: Dict[str, Any] = field(default_factory=dict)
    on_error: str = "stop"        # stop / skip / retry
    retry_count: int = 0
    timeout: int = 60             # seconds

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "params": self.params,
            "on_error": self.on_error,
            "retry_count": self.retry_count,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NodeDef":
        return cls(
            id=d["id"],
            type=d["type"],
            label=d.get("label", ""),
            params=d.get("params", {}),
            on_error=d.get("on_error", "stop"),
            retry_count=d.get("retry_count", 0),
            timeout=d.get("timeout", 60),
        )


@dataclass
class Workflow:
    """完整工作流定义"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    category: str = "custom"      # builtin / custom
    icon: str = "⚙️"
    trigger: Trigger = field(default_factory=Trigger)
    nodes: List[NodeDef] = field(default_factory=list)
    enabled: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # 用户自定义变量

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "trigger": self.trigger.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "variables": self.variables,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Workflow":
        return cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            name=d.get("name", ""),
            description=d.get("description", ""),
            category=d.get("category", "custom"),
            icon=d.get("icon", "⚙️"),
            trigger=Trigger.from_dict(d.get("trigger", {})),
            nodes=[NodeDef.from_dict(n) for n in d.get("nodes", [])],
            enabled=d.get("enabled", False),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            tags=d.get("tags", []),
            variables=d.get("variables", {}),
        )


@dataclass
class NodeResult:
    """单个节点的执行结果"""
    node_id: str
    status: ExecStatus = ExecStatus.PENDING
    output: Any = None
    error: str = ""
    started_at: float = 0
    finished_at: float = 0
    duration_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Execution:
    """一次工作流执行的完整记录"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    workflow_id: str = ""
    workflow_name: str = ""
    status: ExecStatus = ExecStatus.PENDING
    trigger_type: str = "manual"
    started_at: float = 0
    finished_at: float = 0
    node_results: List[NodeResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "trigger_type": self.trigger_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "node_results": [r.to_dict() for r in self.node_results],
            "error": self.error,
        }
