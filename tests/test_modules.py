"""
Unit tests for OpenClaw Voice v3.0 core modules.

Covers: SpeechToText, TextToSpeech, AIBackend, VoiceActivityDetector
All tests run in mock/offline mode — no API keys needed.
"""

import pytest
import numpy as np
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server.stt import SpeechToText, WhisperSTT, STTResult
from src.server.tts import TextToSpeech, ChatterboxTTS
from src.server.backend import AIBackend
from src.server.vad import VoiceActivityDetector


class TestSpeechToText:

    def test_init_creates_instance(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        assert stt is not None

    def test_backward_compat_alias(self):
        assert WhisperSTT is SpeechToText

    def test_backend_is_string(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        assert isinstance(stt._backend, str)

    @pytest.mark.asyncio
    async def test_transcribe_returns_stt_result(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        audio = np.zeros(16000, dtype=np.float32)
        result = await stt.transcribe(audio)
        assert isinstance(result, STTResult)
        assert isinstance(result.text, str)
        assert isinstance(result.emotion, str)
        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_transcribe_with_noise(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        audio = np.random.randn(16000).astype(np.float32) * 0.1
        result = await stt.transcribe(audio)
        assert isinstance(result, STTResult)

    def test_is_cloud_property(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        assert isinstance(stt.is_cloud, bool)


class TestTextToSpeech:

    def test_init_creates_instance(self):
        tts = TextToSpeech()
        assert tts is not None

    def test_backward_compat_alias(self):
        assert ChatterboxTTS is TextToSpeech

    def test_backend_is_string(self):
        tts = TextToSpeech()
        assert isinstance(tts._backend, str)

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio(self):
        tts = TextToSpeech()
        result = await tts.synthesize("Hello world")
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_synthesize_stream_yields_bytes(self):
        tts = TextToSpeech()
        chunks = []
        async for chunk in tts.synthesize_stream("测试语音合成"):
            chunks.append(chunk)
            assert isinstance(chunk, bytes)
        assert len(chunks) > 0

    def test_audio_format_property(self):
        tts = TextToSpeech()
        assert tts.audio_format in ("pcm", "mp3", "wav", "opus")


class TestAIBackend:

    def test_init_creates_client(self):
        backend = AIBackend(backend_type="openai", model="gpt-4o-mini")
        assert backend is not None
        assert backend.backend_type == "openai"

    def test_system_prompt_default(self):
        backend = AIBackend()
        assert backend.system_prompt is not None

    def test_clear_history(self):
        backend = AIBackend()
        backend.conversation_history = [{"role": "user", "content": "test"}]
        backend.clear_history()
        assert len(backend.conversation_history) == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set",
    )
    async def test_chat_returns_response(self):
        backend = AIBackend(
            backend_type="openai",
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        result = await backend.chat("Say 'test' and nothing else.")
        assert isinstance(result, str)
        assert len(result) > 0


class TestVAD:

    def test_init(self):
        vad = VoiceActivityDetector()
        assert vad is not None

    def test_is_speech_silence(self):
        vad = VoiceActivityDetector()
        silence = np.zeros(16000, dtype=np.float32)
        result = vad.is_speech(silence)
        assert isinstance(result, bool)

    def test_is_speech_noise(self):
        vad = VoiceActivityDetector()
        noise = np.random.randn(16000).astype(np.float32)
        result = vad.is_speech(noise)
        assert isinstance(result, bool)


class TestIntegration:

    @pytest.mark.asyncio
    async def test_stt_tts_round_trip(self):
        stt = SpeechToText(model_name="tiny", device="cpu", prefer_cloud=False)
        tts = TextToSpeech()

        audio = np.zeros(16000, dtype=np.float32)
        result = await stt.transcribe(audio)
        assert isinstance(result, STTResult)

        text = result.text if result.text.strip() else "Hello"
        output = await tts.synthesize(text)
        assert isinstance(output, np.ndarray)
        assert len(output) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
