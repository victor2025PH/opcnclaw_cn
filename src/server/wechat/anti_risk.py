# -*- coding: utf-8 -*-
"""
反风控策略模块

模拟真人行为模式，降低微信风控触发风险：
  - 打字节奏模拟（根据回复长度计算真人打字时间）
  - 阅读时间模拟（收到消息后先"读"再"回"）
  - 频率熔断（单小时/单日上限）
  - 活跃度检测（用户在电脑前时暂停自动）
  - 消息长度自然化
"""

import random
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Dict, Optional, Tuple

from loguru import logger


@dataclass
class ContactFrequency:
    """单个联系人的频率追踪"""
    hourly_count: int = 0
    daily_count: int = 0
    last_reply_time: float = 0.0
    last_hour_reset: int = 0  # hour number
    last_day_reset: str = ""  # YYYY-MM-DD


class AntiRiskEngine:
    """
    反风控引擎

    使用方式：
        risk = AntiRiskEngine()
        ok, delay = risk.evaluate(contact, incoming_text, reply_text)
        if ok:
            await asyncio.sleep(delay)
            send_reply(...)
            risk.record_sent(contact)
    """

    def __init__(
        self,
        hourly_limit: int = 15,
        daily_limit: int = 100,
        typing_speed_range: Tuple[float, float] = (2.0, 4.5),  # 字/秒
        min_read_time: float = 1.0,
        max_read_time: float = 4.0,
        cooldown_after_burst: float = 300.0,  # 5分钟冷却
        check_user_active: bool = True,
    ):
        self._hourly_limit = hourly_limit
        self._daily_limit = daily_limit
        self._typing_speed_range = typing_speed_range
        self._min_read_time = min_read_time
        self._max_read_time = max_read_time
        self._cooldown_after_burst = cooldown_after_burst
        self._check_user_active = check_user_active
        self._freq: Dict[str, ContactFrequency] = defaultdict(ContactFrequency)
        self._lock = threading.Lock()
        self._burst_cooldown_until = 0.0

    def evaluate(
        self,
        contact: str,
        incoming_text: str,
        reply_text: str,
    ) -> Tuple[bool, float]:
        """
        评估是否应该回复，以及应该等待多长时间。
        返回 (should_reply, delay_seconds)
        """
        now = time.time()

        # 全局冷却期（频率熔断后）
        if now < self._burst_cooldown_until:
            remaining = self._burst_cooldown_until - now
            logger.debug(f"[AntiRisk] 全局冷却中，剩余 {remaining:.0f}s")
            return False, 0

        # 用户在电脑前 → 暂停自动回复
        if self._check_user_active and self._is_user_active():
            logger.debug("[AntiRisk] 用户活跃中，暂停自动回复")
            return False, 0

        with self._lock:
            freq = self._freq[contact]
            self._reset_counters(freq)

            # 小时频率检查
            if freq.hourly_count >= self._hourly_limit:
                logger.warning(
                    f"[AntiRisk] {contact} 小时频率触顶 ({freq.hourly_count}/{self._hourly_limit})，触发冷却"
                )
                self._burst_cooldown_until = now + self._cooldown_after_burst
                return False, 0

            # 日频率检查
            if freq.daily_count >= self._daily_limit:
                logger.warning(f"[AntiRisk] {contact} 日频率触顶 ({freq.daily_count}/{self._daily_limit})")
                return False, 0

        # 计算延迟
        delay = self._calc_delay(incoming_text, reply_text)

        # 连续快速回复检测 → 额外延迟
        with self._lock:
            if freq.last_reply_time > 0:
                gap = now - freq.last_reply_time
                if gap < 10:  # 10秒内连续回复
                    delay += random.uniform(3.0, 8.0)

        return True, delay

    def record_sent(self, contact: str):
        """记录一次成功发送"""
        with self._lock:
            freq = self._freq[contact]
            self._reset_counters(freq)
            freq.hourly_count += 1
            freq.daily_count += 1
            freq.last_reply_time = time.time()

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "cooldown_active": time.time() < self._burst_cooldown_until,
                "contacts": {
                    name: {
                        "hourly": f.hourly_count,
                        "daily": f.daily_count,
                        "last_reply": f.last_reply_time,
                    }
                    for name, f in self._freq.items()
                },
            }

    def _calc_delay(self, incoming: str, reply: str) -> float:
        """计算自然延迟 = 阅读时间 + 思考时间 + 打字时间"""
        # 阅读时间：根据来消息长度
        read_speed = random.uniform(5, 10)  # 字/秒
        read_time = min(
            self._max_read_time,
            max(self._min_read_time, len(incoming) / read_speed)
        )

        # 思考时间
        think_time = random.uniform(0.5, 2.0)

        # 打字时间：根据回复长度
        typing_speed = random.uniform(*self._typing_speed_range)
        type_time = len(reply) / typing_speed

        # 添加随机抖动
        jitter = random.uniform(-0.5, 1.5)

        total = read_time + think_time + type_time + jitter
        return max(1.5, total)

    def _reset_counters(self, freq: ContactFrequency):
        now = datetime.now()
        current_hour = now.hour
        current_day = now.strftime("%Y-%m-%d")

        if freq.last_hour_reset != current_hour:
            freq.hourly_count = 0
            freq.last_hour_reset = current_hour
        if freq.last_day_reset != current_day:
            freq.daily_count = 0
            freq.last_day_reset = current_day

    def _is_user_active(self) -> bool:
        """检测用户最近 30 秒内是否有鼠标/键盘操作"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("dwTime", ctypes.c_uint),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount()
                idle_ms = tick - lii.dwTime
                return idle_ms < 30_000  # 30 秒内有操作 → 认为用户活跃
        except Exception:
            pass
        return False
