# -*- coding: utf-8 -*-
"""
Tests for CoworkBus, HumanDetector, and ActionJournal.
"""

import time
import threading
import pytest


class TestHumanDetector:
    """人体活动检测器测试"""

    def test_import(self):
        from src.server.human_detector import HumanDetector
        d = HumanDetector()
        assert d.state.idle_ms == 0

    def test_state_default(self):
        from src.server.human_detector import HumanState
        s = HumanState()
        assert s.is_active == False
        assert s.is_typing == False
        assert s.active_window == ""

    def test_to_dict(self):
        from src.server.human_detector import HumanState
        s = HumanState(idle_ms=500, is_active=True, mouse_x=100)
        d = s.to_dict()
        assert d["idle_ms"] == 500
        assert d["is_active"] == True
        assert d["mouse_x"] == 100

    def test_singleton(self):
        from src.server.human_detector import get_detector
        d1 = get_detector()
        d2 = get_detector()
        assert d1 is d2

    def test_gaze_update(self):
        from src.server.human_detector import get_detector
        d = get_detector()
        d.update_gaze("top-left")
        assert d.state.gaze_zone == "top-left"


class TestActionJournal:
    """操作日志测试"""

    def test_record(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        entry = j.record("click", {"x": 100, "y": 200})
        assert entry.action == "click"
        assert entry.id  # 非空
        assert len(j._entries) == 1

    def test_auto_describe(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        e1 = j.record("click", {"x": 0.5, "y": 0.3})
        assert "点击" in e1.description

        e2 = j.record("type", {"text": "hello world"})
        assert "输入" in e2.description

        e3 = j.record("hotkey", {"keys": ["ctrl", "c"]})
        assert "快捷键" in e3.description

    def test_max_entries(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        j.MAX_ENTRIES = 5
        for i in range(10):
            j.record("click", {"x": i})
        assert len(j._entries) == 5

    def test_get_recent(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        j.record("click", {"x": 1})
        j.record("type", {"text": "hi"})
        recent = j.get_recent(limit=10)
        assert len(recent) == 2
        assert recent[0]["action"] == "click"

    def test_undo_last(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        j.record("type", {"text": "abc"})
        # undo_last 会尝试按 backspace，在测试中会失败
        # 但逻辑本身应该标记 undone=True
        result = j.undo_last()
        assert result is not None
        assert result["undone"] == True

    def test_undo_empty(self):
        from src.server.action_journal import ActionJournal
        j = ActionJournal()
        result = j.undo_last()
        assert result is None

    def test_singleton(self):
        from src.server.action_journal import get_journal
        j1 = get_journal()
        j2 = get_journal()
        assert j1 is j2


class TestCoworkBus:
    """协作调度器测试"""

    def test_import(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        assert bus.is_paused == False

    def test_pause_resume(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        bus.pause()
        assert bus.is_paused == True
        assert bus.can_operate_desktop() == False
        bus.resume()
        assert bus.is_paused == False

    def test_add_task(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        task = bus.add_task("t1", "test task", priority=3)
        assert task.status == "pending"
        assert task.priority == 3
        tasks = bus.get_tasks()
        assert len(tasks) == 1

    def test_task_priority_sort(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        bus.add_task("low", "low priority", priority=10)
        bus.add_task("high", "high priority", priority=1)
        tasks = bus.get_tasks()
        assert tasks[0]["id"] == "high"

    def test_get_status(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        status = bus.get_status()
        assert "human_zone" in status
        assert "ai_zone" in status
        assert "can_operate_desktop" in status

    def test_window_conflict_no_detector(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        # 没有 detector 时不会冲突
        assert bus.check_window_conflict("notepad") == False

    def test_paused_blocks_desktop(self):
        from src.server.cowork_bus import CoworkBus
        bus = CoworkBus()
        assert bus.can_operate_desktop() == True
        bus.pause()
        assert bus.can_operate_desktop() == False
