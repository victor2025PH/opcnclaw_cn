# -*- coding: utf-8 -*-
"""
统一数据库管理器

将 13 个独立 SQLite 数据库合并为 2 个：
  - main.db    : 对话记忆、长期记忆、知识库、工作流、审计、事件、统计、情感、档案
  - wechat.db  : 统一收件箱、媒体库、联系人融合、联系人画像、群发、朋友圈分析

设计原则：
  - 每个数据库一个单例连接（SQLite WAL 模式下足够）
  - threading.Lock 保护写操作
  - 支持 schema 版本管理和自动迁移
  - 向后兼容：旧模块可通过 get_conn("memory") 获取 main.db 连接
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

DATA_DIR = Path("data")

# ── 数据库映射 ──────────────────────────────────────────────────────

# 物理数据库文件
_DB_FILES = {
    "main": DATA_DIR / "main.db",
    "wechat": DATA_DIR / "wechat.db",
}

# 旧逻辑名 → 新物理库（向后兼容）
_COMPAT_MAP = {
    "memory": "main",
    "long_memory": "main",
    "knowledge_base": "main",
    "workflows": "main",
    "audit": "main",
    "events": "main",
    "stats": "main",
    "sentiment": "main",
    "accounts": "wechat",
    "unified_inbox": "wechat",
    "media": "wechat",
    "contact_fusion": "wechat",
    "contact_profiles": "wechat",
    "broadcast": "wechat",
    "moments_analytics": "wechat",
}

# ── 连接池（单例） ──────────────────────────────────────────────────

_connections: Dict[str, sqlite3.Connection] = {}
_locks: Dict[str, threading.Lock] = {
    "main": threading.Lock(),
    "wechat": threading.Lock(),
}
_global_lock = threading.Lock()


def _resolve_name(name: str) -> str:
    """将逻辑名解析为物理库名"""
    return _COMPAT_MAP.get(name, name)


def _create_conn(db_path: Path) -> sqlite3.Connection:
    """创建一个配置好的 SQLite 连接"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_schema_done: set = set()


def _ensure_schema(physical: str, conn: sqlite3.Connection):
    """首次连接时自动初始化 schema（防止旧代码/测试跳过 init_schemas）"""
    if physical in _schema_done:
        return
    _schema_done.add(physical)
    try:
        if physical == "main":
            conn.executescript(_MAIN_SCHEMA)
            conn.commit()
        elif physical == "wechat":
            conn.executescript(_WECHAT_SCHEMA)
            conn.commit()
    except Exception as e:
        logger.debug(f"[DB] Auto schema init for {physical}: {e}")


def get_conn(name: str = "main") -> sqlite3.Connection:
    """
    获取数据库连接（单例，线程安全）。

    用法：
        conn = db.get_conn("main")      # 核心数据库
        conn = db.get_conn("wechat")    # 微信数据库
        conn = db.get_conn("memory")    # 向后兼容 → main.db
    """
    physical = _resolve_name(name)

    if physical in _connections:
        return _connections[physical]

    with _global_lock:
        # Double-check after acquiring lock
        if physical in _connections:
            return _connections[physical]

        db_path = _DB_FILES.get(physical)
        if db_path is None:
            raise ValueError(f"Unknown database: {name} (resolved to {physical})")

        conn = _create_conn(db_path)
        _connections[physical] = conn

        # 确保 lock 存在
        if physical not in _locks:
            _locks[physical] = threading.Lock()

        logger.info(f"[DB] Opened connection: {physical} → {db_path}")

        # 首次连接时自动初始化该库的 schema
        _ensure_schema(physical, conn)
        return conn


def get_lock(name: str = "main") -> threading.Lock:
    """获取数据库对应的写锁"""
    physical = _resolve_name(name)
    if physical not in _locks:
        with _global_lock:
            if physical not in _locks:
                _locks[physical] = threading.Lock()
    return _locks[physical]


@contextmanager
def transaction(name: str = "main"):
    """
    事务上下文管理器。自动 commit/rollback。

    用法：
        with db.transaction("main") as conn:
            conn.execute("INSERT INTO messages ...")
    """
    conn = get_conn(name)
    lock = get_lock(name)
    with lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextmanager
def read(name: str = "main"):
    """
    只读上下文（不加写锁，WAL 模式下读不阻塞写）。

    用法：
        with db.read("main") as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = get_conn(name)
    yield conn


# ── Schema 管理 ──────────────────────────────────────────────────────

_SCHEMA_VERSION = {
    "main": 1,
    "wechat": 1,
}

_MAIN_SCHEMA = """
-- 版本追踪
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at REAL DEFAULT 0
);
INSERT OR IGNORE INTO schema_version (id, version, updated_at)
    VALUES (1, 1, strftime('%s', 'now'));

-- 对话消息（原 memory.db）
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session   TEXT    NOT NULL,
    role      TEXT    NOT NULL,
    content   TEXT    NOT NULL,
    ts        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session);

-- FTS5 全文搜索索引（独立表，非 content table，兼容性更好）
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    tokenize='unicode61'
);

-- 自动同步触发器（独立 FTS5 表用 DELETE + INSERT）
CREATE TRIGGER IF NOT EXISTS trg_msg_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS trg_msg_ad AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_msg_au AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

-- 长期记忆片段（原 long_memory.db）
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    summary TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    msg_count INTEGER DEFAULT 0,
    start_ts REAL DEFAULT 0,
    end_ts REAL DEFAULT 0,
    created_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seg_session ON segments(session);

CREATE TABLE IF NOT EXISTS compress_state (
    session TEXT PRIMARY KEY,
    last_compressed_id INTEGER DEFAULT 0
);

-- 用户档案（原 profiles in memory.db）
CREATE TABLE IF NOT EXISTS profiles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    avatar          TEXT DEFAULT '👤',
    environment     TEXT DEFAULT 'family',
    system_prompt   TEXT DEFAULT '',
    voice_id        TEXT DEFAULT 'zh-CN-XiaoxiaoNeural',
    clone_voice_path TEXT DEFAULT '',
    wake_word       TEXT DEFAULT '',
    age_group       TEXT DEFAULT 'adult',
    preferences     TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL,
    is_active       INTEGER DEFAULT 0,
    sort_order      INTEGER DEFAULT 0
);

-- 知识库（原 knowledge_base.db）
CREATE TABLE IF NOT EXISTS kb_documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT DEFAULT '',
    chunk_count INTEGER DEFAULT 0,
    created_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    content TEXT NOT NULL,
    tokens TEXT DEFAULT '[]',
    chunk_index INTEGER DEFAULT 0,
    FOREIGN KEY (doc_id) REFERENCES kb_documents(id)
);
CREATE INDEX IF NOT EXISTS idx_kbc_doc ON kb_chunks(doc_id);

CREATE TABLE IF NOT EXISTS kb_idf_cache (
    term TEXT PRIMARY KEY,
    idf REAL DEFAULT 0,
    df INTEGER DEFAULT 0
);

-- 工作流（原 workflows.db）
CREATE TABLE IF NOT EXISTS workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    definition  TEXT NOT NULL,
    enabled     INTEGER DEFAULT 0,
    category    TEXT DEFAULT 'custom',
    created_at  REAL,
    updated_at  REAL
);

CREATE TABLE IF NOT EXISTS workflow_executions (
    id              TEXT PRIMARY KEY,
    workflow_id     TEXT NOT NULL,
    workflow_name   TEXT DEFAULT '',
    status          TEXT DEFAULT 'pending',
    trigger_type    TEXT DEFAULT 'manual',
    started_at      REAL,
    finished_at     REAL,
    node_results    TEXT DEFAULT '[]',
    context_json    TEXT DEFAULT '{}',
    error           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wfexec_wf ON workflow_executions(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_wfexec_time ON workflow_executions(started_at DESC);

-- 审计日志（原 audit.db）
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    target TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    severity TEXT DEFAULT 'info',
    ip TEXT DEFAULT '',
    timestamp REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- 事件总线（原 events.db）
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    data TEXT DEFAULT '{}',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evt_ts ON events(timestamp);

-- 技能统计（原 stats.db）
CREATE TABLE IF NOT EXISTS skill_usage (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id  TEXT    NOT NULL,
    ts        REAL    NOT NULL,
    session   TEXT,
    input     TEXT,
    success   INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_skill_ts ON skill_usage(skill_id, ts);

CREATE TABLE IF NOT EXISTS skill_meta_cache (
    skill_id   TEXT PRIMARY KEY,
    name_zh    TEXT,
    category   TEXT,
    icon       TEXT,
    updated_at REAL
);

-- 情感分析（原 sentiment.db）
CREATE TABLE IF NOT EXISTS sentiment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT DEFAULT 'default',
    contact TEXT DEFAULT '',
    score REAL DEFAULT 0,
    label TEXT DEFAULT 'neutral',
    message_preview TEXT DEFAULT '',
    timestamp REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sl_ts ON sentiment_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_sl_contact ON sentiment_log(contact);
"""

_WECHAT_SCHEMA = """
-- 版本追踪
CREATE TABLE IF NOT EXISTS schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at REAL DEFAULT 0
);
INSERT OR IGNORE INTO schema_version (id, version, updated_at)
    VALUES (1, 1, strftime('%s', 'now'));

-- 统一收件箱（原 unified_inbox.db）
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    contact TEXT NOT NULL,
    sender TEXT DEFAULT '',
    content TEXT NOT NULL,
    is_group INTEGER DEFAULT 0,
    is_mine INTEGER DEFAULT 0,
    timestamp REAL DEFAULT 0,
    read INTEGER DEFAULT 0,
    starred INTEGER DEFAULT 0,
    forwarded INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inbox_acct ON inbox(account_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_inbox_contact ON inbox(contact, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_inbox_unread ON inbox(read, timestamp DESC);

CREATE TABLE IF NOT EXISTS forward_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    src_account TEXT NOT NULL,
    src_contact TEXT DEFAULT '',
    dst_account TEXT NOT NULL,
    dst_contact TEXT NOT NULL,
    keyword_filter TEXT DEFAULT '',
    transform TEXT DEFAULT 'plain',
    created_at REAL DEFAULT 0
);

-- 媒体库（原 media.db）
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    description TEXT DEFAULT '',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    added_at REAL DEFAULT 0,
    last_used_at REAL DEFAULT 0,
    use_count INTEGER DEFAULT 0,
    ai_analyzed INTEGER DEFAULT 0,
    source TEXT DEFAULT 'local'
);
CREATE INDEX IF NOT EXISTS idx_media_tags ON media(tags);
CREATE INDEX IF NOT EXISTS idx_media_cat ON media(category);

-- 联系人画像（原 contact_profile.py 的 profiles 表）
CREATE TABLE IF NOT EXISTS profiles (
    name            TEXT PRIMARY KEY,
    relationship    TEXT DEFAULT 'normal',
    intimacy        REAL DEFAULT 30.0,
    interests       TEXT DEFAULT '[]',
    comment_style   TEXT DEFAULT 'casual',
    notes           TEXT DEFAULT '',
    total_likes     INTEGER DEFAULT 0,
    total_comments  INTEGER DEFAULT 0,
    total_replies   INTEGER DEFAULT 0,
    last_interaction REAL DEFAULT 0,
    created_at      REAL,
    updated_at      REAL
);

CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact     TEXT NOT NULL,
    action      TEXT NOT NULL,
    content     TEXT DEFAULT '',
    post_text   TEXT DEFAULT '',
    timestamp   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inter_contact
    ON interactions(contact, timestamp DESC);

-- 联系人融合（原 contact_fusion.db）
CREATE TABLE IF NOT EXISTS contact_links (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    account_contacts TEXT DEFAULT '[]',
    relationship TEXT DEFAULT 'normal',
    intimacy REAL DEFAULT 30.0,
    interests TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    total_interactions INTEGER DEFAULT 0,
    created_at REAL DEFAULT 0,
    updated_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alias_map (
    account_id TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    fused_id TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    match_method TEXT DEFAULT 'manual',
    PRIMARY KEY (account_id, contact_name)
);

-- 群发（原 broadcast.py）
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    variables TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    created_at REAL DEFAULT 0,
    use_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    template_id TEXT DEFAULT '',
    name TEXT NOT NULL,
    message TEXT NOT NULL,
    audience_filter TEXT DEFAULT '{}',
    personalize INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    total_targets INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    created_at REAL DEFAULT 0,
    started_at REAL DEFAULT 0,
    completed_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    message_sent TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    sent_at REAL DEFAULT 0,
    error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_log_campaign ON send_log(campaign_id);
CREATE INDEX IF NOT EXISTS idx_log_status ON send_log(status);

-- 微信账号管理（原 account_manager.py）
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wx_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    hwnd INTEGER DEFAULT 0,
    pid INTEGER DEFAULT 0,
    autoreply_config TEXT DEFAULT '{}',
    moments_config TEXT DEFAULT '{}',
    is_active INTEGER DEFAULT 1,
    created_at REAL DEFAULT 0,
    last_active REAL DEFAULT 0,
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'disconnected'
);

-- 消息路由规则（原 msg_router.py）
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 50,
    match_type TEXT DEFAULT 'keyword',
    match_pattern TEXT DEFAULT '',
    match_contacts TEXT DEFAULT '',
    action_type TEXT DEFAULT 'workflow',
    action_target TEXT DEFAULT '',
    action_params TEXT DEFAULT '{}',
    created_at REAL DEFAULT 0,
    trigger_count INTEGER DEFAULT 0,
    cooldown_seconds INTEGER DEFAULT 60,
    last_triggered REAL DEFAULT 0
);

-- 朋友圈分析（原 moments_analytics.py）
CREATE TABLE IF NOT EXISTS moments_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT DEFAULT '',
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    published_at REAL DEFAULT 0,
    hour INTEGER DEFAULT 0,
    weekday INTEGER DEFAULT 0,
    likes_received INTEGER DEFAULT 0,
    comments_received INTEGER DEFAULT 0,
    views_estimated INTEGER DEFAULT 0,
    engagement_score REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pub_ts ON moments_stats(published_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    target_author TEXT DEFAULT '',
    content_text TEXT DEFAULT '',
    content_category TEXT DEFAULT '',
    content_tags TEXT DEFAULT '[]',
    hour INTEGER DEFAULT 0,
    weekday INTEGER DEFAULT 0,
    timestamp REAL DEFAULT 0,
    extra TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_author ON events(target_author);
"""


def init_schemas():
    """初始化所有数据库 schema（幂等，可重复调用）"""
    conn_main = get_conn("main")
    with get_lock("main"):
        conn_main.executescript(_MAIN_SCHEMA)
        conn_main.commit()
    logger.info("[DB] main.db schema initialized")

    conn_wechat = get_conn("wechat")
    with get_lock("wechat"):
        conn_wechat.executescript(_WECHAT_SCHEMA)
        conn_wechat.commit()
    logger.info("[DB] wechat.db schema initialized")

    # 初始同步 FTS 索引（仅在 FTS 表为空且 messages 表有数据时执行）
    _sync_fts_index(conn_main)


def _sync_fts_index(conn: sqlite3.Connection):
    """将已有 messages 数据同步到 FTS5 索引（首次迁移用）"""
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if fts_count == 0 and msg_count > 0:
            conn.execute(
                "INSERT INTO messages_fts(rowid, content) "
                "SELECT id, content FROM messages"
            )
            conn.commit()
            logger.info(f"[DB] FTS index synced: {msg_count} messages indexed")
    except Exception as e:
        logger.warning(f"[DB] FTS sync failed (non-fatal): {e}")


def rebuild_fts_index():
    """重建 FTS 索引（清空后重新导入）"""
    conn = get_conn("main")
    with get_lock("main"):
        conn.execute("DELETE FROM messages_fts")
        conn.execute(
            "INSERT INTO messages_fts(rowid, content) "
            "SELECT id, content FROM messages"
        )
        conn.commit()
    logger.info("[DB] FTS index rebuilt")


# ── 数据迁移 ──────────────────────────────────────────────────────────

_OLD_DB_MAP = {
    "memory": ("messages", "messages"),
    "long_memory_segments": ("long_memory", "segments"),
    "long_memory_compress": ("long_memory", "compress_state"),
    "audit": ("audit", "audit_log"),
    "events": ("events", "events"),
    "stats_usage": ("stats", "skill_usage"),
    "stats_meta": ("stats", "skill_meta_cache"),
    "sentiment": ("sentiment", "sentiment_log"),
    "workflows": ("workflows", "workflows"),
    "workflow_exec": ("workflows", "executions"),
    "unified_inbox": ("unified_inbox", "inbox"),
    "unified_forward": ("unified_inbox", "forward_rules"),
}

# 需要改名的表（旧名 → 新名）
_TABLE_RENAMES = {
    ("knowledge_base", "documents"): "kb_documents",
    ("knowledge_base", "chunks"): "kb_chunks",
    ("knowledge_base", "idf_cache"): "kb_idf_cache",
    ("workflows", "executions"): "workflow_executions",
    ("contact_fusion", "fused_contacts"): "contact_links",
    ("moments_analytics", "publish_metrics"): "moments_stats",
}


def migrate_from_old_dbs():
    """
    从旧的独立数据库迁移数据到新的合并数据库。

    安全策略：
    - 逐表检查，跳过空表和已迁移的数据
    - 旧数据库文件不删除，仅重命名为 .bak
    - 迁移完成后记录日志
    """
    import shutil
    import time

    old_dbs = {
        "memory": DATA_DIR / "memory.db",
        "long_memory": DATA_DIR / "long_memory.db",
        "knowledge_base": DATA_DIR / "knowledge_base.db",
        "workflows": DATA_DIR / "workflows.db",
        "audit": DATA_DIR / "audit.db",
        "events": DATA_DIR / "events.db",
        "stats": DATA_DIR / "stats.db",
        "sentiment": DATA_DIR / "sentiment.db",
        "accounts": DATA_DIR / "accounts.db",
        "unified_inbox": DATA_DIR / "unified_inbox.db",
        "media": DATA_DIR / "media" / "media.db",
        "contact_fusion": DATA_DIR / "contact_fusion.db",
        "contact_profiles": DATA_DIR / "contact_profiles.db",
        "broadcast": DATA_DIR / "broadcast.db",
        "moments_analytics": DATA_DIR / "moments_analytics.db",
    }

    # 先初始化新 schema
    init_schemas()

    migrated_any = False

    for db_name, old_path in old_dbs.items():
        if not old_path.exists():
            continue

        # 确定目标库
        target = _COMPAT_MAP.get(db_name, db_name)
        if target not in ("main", "wechat"):
            continue

        try:
            old_conn = sqlite3.connect(str(old_path), check_same_thread=False)
            old_conn.row_factory = sqlite3.Row

            # 获取旧库中的所有表
            tables = [
                r[0] for r in
                old_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if not r[0].startswith("sqlite_")
            ]

            new_conn = get_conn(target)
            lock = get_lock(target)

            for table in tables:
                # 确定新表名
                new_table = _TABLE_RENAMES.get((db_name, table), table)

                # 检查新表是否存在
                exists = new_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (new_table,)
                ).fetchone()
                if not exists:
                    logger.warning(f"[DB Migration] Target table {new_table} not found, skipping")
                    continue

                # 检查新表是否已有数据（避免重复迁移）
                count = new_conn.execute(f"SELECT COUNT(*) FROM [{new_table}]").fetchone()[0]
                if count > 0:
                    logger.debug(f"[DB Migration] {new_table} already has {count} rows, skipping")
                    continue

                # 读取旧数据
                rows = old_conn.execute(f"SELECT * FROM [{table}]").fetchall()
                if not rows:
                    continue

                # 获取列名
                old_cols = [desc[0] for desc in old_conn.execute(f"SELECT * FROM [{table}] LIMIT 1").description]
                new_cols_info = new_conn.execute(f"PRAGMA table_info([{new_table}])").fetchall()
                new_col_names = {r["name"] for r in new_cols_info}

                # 取交集（只迁移两边都有的列）
                common_cols = [c for c in old_cols if c in new_col_names]
                if not common_cols:
                    continue

                placeholders = ",".join("?" * len(common_cols))
                col_list = ",".join(f"[{c}]" for c in common_cols)
                insert_sql = f"INSERT OR IGNORE INTO [{new_table}] ({col_list}) VALUES ({placeholders})"

                with lock:
                    for row in rows:
                        values = tuple(row[c] for c in common_cols)
                        try:
                            new_conn.execute(insert_sql, values)
                        except sqlite3.IntegrityError:
                            pass
                    new_conn.commit()

                logger.info(f"[DB Migration] {db_name}.{table} → {target}.{new_table}: {len(rows)} rows")
                migrated_any = True

            old_conn.close()

            # 备份旧数据库
            bak_path = old_path.with_suffix(".db.bak")
            if not bak_path.exists():
                shutil.copy2(str(old_path), str(bak_path))
                logger.info(f"[DB Migration] Backed up {old_path.name} → {bak_path.name}")

        except Exception as e:
            logger.error(f"[DB Migration] Failed for {db_name}: {e}")
            continue

    if migrated_any:
        logger.info("[DB Migration] ✅ Migration complete")
        # 清理已迁移的旧数据库文件（.bak 保留作为安全备份）
        for db_name, old_path in old_dbs.items():
            if old_path.exists() and old_path.with_suffix(".db.bak").exists():
                try:
                    old_path.unlink()
                    # 清理 WAL/SHM 附属文件
                    for suffix in ["-wal", "-shm", "-journal"]:
                        wal = old_path.with_name(old_path.name + suffix)
                        if wal.exists():
                            wal.unlink()
                    logger.debug(f"[DB Migration] Removed old {old_path.name}")
                except Exception:
                    pass
    else:
        logger.info("[DB Migration] No data to migrate (fresh install or already migrated)")


# ── 维护任务 ──────────────────────────────────────────────────────────

def vacuum_all():
    """对所有数据库执行 VACUUM（压缩空间，建议低峰期运行）"""
    for name in ("main", "wechat"):
        try:
            conn = get_conn(name)
            with get_lock(name):
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
            logger.info(f"[DB] VACUUM complete: {name}")
        except Exception as e:
            logger.warning(f"[DB] VACUUM failed for {name}: {e}")


def backup(backup_dir: Optional[Path] = None):
    """备份所有数据库"""
    import shutil
    import time

    if backup_dir is None:
        backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    for name, path in _DB_FILES.items():
        if path.exists():
            dst = backup_dir / f"{name}_{ts}.db"
            # 使用 SQLite backup API 确保一致性
            conn = get_conn(name)
            with get_lock(name):
                bak_conn = sqlite3.connect(str(dst))
                conn.backup(bak_conn)
                bak_conn.close()
            logger.info(f"[DB] Backup: {name} → {dst}")


def close_all():
    """关闭所有连接（用于优雅退出）"""
    for name, conn in _connections.items():
        try:
            conn.close()
            logger.debug(f"[DB] Closed: {name}")
        except Exception:
            pass
    _connections.clear()
    _schema_done.clear()
