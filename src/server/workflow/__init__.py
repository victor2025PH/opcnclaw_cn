# -*- coding: utf-8 -*-
"""
OpenClaw 工作流引擎模块

多场景工作流系统：
  - 20 个内置场景（晨间例行、专注模式、番茄钟等）
  - JSON DSL 定义工作流，可视化编辑
  - 18 种节点类型（LLM/微信/TTS/HTTP/文件/控制流等）
  - 支持 schedule / interval / event / manual 四种触发方式
  - 微信自动回复作为可编排的工作流节点

使用：
    from src.server.workflow import get_engine, store

    engine = get_engine()
    await engine.start(ai_backend=backend, tts_engine=tts)

    ex = await engine.execute("builtin_morning")
"""

from .engine import WorkflowEngine, get_engine
from .models import (
    ExecStatus, Execution, NodeDef, NodeResult,
    Trigger, TriggerType, Workflow,
)
from . import store
from .nodes import get_available_nodes, NODE_REGISTRY

__all__ = [
    "WorkflowEngine", "get_engine",
    "Workflow", "NodeDef", "Trigger", "TriggerType",
    "Execution", "NodeResult", "ExecStatus",
    "store", "get_available_nodes", "NODE_REGISTRY",
]
