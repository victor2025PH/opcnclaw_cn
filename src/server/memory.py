"""
Persistent conversation memory using SQLite.

Supports multiple sessions (different devices/users have independent histories).
Thread-safe via connection-per-call pattern (SQLite WAL mode).
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from loguru import logger

DB_PATH = Path("data/memory.db")
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the SQLite DB, creating tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode for concurrent reads
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            session   TEXT    NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            ts        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session)")
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────

def add_message(session: str, role: str, content) -> None:
    """Append a message to a session's history."""
    if isinstance(content, (list, dict)):
        content = json.dumps(content, ensure_ascii=False)
    with _lock:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO messages (session, role, content) VALUES (?, ?, ?)",
                (session, role, str(content)),
            )
            conn.commit()
        finally:
            conn.close()


def get_history(session: str, limit: int = 20) -> List[Dict]:
    """
    Return the last `limit` messages for a session as a list of
    {"role": ..., "content": ...} dicts (oldest first).
    """
    with _lock:
        conn = _get_conn()
        try:
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
        finally:
            conn.close()


def clear_history(session: str) -> int:
    """Delete all messages for a session. Returns the number of deleted rows."""
    with _lock:
        conn = _get_conn()
        try:
            cur = conn.execute("DELETE FROM messages WHERE session = ?", (session,))
            conn.commit()
            deleted = cur.rowcount
            logger.info(f"Memory cleared: session={session} ({deleted} messages)")
            return deleted
        finally:
            conn.close()


def list_sessions() -> List[Dict]:
    """Return a summary of all sessions."""
    with _lock:
        conn = _get_conn()
        try:
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
        finally:
            conn.close()


def get_history_raw(session: str, limit: int = 100) -> List[Dict]:
    """Return messages with timestamps (for the /api/history endpoint)."""
    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, role, content, ts
                FROM messages
                WHERE session = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session, limit),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": _decode(r["content"]),
                    "ts": r["ts"],
                }
                for r in rows
            ]
        finally:
            conn.close()


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
