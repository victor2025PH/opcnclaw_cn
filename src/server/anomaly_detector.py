# -*- coding: utf-8 -*-
"""
异常行为检测 + 自动熔断

检测 3 类异常：
  1. 频率异常：消息发送/接收速率突然偏离历史基线
  2. 错误异常：错误率持续升高
  3. 连接异常：账号频繁断开重连

检测方法：
  方案A: 固定阈值 → 不适应不同账号的使用模式
  方案B: 滑动窗口 + Z-Score → 自适应，选这个
  用最近 7 天的数据建立基线，偏差超过 2σ 视为异常。
  不存历史数据时用保守的固定阈值做兜底。

熔断策略：
  - Level 1 (warning): 发 SSE 告警 + 降低操作频率
  - Level 2 (danger): 暂停该账号的自动操作
  - Level 3 (critical): 暂停所有自动操作 + TTS 报警
"""

from __future__ import annotations

import math
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class MetricWindow:
    """滑动窗口指标"""
    values: deque = field(default_factory=lambda: deque(maxlen=168))  # 7天 * 24h
    timestamps: deque = field(default_factory=lambda: deque(maxlen=168))

    def add(self, value: float, ts: float = 0):
        self.values.append(value)
        self.timestamps.append(ts or time.time())

    @property
    def mean(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    @property
    def std(self) -> float:
        if len(self.values) < 3:
            return 0.0
        m = self.mean
        variance = sum((v - m) ** 2 for v in self.values) / len(self.values)
        return math.sqrt(variance)

    def z_score(self, current: float) -> float:
        """当前值相对基线的 Z-Score"""
        s = self.std
        if s < 0.001:
            # 标准差为零（所有值相同），用均值比例判断
            if self.mean > 0 and current > self.mean * 2:
                return (current - self.mean) / max(self.mean * 0.1, 0.01)
            return 0.0
        return (current - self.mean) / s

    @property
    def has_baseline(self) -> bool:
        return len(self.values) >= 10


@dataclass
class AnomalyAlert:
    """异常告警"""
    account_id: str = ""
    alert_type: str = ""     # rate_spike / error_surge / conn_flap
    level: int = 1           # 1=warning, 2=danger, 3=critical
    message: str = ""
    metric_value: float = 0
    baseline_mean: float = 0
    z_score: float = 0
    timestamp: float = 0
    auto_action: str = ""    # throttle / pause / pause_all

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "alert_type": self.alert_type,
            "level": self.level,
            "level_name": ["", "warning", "danger", "critical"][min(self.level, 3)],
            "message": self.message,
            "metric_value": round(self.metric_value, 2),
            "baseline_mean": round(self.baseline_mean, 2),
            "z_score": round(self.z_score, 2),
            "auto_action": self.auto_action,
            "timestamp": self.timestamp,
        }


class AnomalyDetector:
    """
    异常行为检测引擎

    用法：
        detector = AnomalyDetector()
        detector.record_hourly("acct1", send_rate=15, error_rate=2, conn_drops=0)
        alerts = detector.check("acct1", current_send=50, current_error=8)
    """

    def __init__(self, z_threshold: float = 2.0):
        self._baselines: Dict[str, Dict[str, MetricWindow]] = {}
        self._alerts: List[AnomalyAlert] = []
        self._circuit_breakers: Dict[str, int] = {}  # account → level
        self._z_threshold = z_threshold
        self._lock = threading.Lock()
        # 固定阈值兜底（无基线数据时使用）
        self._fallback_max_send = 60    # 发送/小时
        self._fallback_max_error = 10   # 错误/小时
        self._fallback_max_drops = 3    # 断连/小时

    def _ensure_baseline(self, account_id: str) -> Dict[str, MetricWindow]:
        if account_id not in self._baselines:
            self._baselines[account_id] = {
                "send_rate": MetricWindow(),
                "error_rate": MetricWindow(),
                "conn_drops": MetricWindow(),
            }
        return self._baselines[account_id]

    def record_hourly(
        self,
        account_id: str,
        send_rate: float = 0,
        error_rate: float = 0,
        conn_drops: float = 0,
    ):
        """记录每小时的指标快照（由定时任务调用）"""
        bl = self._ensure_baseline(account_id)
        now = time.time()
        bl["send_rate"].add(send_rate, now)
        bl["error_rate"].add(error_rate, now)
        bl["conn_drops"].add(conn_drops, now)

    def check(
        self,
        account_id: str,
        current_send: float = 0,
        current_error: float = 0,
        current_drops: float = 0,
    ) -> List[AnomalyAlert]:
        """检查当前指标是否异常"""
        bl = self._ensure_baseline(account_id)
        alerts = []
        now = time.time()

        # 发送频率异常
        alert = self._check_metric(
            account_id, "send_rate", bl["send_rate"],
            current_send, self._fallback_max_send,
            "rate_spike", "消息发送频率异常偏高",
        )
        if alert:
            alerts.append(alert)

        # 错误率异常
        alert = self._check_metric(
            account_id, "error_rate", bl["error_rate"],
            current_error, self._fallback_max_error,
            "error_surge", "错误率异常升高",
        )
        if alert:
            alerts.append(alert)

        # 连接断开异常
        alert = self._check_metric(
            account_id, "conn_drops", bl["conn_drops"],
            current_drops, self._fallback_max_drops,
            "conn_flap", "连接频繁断开重连",
        )
        if alert:
            alerts.append(alert)

        # 更新熔断等级
        if alerts:
            max_level = max(a.level for a in alerts)
            with self._lock:
                self._circuit_breakers[account_id] = max_level
                self._alerts.extend(alerts)
                if len(self._alerts) > 200:
                    self._alerts = self._alerts[-200:]

            # 发布 SSE
            try:
                from .event_bus import publish
                for a in alerts:
                    publish("anomaly_alert", a.to_dict())
            except Exception:
                pass

        return alerts

    def _check_metric(
        self,
        account_id: str,
        metric_name: str,
        window: MetricWindow,
        current: float,
        fallback_max: float,
        alert_type: str,
        desc: str,
    ) -> Optional[AnomalyAlert]:
        """检查单个指标"""
        if current <= 0:
            return None

        if window.has_baseline:
            z = window.z_score(current)
            if z <= self._z_threshold:
                return None
            level = 1 if z < 3 else (2 if z < 4 else 3)
        else:
            if current <= fallback_max:
                return None
            z = 0
            level = 1 if current < fallback_max * 2 else (2 if current < fallback_max * 3 else 3)

        actions = {1: "throttle", 2: "pause", 3: "pause_all"}
        return AnomalyAlert(
            account_id=account_id,
            alert_type=alert_type,
            level=level,
            message=f"{desc}: 当前 {current:.1f}（基线 {window.mean:.1f}±{window.std:.1f}）",
            metric_value=current,
            baseline_mean=window.mean,
            z_score=z,
            timestamp=time.time(),
            auto_action=actions.get(level, "throttle"),
        )

    def get_circuit_breaker(self, account_id: str) -> int:
        """获取账号的熔断等级 (0=正常, 1=限流, 2=暂停, 3=全局暂停)"""
        return self._circuit_breakers.get(account_id, 0)

    def reset_circuit_breaker(self, account_id: str):
        """手动重置熔断"""
        with self._lock:
            self._circuit_breakers.pop(account_id, None)

    def is_operation_allowed(self, account_id: str) -> bool:
        """检查账号是否允许自动操作"""
        level = self.get_circuit_breaker(account_id)
        return level < 2

    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        return [a.to_dict() for a in self._alerts[-limit:]]

    def get_status(self) -> Dict:
        return {
            "circuit_breakers": dict(self._circuit_breakers),
            "total_alerts": len(self._alerts),
            "baselines": {
                acct: {k: {"mean": round(w.mean, 2), "std": round(w.std, 2), "samples": len(w.values)}
                       for k, w in metrics.items()}
                for acct, metrics in self._baselines.items()
            },
        }


# 全局单例
_detector: Optional[AnomalyDetector] = None


def get_detector() -> AnomalyDetector:
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector
