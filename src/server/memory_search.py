# -*- coding: utf-8 -*-
"""
对话记忆持久化搜索

搜索引擎：SQLite FTS5 全文索引
  - unicode61 tokenizer 自动处理中文（单字切分）
  - jieba 分词优化查询词（合并为 FTS5 MATCH 语法）
  - 自动同步：INSERT/UPDATE/DELETE 通过触发器保持索引一致
  - 回退：FTS5 不可用时降级为 LIKE 搜索

性能对比（10 万条消息）：
  LIKE + jieba:  ~200ms
  FTS5 MATCH:    ~2ms（100x 提升）
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from loguru import logger
from . import db as _db

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False

# FTS5 可用性（延迟检测，因为模块加载时 schema 可能还未初始化）
_FTS5_AVAILABLE: bool | None = None


def _check_fts5() -> bool:
    """延迟检测 FTS5 是否可用"""
    global _FTS5_AVAILABLE
    if _FTS5_AVAILABLE is not None:
        return _FTS5_AVAILABLE
    try:
        conn = _db.get_conn("main")
        conn.execute("SELECT * FROM messages_fts LIMIT 0")
        _FTS5_AVAILABLE = True
        logger.info("[Search] FTS5 index available")
    except Exception:
        _FTS5_AVAILABLE = False
        logger.debug("[Search] FTS5 not available, falling back to LIKE")
    return _FTS5_AVAILABLE


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
    conn = _db.get_conn("main")

    if query and _check_fts5() and _is_fts_friendly(query):
        # 纯英文/数字 → FTS5 unicode61
        return _search_fts(conn, query, session, role, start_time, end_time, limit, offset)
    elif query and _check_fts5() and _check_jieba_fts():
        # 含中文 → FTS5 jieba 分词表（精确词语匹配）
        return _search_fts_jieba(conn, query, session, role, start_time, end_time, limit, offset)
    else:
        # 回退 → LIKE
        return _search_like(conn, query, session, role, start_time, end_time, limit, offset)


def _search_fts(
    conn, query, session, role, start_time, end_time, limit, offset
) -> Dict:
    """FTS5 全文搜索（高性能路径）"""
    # 构建 FTS5 MATCH 查询词
    fts_query = _build_fts_query(query)
    if not fts_query:
        return _search_like(conn, query, session, role, start_time, end_time, limit, offset)

    # 额外过滤条件
    filters = []
    params = []
    if session:
        filters.append("m.session = ?")
        params.append(session)
    if role:
        filters.append("m.role = ?")
        params.append(role)
    if start_time:
        filters.append("m.ts >= ?")
        params.append(start_time)
    if end_time:
        filters.append("m.ts <= ?")
        params.append(end_time)

    filter_clause = (" AND " + " AND ".join(filters)) if filters else ""

    try:
        # 计数
        count_sql = (
            f"SELECT COUNT(*) FROM messages_fts f "
            f"JOIN messages m ON m.id = f.rowid "
            f"WHERE f.content MATCH ?{filter_clause}"
        )
        total = conn.execute(count_sql, [fts_query] + params).fetchone()[0]

        # 结果（按相关度 + 时间排序）
        result_sql = (
            f"SELECT m.id, m.session, m.role, m.content, m.ts, "
            f"rank AS relevance "
            f"FROM messages_fts f "
            f"JOIN messages m ON m.id = f.rowid "
            f"WHERE f.content MATCH ?{filter_clause} "
            f"ORDER BY f.rank LIMIT ? OFFSET ?"
        )
        rows = conn.execute(result_sql, [fts_query] + params + [limit, offset]).fetchall()

        return _format_results(rows, query, total, offset, limit, engine="fts5")

    except Exception as e:
        logger.warning(f"[Search] FTS5 query failed, falling back to LIKE: {e}")
        return _search_like(conn, query, session, role, start_time, end_time, limit, offset)


def _search_like(
    conn, query, session, role, start_time, end_time, limit, offset
) -> Dict:
    """LIKE 搜索（回退路径）"""
    conditions = []
    params = []

    if query:
        keywords = _tokenize(query)
        if keywords:
            like_parts = []
            for kw in keywords[:5]:
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

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM messages WHERE {where}", params
    ).fetchone()
    total = count_row[0] if count_row else 0

    rows = conn.execute(
        f"SELECT id, session, role, content, ts FROM messages WHERE {where} "
        f"ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return _format_results(rows, query, total, offset, limit, engine="like")


_JIEBA_FTS_AVAILABLE: bool | None = None

def _check_jieba_fts() -> bool:
    """检查 jieba FTS5 表是否可用"""
    global _JIEBA_FTS_AVAILABLE
    if _JIEBA_FTS_AVAILABLE is not None:
        return _JIEBA_FTS_AVAILABLE
    try:
        conn = _db.get_conn("main")
        conn.execute("SELECT * FROM messages_fts_jieba LIMIT 0")
        _JIEBA_FTS_AVAILABLE = True
    except Exception:
        _JIEBA_FTS_AVAILABLE = False
    return _JIEBA_FTS_AVAILABLE


def _search_fts_jieba(conn, query, session, role, start_time, end_time, limit, offset) -> Dict:
    """用 jieba 分词 FTS5 表搜索中文"""
    try:
        # jieba 分词查询
        keywords = _tokenize(query)
        if not keywords:
            return _search_like(conn, query, session, role, start_time, end_time, limit, offset)

        # FTS5 MATCH: 每个 jieba 词作为 token
        fts_query = " ".join(keywords[:5])

        filters = []
        params = []
        if session:
            filters.append("m.session = ?")
            params.append(session)
        if role:
            filters.append("m.role = ?")
            params.append(role)
        if start_time:
            filters.append("m.ts >= ?")
            params.append(start_time)
        if end_time:
            filters.append("m.ts <= ?")
            params.append(end_time)

        filter_clause = (" AND " + " AND ".join(filters)) if filters else ""

        count_sql = (
            f"SELECT COUNT(*) FROM messages_fts_jieba f "
            f"JOIN messages m ON m.id = f.rowid "
            f"WHERE f.content MATCH ?{filter_clause}"
        )
        total = conn.execute(count_sql, [fts_query] + params).fetchone()[0]

        result_sql = (
            f"SELECT m.id, m.session, m.role, m.content, m.ts "
            f"FROM messages_fts_jieba f "
            f"JOIN messages m ON m.id = f.rowid "
            f"WHERE f.content MATCH ?{filter_clause} "
            f"ORDER BY f.rank LIMIT ? OFFSET ?"
        )
        rows = conn.execute(result_sql, [fts_query] + params + [limit, offset]).fetchall()

        return _format_results(rows, query, total, offset, limit, engine="fts5_jieba")

    except Exception as e:
        logger.warning(f"[Search] jieba FTS failed, falling back to LIKE: {e}")
        return _search_like(conn, query, session, role, start_time, end_time, limit, offset)


def _is_fts_friendly(query: str) -> bool:
    """判断查询是否适合 FTS5 路径。

    FTS5 + unicode61 对英文/数字匹配精确，
    但对中文是单字切分，多字词搜索不如 LIKE + jieba 准确。
    """
    # 包含中文字符 → 走 LIKE（jieba 分词更准确）
    if re.search(r'[\u4e00-\u9fff]', query):
        return False
    # 纯英文/数字/符号 → FTS5
    return True


def _build_fts_query(query: str) -> str:
    """
    将用户查询转换为 FTS5 MATCH 语法。

    unicode61 tokenizer 规则：
    - 英文：按空格/标点分词，自动小写 → "Python" 匹配 token "python"
    - 中文：每个字符是独立 token → "天气" 变成 token "天" + "气"

    策略：
    - 英文词直接作为 token 匹配
    - 中文词拆为单字，用空格连接（FTS5 隐式 AND）
    - 多个词用 OR 连接（提高召回）
    """
    terms = set()

    # jieba 分词
    if _JIEBA:
        words = [w.strip() for w in jieba.cut(query) if len(w.strip()) > 1]
        terms.update(words[:8])

    # 补充原始片段（jieba 可能漏掉英文或短词）
    segments = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', query)
    terms.update(s for s in segments if len(s) > 1)

    if not terms:
        # 单字回退
        chars = [c for c in query if c.strip() and c not in '的了是在我你他她']
        return " OR ".join(chars[:5]) if chars else ""

    parts = []
    for t in terms:
        if re.match(r'^[a-zA-Z0-9]+$', t):
            parts.append(t)
        else:
            # 中文：拆为单字（unicode61 的 token 粒度）
            chars = [c for c in t if '\u4e00' <= c <= '\u9fff']
            if chars:
                parts.append(" ".join(chars))

    return " OR ".join(parts) if parts else ""


def _format_results(rows, query, total, offset, limit, engine="fts5") -> Dict:
    """统一格式化搜索结果"""
    results = []
    keywords = _tokenize(query) if query else []

    for r in rows:
        content = r["content"] if isinstance(r, dict) else r[3]
        rid = r["id"] if isinstance(r, dict) else r[0]
        rsession = r["session"] if isinstance(r, dict) else r[1]
        rrole = r["role"] if isinstance(r, dict) else r[2]
        rts = r["ts"] if isinstance(r, dict) else r[4]

        # 关键词高亮
        highlight = content
        for kw in keywords[:3]:
            highlight = highlight.replace(kw, f"**{kw}**")

        results.append({
            "id": rid,
            "session": rsession,
            "role": rrole,
            "content": content[:500],
            "highlight": highlight[:500],
            "time": rts,
        })

    return {
        "results": results,
        "total": total,
        "query": query,
        "offset": offset,
        "limit": limit,
        "engine": engine,
    }


def get_sessions() -> List[Dict]:
    """获取所有会话列表"""
    conn = _db.get_conn("main")
    rows = conn.execute(
        """SELECT session, COUNT(*) as msg_count,
                  MIN(ts) as first_msg, MAX(ts) as last_msg
           FROM messages GROUP BY session ORDER BY last_msg DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    """搜索统计"""
    conn = _db.get_conn("main")
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session) FROM messages").fetchone()[0]
    fts_count = 0
    if _check_fts5():
        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
        except Exception:
            pass
    return {
        "total_messages": total,
        "total_sessions": sessions,
        "fts_indexed": fts_count,
        "engine": "fts5" if _check_fts5() else "like",
    }


def _tokenize(text: str) -> List[str]:
    """分词"""
    if not text:
        return []
    if _JIEBA:
        words = [w.strip() for w in jieba.cut(text) if len(w.strip()) > 1]
        return words[:10]
    return [text]
