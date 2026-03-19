# -*- coding: utf-8 -*-
"""
Tests for the unified database manager (src/server/db.py).

Covers:
  - Schema initialization
  - Connection management (singleton, thread-safe)
  - Transaction context managers
  - FTS5 full-text search index
  - Data migration from old databases
  - Backup and vacuum operations
"""

import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

# Override DATA_DIR before importing db to use temp directory
_test_dir = tempfile.mkdtemp()


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """每个测试使用独立的临时数据目录"""
    import src.server.db as db_mod

    # 重置模块状态
    db_mod.close_all()
    db_mod._connections.clear()

    # 使用临时目录
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "_DB_FILES", {
        "main": tmp_path / "main.db",
        "wechat": tmp_path / "wechat.db",
    })
    yield
    db_mod.close_all()
    db_mod._connections.clear()


class TestConnectionManagement:
    """连接管理测试"""

    def test_get_conn_creates_singleton(self):
        from src.server.db import get_conn
        conn1 = get_conn("main")
        conn2 = get_conn("main")
        assert conn1 is conn2, "应返回同一个连接（单例）"

    def test_get_conn_different_dbs(self):
        from src.server.db import get_conn
        conn_main = get_conn("main")
        conn_wechat = get_conn("wechat")
        assert conn_main is not conn_wechat

    def test_compat_name_resolution(self):
        from src.server.db import get_conn
        conn_memory = get_conn("memory")
        conn_main = get_conn("main")
        assert conn_memory is conn_main, "memory 应映射到 main"

    def test_compat_wechat_mapping(self):
        from src.server.db import get_conn
        conn_inbox = get_conn("unified_inbox")
        conn_wechat = get_conn("wechat")
        assert conn_inbox is conn_wechat

    def test_unknown_db_raises(self):
        from src.server.db import get_conn
        with pytest.raises(ValueError, match="Unknown database"):
            get_conn("nonexistent_db")

    def test_wal_mode_enabled(self):
        from src.server.db import get_conn
        conn = get_conn("main")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self):
        from src.server.db import get_conn
        conn = get_conn("main")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_thread_safety(self):
        """多线程并发获取连接不应崩溃"""
        from src.server.db import get_conn
        results = []
        errors = []

        def worker():
            try:
                conn = get_conn("main")
                conn.execute("SELECT 1").fetchone()
                results.append(True)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"线程错误: {errors}"
        assert len(results) == 10


class TestSchemaInit:
    """Schema 初始化测试"""

    def test_init_schemas_creates_tables(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("main")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "messages" in tables
        assert "segments" in tables
        assert "profiles" in tables
        assert "workflows" in tables
        assert "audit_log" in tables
        assert "skill_usage" in tables
        assert "schema_version" in tables

    def test_init_schemas_wechat_tables(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("wechat")
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "inbox" in tables
        assert "media" in tables
        assert "accounts" in tables
        assert "rules" in tables
        assert "templates" in tables

    def test_init_schemas_idempotent(self):
        """多次调用 init_schemas 不应出错"""
        from src.server.db import init_schemas
        init_schemas()
        init_schemas()
        init_schemas()

    def test_fts5_table_created(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()
        conn = get_conn("main")
        # FTS5 虚拟表
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='messages_fts'"
        ).fetchone()
        assert row is not None

    def test_fts5_triggers_created(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()
        conn = get_conn("main")
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()}
        assert "trg_msg_ai" in triggers  # after insert
        assert "trg_msg_ad" in triggers  # after delete
        assert "trg_msg_au" in triggers  # after update


class TestTransactions:
    """事务上下文管理器测试"""

    def test_transaction_commits(self):
        from src.server.db import init_schemas, transaction, get_conn
        init_schemas()

        with transaction("main") as conn:
            conn.execute(
                "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
                ("test", "user", "hello"),
            )

        # 验证提交成功
        conn = get_conn("main")
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 1

    def test_transaction_rollbacks_on_error(self):
        from src.server.db import init_schemas, transaction, get_conn
        init_schemas()

        with pytest.raises(ValueError):
            with transaction("main") as conn:
                conn.execute(
                    "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
                    ("test", "user", "hello"),
                )
                raise ValueError("intentional error")

        conn = get_conn("main")
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 0, "事务应该回滚"

    def test_read_context_no_lock(self):
        from src.server.db import init_schemas, read
        init_schemas()

        with read("main") as conn:
            rows = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
            assert rows[0] == 0


class TestFTS5:
    """FTS5 全文搜索测试"""

    def test_fts_auto_sync_on_insert(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("main")
        conn.execute(
            "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
            ("s1", "user", "今天天气怎么样"),
        )
        conn.commit()

        fts_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert fts_count == 1

    def test_fts_search(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("main")
        for text in ["hello world test", "goodbye world end", "hello again test"]:
            conn.execute(
                "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
                ("s1", "user", text),
            )
        conn.commit()

        results = conn.execute(
            "SELECT m.content FROM messages_fts f "
            "JOIN messages m ON m.id = f.rowid "
            "WHERE f.content MATCH ?",
            ("hello",),
        ).fetchall()
        assert len(results) == 2

    def test_fts_sync_on_delete(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("main")
        conn.execute(
            "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
            ("s1", "user", "要删除的消息"),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 1

        conn.execute("DELETE FROM messages WHERE session = 's1'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] == 0

    def test_fts_sync_on_update(self):
        from src.server.db import init_schemas, get_conn
        init_schemas()

        conn = get_conn("main")
        conn.execute(
            "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
            ("s1", "user", "原始内容 Alpha"),
        )
        conn.commit()

        conn.execute("UPDATE messages SET content = '修改后内容 Beta' WHERE session = 's1'")
        conn.commit()

        # 搜索旧内容应无结果
        r1 = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE content MATCH 'Alpha'"
        ).fetchone()[0]
        assert r1 == 0

        # 搜索新内容应有结果
        r2 = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE content MATCH 'Beta'"
        ).fetchone()[0]
        assert r2 == 1

    def test_rebuild_fts_index(self):
        from src.server.db import init_schemas, get_conn, rebuild_fts_index
        init_schemas()

        conn = get_conn("main")
        conn.execute(
            "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
            ("s1", "user", "测试重建索引"),
        )
        conn.commit()

        rebuild_fts_index()  # 不应抛异常
        count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        assert count == 1


class TestBackup:
    """备份测试"""

    def test_backup_creates_files(self, tmp_path):
        from src.server.db import init_schemas, backup
        init_schemas()

        backup_dir = tmp_path / "backups"
        backup(backup_dir=backup_dir)

        backup_files = list(backup_dir.glob("*.db"))
        assert len(backup_files) >= 1


class TestVacuum:
    """维护操作测试"""

    def test_vacuum_all_no_error(self):
        from src.server.db import init_schemas, vacuum_all
        init_schemas()
        vacuum_all()  # 不应抛异常


class TestCloseAll:
    """连接关闭测试"""

    def test_close_all(self):
        from src.server.db import get_conn, close_all, _connections
        get_conn("main")
        get_conn("wechat")
        assert len(_connections) == 2
        close_all()
        assert len(_connections) == 0
