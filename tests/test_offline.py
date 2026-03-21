# -*- coding: utf-8 -*-
"""离线模式管理器测试"""

import pytest
from src.server.offline_manager import OfflineManager, NetworkMode


@pytest.fixture
def manager():
    m = OfflineManager()
    # 不启动后台线程
    return m


class TestNetworkMode:
    def test_initial_state(self, manager):
        assert manager.mode == NetworkMode.ONLINE
        assert manager.is_online is True

    def test_status_dict(self, manager):
        s = manager.get_status()
        assert "online" in s
        assert "mode" in s
        assert "local_model" in s

    def test_mode_change_callback(self, manager):
        called = []
        manager.on_mode_change(lambda old, new: called.append((old.value, new.value)))
        manager._mode = NetworkMode.ONLINE
        manager._notify(NetworkMode.ONLINE, NetworkMode.LOCAL)
        assert len(called) == 1
        assert called[0] == ("online", "local")

    def test_mode_enum(self):
        assert NetworkMode.ONLINE.value == "online"
        assert NetworkMode.LOCAL.value == "local"
        assert NetworkMode.OFFLINE.value == "offline"
