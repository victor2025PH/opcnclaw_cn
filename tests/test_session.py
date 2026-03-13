"""
Tests for multi-user session isolation via memory.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.server.memory import (
    add_message, get_history, clear_history, list_sessions,
)


class TestSessionIsolation:

    def test_different_sessions_isolated(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test_mem.db")

        add_message("wechat:user_A", "user", "你好A")
        add_message("wechat:user_A", "assistant", "你好！我是A的助手")
        add_message("siri:user_B", "user", "你好B")
        add_message("siri:user_B", "assistant", "你好！我是B的助手")

        history_a = get_history("wechat:user_A", limit=10)
        history_b = get_history("siri:user_B", limit=10)

        assert len(history_a) == 2
        assert len(history_b) == 2
        assert "A" in history_a[0]["content"]
        assert "B" in history_b[0]["content"]

    def test_clear_one_session(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test_mem2.db")

        add_message("s1", "user", "msg1")
        add_message("s2", "user", "msg2")

        clear_history("s1")
        assert len(get_history("s1")) == 0
        assert len(get_history("s2")) == 1

    def test_list_sessions(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test_mem3.db")

        add_message("wechat:u1", "user", "hi")
        add_message("siri:u2", "user", "hello")
        add_message("web:default", "user", "hey")

        sessions = list_sessions()
        session_names = [s["session"] for s in sessions]
        assert "wechat:u1" in session_names
        assert "siri:u2" in session_names
        assert "web:default" in session_names

    def test_history_limit(self, tmp_path, monkeypatch):
        import src.server.memory as mem
        monkeypatch.setattr(mem, "DB_PATH", tmp_path / "test_mem4.db")

        for i in range(50):
            add_message("test", "user", f"msg {i}")

        history = get_history("test", limit=5)
        assert len(history) == 5
        assert "45" in history[0]["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
