# -*- coding: utf-8 -*-
"""
对话记忆持久化搜索

支持从 SQLite 对话数据库中搜索历史记录。

搜索维度：
  1. 关键词全文搜索（jieba 分词 + LIKE 回退）
  2. 时间范围筛选
  3. 角色过滤（user/assistant）
  4. 会话 ID 过滤

设计决策：
  方案A: SQLite FTS5 全文索引 → 需要 ALTER TABLE 迁移，中文支持差
  方案B: 应用层 jieba 分词 + SQL LIKE → 零迁移，中文友好，选这个
  方案C: 新建搜索索引表 → 增加复杂度，对当前数据量过度设计

  当前对话量在千级，LIKE + jieba 足够（<10ms）。
  未来超过十万条时可升级为 FTS5。
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False


DB_PATH = Path("data/memory.db")
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def search(
    query: str = "",
    session: str = "",
    role: str = "",
    start_time: str = "",
    end_time: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    """
    搜索对话记忆。

    参数：
      query: 关键词（空字符串表示不过滤）
      session: 会话 ID 过滤
      role: user / assistant 过滤
      start_time: 起始时间 YYYY-MM-DD 或 YYYY-MM-DD HH:MM
      end_time: 结束时间
      limit: 返回条数
      offset: 偏移量

    返回: {results: [...], total: int, query: str}
    """
    conn = _get_conn()
    conditions = []
    params = []

    if query:
        keywords = _tokenize(query)
        if keywords:
            like_parts = []
            for kw in keywords[:5]:  # 最多 5 个关键词
                like_parts.append("content LIKE ?")
                params.append(f"%{kw}%")
            conditions.append(f"({' AND '.join(like_parts)})")
        else:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")

    if session:
        conditions.append("session = ?")
        params.append(session)

    if role:
        conditions.append("role = ?")
        params.append(role)

    if start_time:
        conditions.append("ts >= ?")
        params.append(start_time)

    if end_time:
        conditions.append("ts <= ?")
        params.append(end_time)

    where = " AND ".join(conditions) if conditions else "1=1"

    with _lock:
        # 总数
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE {where}", params
        ).fetchone()
        total = count_row[0] if count_row else 0

        # 结果
        rows = conn.execute(
            f"SELECT id, session, role, content, ts FROM messages WHERE {where} "
            f"ORDER BY ts DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    results = []
    for r in rows:
        content = r["content"]
        # 高亮匹配的关键词
        highlight = content
        if query:
            for kw in _tokenize(query)[:3]:
                highlight = highlight.replace(kw, f"**{kw}**")

        results.append({
            "id": r["id"],
            "session": r["session"],
            "role": r["role"],
            "content": content[:500],
            "highlight": highlight[:500],
            "time": r["ts"],
        })

    return {
        "results": results,
        "total": total,
        "query": query,
        "offset": offset,
        "limit": limit,
    }


def get_sessions() -> List[Dict]:
    """获取所有会话列表"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT session, COUNT(*) as msg_count,
                  MIN(ts) as first_msg, MAX(ts) as last_msg
           FROM messages GROUP BY session ORDER BY last_msg DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    """搜索统计"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session) FROM messages").fetchone()[0]
    return {"total_messages": total, "total_sessions": sessions}


def _tokenize(text: str) -> List[str]:
    """分词"""
    if not text:
        return []
    if _JIEBA:
        words = [w.strip() for w in jieba.cut(text) if len(w.strip()) > 1]
        return words[:10]
    return [text]
