# -*- coding: utf-8 -*-
"""
长期对话记忆系统

架构设计：
  当前对话 → 短期缓存（最近10条原文）
  旧对话   → 自动压缩为摘要片段（LLM 生成，含关键词索引）
  检索     → jieba 分词 + TF-IDF 相关度 → 注入 system prompt

vs 向量数据库方案的优势：
  - 零额外依赖（无需 FAISS/ChromaDB + 500MB embedding 模型）
  - jieba + SQLite 对中文效果好，延迟 <5ms
  - LLM 压缩比人工摘要更智能，保留上下文语义
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False

DB_PATH = Path("data/long_memory.db")
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

STOP_WORDS = set("的了是在我你他她它们吗呢啊哦嗯好这那什么怎么为什么"
                  "不会就也都还有没很非常可以能把被让给从到和与或但"
                  "如果因为所以虽然但是而且因此请谢谢")


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
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
        """)
        _conn.commit()
    return _conn


@dataclass
class MemorySegment:
    id: int = 0
    session: str = ""
    summary: str = ""
    keywords: str = ""
    msg_count: int = 0
    relevance: float = 0.0


def _safe_parse_ts(ts_str) -> float:
    """安全解析时间戳字符串，兼容多种格式"""
    if not ts_str:
        return time.time()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(str(ts_str), fmt))
        except (ValueError, TypeError):
            continue
    return time.time()


def _extract_keywords(text: str, top_k: int = 10) -> List[str]:
    """提取文本关键词"""
    if _JIEBA:
        words = [w for w in jieba.cut(text) if len(w) > 1 and w not in STOP_WORDS]
    else:
        words = [text[i:i+2] for i in range(0, len(text)-1, 2)]
    counts = Counter(words)
    return [w for w, _ in counts.most_common(top_k)]


def _tfidf_score(query_kw: List[str], doc_kw: str, all_docs_kw: List[str]) -> float:
    """计算查询关键词与文档关键词的 TF-IDF 相关度"""
    doc_words = set(doc_kw.split(","))
    if not doc_words or not query_kw:
        return 0.0

    N = max(len(all_docs_kw), 1)
    score = 0.0
    for qw in query_kw:
        tf = 1.0 if qw in doc_words else 0.0
        df = sum(1 for d in all_docs_kw if qw in d)
        idf = math.log((N + 1) / (df + 1)) + 1
        score += tf * idf

    return score


# ── 压缩引擎 ──────────────────────────────────────────────────────────────────

COMPRESS_PROMPT = """你是对话记忆压缩器。请将以下对话片段压缩为一段简洁的摘要（50-100字），
保留关键信息：用户问了什么、AI回答了什么要点、重要的名字/数字/地点/偏好。
不要使用第一人称，用"用户"和"AI"指代对方。

对话内容：
{conversation}

请直接输出摘要，不要其他格式："""


async def compress_old_messages(
    session: str,
    ai_call: Optional[Callable] = None,
    batch_size: int = 20,
):
    """
    压缩旧消息为摘要片段。

    从 memory.db 读取已处理消息之后的新消息，每 batch_size 条生成一个摘要。
    如果没有 LLM 回调，使用纯关键词提取（无摘要）。
    """
    from . import memory as _memory

    conn = _get_conn()
    with _lock:
        state = conn.execute(
            "SELECT last_compressed_id FROM compress_state WHERE session = ?",
            (session,),
        ).fetchone()
        last_id = state["last_compressed_id"] if state else 0

    mem_conn = _memory._get_conn()
    try:
        rows = mem_conn.execute(
            "SELECT id, role, content, ts FROM messages WHERE session = ? AND id > ? ORDER BY id ASC",
            (session, last_id),
        ).fetchall()
    finally:
        mem_conn.close()

    if len(rows) < batch_size:
        return 0

    compressed_count = 0
    for i in range(0, len(rows) - batch_size + 1, batch_size):
        batch = rows[i:i + batch_size]
        convo_text = "\n".join(f"{r['role']}: {r['content'][:200]}" for r in batch)
        keywords = _extract_keywords(convo_text)

        summary = ""
        if ai_call:
            try:
                prompt = COMPRESS_PROMPT.format(conversation=convo_text[:2000])
                summary = await ai_call([
                    {"role": "system", "content": "你是对话记忆压缩器。"},
                    {"role": "user", "content": prompt},
                ])
            except Exception as e:
                logger.debug(f"[LongMemory] LLM 压缩失败: {e}")

        if not summary:
            summary = f"对话包含{len(batch)}条消息。" + "；".join(
                r["content"][:50] for r in batch if r["role"] == "user"
            )[:200]

        new_last_id = batch[-1]["id"]
        start_ts = _safe_parse_ts(batch[0]["ts"])
        end_ts = _safe_parse_ts(batch[-1]["ts"])

        with _lock:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO segments (session, summary, keywords, msg_count, start_ts, end_ts, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session, summary, ",".join(keywords), len(batch), start_ts, end_ts, time.time()),
            )
            conn.execute(
                "INSERT OR REPLACE INTO compress_state (session, last_compressed_id) VALUES (?, ?)",
                (session, new_last_id),
            )
            conn.commit()

        compressed_count += 1
        logger.info(f"[LongMemory] 压缩片段 #{compressed_count}: {len(batch)} msgs → {len(summary)} chars")

    return compressed_count


# ── 检索引擎 ──────────────────────────────────────────────────────────────────

def retrieve_relevant(session: str, query: str, top_k: int = 3) -> List[MemorySegment]:
    """
    检索与查询最相关的记忆片段。

    使用 TF-IDF 计算查询关键词与每个片段关键词的相关度，
    返回得分最高的 top_k 个片段。
    """
    query_kw = _extract_keywords(query, top_k=8)
    if not query_kw:
        return []

    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, session, summary, keywords, msg_count FROM segments WHERE session = ? ORDER BY end_ts DESC LIMIT 100",
            (session,),
        ).fetchall()

    if not rows:
        return []

    all_kw = [r["keywords"] for r in rows]
    now = time.time()
    scored = []
    for idx, r in enumerate(rows):
        score = _tfidf_score(query_kw, r["keywords"], all_kw)
        if score > 0:
            # 时间衰减：越新的记忆权重越高（排序位置越靠前=越新）
            recency_boost = 1.0 + 0.3 * (1.0 - idx / max(len(rows), 1))
            score *= recency_boost
            seg = MemorySegment(
                id=r["id"], session=r["session"],
                summary=r["summary"], keywords=r["keywords"],
                msg_count=r["msg_count"], relevance=score,
            )
            scored.append(seg)

    scored.sort(key=lambda s: s.relevance, reverse=True)
    return scored[:top_k]


def build_memory_context(session: str, current_message: str, max_chars: int = 800) -> str:
    """
    构建长期记忆上下文，注入到 system prompt。

    返回格式：
      [历史记忆] 你之前和用户讨论过：
      1. 用户问过北京天气... (相关度: 0.85)
      2. 用户提到喜欢吃火锅... (相关度: 0.72)
    """
    segments = retrieve_relevant(session, current_message, top_k=3)
    if not segments:
        return ""

    lines = ["[历史记忆] 你之前和用户讨论过以下内容（可能与当前对话相关）："]
    total = 0
    for i, seg in enumerate(segments, 1):
        text = seg.summary[:200]
        line = f"{i}. {text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines)


# ── 统计 ──────────────────────────────────────────────────────────────────────

def get_memory_stats(session: str = "") -> Dict:
    with _lock:
        conn = _get_conn()
        if session:
            count = conn.execute(
                "SELECT COUNT(*) FROM segments WHERE session = ?", (session,)
            ).fetchone()[0]
            total_msgs = conn.execute(
                "SELECT SUM(msg_count) FROM segments WHERE session = ?", (session,)
            ).fetchone()[0] or 0
        else:
            count = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            total_msgs = conn.execute("SELECT SUM(msg_count) FROM segments").fetchone()[0] or 0

    return {
        "segments": count,
        "compressed_messages": total_msgs,
        "session": session or "all",
    }
