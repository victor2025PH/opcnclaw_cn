# -*- coding: utf-8 -*-
"""
系统健康检查 + 模块自检框架

启动时自动检查所有核心模块是否可用，
运行时提供 /api/health 端点返回系统整体状态。

设计决策：
  方案A: pytest 外部测试套件 → 需要额外安装、不适合桌面 App
  方案B: 内置自检框架 → 零依赖、启动即检查、API 可查、选这个

每个模块注册一个 check 函数，返回 (ok, detail)。
检查不阻塞启动，异步执行，结果缓存。
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class CheckResult:
    name: str = ""
    category: str = ""
    ok: bool = False
    detail: str = ""
    elapsed_ms: float = 0
    timestamp: float = 0

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "category": self.category,
            "ok": self.ok,
            "detail": self.detail,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


class HealthChecker:
    """
    模块自检管理器。

    用法：
        checker = HealthChecker()
        checker.register("memory_db", "core", check_memory_db)
        results = await checker.run_all()
    """

    def __init__(self):
        self._checks: Dict[str, Tuple[str, Callable]] = {}  # name → (category, fn)
        self._results: Dict[str, CheckResult] = {}
        self._last_run: float = 0

    def register(self, name: str, category: str, check_fn: Callable):
        """注册检查函数。check_fn() -> (ok: bool, detail: str)"""
        self._checks[name] = (category, check_fn)

    async def run_all(self, force: bool = False) -> List[CheckResult]:
        """执行所有检查"""
        if not force and self._last_run and time.time() - self._last_run < 60:
            return list(self._results.values())

        results = []
        for name, (category, fn) in self._checks.items():
            t0 = time.time()
            try:
                if asyncio.iscoroutinefunction(fn):
                    ok, detail = await fn()
                else:
                    ok, detail = fn()
            except Exception as e:
                ok, detail = False, str(e)

            result = CheckResult(
                name=name, category=category, ok=ok,
                detail=detail, elapsed_ms=(time.time() - t0) * 1000,
                timestamp=time.time(),
            )
            results.append(result)
            self._results[name] = result

        self._last_run = time.time()
        return results

    def get_summary(self) -> Dict:
        total = len(self._results)
        passed = sum(1 for r in self._results.values() if r.ok)
        return {
            "status": "healthy" if passed == total else ("degraded" if passed >= total * 0.5 else "unhealthy"),
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "checks": [r.to_dict() for r in self._results.values()],
            "last_run": self._last_run,
        }


# ── 内置检查函数 ─────────────────────────────────────────────────────────────

def check_memory_db() -> Tuple[bool, str]:
    try:
        from . import memory
        conn = memory._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return True, f"{count} 条消息"
    except Exception as e:
        return False, str(e)


def check_event_bus() -> Tuple[bool, str]:
    try:
        from .event_bus import get_bus
        bus = get_bus()
        return True, f"{bus.subscriber_count} 订阅者"
    except Exception as e:
        return False, str(e)


def check_knowledge_base() -> Tuple[bool, str]:
    try:
        from .knowledge_base import get_stats
        s = get_stats()
        return True, f"{s['documents']} 文档, {s['chunks']} 块"
    except Exception as e:
        return False, str(e)


def check_sentiment_db() -> Tuple[bool, str]:
    try:
        from .sentiment_analyzer import get_overview
        ov = get_overview()
        return True, f"今日 {ov['total_24h']} 条分析"
    except Exception as e:
        return False, str(e)


def check_workflow_store() -> Tuple[bool, str]:
    try:
        from .workflow.store import get_stats
        s = get_stats()
        return True, f"{s.get('total_workflows', 0)} 工作流"
    except Exception as e:
        return False, str(e)


def check_plugin_system() -> Tuple[bool, str]:
    try:
        from .plugin_system import get_plugin_manager
        pm = get_plugin_manager()
        s = pm.get_stats()
        return True, f"{s['enabled']}/{s['total']} 启用"
    except Exception as e:
        return False, str(e)


def check_context_compressor() -> Tuple[bool, str]:
    try:
        from .context_compressor import get_compressor
        c = get_compressor()
        return True, f"缓存 {c.get_stats()['cache_size']}"
    except Exception as e:
        return False, str(e)


def check_anomaly_detector() -> Tuple[bool, str]:
    try:
        from .anomaly_detector import get_detector
        d = get_detector()
        return True, f"{len(d._circuit_breakers)} 熔断器"
    except Exception as e:
        return False, str(e)


# ── 全局单例 ─────────────────────────────────────────────────────────────────

_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    global _checker
    if _checker is None:
        _checker = HealthChecker()
        _checker.register("memory_db", "core", check_memory_db)
        _checker.register("event_bus", "core", check_event_bus)
        _checker.register("knowledge_base", "ai", check_knowledge_base)
        _checker.register("sentiment", "analytics", check_sentiment_db)
        _checker.register("workflow_store", "workflow", check_workflow_store)
        _checker.register("plugin_system", "system", check_plugin_system)
        _checker.register("compressor", "ai", check_context_compressor)
        _checker.register("anomaly_detector", "system", check_anomaly_detector)
    return _checker
