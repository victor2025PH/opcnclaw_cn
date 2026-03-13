# -*- coding: utf-8 -*-
"""
API 速率限制器

滑动窗口算法，按 IP 或 Token 限制请求频率。

设计决策：
  方案A: Redis 令牌桶 → 需要外部依赖
  方案B: 内存滑动窗口 → 零依赖、精度足够、适合单进程、选这个

特性：
  - 按 IP 限制（无 token 时）
  - 按 Token 限制（有 token 时，独立配额）
  - 白名单（localhost 默认不限制）
  - 自动清理过期窗口
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 120
    requests_per_hour: int = 3000
    burst_size: int = 30       # 突发请求数
    whitelist: List[str] = field(default_factory=lambda: ["127.0.0.1", "::1", "localhost"])


class RateLimiter:
    """滑动窗口速率限制器"""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self._config = config or RateLimitConfig()
        self._windows: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def check(self, key: str) -> Tuple[bool, Dict]:
        """
        检查请求是否允许。

        返回: (allowed, info)
          allowed: True=允许, False=拒绝
          info: {"remaining": int, "reset": float, "limit": int}
        """
        if key in self._config.whitelist:
            return True, {"remaining": 999, "reset": 0, "limit": 999}

        now = time.time()
        minute_ago = now - 60
        hour_ago = now - 3600

        with self._lock:
            timestamps = self._windows[key]

            # 清理过期时间戳
            timestamps[:] = [t for t in timestamps if t > hour_ago]

            # 统计
            minute_count = sum(1 for t in timestamps if t > minute_ago)
            hour_count = len(timestamps)

            # 检查限制
            if minute_count >= self._config.requests_per_minute:
                remaining = 0
                reset = timestamps[0] + 60 - now if timestamps else 60
                return False, {
                    "remaining": 0,
                    "reset": round(reset, 1),
                    "limit": self._config.requests_per_minute,
                    "window": "minute",
                }

            if hour_count >= self._config.requests_per_hour:
                reset = timestamps[0] + 3600 - now if timestamps else 3600
                return False, {
                    "remaining": 0,
                    "reset": round(reset, 1),
                    "limit": self._config.requests_per_hour,
                    "window": "hour",
                }

            timestamps.append(now)

            remaining = self._config.requests_per_minute - minute_count - 1
            return True, {
                "remaining": max(0, remaining),
                "reset": 60,
                "limit": self._config.requests_per_minute,
            }

    def get_stats(self) -> Dict:
        """获取限流统计"""
        now = time.time()
        minute_ago = now - 60
        with self._lock:
            active_keys = 0
            total_recent = 0
            for key, timestamps in self._windows.items():
                recent = sum(1 for t in timestamps if t > minute_ago)
                if recent > 0:
                    active_keys += 1
                    total_recent += recent
            return {
                "active_clients": active_keys,
                "requests_last_minute": total_recent,
                "total_tracked": len(self._windows),
                "config": {
                    "rpm": self._config.requests_per_minute,
                    "rph": self._config.requests_per_hour,
                },
            }

    def cleanup(self):
        """手动清理所有过期数据"""
        cutoff = time.time() - 3600
        with self._lock:
            empty_keys = []
            for key, timestamps in self._windows.items():
                timestamps[:] = [t for t in timestamps if t > cutoff]
                if not timestamps:
                    empty_keys.append(key)
            for key in empty_keys:
                del self._windows[key]


# 全局实例
_limiter: Optional[RateLimiter] = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def check_rate_limit(request) -> Tuple[bool, Dict]:
    """从 FastAPI Request 提取 IP/Token 并检查"""
    limiter = get_limiter()

    # 优先用 token，其次用 IP
    token = request.headers.get("x-api-key", "")
    if token:
        key = f"token:{token[:16]}"
    else:
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        key = f"ip:{ip}"

    return limiter.check(key)
