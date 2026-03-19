"""
Persistent conversation memory using SQLite.

Supports multiple sessions (different devices/users have independent histories).
Thread-safe via unified db module (singleton connection + write lock).
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from loguru import logger

from . import db as _db

# 向后兼容：旧代码可能直接引用这些
DB_PATH = Path("data/memory.db")
_lock = _db.get_lock("main")


def _get_conn() -> sqlite3.Connection:
    """获取主数据库连接（单例，通过 db 模块管理）"""
    return _db.get_conn("main")


# ─────────────────────────────────────────────────────
# Startup cleanup
# ─────────────────────────────────────────────────────

def cleanup_oversized_messages(max_len: int = 5000):
    """One-time cleanup: truncate messages with leaked base64 data."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, content FROM messages WHERE length(content) > ?",
            (max_len,),
        ).fetchall()
        cleaned = 0
        for r in rows:
            if "base64" in r["content"]:
                fixed = _strip_multimodal(r["content"])
                if len(fixed) > max_len:
                    fixed = fixed[:500] + "... [历史数据已清理]"
                conn.execute(
                    "UPDATE messages SET content = ? WHERE id = ?",
                    (fixed, r["id"]),
                )
                cleaned += 1
        if cleaned:
            conn.commit()
            logger.info(f"🧹 Cleaned {cleaned} oversized messages from DB")

# 注意：cleanup 不再在模块加载时执行（schema 可能尚未初始化）
# 改为在 main.py startup 事件中 init_schemas() 之后调用


# ─────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────

def add_message(session: str, role: str, content) -> None:
    """Append a message to a session's history."""
    if isinstance(content, (list, dict)):
        content = _strip_multimodal(content)
    elif isinstance(content, str) and content.startswith("[{"):
        content = _strip_multimodal(content)
    text = str(content) if not isinstance(content, str) else content
    if len(text) > 8000 and "base64" in text:
        text = _strip_multimodal(content) if isinstance(content, (list, dict)) else text[:500] + "... [内容已截断]"
    with _db.transaction("main") as conn:
        conn.execute(
            "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
            (session, role, text),
        )


def get_history(session: str, limit: int = 20) -> List[Dict]:
    """
    Return the last `limit` messages for a session as a list of
    {"role": ..., "content": ...} dicts (oldest first).
    """
    with _db.read("main") as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content
                FROM messages
                WHERE session = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (session, limit),
        ).fetchall()
        return [{"role": r["role"], "content": _decode(r["content"])} for r in rows]


def clear_history(session: str) -> int:
    """Delete all messages for a session. Returns the number of deleted rows."""
    with _db.transaction("main") as conn:
        cur = conn.execute("DELETE FROM messages WHERE session = ?", (session,))
        deleted = cur.rowcount
        logger.info(f"Memory cleared: session={session} ({deleted} messages)")
        return deleted


def list_sessions() -> List[Dict]:
    """Return a summary of all sessions."""
    with _db.read("main") as conn:
        rows = conn.execute(
            """
            SELECT session,
                   COUNT(*) AS msg_count,
                   MIN(ts)  AS first_ts,
                   MAX(ts)  AS last_ts
            FROM messages
            GROUP BY session
            ORDER BY last_ts DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]


def get_history_raw(session: str, limit: int = 100, offset: int = 0) -> List[Dict]:
    """Return most recent messages with timestamps. offset=0 means newest."""
    with _db.read("main") as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, ts FROM (
                SELECT id, role, content, ts
                FROM messages
                WHERE session = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            ) sub ORDER BY id ASC
            """,
            (session, limit, offset),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "content": _display_content(r["content"]),
                "ts": r["ts"],
            }
            for r in rows
        ]


def get_messages_since(session: str, after_id: int, limit: int = 50) -> List[Dict]:
    """Return messages with id > after_id (for multi-device sync polling)."""
    with _db.read("main") as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, ts
            FROM messages
            WHERE session = ? AND id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session, after_id, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "content": _display_content(r["content"]),
                "ts": r["ts"],
            }
            for r in rows
        ]


def get_latest_id(session: str) -> int:
    """Return the highest message id for a session, or 0 if empty."""
    with _db.read("main") as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS mid FROM messages WHERE session = ?",
            (session,),
        ).fetchone()
        return row["mid"] if row else 0


# ─────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────

def _decode(content: str):
    """Try to parse JSON content back to list/dict; fallback to string."""
    try:
        v = json.loads(content)
        if isinstance(v, (list, dict)):
            return v
        return content
    except (json.JSONDecodeError, TypeError):
        return content


def _strip_multimodal(content) -> str:
    """Extract display-friendly text from multi-modal content.

    Multi-modal messages (with embedded base64 images) can be 30-50 KB+.
    For storage and display, keep only the text parts and replace images
    with a placeholder.
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
    elif isinstance(content, (list, dict)):
        parsed = content
    else:
        return str(content)

    if not isinstance(parsed, list):
        return content if isinstance(content, str) else json.dumps(parsed, ensure_ascii=False)

    texts, img_count = [], 0
    for part in parsed:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            t = part.get("text", "").strip()
            if t:
                texts.append(t)
        elif part.get("type") == "image_url":
            img_count += 1

    result = " ".join(texts)
    if img_count == 1:
        result += " [图片]"
    elif img_count > 1:
        result += f" [{img_count}张图片]"
    if result:
        return result
    # Fallback: never use str() on raw list/dict — it produces unrecoverable repr
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _display_content(content: str) -> str:
    """Return display-safe content (strip base64 images if multi-modal)."""
    decoded = _decode(content)
    if isinstance(decoded, list):
        return _strip_multimodal(decoded)
    return decoded if isinstance(decoded, str) else str(decoded)
