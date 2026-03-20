# -*- coding: utf-8 -*-
"""
人体活动检测器

整合多源信号判断用户是否在活跃操作电脑：
  - 鼠标/键盘空闲时间 (Windows API)
  - 前台窗口标题变化
  - 注视方向 (来自前端 gaze-tracker.js WebSocket)

用途：
  - CoworkBus 判断是否暂停 AI 操作
  - MomentsGuard 判断用户是否在场
  - 桌面自动化前确认安全
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

IS_WINDOWS = sys.platform == "win32"


@dataclass
class HumanState:
    """人类活动状态快照"""
    idle_ms: int = 0                   # 鼠标/键盘空闲毫秒
    is_active: bool = False            # 30 秒内有操作
    is_typing: bool = False            # 5 秒内有键盘输入
    active_window: str = ""            # 当前前台窗口标题
    active_window_class: str = ""      # 当前前台窗口类名
    mouse_x: int = 0
    mouse_y: int = 0
    gaze_zone: str = ""                # 前端推送的注视区域
    last_update: float = 0.0

    def to_dict(self):
        return {
            "idle_ms": self.idle_ms,
            "is_active": self.is_active,
            "is_typing": self.is_typing,
            "active_window": self.active_window,
            "active_window_class": self.active_window_class,
            "mouse_x": self.mouse_x,
            "mouse_y": self.mouse_y,
            "gaze_zone": self.gaze_zone,
            "last_update": round(self.last_update, 1),
        }


class HumanDetector:
    """人体活动检测器 — 定期采样，维护状态"""

    ACTIVE_THRESHOLD_MS = 30_000   # 30 秒内有操作 = 活跃
    TYPING_THRESHOLD_MS = 5_000    # 5 秒内有键盘 = 正在输入
    POLL_INTERVAL = 1.0            # 采样间隔

    def __init__(self):
        self._state = HumanState()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prev_window = ""
        self._prev_idle = 0
        self._last_idle_decrease = 0.0  # 上次 idle 减少的时间（= 有输入）

    @property
    def state(self) -> HumanState:
        return self._state

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="HumanDetector")
        self._thread.start()
        logger.info("[HumanDetector] 已启动")

    def stop(self):
        self._running = False

    def update_gaze(self, zone: str):
        """前端 WebSocket 推送注视区域"""
        self._state.gaze_zone = zone

    def _poll_loop(self):
        while self._running:
            try:
                self._update()
            except Exception as e:
                logger.debug(f"[HumanDetector] poll error: {e}")
            time.sleep(self.POLL_INTERVAL)

    def _update(self):
        now = time.time()
        self._state.last_update = now

        if not IS_WINDOWS:
            return

        # 1. 鼠标/键盘空闲时间
        idle_ms = self._get_idle_ms()
        self._state.idle_ms = idle_ms
        self._state.is_active = idle_ms < self.ACTIVE_THRESHOLD_MS

        # 2. 键盘输入检测（idle 突然减少 = 有按键）
        if idle_ms < self._prev_idle and idle_ms < 1000:
            self._last_idle_decrease = now
        self._state.is_typing = (now - self._last_idle_decrease) < (self.TYPING_THRESHOLD_MS / 1000)
        self._prev_idle = idle_ms

        # 3. 鼠标位置
        try:
            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            self._state.mouse_x = point.x
            self._state.mouse_y = point.y
        except Exception:
            pass

        # 4. 前台窗口
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            self._state.active_window = buf.value[:100]

            cls_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, cls_buf, 256)
            self._state.active_window_class = cls_buf.value[:100]
        except Exception:
            pass

    @staticmethod
    def _get_idle_ms() -> int:
        """获取用户最后输入距现在的毫秒数"""
        if not IS_WINDOWS:
            return 0
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            return ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        except Exception:
            return 0


# ── 全局单例 ──

_detector: Optional[HumanDetector] = None


def get_detector() -> HumanDetector:
    global _detector
    if _detector is None:
        _detector = HumanDetector()
        _detector.start()
    return _detector


def get_human_state() -> HumanState:
    return get_detector().state
