"""
Tests for model download manager.
"""

import json
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.server.model_downloader import (
    AVAILABLE_MODELS,
    ModelInfo,
    get_models,
    get_gpu_info,
    get_disk_space,
    get_installed_summary,
    get_install_mode,
    _load_status,
    _save_status,
)


class TestModelInfo:

    def test_available_models_not_empty(self):
        assert len(AVAILABLE_MODELS) > 0

    def test_all_models_have_required_fields(self):
        for m in AVAILABLE_MODELS:
            assert isinstance(m.id, str) and m.id
            assert isinstance(m.name, str) and m.name
            assert isinstance(m.description, str)
            assert isinstance(m.size_mb, int) and m.size_mb > 0
            assert isinstance(m.pip_packages, list) and len(m.pip_packages) > 0
            assert isinstance(m.category, str) and m.category

    def test_unique_ids(self):
        ids = [m.id for m in AVAILABLE_MODELS]
        assert len(ids) == len(set(ids)), "Duplicate model IDs found"

    def test_categories_valid(self):
        valid = {"stt", "runtime", "vad", "vision"}
        for m in AVAILABLE_MODELS:
            assert m.category in valid, f"Invalid category: {m.category}"


class TestStatusPersistence:

    def test_save_and_load(self, tmp_path, monkeypatch):
        status_file = tmp_path / "status.json"
        import src.server.model_downloader as md
        monkeypatch.setattr(md, "STATUS_FILE", status_file)

        data = {"torch-cpu": {"installed": True, "installed_at": "2026-01-01"}}
        _save_status(data)
        loaded = _load_status()
        assert loaded["torch-cpu"]["installed"] is True

    def test_load_missing_file(self, tmp_path, monkeypatch):
        import src.server.model_downloader as md
        monkeypatch.setattr(md, "STATUS_FILE", tmp_path / "nonexistent.json")
        result = _load_status()
        assert result == {}


class TestGetters:

    def test_get_models_returns_list(self):
        models = get_models()
        assert isinstance(models, list)
        assert all(isinstance(m, ModelInfo) for m in models)

    def test_get_gpu_info_returns_dict(self):
        info = get_gpu_info()
        assert isinstance(info, dict)
        assert "available" in info
        assert isinstance(info["available"], bool)

    def test_get_disk_space_returns_dict(self):
        info = get_disk_space()
        assert isinstance(info, dict)
        assert "free_gb" in info
        assert "total_gb" in info
        assert info["free_gb"] >= 0

    def test_get_installed_summary(self):
        summary = get_installed_summary()
        assert isinstance(summary, dict)
        assert "installed_count" in summary
        assert "total_count" in summary
        assert "installed_size_mb" in summary
        assert "mode" in summary
        assert summary["mode"] in ("minimal", "full")

    def test_get_install_mode_default(self):
        mode = get_install_mode()
        assert mode in ("minimal", "full")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
