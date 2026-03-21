# -*- coding: utf-8 -*-
"""微信增强功能测试

覆盖：
  - 消息类型检测（13种类型）
  - @检测（精确匹配+泛匹配+提取列表）
  - 群聊识别
  - 朋友圈数据模型
  - MomentsPage 分页
  - 意图融合→桌面自动执行桥接
"""

import os
import time
import pytest


class TestMsgTypeDetection:
    """消息类型检测测试（13种）"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.server.wechat_monitor import _detect_msg_type
        self.detect = _detect_msg_type

    def test_image(self):
        assert self.detect("[图片]") == "image"
        assert self.detect("[图片消息]") == "image"
        assert self.detect("[Photo]") == "image"

    def test_voice(self):
        assert self.detect("[语音]") == "voice"
        assert self.detect("[Voice]") == "voice"

    def test_file(self):
        assert self.detect("[文件]") == "file"
        assert self.detect("[File]") == "file"

    def test_video(self):
        assert self.detect("[视频]") == "video"
        assert self.detect("[Video]") == "video"
        assert self.detect("[小视频]") == "video"

    def test_sticker(self):
        assert self.detect("[动画表情]") == "sticker"
        assert self.detect("[Sticker]") == "sticker"

    def test_location(self):
        assert self.detect("[位置]") == "location"
        assert self.detect("[Location]") == "location"

    def test_contact_card(self):
        assert self.detect("[名片]") == "contact_card"
        assert self.detect("[Contact]") == "contact_card"

    def test_transfer_and_red_packet(self):
        assert self.detect("[转账]") == "transfer"
        assert self.detect("[红包]") == "red_packet"

    def test_link(self):
        assert self.detect("[链接]这是一个链接") == "link"
        assert self.detect("[Link]https://example.com") == "link"
        assert self.detect("看看这个 https://example.com/page") == "link"

    def test_miniprogram(self):
        assert self.detect("[小程序]美团外卖") == "miniprogram"
        assert self.detect("[MiniApp]滴滴出行") == "miniprogram"

    def test_quote(self):
        assert self.detect("[引用]张三:你好") == "quote"
        assert self.detect("[Reply]Hi there") == "quote"

    def test_channels_video(self):
        assert self.detect("[视频号]李四的视频") == "channels_video"

    def test_music(self):
        assert self.detect("[音乐]") == "music"
        assert self.detect("[Music]") == "music"

    def test_system(self):
        assert self.detect("[撤回了一条消息]") == "system"
        assert self.detect("[系统消息]") == "system"

    def test_plain_text(self):
        assert self.detect("你好啊") == "text"
        assert self.detect("Hello world") == "text"
        assert self.detect("") == "text"

    def test_long_bracket_content_is_system(self):
        """短 [] 内容判为 system，长内容也是 system（如果是 [xxx] 格式）"""
        short = "[撤回了一条消息]"
        assert self.detect(short) == "system"
        # 超过30字符的 [xxx] 不判为 system
        long = "[这是一段超过三十个字符的非常非常非常非常非常非常非常长的括号内容不应该被判断]"
        assert self.detect(long) == "text"


class TestAtDetection:
    """@检测测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.server.wechat_monitor import _check_at_me, _check_at_anyone, _MY_NICKNAME
        self.check_at_me = _check_at_me
        self.check_at_anyone = _check_at_anyone
        # 清除缓存的昵称
        import src.server.wechat_monitor as wm
        wm._MY_NICKNAME = ""

    def test_at_everyone(self):
        assert self.check_at_me("@所有人 开会了") is True

    def test_at_generic(self):
        """泛 @ 匹配"""
        assert self.check_at_me("@张三 你好") is True

    def test_no_at(self):
        assert self.check_at_me("你好") is False

    def test_at_my_nickname(self):
        """精确匹配我的昵称"""
        import src.server.wechat_monitor as wm
        os.environ["OPENCLAW_WECHAT_NICKNAME"] = "小龙虾"
        wm._MY_NICKNAME = ""  # 清除缓存强制重读

        assert self.check_at_me("@小龙虾 你好") is True
        assert self.check_at_me("@别人 你好") is True  # 回退泛匹配

        # 清理
        os.environ.pop("OPENCLAW_WECHAT_NICKNAME", None)
        wm._MY_NICKNAME = ""

    def test_extract_at_list(self):
        """提取所有被@的人"""
        names = self.check_at_anyone("@张三 @李四 你们好 @所有人")
        assert "所有人" in names
        assert "张三" in names
        assert "李四" in names

    def test_extract_at_empty(self):
        names = self.check_at_anyone("没有人被提到")
        assert names == []

    def test_extract_at_in_sentence(self):
        """句中 @ 应被提取"""
        names = self.check_at_anyone("没有@任何人")
        assert "任何人" in names  # @ 后的内容会被提取


class TestGroupDetection:
    """群聊识别测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.server.wechat_monitor import _is_group_name
        self.is_group = _is_group_name

    def test_group_with_number(self):
        assert self.is_group("工作群(12)") is True
        assert self.is_group("家庭群（5）") is True

    def test_long_name_is_group(self):
        assert self.is_group("我的超级无敌长名字群组") is True

    def test_personal_chat(self):
        assert self.is_group("张三") is False
        assert self.is_group("小明") is False


class TestMomentsModel:
    """朋友圈数据模型测试"""

    def test_moment_post_fingerprint(self):
        from src.server.wechat.moments_reader import MomentPost
        p = MomentPost(author="张三", text="今天天气不错", time_str="2小时前")
        fp = p.fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 32  # MD5 hex

    def test_moment_post_with_id(self):
        from src.server.wechat.moments_reader import MomentPost
        p = MomentPost(post_id="abc123", author="张三", text="test")
        assert p.fingerprint() == "abc123"

    def test_moments_page_defaults(self):
        from src.server.wechat.moments_reader import MomentsPage
        page = MomentsPage()
        assert page.has_more is True
        assert page.scroll_position == 0
        assert page.posts == []


class TestIntentAutoExecute:
    """Intent→Desktop 自动执行桥接测试"""

    def test_desktop_actions_defined(self):
        from src.server.intent_fusion import _DESKTOP_ACTIONS
        assert "click" in _DESKTOP_ACTIONS
        assert "confirm" in _DESKTOP_ACTIONS
        assert "scroll_up" in _DESKTOP_ACTIONS

    def test_auto_execute_threshold(self):
        from src.server.intent_fusion import _AUTO_EXECUTE_THRESHOLD
        assert _AUTO_EXECUTE_THRESHOLD >= 0.5
        assert _AUTO_EXECUTE_THRESHOLD <= 1.0

    def test_low_confidence_skipped(self):
        """低置信度不触发自动执行"""
        from src.server.intent_fusion import _auto_execute_intent, FusedIntent, Signal
        sig = Signal(channel="voice", name="yes", confidence=0.3)
        intent = FusedIntent(
            intent="confirm", confidence=0.3,
            priority=10, sources=[sig],
        )
        # 不应崩溃，应静默跳过
        _auto_execute_intent(intent)

    def test_non_desktop_action_skipped(self):
        """非桌面动作不触发"""
        from src.server.intent_fusion import _auto_execute_intent, FusedIntent, Signal
        sig = Signal(channel="voice", name="open_wechat", confidence=0.9)
        intent = FusedIntent(
            intent="open_wechat", confidence=0.9,
            priority=10, sources=[sig],
        )
        _auto_execute_intent(intent)  # 不应崩溃


class TestIntentFusionBridgeStats:
    """融合引擎统计测试"""

    def test_engine_stats_keys(self):
        from src.server.intent_fusion import IntentFusionEngine
        e = IntentFusionEngine()
        assert "signals_received" in e._stats
        assert "fusions_performed" in e._stats
        assert "emergency_stops" in e._stats
        assert "cross_modal_boosts" in e._stats
