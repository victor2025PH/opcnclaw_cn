"""Tests for Phase 13: Smart features — IoT, TTS emotion, memory, offline skills."""

import pytest
import time


class TestIoTIntentParser:
    """Test natural language → IoT intent parsing."""

    def test_turn_on_chinese(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("打开客厅灯")
        assert intent is not None
        assert intent["action"] == "turn_on"
        assert "living_room" in intent["entity_id"]

    def test_turn_off_chinese(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("关闭卧室灯")
        assert intent is not None
        assert intent["action"] == "turn_off"
        assert "bedroom" in intent["entity_id"]

    def test_set_value(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("把空调调到26")
        assert intent is not None
        assert intent["action"] == "set"
        assert intent["value"] == 26

    def test_status_query(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("客厅灯什么状态")
        assert intent is not None
        assert intent["action"] == "status"

    def test_non_iot_text(self):
        from src.server.iot_intent import parse_intent
        assert parse_intent("今天天气怎么样") is None
        assert parse_intent("给我讲个故事") is None

    def test_is_iot_intent(self):
        from src.server.iot_intent import is_iot_intent
        assert is_iot_intent("打开客厅灯") is True
        assert is_iot_intent("今天天气怎么样") is False

    def test_english_intent(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("turn on the living room")
        assert intent is not None
        assert intent["action"] == "turn_on"

    def test_update_aliases(self):
        from src.server.iot_intent import update_aliases_from_ha, _DEVICE_ALIASES
        update_aliases_from_ha([
            {"entity_id": "light.custom_room", "attributes": {"friendly_name": "自定义灯"}},
        ])
        assert _DEVICE_ALIASES.get("自定义灯") == "light.custom_room"

    def test_scene_intent(self):
        from src.server.iot_intent import parse_intent
        intent = parse_intent("激活场景回家模式")
        assert intent is not None
        assert intent["action"] == "scene"


class TestTTSEmotionDetection:

    def test_detect_happy(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts.emotion = "neutral"
        assert tts.detect_emotion("太好了！恭喜你完成了！") == "happy"

    def test_detect_sad(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts.emotion = "neutral"
        assert tts.detect_emotion("很抱歉听到这个消息") == "sad"

    def test_detect_neutral(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts.emotion = "neutral"
        assert tts.detect_emotion("今天是周三") == "neutral"

    def test_detect_gentle(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts.emotion = "neutral"
        assert tts.detect_emotion("别担心，慢慢来就好") == "gentle"

    def test_ssml_wrap(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts._edge_voice = "zh-CN-XiaoxiaoNeural"
        ssml = tts._wrap_ssml("你好世界", "happy")
        assert "<prosody" in ssml
        assert "rate" in ssml
        assert 'zh-CN-XiaoxiaoNeural' in ssml

    def test_ssml_neutral_no_wrap(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts._edge_voice = "zh-CN-XiaoxiaoNeural"
        result = tts._wrap_ssml("你好", "neutral")
        assert result == "你好"

    def test_ssml_escapes_xml(self):
        from src.server.tts import TextToSpeech
        tts = TextToSpeech.__new__(TextToSpeech)
        tts._edge_voice = "zh-CN-XiaoxiaoNeural"
        ssml = tts._wrap_ssml("A < B & C > D", "happy")
        assert "&lt;" in ssml
        assert "&amp;" in ssml


class TestOfflineSkills:

    def test_time_query(self):
        from src.server.offline_skills import process
        result = process("现在几点了")
        assert result is not None
        assert result[0] == "时间查询"
        assert "年" in result[1]

    def test_calculator(self):
        from src.server.offline_skills import process
        result = process("计算 2 + 3 * 4")
        assert result is not None
        assert result[0] == "计算器"
        assert "14" in result[1]

    def test_bare_expression(self):
        from src.server.offline_skills import process
        result = process("100 / 4")
        assert result is not None
        assert "25" in result[1]

    def test_unit_conversion_km(self):
        from src.server.offline_skills import process
        result = process("10公里转换为英里")
        assert result is not None
        assert result[0] == "单位换算"
        assert "6.21" in result[1]

    def test_unit_conversion_celsius(self):
        from src.server.offline_skills import process
        result = process("36摄氏转换华氏")
        assert result is not None
        assert "96.8" in result[1]

    def test_date_calc(self):
        from src.server.offline_skills import process
        result = process("30天后是几号")
        assert result is not None
        assert result[0] == "日期计算"
        assert "星期" in result[1]

    def test_timer(self):
        from src.server.offline_skills import process
        result = process("定时5分钟")
        assert result is not None
        assert result[0] == "定时器"
        assert "[timer:300]" in result[1]

    def test_no_match(self):
        from src.server.offline_skills import process
        assert process("给我讲个笑话") is None
        assert process("帮我写一封邮件") is None

    def test_math_functions(self):
        from src.server.offline_skills import process
        result = process("计算 sqrt(144)")
        assert result is not None
        assert "12" in result[1]


class TestMemoryCompact:

    def test_message_count(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test.db")
        mem.add_message("test_compact", "user", "hello")
        mem.add_message("test_compact", "assistant", "hi there")
        assert mem.message_count("test_compact") == 2

    def test_compact_below_threshold(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test.db")
        mem.add_message("test_below", "user", "hello")
        removed = mem.compact_history("test_below", "summary text", keep_recent=5)
        assert removed == 0

    def test_fallback_summary(self):
        from src.server.memory import _fallback_summary
        msgs = [
            {"role": "user", "content": "今天天气怎么样"},
            {"role": "assistant", "content": "今天晴天"},
            {"role": "user", "content": "推荐一家餐厅"},
        ]
        summary = _fallback_summary(msgs)
        assert "天气" in summary
        assert "餐厅" in summary

    def test_compact_removes_old(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test.db")
        for i in range(25):
            mem.add_message("test_compact2", "user", f"msg {i}")
            mem.add_message("test_compact2", "assistant", f"reply {i}")

        assert mem.message_count("test_compact2") == 50
        removed = mem.compact_history("test_compact2", "old summary", keep_recent=10)
        assert removed > 0
        remaining = mem.message_count("test_compact2")
        assert remaining <= 11  # 10 kept + 1 summary


class TestVoiceList:

    def test_edge_voices_populated(self):
        from src.server.main import EDGE_VOICES
        assert len(EDGE_VOICES) >= 10
        for v in EDGE_VOICES:
            assert "id" in v
            assert "name" in v
            assert "lang" in v
