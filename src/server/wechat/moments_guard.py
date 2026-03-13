# -*- coding: utf-8 -*-
"""
朋友圈专用风控引擎

继承 AntiRiskEngine 的核心理念，但针对朋友圈操作做专门调优：
  - 点赞/评论/发圈 各有独立的频率限制
  - 随机化操作间隔，破坏规律性
  - 鼠标点击添加像素偏移
  - 时段限制：仅在活跃时段操作
  - 内容去重：同一条动态不重复互动
"""

from __future__ import annotations

import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from loguru import logger


@dataclass
class MomentsFrequency:
    """朋友圈操作频率追踪"""
    likes_today: int = 0
    comments_today: int = 0
    publishes_today: int = 0
    last_like_time: float = 0
    last_comment_time: float = 0
    last_publish_time: float = 0
    last_reset_date: str = ""
    interacted_posts: set = field(default_factory=set)  # 已互动的动态ID

    def reset_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.likes_today = 0
            self.comments_today = 0
            self.publishes_today = 0
            self.interacted_posts.clear()
            self.last_reset_date = today


class MomentsGuard:
    """
    朋友圈风控引擎

    使用方式：
        guard = MomentsGuard()
        ok, delay = guard.can_like(post_id)
        if ok:
            await asyncio.sleep(delay)
            do_like(...)
            guard.record_like(post_id)
    """

    def __init__(
        self,
        daily_like_limit: int = 50,
        daily_comment_limit: int = 20,
        daily_publish_limit: int = 5,
        like_interval: Tuple[float, float] = (5.0, 15.0),
        comment_interval: Tuple[float, float] = (15.0, 45.0),
        publish_interval_minutes: int = 30,
        active_hours: Tuple[int, int] = (7, 23),
        click_offset_px: int = 5,
        rest_probability: float = 0.15,
        rest_duration: Tuple[float, float] = (60.0, 180.0),
    ):
        self._daily_like_limit = daily_like_limit
        self._daily_comment_limit = daily_comment_limit
        self._daily_publish_limit = daily_publish_limit
        self._like_interval = like_interval
        self._comment_interval = comment_interval
        self._publish_interval_min = publish_interval_minutes
        self._active_hours = active_hours
        self._click_offset = click_offset_px
        self._rest_prob = rest_probability
        self._rest_duration = rest_duration

        self._freq = MomentsFrequency()
        self._lock = threading.Lock()
        self._cooldown_until = 0.0

    # ── 评估接口 ─────────────────────────────────────────────────────────────────

    def can_like(self, post_id: str = "") -> Tuple[bool, float]:
        """评估是否可以点赞，返回 (可以, 延迟秒数)"""
        with self._lock:
            self._freq.reset_if_needed()

            if not self._in_active_hours():
                return False, 0

            if time.time() < self._cooldown_until:
                return False, 0

            if self._is_user_active():
                return False, 0

            if self._freq.likes_today >= self._daily_like_limit:
                logger.debug(f"[MomentsGuard] 今日点赞已达上限 {self._daily_like_limit}")
                return False, 0

            if post_id and post_id in self._freq.interacted_posts:
                return False, 0

            delay = self._calc_like_delay()
            return True, delay

    def can_comment(self, post_id: str = "") -> Tuple[bool, float]:
        """评估是否可以评论"""
        with self._lock:
            self._freq.reset_if_needed()

            if not self._in_active_hours():
                return False, 0

            if time.time() < self._cooldown_until:
                return False, 0

            if self._is_user_active():
                return False, 0

            if self._freq.comments_today >= self._daily_comment_limit:
                logger.debug(f"[MomentsGuard] 今日评论已达上限 {self._daily_comment_limit}")
                return False, 0

            if post_id and post_id in self._freq.interacted_posts:
                return False, 0

            delay = self._calc_comment_delay()
            return True, delay

    def can_publish(self) -> Tuple[bool, float]:
        """评估是否可以发朋友圈"""
        with self._lock:
            self._freq.reset_if_needed()

            if not self._in_active_hours():
                return False, 0

            if self._freq.publishes_today >= self._daily_publish_limit:
                logger.debug(f"[MomentsGuard] 今日发圈已达上限 {self._daily_publish_limit}")
                return False, 0

            elapsed = time.time() - self._freq.last_publish_time
            min_gap = self._publish_interval_min * 60
            if elapsed < min_gap:
                return False, min_gap - elapsed

            return True, 0

    # ── 记录接口 ─────────────────────────────────────────────────────────────────

    def record_like(self, post_id: str = ""):
        with self._lock:
            self._freq.likes_today += 1
            self._freq.last_like_time = time.time()
            if post_id:
                self._freq.interacted_posts.add(post_id)
            self._maybe_rest()

    def record_comment(self, post_id: str = ""):
        with self._lock:
            self._freq.comments_today += 1
            self._freq.last_comment_time = time.time()
            if post_id:
                self._freq.interacted_posts.add(post_id)
            self._maybe_rest()

    def record_publish(self):
        with self._lock:
            self._freq.publishes_today += 1
            self._freq.last_publish_time = time.time()

    # ── 工具方法 ─────────────────────────────────────────────────────────────────

    def get_click_offset(self) -> Tuple[int, int]:
        """获取随机鼠标偏移量（像素），防止固定坐标点击"""
        ox = random.randint(-self._click_offset, self._click_offset)
        oy = random.randint(-self._click_offset, self._click_offset)
        return ox, oy

    def get_stats(self) -> Dict:
        with self._lock:
            self._freq.reset_if_needed()
            return {
                "likes_today": self._freq.likes_today,
                "comments_today": self._freq.comments_today,
                "publishes_today": self._freq.publishes_today,
                "daily_like_limit": self._daily_like_limit,
                "daily_comment_limit": self._daily_comment_limit,
                "daily_publish_limit": self._daily_publish_limit,
                "cooldown_active": time.time() < self._cooldown_until,
                "in_active_hours": self._in_active_hours(),
            }

    # ── 内部 ─────────────────────────────────────────────────────────────────────

    def _calc_like_delay(self) -> float:
        base = random.uniform(*self._like_interval)
        jitter = random.uniform(-1.0, 2.0)
        elapsed = time.time() - self._freq.last_like_time
        if elapsed < self._like_interval[0]:
            base += self._like_interval[0] - elapsed
        return max(2.0, base + jitter)

    def _calc_comment_delay(self) -> float:
        base = random.uniform(*self._comment_interval)
        jitter = random.uniform(-2.0, 5.0)
        return max(5.0, base + jitter)

    def _maybe_rest(self):
        """随机概率触发短暂休息"""
        if random.random() < self._rest_prob:
            rest = random.uniform(*self._rest_duration)
            self._cooldown_until = time.time() + rest
            logger.info(f"[MomentsGuard] 随机休息 {rest:.0f}s")

    def _in_active_hours(self) -> bool:
        hour = datetime.now().hour
        start, end = self._active_hours
        return start <= hour < end

    def _is_user_active(self) -> bool:
        """检测用户是否在操作电脑"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount()
                idle_ms = tick - lii.dwTime
                return idle_ms < 30_000
        except Exception:
            pass
        return False
