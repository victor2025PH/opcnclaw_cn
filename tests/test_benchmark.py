"""
Performance benchmarks for OpenClaw core pipeline.

Measures latency for STT, TTS, AI, and end-to-end flow.
Run: pytest tests/test_benchmark.py -v -s
"""

import asyncio
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _measure_ms(func, *args, **kwargs):
    t0 = time.perf_counter()
    result = func(*args, **kwargs)
    return result, int((time.perf_counter() - t0) * 1000)


async def _ameasure_ms(coro):
    t0 = time.perf_counter()
    result = await coro
    return result, int((time.perf_counter() - t0) * 1000)


class TestSTTBenchmark:

    @pytest.mark.asyncio
    async def test_stt_init_time(self):
        from src.server.stt import SpeechToText
        _, ms = _measure_ms(SpeechToText, model_name="tiny", device="cpu",
                            prefer_cloud=False)
        print(f"\n  STT init: {ms}ms")
        assert ms < 30000, f"STT init too slow: {ms}ms"

    @pytest.mark.asyncio
    async def test_stt_transcribe_latency(self):
        from src.server.stt import SpeechToText
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        audio = np.zeros(16000, dtype=np.float32)

        latencies = []
        for _ in range(3):
            _, ms = await _ameasure_ms(stt.transcribe(audio))
            latencies.append(ms)

        avg = sum(latencies) // len(latencies)
        print(f"\n  STT transcribe: avg={avg}ms, runs={latencies}")
        assert avg < 10000, f"STT too slow: avg {avg}ms"


class TestTTSBenchmark:

    @pytest.mark.asyncio
    async def test_tts_init_time(self):
        from src.server.tts import TextToSpeech
        _, ms = _measure_ms(TextToSpeech)
        print(f"\n  TTS init: {ms}ms")
        assert ms < 30000, f"TTS init too slow: {ms}ms"

    @pytest.mark.asyncio
    async def test_tts_synthesize_latency(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech()

        latencies = []
        for _ in range(3):
            _, ms = await _ameasure_ms(tts.synthesize("你好世界"))
            latencies.append(ms)

        avg = sum(latencies) // len(latencies)
        print(f"\n  TTS synthesize: avg={avg}ms, runs={latencies}")
        assert avg < 15000, f"TTS too slow: avg {avg}ms"

    @pytest.mark.asyncio
    async def test_tts_stream_first_chunk(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech()
        t0 = time.perf_counter()
        first_chunk = None
        async for chunk in tts.synthesize_stream("测试流式合成"):
            if first_chunk is None:
                first_chunk = int((time.perf_counter() - t0) * 1000)
            break
        print(f"\n  TTS stream first chunk: {first_chunk}ms")


class TestAIBenchmark:

    @pytest.mark.asyncio
    async def test_ai_init_time(self):
        from src.server.backend import AIBackend
        _, ms = _measure_ms(AIBackend, backend_type="openai", model="gpt-4o-mini")
        print(f"\n  AI Backend init: {ms}ms")
        assert ms < 8000  # jieba 首次加载可能需要 5-6s

    @pytest.mark.asyncio
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No API key")
    async def test_ai_chat_latency(self):
        from src.server.backend import AIBackend
        backend = AIBackend(
            backend_type="openai",
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        _, ms = await _ameasure_ms(
            backend.chat("回复'测试'两个字，不要说任何其他内容"))
        print(f"\n  AI chat: {ms}ms")
        assert ms < 30000


class TestEndToEndBenchmark:

    @pytest.mark.asyncio
    async def test_stt_then_tts(self):
        from src.server.stt import SpeechToText
        from src.server.tts import TextToSpeech

        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        tts = TextToSpeech()
        audio = np.zeros(16000, dtype=np.float32)

        t0 = time.perf_counter()
        result = await stt.transcribe(audio)
        text = result.text if result.text.strip() else "你好"
        output = await tts.synthesize(text)
        total_ms = int((time.perf_counter() - t0) * 1000)

        print(f"\n  E2E (STT+TTS): {total_ms}ms, "
              f"STT latency={result.latency_ms}ms, "
              f"output size={len(output)} samples")
        assert total_ms < 30000


class TestHealthBenchmark:

    def test_health_check_speed(self):
        from src.server.health import HealthChecker
        hc = HealthChecker()
        _, ms = _measure_ms(hc.run_all)
        print(f"\n  Health check: {ms}ms ({len(hc.run_all())} checks)")
        assert ms < 15000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
