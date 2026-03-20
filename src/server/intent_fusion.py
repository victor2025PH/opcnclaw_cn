# -*- coding: utf-8 -*-
"""
意图融合引擎 — 多模态信号融合与意图决策

四通道信号源：
  1. 注视 (gaze)      — 前端 gaze-tracker.js → HTTP/WS
  2. 表情 (expression) — 前端 expression-system.js → HTTP/WS
  3. 语音 (voice)      — 后端 STT 转写结果
  4. 桌面 (desktop)    — 后端 HumanDetector 鼠标/键盘

融合策略：
  - 500ms 滑动时间窗口收集多通道信号
  - 优先级：紧急停止 > 语音指令 > 手势动作 > 情感上下文
  - 跨模态增强：点头 + "好" = 2x 置信度
  - 与 CoworkBus 集成：融合结果影响桌面操作决策

设计决策：
  采用混合架构——前端实时融合摄像头信号(低延迟)，
  后端做最终权威决策(整合键鼠+语音+前端信号)。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


# ── 数据模型 ──────────────────────────────────────────────────────

class SignalPriority(IntEnum):
    """信号优先级（数值越高越优先）"""
    CONTEXT = 1       # 情感上下文
    GESTURE = 5       # 手势/表情动作
    VOICE = 10        # 语音指令
    EMERGENCY = 100   # 紧急停止


# 信号通道→默认优先级映射
CHANNEL_PRIORITY: Dict[str, SignalPriority] = {
    "gaze": SignalPriority.CONTEXT,
    "expression": SignalPriority.GESTURE,
    "voice": SignalPriority.VOICE,
    "touch": SignalPriority.GESTURE,
    "desktop": SignalPriority.CONTEXT,
}

# 意图语义类别
INTENT_CATEGORIES = {
    "confirm":    {"nod", "smile_hold", "yes", "ok", "okay", "好", "确认", "是的", "对"},
    "cancel":     {"shake", "no", "cancel", "不", "取消", "算了", "不要"},
    "click":      {"wink_left", "click", "tap", "点击"},
    "right_click": {"wink_right", "right_click", "右键"},
    "scroll_up":  {"brow_up", "scroll_up", "向上", "上翻"},
    "scroll_down": {"brow_down", "scroll_down", "向下", "下翻"},
    "start_voice": {"mouth_open", "start_listening", "开始", "说话"},
    "undo":       {"tilt_left", "undo", "撤销", "回退"},
    "redo":       {"tilt_right", "redo", "重做"},
    "stop":       {"emergency_stop", "stop", "停", "停止", "别动"},
    "screenshot": {"screenshot", "截图"},
    "escape":     {"escape", "退出", "关闭"},
}

# 反向映射：信号名 → 意图类别
_SIGNAL_TO_INTENT: Dict[str, str] = {}
for intent, signals in INTENT_CATEGORIES.items():
    for sig in signals:
        _SIGNAL_TO_INTENT[sig] = intent

# 跨模态增强矩阵：(通道A, 通道B) → 增强倍数
CROSS_MODAL_BOOST = {
    ("expression", "voice"): {
        ("nod", "confirm"):      2.0,
        ("shake", "cancel"):     2.0,
        ("smile_hold", "confirm"): 1.5,
        ("mouth_open", "start_voice"): 1.5,
    },
    ("expression", "gaze"): {
        ("wink_left", "click"):  1.5,  # 眨眼+注视目标
        ("wink_right", "right_click"): 1.5,
    },
}


@dataclass
class Signal:
    """单条信号"""
    channel: str          # gaze / expression / voice / touch / desktop
    name: str             # 信号名 (如 "nod", "smile_hold", "yes")
    confidence: float     # 0.0 - 1.0
    timestamp: float = field(default_factory=time.time)
    priority: int = 0     # 覆盖默认优先级 (0=使用通道默认)
    params: Dict = field(default_factory=dict)

    @property
    def effective_priority(self) -> int:
        if self.priority > 0:
            return self.priority
        return CHANNEL_PRIORITY.get(self.channel, SignalPriority.CONTEXT)

    @property
    def intent(self) -> str:
        return _SIGNAL_TO_INTENT.get(self.name, self.name)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "name": self.name,
            "confidence": round(self.confidence, 3),
            "priority": self.effective_priority,
            "intent": self.intent,
            "timestamp": round(self.timestamp, 3),
            "params": self.params,
        }


@dataclass
class FusedIntent:
    """融合后的意图决策"""
    intent: str                    # 语义意图名（confirm/cancel/click/...）
    confidence: float              # 融合后的置信度 0.0 - 1.0
    priority: int                  # 最高信号的优先级
    sources: List[Signal]          # 参与融合的原始信号
    timestamp: float = field(default_factory=time.time)
    boosted: bool = False          # 是否触发了跨模态增强
    boost_factor: float = 1.0     # 增强倍数

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
            "source_count": len(self.sources),
            "channels": list({s.channel for s in self.sources}),
            "boosted": self.boosted,
            "boost_factor": self.boost_factor,
            "timestamp": round(self.timestamp, 3),
        }


# ── 融合引擎 ──────────────────────────────────────────────────────

class IntentFusionEngine:
    """
    多模态意图融合引擎

    工作流程：
      1. 各通道推送 Signal 到 buffer
      2. 500ms 窗口到期 → 执行融合
      3. 融合结果通过回调+EventBus 通知
      4. CoworkBus 可查询当前融合状态
    """

    WINDOW_MS = 500           # 融合窗口（毫秒）
    MIN_CONFIDENCE = 0.3      # 最低置信度阈值
    EMERGENCY_THRESHOLD = 0.6 # 紧急停止最低置信度
    MAX_HISTORY = 50          # 历史融合结果保留数
    SIGNAL_TTL = 2.0          # 信号过期时间（秒）

    def __init__(self):
        self._buffer: List[Signal] = []
        self._lock = threading.Lock()
        self._last_fusion: float = 0.0
        self._current_intent: Optional[FusedIntent] = None
        self._history: List[FusedIntent] = []
        self._listeners: List[Callable[[FusedIntent], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._emergency_callback: Optional[Callable] = None
        self._stats = {
            "signals_received": 0,
            "fusions_performed": 0,
            "emergency_stops": 0,
            "cross_modal_boosts": 0,
        }

    # ── 公共 API ─────────────────────────────────────────────

    def start(self):
        """启动融合循环"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._fusion_loop, daemon=True, name="IntentFusion"
        )
        self._thread.start()
        logger.info("[IntentFusion] 引擎启动（窗口={}ms）", self.WINDOW_MS)

    def stop(self):
        self._running = False

    def push_signal(self, signal: Signal):
        """
        推送一条信号到融合缓冲区。

        紧急停止信号立即处理，不等窗口。
        """
        self._stats["signals_received"] += 1

        # 紧急停止：立即响应，不进入窗口
        if signal.intent == "stop" and signal.confidence >= self.EMERGENCY_THRESHOLD:
            self._handle_emergency(signal)
            return

        with self._lock:
            self._buffer.append(signal)

    def push_raw(self, channel: str, name: str, confidence: float = 1.0,
                 params: dict = None, priority: int = 0):
        """快捷推送（不需要手动创建 Signal 对象）"""
        self.push_signal(Signal(
            channel=channel,
            name=name,
            confidence=confidence,
            params=params or {},
            priority=priority,
        ))

    def on_intent(self, callback: Callable[[FusedIntent], None]):
        """注册融合结果监听器"""
        self._listeners.append(callback)

    def on_emergency(self, callback: Callable):
        """注册紧急停止回调"""
        self._emergency_callback = callback

    @property
    def current_intent(self) -> Optional[FusedIntent]:
        return self._current_intent

    def get_state(self) -> dict:
        """返回当前融合引擎状态"""
        now = time.time()
        with self._lock:
            active_signals = [
                s.to_dict() for s in self._buffer
                if (now - s.timestamp) < self.SIGNAL_TTL
            ]

        return {
            "running": self._running,
            "current_intent": self._current_intent.to_dict() if self._current_intent else None,
            "active_signals": active_signals,
            "signal_count": len(active_signals),
            "window_ms": self.WINDOW_MS,
            "stats": self._stats.copy(),
        }

    def get_history(self, limit: int = 20) -> List[dict]:
        return [h.to_dict() for h in self._history[-limit:]]

    # ── 内部逻辑 ──────────────────────────────────────────────

    def _fusion_loop(self):
        """主循环：每 WINDOW_MS 执行一次融合"""
        interval = self.WINDOW_MS / 1000.0
        while self._running:
            try:
                time.sleep(interval)
                self._do_fusion()
            except Exception as e:
                logger.debug(f"[IntentFusion] fusion error: {e}")

    def _do_fusion(self):
        """核心融合算法"""
        now = time.time()

        # 1. 取出窗口内的信号，清除过期信号
        with self._lock:
            active = [s for s in self._buffer if (now - s.timestamp) < self.SIGNAL_TTL]
            self._buffer = active.copy()  # 保留未过期的信号供下次融合

        if not active:
            # 无信号时清除当前意图（2秒后）
            if self._current_intent and (now - self._current_intent.timestamp) > 2.0:
                self._current_intent = None
            return

        # 2. 按意图分组
        intent_groups: Dict[str, List[Signal]] = defaultdict(list)
        for sig in active:
            intent_groups[sig.intent].append(sig)

        # 3. 对每个意图组计算融合置信度
        candidates: List[FusedIntent] = []
        for intent_name, signals in intent_groups.items():
            fused = self._fuse_group(intent_name, signals)
            if fused and fused.confidence >= self.MIN_CONFIDENCE:
                candidates.append(fused)

        if not candidates:
            return

        # 4. 选择最优意图：先按优先级，再按置信度
        candidates.sort(key=lambda f: (f.priority, f.confidence), reverse=True)
        best = candidates[0]

        # 5. 更新状态
        self._current_intent = best
        self._history.append(best)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

        self._stats["fusions_performed"] += 1
        self._last_fusion = now

        # 6. 通知监听器
        self._notify(best)

        # 7. 从 buffer 中移除已融合的信号（避免重复融合）
        fused_ids = {id(s) for s in best.sources}
        with self._lock:
            self._buffer = [s for s in self._buffer if id(s) not in fused_ids]

    def _fuse_group(self, intent_name: str, signals: List[Signal]) -> Optional[FusedIntent]:
        """融合同一意图的多通道信号"""
        if not signals:
            return None

        # 通道权重：语音 > 手势 > 注视
        channel_weight = {
            "voice": 1.0,
            "expression": 0.8,
            "touch": 0.7,
            "gaze": 0.4,
            "desktop": 0.3,
        }

        # 加权平均置信度
        total_weight = 0.0
        weighted_conf = 0.0
        for sig in signals:
            w = channel_weight.get(sig.channel, 0.5)
            weighted_conf += sig.confidence * w
            total_weight += w

        avg_confidence = weighted_conf / total_weight if total_weight > 0 else 0

        # 多通道增强：同一意图来自2+通道 → 置信度提升
        channels = {s.channel for s in signals}
        multi_channel_boost = 1.0
        if len(channels) >= 2:
            multi_channel_boost = 1.0 + 0.2 * (len(channels) - 1)  # 2通道=1.2x, 3通道=1.4x

        # 跨模态增强矩阵查找
        cross_boost = 1.0
        boosted = False
        for (ch_a, ch_b), boosts in CROSS_MODAL_BOOST.items():
            sigs_a = [s for s in signals if s.channel == ch_a]
            sigs_b = [s for s in signals if s.channel == ch_b]
            if sigs_a and sigs_b:
                for sig_a in sigs_a:
                    # 查找 (信号名, 意图名) 的增强
                    key = (sig_a.name, intent_name)
                    if key in boosts:
                        cross_boost = max(cross_boost, boosts[key])
                        boosted = True

        # 最终置信度（cap 在 1.0）
        final_confidence = min(avg_confidence * multi_channel_boost * cross_boost, 1.0)
        max_priority = max(s.effective_priority for s in signals)

        return FusedIntent(
            intent=intent_name,
            confidence=final_confidence,
            priority=max_priority,
            sources=signals,
            boosted=boosted,
            boost_factor=multi_channel_boost * cross_boost,
        )

    def _handle_emergency(self, signal: Signal):
        """紧急停止：立即响应"""
        logger.warning("[IntentFusion] 紧急停止! 来源: {} 置信度: {:.2f}",
                       signal.channel, signal.confidence)
        self._stats["emergency_stops"] += 1

        emergency = FusedIntent(
            intent="stop",
            confidence=signal.confidence,
            priority=SignalPriority.EMERGENCY,
            sources=[signal],
        )
        self._current_intent = emergency
        self._history.append(emergency)

        # 触发紧急回调
        if self._emergency_callback:
            try:
                self._emergency_callback()
            except Exception as e:
                logger.error(f"[IntentFusion] emergency callback error: {e}")

        self._notify(emergency)

    def _notify(self, intent: FusedIntent):
        """通知所有监听器"""
        for listener in self._listeners:
            try:
                listener(intent)
            except Exception as e:
                logger.debug(f"[IntentFusion] listener error: {e}")

        # 通过 EventBus 广播（延迟导入避免循环）
        try:
            from .event_bus import publish
            publish("intent:fused", intent.to_dict())
        except Exception:
            pass


# ── 全局单例 ──────────────────────────────────────────────────────

_engine: Optional[IntentFusionEngine] = None


def get_engine() -> IntentFusionEngine:
    """获取全局融合引擎单例"""
    global _engine
    if _engine is None:
        _engine = IntentFusionEngine()

        # 注册紧急停止回调 → CoworkBus 暂停
        def _on_emergency():
            try:
                from .cowork_bus import get_bus
                bus = get_bus()
                bus.pause()
                logger.info("[IntentFusion] 紧急停止 → CoworkBus 已暂停")
            except Exception:
                pass

        _engine.on_emergency(_on_emergency)
        _engine.start()
    return _engine


def push_signal(channel: str, name: str, confidence: float = 1.0,
                params: dict = None, priority: int = 0):
    """全局快捷推送信号"""
    get_engine().push_raw(channel, name, confidence, params, priority)
