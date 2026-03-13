"""
Tests for new API routers: models, mcp, and emotion endpoints.

All tests run offline — no API keys, GPU, or network required.
"""

import json
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server.emotion import EmotionEngine, EmotionState
from src.server.model_downloader import get_models, get_gpu_info, get_disk_space
from src.mcp.skill_generator import generate_skill, delete_skill, list_user_skills


# ═══════════════════════════════════════════════════════════════
# Emotion Engine
# ═══════════════════════════════════════════════════════════════

class TestEmotionState:

    def test_default_neutral(self):
        state = EmotionState()
        assert state.current == "neutral"
        assert state.dominant == "neutral"
        assert state.history == []

    def test_update_tracks_history(self):
        state = EmotionState()
        state.update("happy")
        state.update("happy")
        assert state.current == "happy"
        assert len(state.history) == 2

    def test_dominant_uses_recent(self):
        state = EmotionState()
        for _ in range(3):
            state.update("sad")
        state.update("happy")
        assert state.dominant == "sad"

    def test_history_limit(self):
        state = EmotionState()
        for i in range(15):
            state.update("happy")
        assert len(state.history) <= 10


class TestEmotionEngine:

    def test_init(self):
        engine = EmotionEngine()
        assert engine.enabled is True
        assert engine.state.current == "neutral"

    def test_process_stt_result(self):
        engine = EmotionEngine()
        engine.process_stt_result("happy", ["laughter"])
        assert engine.state.current == "happy"
        assert engine.state.events == ["laughter"]

    def test_system_prompt_addon_neutral(self):
        engine = EmotionEngine()
        addon = engine.get_system_prompt_addon()
        assert addon == ""

    def test_system_prompt_addon_happy(self):
        engine = EmotionEngine()
        engine.process_stt_result("happy")
        addon = engine.get_system_prompt_addon()
        assert "愉悦" in addon or "轻松" in addon

    def test_tts_emotion_mapping(self):
        engine = EmotionEngine()
        engine.process_stt_result("sad")
        assert engine.get_tts_emotion() == "gentle"

    def test_event_response(self):
        engine = EmotionEngine()
        engine.process_stt_result("neutral", ["laughter"])
        resp = engine.get_event_response()
        assert resp is not None
        assert "心情" in resp

    def test_disabled_returns_empty(self):
        engine = EmotionEngine()
        engine.enabled = False
        engine.process_stt_result("angry", ["cough"])
        assert engine.get_system_prompt_addon() == ""
        assert engine.get_tts_emotion() == "neutral"
        assert engine.get_event_response() is None

    def test_build_messages(self):
        engine = EmotionEngine()
        engine.process_stt_result("sad")
        msgs = engine.build_messages("你是AI助手", "今天好累", [])
        assert len(msgs) >= 2
        assert "情感提示" in msgs[0]["content"]
        assert msgs[-1]["content"] == "今天好累"


# ═══════════════════════════════════════════════════════════════
# STTResult handling
# ═══════════════════════════════════════════════════════════════

class TestSTTResultCompat:
    """Verify STTResult is handled correctly (not stringified)."""

    def test_stt_result_has_text(self):
        from src.server.stt import STTResult
        r = STTResult(text="hello", emotion="happy", events=["laughter"])
        assert r.text == "hello"
        assert r.emotion == "happy"
        assert r.events == ["laughter"]

    def test_stt_result_default_neutral(self):
        from src.server.stt import STTResult
        r = STTResult(text="test")
        assert r.emotion == "neutral"
        assert r.events == []


# ═══════════════════════════════════════════════════════════════
# MCP Skill Generator
# ═══════════════════════════════════════════════════════════════

class TestSkillGenerator:

    def test_generate_and_delete(self, tmp_path, monkeypatch):
        import src.mcp.skill_generator as sg
        monkeypatch.setattr(sg, "USER_SKILLS_DIR", tmp_path / "user_skills")
        monkeypatch.setattr(sg, "SKILLS_ROOT", tmp_path)

        skill = generate_skill("帮我写日报", name="日报助手")
        assert skill["id"].startswith("user_")
        assert skill["name_zh"] == "日报助手"
        assert skill["type"] == "prompt"

        skills = list_user_skills()
        assert len(skills) == 1

        ok = delete_skill(skill["id"])
        assert ok is True
        assert len(list_user_skills()) == 0

    def test_generate_without_name(self, tmp_path, monkeypatch):
        import src.mcp.skill_generator as sg
        monkeypatch.setattr(sg, "USER_SKILLS_DIR", tmp_path / "user_skills")
        monkeypatch.setattr(sg, "SKILLS_ROOT", tmp_path)

        skill = generate_skill("翻译英文邮件为中文")
        assert skill["name_zh"]
        assert len(skill["trigger_words"]) > 0


# ═══════════════════════════════════════════════════════════════
# Model Downloader (getter functions only — no actual installs)
# ═══════════════════════════════════════════════════════════════

class TestModelDownloaderAPI:

    def test_models_list_not_empty(self):
        models = get_models()
        assert len(models) >= 5

    def test_gpu_info_shape(self):
        info = get_gpu_info()
        assert "available" in info
        assert isinstance(info["available"], bool)

    def test_disk_space_shape(self):
        info = get_disk_space()
        assert "free_gb" in info
        assert "total_gb" in info


# ═══════════════════════════════════════════════════════════════
# Health Checker (updated SSL path check)
# ═══════════════════════════════════════════════════════════════

class TestHealthSSLPaths:

    def test_ssl_checks_certs_dir(self, tmp_path):
        from src.server.health import HealthChecker
        hc = HealthChecker(base_dir=str(tmp_path))
        assert hc.check_ssl().ok is False

        (tmp_path / "certs").mkdir()
        (tmp_path / "certs" / "server.crt").write_text("fake")
        (tmp_path / "certs" / "server.key").write_text("fake")
        assert hc.check_ssl().ok is True
        assert "certs/" in hc.check_ssl().detail

    def test_ssl_checks_legacy_dir(self, tmp_path):
        from src.server.health import HealthChecker
        hc = HealthChecker(base_dir=str(tmp_path))

        (tmp_path / "ssl").mkdir()
        (tmp_path / "ssl" / "cert.pem").write_text("fake")
        (tmp_path / "ssl" / "key.pem").write_text("fake")
        assert hc.check_ssl().ok is True


# ═══════════════════════════════════════════════════════════════
# FastAPI Router Integration Tests (TestClient)
# ═══════════════════════════════════════════════════════════════

class TestModelsRouter:
    """Integration tests for /api/models endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from fastapi.testclient import TestClient
            self.TestClient = TestClient
        except ImportError:
            pytest.skip("fastapi not installed")

    def _make_app(self):
        from fastapi import FastAPI
        from src.server.routers.models import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_list_models(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/models")
        assert r.status_code == 200
        data = r.json()
        assert "models" in data
        assert "mode" in data
        assert len(data["models"]) >= 5
        for m in data["models"]:
            assert "id" in m
            assert "name" in m
            assert "installed" in m

    def test_models_summary(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/models/summary")
        assert r.status_code == 200
        data = r.json()
        assert "installed_count" in data
        assert "mode" in data

    def test_gpu_info(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/system/gpu")
        assert r.status_code == 200
        data = r.json()
        assert "available" in data

    def test_disk_info(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/system/disk")
        assert r.status_code == 200
        data = r.json()
        assert "free_gb" in data

    def test_health_check(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/system/health")
        assert r.status_code == 200
        data = r.json()
        assert "healthy" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_check_model_installed(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/models/sensevoice/check")
        assert r.status_code == 200
        data = r.json()
        assert data["model_id"] == "sensevoice"
        assert isinstance(data["installed"], bool)

    def test_s2s_status(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/s2s/status")
        assert r.status_code == 200
        data = r.json()
        assert "available" in data
        assert "backend" in data


class TestMCPRouter:
    """Integration tests for /api/mcp endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from fastapi.testclient import TestClient
            self.TestClient = TestClient
        except ImportError:
            pytest.skip("fastapi not installed")

    def _make_app(self):
        from fastapi import FastAPI
        from src.server.routers.mcp import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_list_servers_empty(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/mcp/servers")
        assert r.status_code == 200
        data = r.json()
        assert "servers" in data
        assert "count" in data

    def test_list_tools_empty(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/mcp/tools")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert data["count"] == 0

    def test_list_skills(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/mcp/skills")
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data

    def test_generate_and_delete_skill(self, tmp_path, monkeypatch):
        import src.mcp.skill_generator as sg
        monkeypatch.setattr(sg, "USER_SKILLS_DIR", tmp_path / "user_skills")
        monkeypatch.setattr(sg, "SKILLS_ROOT", tmp_path)

        client = self.TestClient(self._make_app())
        r = client.post("/api/mcp/skills/generate", json={
            "description": "帮我整理会议纪要",
            "name": "会议助手",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        skill_id = data["skill"]["id"]

        r2 = client.delete(f"/api/mcp/skills/{skill_id}")
        assert r2.status_code == 200
        assert r2.json()["ok"] is True


class TestVisionControlRouter:
    """Integration tests for /api/vision-control endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        try:
            from fastapi.testclient import TestClient
            self.TestClient = TestClient
        except ImportError:
            pytest.skip("fastapi not installed")

    def _make_app(self):
        from fastapi import FastAPI
        from src.server.routers.desktop import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_describe_screen(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/vision-control/describe")
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            assert "text" in r.json()

    def test_screen_state(self):
        client = self.TestClient(self._make_app())
        r = client.get("/api/vision-control/screen")
        assert r.status_code in (200, 503)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
