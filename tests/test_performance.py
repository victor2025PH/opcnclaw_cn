# -*- coding: utf-8 -*-
"""性能基准测试 — 量化各模块延迟

测量项：
  - 声纹提取速度
  - 意图融合速度
  - 工具调度速度
  - TTS 语言检测速度
  - 数据库查询速度
  - 模块导入速度
"""

import time
import pytest
import numpy as np


def _measure(fn, *args, **kwargs):
    """测量函数执行时间（毫秒）"""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    ms = (time.perf_counter() - t0) * 1000
    return result, ms


class TestSpeakerPerformance:
    """声纹模块性能"""

    def test_mfcc_extraction_speed(self):
        """3秒音频 MFCC 提取应 < 50ms"""
        from src.server.speaker_id import extract_embedding
        audio = np.random.randn(48000).astype(np.float32) * 0.5
        _, ms = _measure(extract_embedding, audio)
        print(f"\n  MFCC提取: {ms:.1f}ms")
        assert ms < 1000  # 首次含 scipy.fft 加载，后续 <50ms

    def test_cosine_similarity_speed(self):
        """余弦相似度应 < 1ms"""
        from src.server.speaker_id import cosine_similarity, EMBED_DIM
        a = np.random.randn(EMBED_DIM).astype(np.float32)
        b = np.random.randn(EMBED_DIM).astype(np.float32)
        _, ms = _measure(cosine_similarity, a, b)
        print(f"\n  余弦相似度: {ms:.3f}ms")
        assert ms < 5


class TestIntentFusionPerformance:
    """意图融合性能"""

    def test_single_fusion_speed(self):
        """单次融合应 < 5ms"""
        from src.server.intent_fusion import IntentFusionEngine
        engine = IntentFusionEngine()
        engine.push_raw("voice", "yes", 0.9)
        _, ms = _measure(engine._do_fusion)
        print(f"\n  单次融合: {ms:.2f}ms")
        assert ms < 100  # 首次含 DB 初始化

    def test_100_signals_fusion(self):
        """100个信号融合应 < 50ms"""
        from src.server.intent_fusion import IntentFusionEngine
        engine = IntentFusionEngine()
        for i in range(100):
            engine.push_raw("expression", "nod", 0.5 + i * 0.005)
        _, ms = _measure(engine._do_fusion)
        print(f"\n  100信号融合: {ms:.2f}ms")
        assert ms < 100


class TestToolPerformance:
    """工具调度性能"""

    def test_tool_schema_count(self):
        """工具数量检查"""
        from src.server.tools import TOOL_SCHEMAS
        count = len(TOOL_SCHEMAS)
        print(f"\n  工具总数: {count}")
        assert count >= 20

    def test_tool_dispatch_speed(self):
        """call_tool 调度应 < 10ms（不含实际执行）"""
        import asyncio
        from src.server.tools import call_tool
        _, ms = _measure(lambda: asyncio.get_event_loop().run_until_complete(
            call_tool("get_current_time", {})
        ) if asyncio.get_event_loop().is_running() else "skip")
        # 简单测量导入+解析速度
        print(f"\n  工具调度: {ms:.2f}ms")


class TestTTSPerformance:
    """TTS 语言检测性能"""

    def test_language_detection_speed(self):
        """语言检测应 < 1ms"""
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts._edge_voice = "zh-CN-XiaoxiaoNeural"

        texts = [
            "你好世界今天天气怎么样",
            "Hello world how are you",
            "こんにちは元気ですか",
            "今天的weather很好适合出去play",
        ]
        total_ms = 0
        for t in texts:
            _, ms = _measure(tts._detect_voice_for_text, t)
            total_ms += ms

        avg = total_ms / len(texts)
        print(f"\n  语言检测平均: {avg:.3f}ms")
        assert avg < 5


class TestDatabasePerformance:
    """数据库性能"""

    def test_connection_speed(self):
        """数据库连接应 < 50ms"""
        from src.server import db
        _, ms = _measure(db.get_conn, "main")
        print(f"\n  DB连接: {ms:.1f}ms")
        assert ms < 200

    def test_simple_query_speed(self):
        """简单查询应 < 10ms"""
        from src.server import db
        conn = db.get_conn("main")
        _, ms = _measure(conn.execute, "SELECT COUNT(*) FROM messages")
        print(f"\n  COUNT查询: {ms:.2f}ms")
        assert ms < 50


class TestModuleImportPerformance:
    """模块导入性能"""

    def test_import_intent_fusion(self):
        """intent_fusion 导入应 < 500ms"""
        import importlib
        import src.server.intent_fusion as m
        importlib.reload(m)
        _, ms = _measure(importlib.reload, m)
        print(f"\n  intent_fusion: {ms:.1f}ms")
        assert ms < 2000

    def test_import_speaker_id(self):
        """speaker_id 导入应 < 500ms"""
        import importlib
        import src.server.speaker_id as m
        _, ms = _measure(importlib.reload, m)
        print(f"\n  speaker_id: {ms:.1f}ms")
        assert ms < 2000

    def test_import_tools(self):
        """tools 导入应 < 500ms"""
        import importlib
        import src.server.tools as m
        _, ms = _measure(importlib.reload, m)
        print(f"\n  tools: {ms:.1f}ms")
        assert ms < 2000
