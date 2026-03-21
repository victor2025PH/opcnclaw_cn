# -*- coding: utf-8 -*-
"""TTS 多语言自动切换测试"""

import pytest
from src.server.tts import TextToSpeech


@pytest.fixture
def tts():
    """创建 TTS 实例（不加载模型）"""
    t = TextToSpeech.__new__(TextToSpeech)
    t._edge_voice = "zh-CN-XiaoxiaoNeural"
    return t


class TestLanguageDetection:
    def test_chinese(self, tts):
        voice = tts._detect_voice_for_text("你好世界，今天天气怎么样")
        assert "zh-CN" in voice

    def test_english(self, tts):
        voice = tts._detect_voice_for_text("Hello world, how are you today")
        assert "en-US" in voice

    def test_japanese(self, tts):
        voice = tts._detect_voice_for_text("こんにちは、元気ですか")
        assert "ja-JP" in voice

    def test_korean(self, tts):
        voice = tts._detect_voice_for_text("안녕하세요 오늘 날씨가 좋네요")
        assert "ko-KR" in voice

    def test_mixed_zh_en(self, tts):
        """中英混合，中文多→中文声音"""
        voice = tts._detect_voice_for_text("今天的weather很好，适合出去play")
        assert "zh-CN" in voice

    def test_empty(self, tts):
        """空文本返回默认声音"""
        voice = tts._detect_voice_for_text("")
        assert voice == tts._edge_voice

    def test_short(self, tts):
        """极短文本返回默认"""
        voice = tts._detect_voice_for_text("hi")
        assert voice == tts._edge_voice

    def test_numbers_only(self, tts):
        """纯数字返回默认"""
        voice = tts._detect_voice_for_text("12345")
        assert voice == tts._edge_voice
