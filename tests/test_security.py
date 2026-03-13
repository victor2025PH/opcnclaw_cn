"""Tests for Phase 12: Security & IoT bridge features."""

import time
import pytest


class TestSlidingWindowLimiter:
    """Test the sliding-window rate limiter."""

    def test_basic_allow_and_deny(self):
        from src.server.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(default_limit=3, window_seconds=60)
        assert limiter.allow("user:a") is True
        assert limiter.allow("user:a") is True
        assert limiter.allow("user:a") is True
        assert limiter.allow("user:a") is False

    def test_different_keys_independent(self):
        from src.server.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(default_limit=2, window_seconds=60)
        assert limiter.allow("user:a") is True
        assert limiter.allow("user:a") is True
        assert limiter.allow("user:a") is False
        assert limiter.allow("user:b") is True

    def test_remaining_count(self):
        from src.server.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(default_limit=5, window_seconds=60)
        assert limiter.remaining("x") == 5
        limiter.allow("x")
        limiter.allow("x")
        assert limiter.remaining("x") == 3

    def test_custom_limit_per_key(self):
        from src.server.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(default_limit=10, window_seconds=60)
        limiter.set_limit("vip", 2)
        assert limiter.allow("vip") is True
        assert limiter.allow("vip") is True
        assert limiter.allow("vip") is False
        # Default-limit key still has plenty
        assert limiter.allow("normal") is True

    def test_cleanup_removes_stale(self):
        from src.server.auth import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(default_limit=10, window_seconds=0.01)
        limiter.allow("old")
        time.sleep(0.05)
        limiter.cleanup(max_idle=0.02)
        assert "old" not in limiter._windows


class TestSecretsStore:
    """Test config value encryption/decryption."""

    def test_encrypt_decrypt_round_trip(self):
        from src.server.secrets_store import encrypt_value, decrypt_value
        original = "sk-test-api-key-12345"
        encrypted = encrypt_value(original)
        assert encrypted.startswith("ENC:") or encrypted == original
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_empty_string_passthrough(self):
        from src.server.secrets_store import encrypt_value, decrypt_value
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_already_encrypted_not_double_encrypted(self):
        from src.server.secrets_store import encrypt_value, decrypt_value
        original = "my-secret"
        enc = encrypt_value(original)
        enc2 = encrypt_value(enc)
        assert enc == enc2

    def test_is_encrypted(self):
        from src.server.secrets_store import is_encrypted
        assert is_encrypted("ENC:abc123") is True
        assert is_encrypted("plaintext") is False
        assert is_encrypted("") is False

    def test_protect_config(self, tmp_path):
        import configparser
        from src.server.secrets_store import protect_config, decrypt_value

        cfg_path = tmp_path / "config.ini"
        cfg = configparser.ConfigParser()
        cfg.add_section("bridge.wechat_mp")
        cfg.set("bridge.wechat_mp", "app_secret", "wx-secret-value")
        cfg.set("bridge.wechat_mp", "app_id", "wxid123")
        with open(str(cfg_path), "w") as f:
            cfg.write(f)

        count = protect_config(str(cfg_path))
        assert count >= 1

        cfg2 = configparser.ConfigParser()
        cfg2.read(str(cfg_path))
        raw = cfg2.get("bridge.wechat_mp", "app_secret")
        assert raw.startswith("ENC:") or raw == "wx-secret-value"
        assert decrypt_value(raw) == "wx-secret-value"
        # Non-sensitive keys remain plaintext
        assert cfg2.get("bridge.wechat_mp", "app_id") == "wxid123"


class TestHomeAssistantBridge:
    """Test HA bridge initialization and intent mapping."""

    def test_init_defaults(self):
        from src.bridge.homeassistant import HomeAssistantBridge
        bridge = HomeAssistantBridge()
        assert bridge.configured is False

    def test_init_with_params(self):
        from src.bridge.homeassistant import HomeAssistantBridge
        bridge = HomeAssistantBridge(url="http://ha.local:8123", token="test-token")
        assert bridge.configured is True
        assert bridge.url == "http://ha.local:8123"

    @pytest.mark.asyncio
    async def test_execute_intent_no_entity(self):
        from src.bridge.homeassistant import HomeAssistantBridge
        bridge = HomeAssistantBridge(url="http://ha.local:8123", token="t")
        result = await bridge.execute_intent("开")
        assert "请指定" in result

    @pytest.mark.asyncio
    async def test_execute_intent_unknown(self):
        from src.bridge.homeassistant import HomeAssistantBridge
        bridge = HomeAssistantBridge(url="http://ha.local:8123", token="t")
        result = await bridge.execute_intent("飞", "light.room")
        assert "未识别" in result


class TestTokenManagerSlidingWindow:
    """Verify TokenManager uses sliding window."""

    def test_check_rate_limit_uses_sliding(self):
        from src.server.auth import TokenManager, APIKey
        from datetime import datetime

        mgr = TokenManager()
        key = APIKey(
            key_id="test1", key_hash="h", name="t",
            created_at=datetime.now(), rate_limit_per_minute=2,
        )
        mgr._keys["test1"] = key

        assert mgr.check_rate_limit(key) is True
        assert mgr.check_rate_limit(key) is True
        assert mgr.check_rate_limit(key) is False

    def test_ip_rate_limit(self):
        from src.server.auth import TokenManager
        # IP limiter has a high default (120/min), so this should pass
        assert TokenManager.check_ip_rate_limit("192.168.1.100") is True
