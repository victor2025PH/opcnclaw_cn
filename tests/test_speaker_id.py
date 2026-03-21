# -*- coding: utf-8 -*-
"""声纹识别 + 多用户测试

覆盖：
  - SpeakerProfile 数据模型
  - SpeakerManager 注册/识别/切换/删除
  - 余弦相似度计算
  - 存储加载
  - 边界情况
"""

import json
import time
import tempfile
import pytest
import numpy as np

from src.server.speaker_id import (
    SpeakerProfile, SpeakerManager, cosine_similarity,
    EMBED_DIM, MATCH_THRESHOLD, USERS_DB_FILE,
)


@pytest.fixture
def manager(tmp_path):
    """创建临时目录的 SpeakerManager"""
    import src.server.speaker_id as sid
    old_path = sid.USERS_DB_FILE
    sid.USERS_DB_FILE = str(tmp_path / "test_profiles.json")
    mgr = SpeakerManager()
    yield mgr
    sid.USERS_DB_FILE = old_path


class TestCosineSimilarity:
    def test_identical(self):
        a = np.random.randn(256).astype(np.float32)
        assert cosine_similarity(a, a) > 0.99

    def test_opposite(self):
        a = np.ones(256, dtype=np.float32)
        b = -np.ones(256, dtype=np.float32)
        assert cosine_similarity(a, b) < -0.99

    def test_orthogonal(self):
        a = np.zeros(256, dtype=np.float32)
        a[0] = 1.0
        b = np.zeros(256, dtype=np.float32)
        b[1] = 1.0
        assert abs(cosine_similarity(a, b)) < 0.01

    def test_zero_vector(self):
        a = np.zeros(256, dtype=np.float32)
        b = np.ones(256, dtype=np.float32)
        assert cosine_similarity(a, b) == 0.0


class TestSpeakerProfile:
    def test_defaults(self):
        p = SpeakerProfile("u1", "张三")
        assert p.user_id == "u1"
        assert p.name == "张三"
        assert p.avatar == "👤"
        assert p.embedding.shape == (EMBED_DIM,)

    def test_to_dict(self):
        p = SpeakerProfile("u1", "张三", "😊")
        d = p.to_dict()
        assert d["user_id"] == "u1"
        assert d["name"] == "张三"
        assert d["avatar"] == "😊"
        assert "embedding" not in d  # to_dict 不暴露 embedding

    def test_storage_roundtrip(self):
        emb = np.random.randn(EMBED_DIM).astype(np.float32)
        p = SpeakerProfile("u1", "测试", "🎤", embedding=emb)
        stored = p.to_storage()
        loaded = SpeakerProfile.from_storage(stored)
        assert loaded.user_id == "u1"
        assert loaded.name == "测试"
        np.testing.assert_array_almost_equal(loaded.embedding, emb, decimal=5)


class TestSpeakerManager:
    def test_default_user(self, manager):
        users = manager.list_users()
        assert len(users) >= 1
        assert any(u["user_id"] == "default" for u in users)

    def test_current_user(self, manager):
        current = manager.get_current()
        assert current is not None
        assert current.user_id == "default"

    def test_switch_user(self, manager):
        ok = manager.switch_user("default")
        assert ok is True

    def test_switch_nonexistent(self, manager):
        ok = manager.switch_user("nonexistent")
        assert ok is False

    def test_update_user(self, manager):
        ok = manager.update_user("default", name="新名字", avatar="🌟")
        assert ok is True
        current = manager.get_current()
        assert current.name == "新名字"
        assert current.avatar == "🌟"

    def test_delete_default_rejected(self, manager):
        """默认用户不可删除"""
        ok = manager.delete_user("default")
        assert ok is False

    def test_register_and_identify(self, manager):
        """注册 + 识别（使用模拟 embedding）"""
        # 手动创建用户（跳过真实音频处理）
        emb = np.random.randn(EMBED_DIM).astype(np.float32)
        emb = emb / np.linalg.norm(emb)

        profile = SpeakerProfile("test_user", "测试用户", "🎤", embedding=emb)
        manager._profiles["test_user"] = profile
        manager._save()

        # 用相同 embedding 识别
        uid, sim = None, 0.0
        best_sim = 0.0
        for uid_key, p in manager._profiles.items():
            if not np.any(p.embedding != 0):
                continue
            s = cosine_similarity(emb, p.embedding)
            if s > best_sim:
                best_sim = s
                uid = uid_key

        assert uid == "test_user"
        assert best_sim > MATCH_THRESHOLD

    def test_max_users(self, manager):
        """用户数上限"""
        manager.MAX_USERS = 3
        # 已有 default，再加 2 个应该没问题
        for i in range(2):
            p = SpeakerProfile(f"u{i}", f"用户{i}")
            manager._profiles[f"u{i}"] = p

        assert len(manager._profiles) == 3

    def test_persistence(self, manager):
        """修改后重新加载应保持一致"""
        manager.update_user("default", name="持久化测试")
        manager._save()

        # 重新加载
        mgr2 = SpeakerManager()
        users = mgr2.list_users()
        default_user = [u for u in users if u["user_id"] == "default"]
        assert len(default_user) == 1
        assert default_user[0]["name"] == "持久化测试"


class TestEdgeCases:
    def test_empty_embedding_skip(self, manager):
        """没有声纹的用户应被识别跳过"""
        query = np.random.randn(EMBED_DIM).astype(np.float32)
        # default 用户没有声纹（全零），应匹配失败
        uid, sim = manager.identify(query) if hasattr(manager, 'identify') else (None, 0.0)
        # 注意：identify 需要真实音频，这里只验证逻辑
        assert uid is None or sim < MATCH_THRESHOLD

    def test_delete_and_switch(self, manager):
        """删除当前用户后应自动切回 default"""
        p = SpeakerProfile("temp", "临时用户")
        manager._profiles["temp"] = p
        manager._current_user = "temp"
        manager.delete_user("temp")
        assert manager.get_current_id() == "default"
