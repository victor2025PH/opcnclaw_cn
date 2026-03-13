"""
Proactive context-aware engine.

Monitors time, user behavior, and screen state to anticipate needs
and deliver proactive suggestions without explicit user commands.
"""

import asyncio
import datetime
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger


@dataclass
class ContextEvent:
    type: str
    message: str
    priority: int = 0
    timestamp: float = 0.0
    data: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class TimeAwareness:
    """Time-based proactive triggers."""

    _GREETINGS = {
        (5, 8): "早上好！新的一天开始了。",
        (8, 12): "上午好！今天精神不错吧。",
        (12, 14): "中午好！记得吃午饭哦。",
        (14, 17): "下午好！继续加油。",
        (17, 19): "傍晚了，今天辛苦了。",
        (19, 23): "晚上好！注意休息。",
        (23, 5): "夜深了，早点休息吧。",
    }

    def __init__(self):
        self._last_greeting_date: Optional[str] = None
        self._work_start_time: Optional[float] = None

    def check(self) -> Optional[ContextEvent]:
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        hour = now.hour

        if self._last_greeting_date != today and 5 <= hour <= 9:
            self._last_greeting_date = today
            greeting = self._get_greeting(hour)
            return ContextEvent(
                type="greeting", message=greeting, priority=1)

        if self._work_start_time:
            elapsed = time.time() - self._work_start_time
            if elapsed > 7200:
                self._work_start_time = time.time()
                return ContextEvent(
                    type="health",
                    message="已经连续工作超过两小时了，建议站起来活动一下。",
                    priority=2)

        return None

    def record_activity(self):
        if self._work_start_time is None:
            self._work_start_time = time.time()

    def _get_greeting(self, hour: int) -> str:
        for (start, end), msg in self._GREETINGS.items():
            if start <= end:
                if start <= hour < end:
                    return msg
            else:
                if hour >= start or hour < end:
                    return msg
        return "你好！"


class BehaviorAwareness:
    """Tracks user interaction patterns."""

    def __init__(self):
        self._skill_usage: Dict[str, int] = {}
        self._last_interaction: float = 0
        self._idle_notified = False

    def record_skill_use(self, skill_id: str):
        self._skill_usage[skill_id] = self._skill_usage.get(skill_id, 0) + 1
        self._last_interaction = time.time()
        self._idle_notified = False

    def record_interaction(self):
        self._last_interaction = time.time()
        self._idle_notified = False

    def get_suggested_skills(self, top_n: int = 3) -> List[str]:
        sorted_skills = sorted(
            self._skill_usage.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_skills[:top_n]]

    def check(self) -> Optional[ContextEvent]:
        if (self._last_interaction > 0
                and not self._idle_notified
                and time.time() - self._last_interaction > 1800):
            self._idle_notified = True
            return ContextEvent(
                type="idle",
                message="好久没聊了，有什么我能帮你的吗？",
                priority=0)
        return None


class ScreenAwareness:
    """Optional screen-state detection using lightweight screenshot analysis."""

    def __init__(self):
        self._enabled = False
        self._last_check: float = 0
        self._check_interval = 30.0

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def check(self) -> Optional[ContextEvent]:
        if not self._enabled:
            return None
        if time.time() - self._last_check < self._check_interval:
            return None
        self._last_check = time.time()

        try:
            app_name = self._get_foreground_app()
            if not app_name:
                return None
            return self._analyze_context(app_name)
        except Exception:
            return None

    def _get_foreground_app(self) -> Optional[str]:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            return buf.value
        except Exception:
            return None

    _APP_HINTS = {
        "Word": ("document", "看起来你在编辑文档，需要帮你检查语法或润色吗？"),
        "Excel": ("spreadsheet", "在处理表格数据？我可以帮你做计算。"),
        "PowerPoint": ("presentation", "在做PPT？需要帮忙整理内容吗？"),
        "Calculator": ("calculator", "有什么需要计算的？直接告诉我就行。"),
        "Chrome": ("browser", None),
        "Edge": ("browser", None),
        "Firefox": ("browser", None),
    }

    def _analyze_context(self, title: str) -> Optional[ContextEvent]:
        for keyword, (ctx_type, msg) in self._APP_HINTS.items():
            if keyword.lower() in title.lower():
                if msg:
                    return ContextEvent(
                        type="screen_hint", message=msg, priority=0,
                        data={"app": keyword, "context": ctx_type})
        return None


class ContextEngine:
    """Orchestrates all context-awareness modules."""

    def __init__(self):
        self.time = TimeAwareness()
        self.behavior = BehaviorAwareness()
        self.screen = ScreenAwareness()
        self._callbacks: List[Callable[[ContextEvent], None]] = []
        self._running = False

    def on_event(self, callback: Callable[[ContextEvent], None]):
        self._callbacks.append(callback)

    async def start(self):
        self._running = True
        logger.info("Context engine started")
        while self._running:
            events = self._poll()
            for ev in events:
                for cb in self._callbacks:
                    try:
                        cb(ev)
                    except Exception as e:
                        logger.debug(f"Context callback error: {e}")
            await asyncio.sleep(10)

    def stop(self):
        self._running = False

    def _poll(self) -> List[ContextEvent]:
        events = []
        for module in (self.time, self.behavior, self.screen):
            ev = module.check()
            if ev:
                events.append(ev)
        return sorted(events, key=lambda e: e.priority, reverse=True)

    def record_interaction(self, skill_id: Optional[str] = None):
        self.time.record_activity()
        self.behavior.record_interaction()
        if skill_id:
            self.behavior.record_skill_use(skill_id)
