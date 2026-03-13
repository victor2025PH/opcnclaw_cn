"""Shared fixtures for OpenClaw tests."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Prevent tests from reading real .env or writing to project dirs."""
    monkeypatch.setenv("OPENCLAW_PORT", "18799")
    monkeypatch.chdir(tmp_path)
