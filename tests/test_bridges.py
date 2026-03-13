"""
Tests for IM bridge modules (WeChat MP, Siri, Feishu, etc.)
"""

import pytest
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bridge.wechat_mp import WeChatMPBridge
from src.bridge.siri import SiriBridge


class TestWeChatMPBridge:

    def _make_bridge(self):
        return WeChatMPBridge(
            app_id="wx_test_id",
            app_secret="test_secret",
            token="test_token_123",
            encoding_aes_key="",
        )

    def test_init(self):
        bridge = self._make_bridge()
        assert bridge.app_id == "wx_test_id"
        assert bridge.token == "test_token_123"

    def test_verify_signature_valid(self):
        bridge = self._make_bridge()
        import hashlib
        timestamp = "1234567890"
        nonce = "nonce123"
        items = sorted([bridge.token, timestamp, nonce])
        expected = hashlib.sha1("".join(items).encode()).hexdigest()
        assert bridge.verify_signature(expected, timestamp, nonce) is True

    def test_verify_signature_invalid(self):
        bridge = self._make_bridge()
        assert bridge.verify_signature("invalid", "123", "abc") is False

    def test_parse_text_message(self):
        xml = (
            "<xml>"
            "<ToUserName><![CDATA[gh_test]]></ToUserName>"
            "<FromUserName><![CDATA[user_openid]]></FromUserName>"
            "<CreateTime>1348831860</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[你好]]></Content>"
            "<MsgId>1234567890</MsgId>"
            "</xml>"
        )
        msg = WeChatMPBridge.parse_message(xml)
        assert msg["msg_type"] == "text"
        assert msg["content"] == "你好"
        assert msg["from_user"] == "user_openid"
        assert msg["to_user"] == "gh_test"

    def test_parse_voice_message(self):
        xml = (
            "<xml>"
            "<ToUserName><![CDATA[gh_test]]></ToUserName>"
            "<FromUserName><![CDATA[user_openid]]></FromUserName>"
            "<CreateTime>1348831860</CreateTime>"
            "<MsgType><![CDATA[voice]]></MsgType>"
            "<MediaId><![CDATA[media_id_123]]></MediaId>"
            "<Format><![CDATA[amr]]></Format>"
            "<Recognition><![CDATA[识别的文字]]></Recognition>"
            "<MsgId>1234567890</MsgId>"
            "</xml>"
        )
        msg = WeChatMPBridge.parse_message(xml)
        assert msg["msg_type"] == "voice"
        assert msg["recognition"] == "识别的文字"
        assert msg["media_id"] == "media_id_123"

    def test_parse_subscribe_event(self):
        xml = (
            "<xml>"
            "<ToUserName><![CDATA[gh_test]]></ToUserName>"
            "<FromUserName><![CDATA[user_openid]]></FromUserName>"
            "<CreateTime>1348831860</CreateTime>"
            "<MsgType><![CDATA[event]]></MsgType>"
            "<Event><![CDATA[subscribe]]></Event>"
            "</xml>"
        )
        msg = WeChatMPBridge.parse_message(xml)
        assert msg["msg_type"] == "event"
        assert msg["event"] == "subscribe"

    def test_parse_invalid_xml(self):
        msg = WeChatMPBridge.parse_message("not xml at all <><")
        assert msg == {}

    def test_build_text_reply(self):
        reply = WeChatMPBridge.build_text_reply("user1", "gh_test", "回复内容")
        assert "<ToUserName><![CDATA[user1]]>" in reply
        assert "<FromUserName><![CDATA[gh_test]]>" in reply
        assert "<MsgType><![CDATA[text]]>" in reply
        assert "<Content><![CDATA[回复内容]]>" in reply

    def test_build_voice_reply(self):
        reply = WeChatMPBridge.build_voice_reply("user1", "gh_test", "media_123")
        assert "<MsgType><![CDATA[voice]]>" in reply
        assert "<MediaId><![CDATA[media_123]]>" in reply


class TestWeChatMPBridgeAES:

    def _make_bridge_aes(self):
        import base64, os
        raw_key = os.urandom(32)
        aes_key_b64 = base64.b64encode(raw_key).decode("utf-8").rstrip("=")
        return WeChatMPBridge(
            app_id="wx_test_aes",
            app_secret="test_secret",
            token="test_token_aes",
            encoding_aes_key=aes_key_b64,
        )

    def test_encrypt_decrypt_round_trip(self):
        bridge = self._make_bridge_aes()
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher
        except ImportError:
            pytest.skip("cryptography not installed")

        original_xml = (
            "<xml><ToUserName><![CDATA[user1]]></ToUserName>"
            "<Content><![CDATA[你好]]></Content></xml>"
        )
        nonce = "test_nonce"
        encrypted_xml = bridge.encrypt_message(original_xml, nonce)
        assert encrypted_xml is not None
        assert "<Encrypt>" in encrypted_xml

        import xml.etree.ElementTree as ET
        root = ET.fromstring(encrypted_xml)
        encrypt_content = root.findtext("Encrypt", "")
        msg_sig = root.findtext("MsgSignature", "")
        timestamp = root.findtext("TimeStamp", "")
        enc_nonce = root.findtext("Nonce", "")

        decrypted = bridge.decrypt_message(
            encrypt_content, msg_sig, timestamp, enc_nonce)
        assert decrypted is not None
        assert "你好" in decrypted

    def test_decrypt_without_key(self):
        bridge = WeChatMPBridge(
            app_id="wx_test_id",
            app_secret="test_secret",
            token="test_token_123",
            encoding_aes_key="",
        )
        result = bridge.decrypt_message("enc", "sig", "ts", "nonce")
        assert result is None

    def test_decrypt_bad_signature(self):
        bridge = self._make_bridge_aes()
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher
        except ImportError:
            pytest.skip("cryptography not installed")
        result = bridge.decrypt_message("bad_base64", "wrong_sig", "123", "n")
        assert result is None


class TestSiriBridge:

    def test_init_default(self):
        siri = SiriBridge()
        assert siri.enabled is True
        assert siri.api_token == ""

    def test_verify_token_no_token(self):
        siri = SiriBridge(api_token="")
        assert siri.verify_token("anything") is True
        assert siri.verify_token("") is True

    def test_verify_token_with_token(self):
        siri = SiriBridge(api_token="secret123")
        assert siri.verify_token("secret123") is True
        assert siri.verify_token("wrong") is False
        assert siri.verify_token("") is False

    def test_build_shortcut_config(self):
        config = SiriBridge.build_shortcut_config("192.168.1.10", 8766, "tok")
        assert config["name"] == "OpenClaw AI 助手"
        assert "192.168.1.10" in config["api_url"]
        assert "8766" in config["api_url"]
        assert "Bearer tok" in config["headers"]["Authorization"]
        assert isinstance(config["setup_steps"], list)
        assert len(config["setup_steps"]) > 0

    def test_build_shortcut_config_no_token(self):
        config = SiriBridge.build_shortcut_config("10.0.0.1", 9999)
        assert "Authorization" not in config["headers"]

    def test_build_shortcut_url(self):
        url = SiriBridge.build_shortcut_url("192.168.1.1", 8766)
        assert "shortcut.html" in url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
