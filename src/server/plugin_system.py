# -*- coding: utf-8 -*-
"""
插件市场架构

将系统各功能模块抽象为可热插拔的插件。

设计原则：
  1. 约定大于配置 — 插件只需实现几个钩子函数即可接入
  2. 声明式注册 — 插件自描述（名称、版本、依赖、配置 schema）
  3. 生命周期管理 — setup → enable → disable → teardown
  4. 隔离性 — 插件崩溃不影响主系统

架构：
  Plugin 基类 → PluginRegistry（注册表）→ PluginManager（生命周期）

  内置插件自动注册，第三方插件放 data/plugins/ 目录。

方案对比：
  方案A: Python entry_points → 太重，需要打包
  方案B: 目录扫描 + 约定接口 → 轻量灵活，选这个
"""

from __future__ import annotations

import importlib
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class PluginState(str, Enum):
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginMeta:
    """插件元数据"""
    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    category: str = "general"  # general / wechat / ai / workflow / analytics / system
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "dependencies": self.dependencies,
        }


class Plugin:
    """
    插件基类。

    所有插件继承此类，实现所需的钩子方法。
    """

    meta = PluginMeta()

    def setup(self, config: Dict = None):
        """初始化（加载配置、创建数据库等）"""
        pass

    def enable(self):
        """启用插件"""
        pass

    def disable(self):
        """禁用插件"""
        pass

    def teardown(self):
        """清理资源"""
        pass

    def get_api_routes(self) -> List[Dict]:
        """
        返回插件提供的 API 路由。

        格式: [{"method": "GET", "path": "/api/xxx", "handler": callable, "summary": "..."}]
        """
        return []

    def get_admin_pages(self) -> List[Dict]:
        """
        返回插件提供的 Admin 页面。

        格式: [{"id": "page-xxx", "label": "页面名", "icon": "📦"}]
        """
        return []

    def on_message(self, message: Dict) -> Optional[Dict]:
        """消息钩子：收到微信消息时触发"""
        return None

    def on_event(self, event: str, data: Dict = None):
        """事件钩子：系统事件触发"""
        pass

    def get_status(self) -> Dict:
        """返回插件运行状态"""
        return {}


# ── 插件注册表 ───────────────────────────────────────────────────────────────

@dataclass
class PluginEntry:
    plugin: Plugin
    meta: PluginMeta
    state: PluginState = PluginState.REGISTERED
    config: Dict = field(default_factory=dict)
    error: str = ""
    enabled_at: float = 0
    load_time_ms: float = 0

    def to_dict(self) -> Dict:
        return {
            **self.meta.to_dict(),
            "state": self.state.value,
            "error": self.error,
            "enabled_at": self.enabled_at,
            "load_time_ms": round(self.load_time_ms, 1),
        }


class PluginManager:
    """
    插件管理器

    用法：
        pm = PluginManager()
        pm.register(MyPlugin())
        pm.enable_all()
        pm.broadcast_event("wechat_message", {"contact": "Alice", ...})
    """

    def __init__(self):
        self._plugins: Dict[str, PluginEntry] = {}
        self._hooks_message: List[str] = []    # 注册了 on_message 的插件 ID
        self._hooks_event: List[str] = []      # 注册了 on_event 的插件 ID

    def register(self, plugin: Plugin, config: Dict = None) -> bool:
        """注册插件"""
        meta = plugin.meta
        if not meta.id:
            logger.warning(f"Plugin has no ID, skipping")
            return False

        if meta.id in self._plugins:
            logger.warning(f"Plugin {meta.id} already registered")
            return False

        # 检查依赖
        for dep in meta.dependencies:
            if dep not in self._plugins:
                logger.warning(f"Plugin {meta.id} depends on {dep} which is not registered")

        entry = PluginEntry(plugin=plugin, meta=meta, config=config or {})

        try:
            t0 = time.time()
            plugin.setup(entry.config)
            entry.load_time_ms = (time.time() - t0) * 1000
        except Exception as e:
            entry.state = PluginState.ERROR
            entry.error = str(e)
            logger.error(f"Plugin {meta.id} setup failed: {e}")

        self._plugins[meta.id] = entry

        # 检查是否有消息/事件钩子
        if type(plugin).on_message is not Plugin.on_message:
            self._hooks_message.append(meta.id)
        if type(plugin).on_event is not Plugin.on_event:
            self._hooks_event.append(meta.id)

        logger.info(f"[PluginSystem] 注册: {meta.name} v{meta.version} ({entry.load_time_ms:.0f}ms)")
        return True

    def enable(self, plugin_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if not entry:
            return False
        try:
            entry.plugin.enable()
            entry.state = PluginState.ENABLED
            entry.enabled_at = time.time()
            entry.error = ""
            return True
        except Exception as e:
            entry.state = PluginState.ERROR
            entry.error = str(e)
            return False

    def disable(self, plugin_id: str) -> bool:
        entry = self._plugins.get(plugin_id)
        if not entry:
            return False
        try:
            entry.plugin.disable()
            entry.state = PluginState.DISABLED
            entry.error = ""
            return True
        except Exception as e:
            entry.state = PluginState.ERROR
            entry.error = str(e)
            return False

    def enable_all(self):
        for pid in self._plugins:
            entry = self._plugins[pid]
            if entry.state != PluginState.ERROR:
                self.enable(pid)

    def broadcast_message(self, message: Dict) -> List[Dict]:
        """广播消息到所有注册了 on_message 的插件"""
        results = []
        for pid in self._hooks_message:
            entry = self._plugins.get(pid)
            if not entry or entry.state != PluginState.ENABLED:
                continue
            try:
                result = entry.plugin.on_message(message)
                if result:
                    results.append({"plugin": pid, **result})
            except Exception as e:
                logger.debug(f"Plugin {pid} on_message error: {e}")
        return results

    def broadcast_event(self, event: str, data: Dict = None):
        """广播事件到所有注册了 on_event 的插件"""
        for pid in self._hooks_event:
            entry = self._plugins.get(pid)
            if not entry or entry.state != PluginState.ENABLED:
                continue
            try:
                entry.plugin.on_event(event, data or {})
            except Exception as e:
                logger.debug(f"Plugin {pid} on_event error: {e}")

    def list_plugins(self) -> List[Dict]:
        return [e.to_dict() for e in self._plugins.values()]

    def get_plugin(self, plugin_id: str) -> Optional[Dict]:
        entry = self._plugins.get(plugin_id)
        return entry.to_dict() if entry else None

    def get_stats(self) -> Dict:
        states = [e.state.value for e in self._plugins.values()]
        return {
            "total": len(self._plugins),
            "enabled": states.count("enabled"),
            "disabled": states.count("disabled"),
            "error": states.count("error"),
            "categories": list(set(e.meta.category for e in self._plugins.values())),
        }


# ── 内置插件声明 ─────────────────────────────────────────────────────────────

class DailyReportPlugin(Plugin):
    meta = PluginMeta(
        id="daily_report", name="智能日报", version="1.0.0",
        description="每天自动汇总全系统数据，生成结构化日报",
        category="analytics",
    )

class SentimentPlugin(Plugin):
    meta = PluginMeta(
        id="sentiment", name="情感分析", version="1.0.0",
        description="消息情感打分和趋势追踪",
        category="analytics",
    )

class KnowledgeBasePlugin(Plugin):
    meta = PluginMeta(
        id="knowledge_base", name="知识库 RAG", version="1.0.0",
        description="私有文档导入和检索增强生成",
        category="ai",
    )

class AnomalyDetectorPlugin(Plugin):
    meta = PluginMeta(
        id="anomaly_detector", name="异常检测", version="1.0.0",
        description="行为异常检测和自动熔断",
        category="system",
    )

class GroupManagerPlugin(Plugin):
    meta = PluginMeta(
        id="group_manager", name="群聊管理", version="1.0.0",
        description="群聊话题分类、摘要和新成员欢迎",
        category="wechat",
    )

class ContextCompressorPlugin(Plugin):
    meta = PluginMeta(
        id="context_compressor", name="上下文压缩", version="1.0.0",
        description="智能对话上下文压缩，降低 token 消耗",
        category="ai",
    )

class AdaptiveStylePlugin(Plugin):
    meta = PluginMeta(
        id="adaptive_style", name="自适应风格", version="1.0.0",
        description="根据联系人和场景自动调整对话风格",
        category="ai",
    )

class WorkflowEditorPlugin(Plugin):
    meta = PluginMeta(
        id="workflow_editor", name="可视化编辑器", version="1.0.0",
        description="工作流可视化编辑和模拟执行",
        category="workflow",
    )


BUILTIN_PLUGINS: List[Plugin] = [
    DailyReportPlugin(),
    SentimentPlugin(),
    KnowledgeBasePlugin(),
    AnomalyDetectorPlugin(),
    GroupManagerPlugin(),
    ContextCompressorPlugin(),
    AdaptiveStylePlugin(),
    WorkflowEditorPlugin(),
]


# 全局单例
_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
        for p in BUILTIN_PLUGINS:
            _manager.register(p)
        _manager.enable_all()
    return _manager
