# -*- coding: utf-8 -*-
"""
账号健康度监控

为每个微信账号维护实时健康指标：
  - 连接状态心跳（定期检测窗口是否存活）
  - 消息收发频率（过高/过低都不正常）
  - 操作错误率（连续失败 → 降级）
  - 风控指标（综合评分 0-100）

设计决策：
  全内存计算，不落库。指标是实时性的，重启后归零可接受。
  每个账号一个 AccountMetrics 对象，通过 record_* 方法收集数据。
"""

from __future__ import annotations

import ctypes
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class AccountMetrics:
    """单个账号的健康指标"""
    account_id: str = ""
    # 连接
    connected: bool = False
    last_heartbeat: float = 0
    heartbeat_failures: int = 0
    # 消息
    msgs_sent: int = 0
    msgs_received: int = 0
    last_msg_sent: float = 0
    last_msg_received: float = 0
    # 错误
    errors: int = 0
    last_error: str = ""
    last_error_time: float = 0
    # 频率跟踪（最近 1 小时的时间戳）
    _send_timestamps: deque = field(default_factory=lambda: deque(maxlen=200))
    _recv_timestamps: deque = field(default_factory=lambda: deque(maxlen=500))
    _error_timestamps: deque = field(default_factory=lambda: deque(maxlen=100))

    def record_send(self):
        self.msgs_sent += 1
        self.last_msg_sent = time.time()
        self._send_timestamps.append(time.time())

    def record_receive(self):
        self.msgs_received += 1
        self.last_msg_received = time.time()
        self._recv_timestamps.append(time.time())

    def record_error(self, msg: str = ""):
        self.errors += 1
        self.last_error = msg
        self.last_error_time = time.time()
        self._error_timestamps.append(time.time())

    def record_heartbeat(self, alive: bool):
        self.last_heartbeat = time.time()
        if alive:
            self.connected = True
            self.heartbeat_failures = 0
        else:
            self.heartbeat_failures += 1
            if self.heartbeat_failures >= 3:
                self.connected = False

    @property
    def send_rate_per_hour(self) -> float:
        """每小时发送频率"""
        cutoff = time.time() - 3600
        recent = [t for t in self._send_timestamps if t > cutoff]
        return len(recent)

    @property
    def recv_rate_per_hour(self) -> float:
        cutoff = time.time() - 3600
        recent = [t for t in self._recv_timestamps if t > cutoff]
        return len(recent)

    @property
    def error_rate_per_hour(self) -> float:
        cutoff = time.time() - 3600
        recent = [t for t in self._error_timestamps if t > cutoff]
        return len(recent)

    @property
    def health_score(self) -> int:
        """
        综合健康评分 0-100。

        扣分规则：
          - 未连接: -40
          - 心跳失败: -10/次
          - 高错误率 (>5/h): -20
          - 异常发送频率 (>30/h): -15
          - 长时间无消息 (>2h): -10
        """
        score = 100

        if not self.connected:
            score -= 40
        score -= min(self.heartbeat_failures * 10, 30)

        err_rate = self.error_rate_per_hour
        if err_rate >= 10:
            score -= 30
        elif err_rate >= 5:
            score -= 20
        elif err_rate >= 2:
            score -= 10

        send_rate = self.send_rate_per_hour
        if send_rate > 50:
            score -= 20
        elif send_rate > 30:
            score -= 15

        if self.last_msg_received and time.time() - self.last_msg_received > 7200:
            score -= 10

        return max(0, min(100, score))

    @property
    def risk_level(self) -> str:
        s = self.health_score
        if s >= 80:
            return "safe"
        elif s >= 50:
            return "warning"
        else:
            return "danger"

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "connected": self.connected,
            "health_score": self.health_score,
            "risk_level": self.risk_level,
            "msgs_sent": self.msgs_sent,
            "msgs_received": self.msgs_received,
            "send_rate_per_hour": round(self.send_rate_per_hour, 1),
            "recv_rate_per_hour": round(self.recv_rate_per_hour, 1),
            "error_rate_per_hour": round(self.error_rate_per_hour, 1),
            "errors": self.errors,
            "last_error": self.last_error,
            "heartbeat_failures": self.heartbeat_failures,
            "last_heartbeat": self.last_heartbeat,
        }


class HealthMonitor:
    """
    多账号健康监控器

    用法：
        monitor = HealthMonitor()
        monitor.record_send("acct1")
        monitor.record_receive("acct1")
        status = monitor.get_all_status()
    """

    def __init__(self):
        self._metrics: Dict[str, AccountMetrics] = {}
        self._lock = threading.Lock()

    def _ensure(self, account_id: str) -> AccountMetrics:
        if account_id not in self._metrics:
            with self._lock:
                if account_id not in self._metrics:
                    self._metrics[account_id] = AccountMetrics(account_id=account_id)
        return self._metrics[account_id]

    def record_send(self, account_id: str):
        self._ensure(account_id).record_send()

    def record_receive(self, account_id: str):
        self._ensure(account_id).record_receive()

    def record_error(self, account_id: str, msg: str = ""):
        self._ensure(account_id).record_error(msg)

    def heartbeat(self, account_id: str, alive: bool):
        self._ensure(account_id).record_heartbeat(alive)

    async def check_all_heartbeats(self):
        """检查所有账号的窗口存活状态"""
        from .account_manager import list_accounts

        IsWindow = ctypes.windll.user32.IsWindow
        for acct in list_accounts():
            if acct.hwnd:
                alive = bool(IsWindow(acct.hwnd))
                self.heartbeat(acct.id, alive)
                if not alive:
                    logger.warning(f"[Health] 账号 {acct.name} 窗口已关闭")

    def get_status(self, account_id: str) -> Dict:
        m = self._metrics.get(account_id)
        return m.to_dict() if m else {"account_id": account_id, "connected": False, "health_score": 0}

    def get_all_status(self) -> List[Dict]:
        return [m.to_dict() for m in self._metrics.values()]

    def get_overview(self) -> Dict:
        all_m = list(self._metrics.values())
        if not all_m:
            return {"total": 0, "connected": 0, "avg_health": 0, "danger_count": 0}
        return {
            "total": len(all_m),
            "connected": sum(1 for m in all_m if m.connected),
            "avg_health": round(sum(m.health_score for m in all_m) / len(all_m)),
            "danger_count": sum(1 for m in all_m if m.risk_level == "danger"),
            "total_sent": sum(m.msgs_sent for m in all_m),
            "total_received": sum(m.msgs_received for m in all_m),
            "total_errors": sum(m.errors for m in all_m),
        }


# 全局单例
_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor
