# -*- coding: utf-8 -*-
"""
CoworkBus — 人机协作调度器

核心逻辑：
  - 用户在操作的窗口 = 人类区域 (human zone)
  - AI 要操作的窗口 = AI 区域 (ai zone)
  - 两者重叠 = 冲突 → AI 暂停
  - 用户空闲 > 30s → AI 可以操作桌面

调度策略：
  1. 用户活跃 → AI 只做后台计算（聊天/分析），不动桌面
  2. 用户空闲 → AI 可以操作桌面
  3. 用户突然回来 → AI 立即暂停，保存进度
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class CoworkTask:
    """后台任务"""
    id: str = ""
    description: str = ""
    target_window: str = ""        # 需要操作的窗口标题（空=不需要桌面）
    status: str = "pending"        # pending / running / paused / done / failed
    priority: int = 5              # 1(最高) - 10(最低)
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    progress: float = 0.0          # 0.0 - 1.0
    result: str = ""
    executor: Optional[Callable] = field(default=None, repr=False)

    def to_dict(self):
        return {
            "id": self.id,
            "desc": self.description,
            "target_window": self.target_window,
            "status": self.status,
            "priority": self.priority,
            "progress": round(self.progress, 2),
            "created_at": round(self.created_at, 1),
        }


class CoworkBus:
    """人机协作调度器"""

    IDLE_THRESHOLD = 30.0  # 秒：用户空闲超过此时间 AI 才操作桌面

    def __init__(self):
        self._paused = False
        self._tasks: List[CoworkTask] = []
        self._lock = threading.Lock()
        self._human_detector = None

    def set_detector(self, detector):
        """注入 HumanDetector"""
        self._human_detector = detector

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self):
        self._paused = True
        # 暂停所有运行中的任务
        with self._lock:
            for t in self._tasks:
                if t.status == "running":
                    t.status = "paused"
                    logger.info(f"[CoworkBus] 暂停任务: {t.description}")

    def resume(self):
        self._paused = False

    def can_operate_desktop(self) -> bool:
        """AI 是否可以操作桌面"""
        if self._paused:
            return False
        if self._human_detector:
            state = self._human_detector.state
            # 用户活跃 → 不操作桌面
            if state.is_active:
                return False
            # 用户在打字 → 绝对不操作
            if state.is_typing:
                return False
        return True

    def check_window_conflict(self, target_title: str) -> bool:
        """检查 AI 要操作的窗口是否和用户当前窗口冲突"""
        if not target_title:
            return False
        if self._human_detector:
            human_window = self._human_detector.state.active_window
            if human_window and target_title.lower() in human_window.lower():
                logger.debug(f"[CoworkBus] 窗口冲突: AI→{target_title} vs 用户→{human_window}")
                return True
        return False

    def add_task(self, task_id: str, description: str, target_window: str = "",
                 priority: int = 5, executor: Callable = None) -> CoworkTask:
        """添加后台任务"""
        task = CoworkTask(
            id=task_id,
            description=description,
            target_window=target_window,
            priority=priority,
            created_at=time.time(),
            executor=executor,
        )
        with self._lock:
            self._tasks.append(task)
            # 按优先级排序
            self._tasks.sort(key=lambda t: t.priority)
        logger.info(f"[CoworkBus] 新任务: {description}")
        return task

    def get_tasks(self) -> List[dict]:
        with self._lock:
            return [t.to_dict() for t in self._tasks[-20:]]

    def get_status(self) -> dict:
        human_zone = "idle"
        human_window = ""
        if self._human_detector:
            s = self._human_detector.state
            human_zone = "typing" if s.is_typing else ("active" if s.is_active else "idle")
            human_window = s.active_window

        running = [t for t in self._tasks if t.status == "running"]
        pending = [t for t in self._tasks if t.status == "pending"]

        return {
            "human_zone": human_zone,
            "human_window": human_window,
            "ai_zone": "paused" if self._paused else ("working" if running else "ready"),
            "paused": self._paused,
            "can_operate_desktop": self.can_operate_desktop(),
            "tasks_running": len(running),
            "tasks_pending": len(pending),
            "queue": [t.to_dict() for t in (running + pending)[:10]],
        }


# ── 全局单例 ──

_bus: Optional[CoworkBus] = None


def get_bus() -> CoworkBus:
    global _bus
    if _bus is None:
        _bus = CoworkBus()
        # 自动注入 HumanDetector
        try:
            from .human_detector import get_detector
            _bus.set_detector(get_detector())
        except Exception:
            pass
    return _bus
