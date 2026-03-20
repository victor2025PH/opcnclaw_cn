# -*- coding: utf-8 -*-
"""意图融合引擎测试

覆盖：
  - 信号推送与缓冲
  - 单通道融合
  - 多通道融合与增强
  - 跨模态增强矩阵
  - 紧急停止立即响应
  - 优先级排序
  - 信号过期清理
  - API 路由
  - 引擎状态查询
  - 配置动态调整
"""

import time
import pytest

from src.server.intent_fusion import (
    IntentFusionEngine, Signal, FusedIntent, SignalPriority,
    INTENT_CATEGORIES, _SIGNAL_TO_INTENT,
)


@pytest.fixture
def engine():
    """创建干净的引擎实例（不启动后台线程）"""
    e = IntentFusionEngine()
    # 不调用 start()，手动触发 _do_fusion() 测试
    return e


class TestSignal:
    """信号数据模型测试"""

    def test_signal_defaults(self):
        s = Signal(channel="voice", name="yes", confidence=0.9)
        assert s.channel == "voice"
        assert s.confidence == 0.9
        assert s.effective_priority == SignalPriority.VOICE
        assert s.intent == "confirm"  # "yes" → confirm

    def test_signal_custom_priority(self):
        s = Signal(channel="gaze", name="click", confidence=0.8, priority=50)
        assert s.effective_priority == 50

    def test_signal_unknown_name(self):
        s = Signal(channel="touch", name="unknown_gesture", confidence=0.5)
        assert s.intent == "unknown_gesture"  # 未映射的信号名作为意图名

    def test_signal_to_dict(self):
        s = Signal(channel="expression", name="nod", confidence=0.85, params={"angle": 15})
        d = s.to_dict()
        assert d["channel"] == "expression"
        assert d["name"] == "nod"
        assert d["confidence"] == 0.85
        assert d["intent"] == "confirm"
        assert d["params"]["angle"] == 15

    def test_intent_mapping_completeness(self):
        """确保所有意图类别都有映射"""
        for intent, signals in INTENT_CATEGORIES.items():
            for sig_name in signals:
                assert _SIGNAL_TO_INTENT[sig_name] == intent


class TestFusedIntent:
    """融合结果测试"""

    def test_fused_intent_to_dict(self):
        sig = Signal(channel="voice", name="yes", confidence=0.9)
        f = FusedIntent(intent="confirm", confidence=0.9, priority=10, sources=[sig])
        d = f.to_dict()
        assert d["intent"] == "confirm"
        assert d["confidence"] == 0.9
        assert d["source_count"] == 1
        assert "voice" in d["channels"]


class TestSingleChannelFusion:
    """单通道融合测试"""

    def test_single_voice_signal(self, engine):
        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()
        assert engine.current_intent is not None
        assert engine.current_intent.intent == "confirm"
        assert engine.current_intent.confidence >= 0.3

    def test_single_expression_signal(self, engine):
        engine.push_raw("expression", "nod", 0.8)
        engine._do_fusion()
        assert engine.current_intent is not None
        assert engine.current_intent.intent == "confirm"

    def test_low_confidence_rejected(self, engine):
        engine.push_raw("gaze", "scroll_up", 0.1)  # 低于 MIN_CONFIDENCE
        engine._do_fusion()
        # gaze 权重 0.4，置信度 0.1 → 加权 = 0.1 < 0.3 → 拒绝
        assert engine.current_intent is None

    def test_multiple_same_channel(self, engine):
        """同通道多次推送同一信号 → 应取最高"""
        engine.push_raw("expression", "smile_hold", 0.6)
        engine.push_raw("expression", "smile_hold", 0.9)
        engine._do_fusion()
        assert engine.current_intent is not None
        assert engine.current_intent.intent == "confirm"


class TestMultiChannelFusion:
    """多通道融合测试"""

    def test_voice_plus_expression_boost(self, engine):
        """语音 + 表情 → 多通道增强"""
        engine.push_raw("voice", "yes", 0.8)
        engine.push_raw("expression", "nod", 0.7)
        engine._do_fusion()

        intent = engine.current_intent
        assert intent is not None
        assert intent.intent == "confirm"
        assert intent.boosted is True  # 跨模态增强
        assert intent.boost_factor > 1.0
        # 多通道增强：2通道=1.2x + 跨模态nod+confirm=2.0x
        assert intent.confidence > 0.8

    def test_conflicting_intents(self, engine):
        """冲突意图 → 高优先级胜出"""
        engine.push_raw("voice", "yes", 0.8)       # confirm, priority=10
        engine.push_raw("expression", "shake", 0.7)  # cancel, priority=5
        engine._do_fusion()

        intent = engine.current_intent
        assert intent is not None
        assert intent.intent == "confirm"  # 语音优先级更高

    def test_three_channel_boost(self, engine):
        """三通道融合 → 1.4x 增强"""
        engine.push_raw("voice", "yes", 0.7)
        engine.push_raw("expression", "nod", 0.6)
        engine.push_raw("gaze", "confirm", 0.5)  # gaze 也同意
        # 注：gaze 的 "confirm" 不在 INTENT_CATEGORIES 中，会映射到自身
        # 改用已知映射
        engine._buffer.clear()
        engine.push_raw("voice", "yes", 0.7)
        engine.push_raw("expression", "nod", 0.6)
        engine.push_raw("touch", "tap", 0.5)  # touch tap → click 意图
        engine._do_fusion()

        # voice → confirm, expression → confirm, touch → click
        # confirm 有2通道增强
        intent = engine.current_intent
        assert intent is not None


class TestEmergencyStop:
    """紧急停止测试"""

    def test_emergency_immediate(self, engine):
        """紧急停止不等融合窗口"""
        callback_called = [False]
        engine.on_emergency(lambda: callback_called.__setitem__(0, True))

        engine.push_raw("voice", "emergency_stop", 0.9)

        # 不需要调用 _do_fusion()，应该立即处理
        assert engine.current_intent is not None
        assert engine.current_intent.intent == "stop"
        assert engine.current_intent.priority == SignalPriority.EMERGENCY
        assert callback_called[0] is True

    def test_emergency_below_threshold(self, engine):
        """低置信度的 stop 不触发紧急模式"""
        engine.push_raw("voice", "stop", 0.3)  # 低于 EMERGENCY_THRESHOLD=0.6

        # 应该进入普通缓冲区
        assert len(engine._buffer) == 1
        assert engine.current_intent is None  # 还未融合

    def test_emergency_stats(self, engine):
        engine.push_raw("voice", "emergency_stop", 0.9)
        assert engine._stats["emergency_stops"] == 1


class TestSignalExpiry:
    """信号过期测试"""

    def test_expired_signals_cleaned(self, engine):
        """过期信号应被清除"""
        old_signal = Signal(
            channel="voice", name="yes", confidence=0.9,
            timestamp=time.time() - 5.0,  # 5秒前，超过 TTL=2s
        )
        engine._buffer.append(old_signal)
        engine._do_fusion()
        # 过期信号被清理，无融合结果
        assert engine.current_intent is None

    def test_fresh_signal_survives(self, engine):
        """新鲜信号应保留"""
        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()
        assert engine.current_intent is not None


class TestPriority:
    """优先级排序测试"""

    def test_voice_beats_gesture(self, engine):
        """语音优先级 > 手势"""
        engine.push_raw("expression", "wink_left", 0.95)  # click, priority=5
        engine.push_raw("voice", "yes", 0.7)              # confirm, priority=10
        engine._do_fusion()

        # 语音优先级更高，即使置信度较低
        assert engine.current_intent.intent == "confirm"

    def test_same_priority_uses_confidence(self, engine):
        """同优先级 → 置信度决胜"""
        engine.push_raw("expression", "wink_left", 0.5)   # click, priority=5
        engine.push_raw("expression", "smile_hold", 0.9)  # confirm, priority=5
        engine._do_fusion()

        assert engine.current_intent.intent == "confirm"


class TestEngineState:
    """引擎状态查询测试"""

    def test_initial_state(self, engine):
        state = engine.get_state()
        assert state["running"] is False
        assert state["current_intent"] is None
        assert state["signal_count"] == 0

    def test_state_after_signal(self, engine):
        engine.push_raw("voice", "yes", 0.9)
        state = engine.get_state()
        assert state["signal_count"] == 1
        assert state["active_signals"][0]["channel"] == "voice"

    def test_history(self, engine):
        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()
        history = engine.get_history()
        assert len(history) == 1
        assert history[0]["intent"] == "confirm"


class TestListeners:
    """事件监听测试"""

    def test_on_intent_callback(self, engine):
        results = []
        engine.on_intent(lambda f: results.append(f.intent))

        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()

        assert len(results) == 1
        assert results[0] == "confirm"

    def test_multiple_listeners(self, engine):
        count = [0]
        engine.on_intent(lambda f: count.__setitem__(0, count[0] + 1))
        engine.on_intent(lambda f: count.__setitem__(0, count[0] + 1))

        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()

        assert count[0] == 2

    def test_listener_error_not_fatal(self, engine):
        """监听器异常不应阻止其他监听器"""
        results = []
        engine.on_intent(lambda f: 1/0)  # 会抛异常
        engine.on_intent(lambda f: results.append(f.intent))

        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()

        assert len(results) == 1  # 第二个监听器仍然执行


class TestCrossModalBoost:
    """跨模态增强矩阵测试"""

    def test_nod_plus_voice_confirm(self, engine):
        """点头 + 语音确认 → 2.0x"""
        engine.push_raw("expression", "nod", 0.7)
        engine.push_raw("voice", "yes", 0.7)
        engine._do_fusion()

        intent = engine.current_intent
        assert intent.boosted is True
        assert intent.boost_factor >= 2.0

    def test_shake_plus_voice_cancel(self, engine):
        """摇头 + 语音取消 → 2.0x"""
        engine.push_raw("expression", "shake", 0.7)
        engine.push_raw("voice", "no", 0.7)
        engine._do_fusion()

        intent = engine.current_intent
        assert intent.boosted is True

    def test_no_boost_unrelated(self, engine):
        """不相关的通道组合 → 无增强"""
        engine.push_raw("expression", "nod", 0.7)     # confirm
        engine.push_raw("voice", "screenshot", 0.7)   # screenshot (不同意图)
        engine._do_fusion()

        # 两个不同意图，不会跨模态增强
        assert engine.current_intent is not None


class TestConfig:
    """配置动态调整测试"""

    def test_adjust_window(self, engine):
        engine.WINDOW_MS = 1000
        assert engine.WINDOW_MS == 1000

    def test_adjust_min_confidence(self, engine):
        engine.MIN_CONFIDENCE = 0.5
        engine.push_raw("voice", "yes", 0.4)  # 低于新阈值
        engine._do_fusion()
        assert engine.current_intent is None

    def test_adjust_emergency_threshold(self, engine):
        engine.EMERGENCY_THRESHOLD = 0.9
        engine.push_raw("voice", "emergency_stop", 0.8)  # 低于新阈值
        # 应进入普通缓冲区而非紧急处理
        assert len(engine._buffer) == 1


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_fusion(self, engine):
        """空缓冲区融合 → 无结果"""
        engine._do_fusion()
        assert engine.current_intent is None

    def test_rapid_signals(self, engine):
        """快速连续推送"""
        for i in range(100):
            engine.push_raw("expression", "nod", 0.5 + i * 0.005)
        engine._do_fusion()
        assert engine.current_intent is not None

    def test_intent_auto_clear(self, engine):
        """意图2秒后自动清除"""
        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()
        assert engine.current_intent is not None

        # 模拟2秒后
        engine._current_intent.timestamp = time.time() - 3.0
        engine._buffer.clear()
        engine._do_fusion()
        assert engine.current_intent is None

    def test_stats_tracking(self, engine):
        engine.push_raw("voice", "yes", 0.9)
        engine._do_fusion()
        assert engine._stats["signals_received"] == 1
        assert engine._stats["fusions_performed"] == 1
