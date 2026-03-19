# -*- coding: utf-8 -*-
"""
私有知识库 RAG (Retrieval-Augmented Generation)

让 AI 基于用户导入的私有文档回答问题，实现全离线知识问答。

方案对比：
  方案A: 向量数据库 (Chroma/FAISS) + Embedding 模型
         → 需要额外安装大依赖，且 embedding 模型占内存
  方案B: TF-IDF + BM25 纯文本检索
         → 零依赖，效果对中文已经很好（long_memory.py 验证过）
  选择B，与 long_memory.py 复用 jieba 分词，保持轻量。

架构：
  1. 文档导入：支持 .txt/.md/.json，分块存储到 SQLite
  2. 索引构建：jieba 分词 + TF-IDF 词频表
  3. 检索：BM25 算法匹配 top-K 相关块
  4. 注入：将匹配的文档块作为上下文注入 system prompt
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

from . import db as _db

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False


_lock = threading.Lock()

# 停用词
_STOP_WORDS = {"的", "了", "是", "在", "我", "你", "他", "她", "它",
               "吗", "呢", "啊", "哦", "嗯", "好", "不", "会", "就",
               "也", "都", "还", "有", "没", "很", "把", "被", "让",
               "给", "从", "到", "和", "或", "但", "如果", "因为",
               "所以", "这", "那", "什么", "怎么", "为什么", "可以",
               "能", "要", "应该", "the", "a", "an", "is", "are",
               "was", "were", "in", "on", "at", "to", "for", "of"}


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("main")


# ── 分词 ─────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """中英文混合分词"""
    if not text:
        return []
    if _JIEBA:
        words = list(jieba.cut(text.lower()))
    else:
        words = text.lower().split()
    return [w.strip() for w in words if len(w.strip()) > 1 and w.strip() not in _STOP_WORDS]


# ── 文档导入 ─────────────────────────────────────────────────────────────────

def import_document(
    title: str,
    content: str,
    source: str = "",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> str:
    """
    导入文档，自动分块和索引。

    返回 doc_id。
    """
    doc_id = str(uuid.uuid4())[:8]
    chunks = _split_chunks(content, chunk_size, chunk_overlap)

    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO kb_documents (id, title, source, chunk_count, created_at) VALUES (?,?,?,?,?)",
            (doc_id, title, source, len(chunks), time.time()),
        )
        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}"
            tokens = _tokenize(chunk_text)
            conn.execute(
                "INSERT INTO kb_chunks (id, doc_id, content, tokens, chunk_index) VALUES (?,?,?,?,?)",
                (chunk_id, doc_id, chunk_text, json.dumps(tokens, ensure_ascii=False), i),
            )
        conn.commit()

    # 重建 IDF 缓存
    _rebuild_idf()
    logger.info(f"[KnowledgeBase] 导入文档: {title} ({len(chunks)} 块)")
    return doc_id


def _split_chunks(text: str, size: int, overlap: int) -> List[str]:
    """将文本分割为重叠的块"""
    if len(text) <= size:
        return [text] if text.strip() else []

    chunks = []
    # 优先按段落分割
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 <= size:
            current = current + "\n" + para if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > size:
                # 长段落强制切分
                for j in range(0, len(para), size - overlap):
                    chunk = para[j:j + size]
                    if chunk.strip():
                        chunks.append(chunk)
            else:
                current = para
                continue
            current = ""

    if current.strip():
        chunks.append(current)

    return chunks if chunks else [text[:size]]


def _rebuild_idf():
    """重建逆文档频率缓存"""
    conn = _get_conn()
    all_chunks = conn.execute("SELECT tokens FROM kb_chunks").fetchall()
    total_docs = len(all_chunks)
    if total_docs == 0:
        return

    df_counter: Counter = Counter()
    for row in all_chunks:
        tokens = set(json.loads(row["tokens"]))
        for t in tokens:
            df_counter[t] += 1

    with _lock:
        conn.execute("DELETE FROM kb_idf_cache")
        for term, df in df_counter.items():
            idf = math.log((total_docs + 1) / (df + 1)) + 1
            conn.execute("INSERT INTO kb_idf_cache (term, idf, df) VALUES (?,?,?)", (term, idf, df))
        conn.commit()


# ── 检索 ─────────────────────────────────────────────────────────────────────

def search(query: str, top_k: int = 3) -> List[Dict]:
    """
    BM25 检索相关文档块。

    返回: [{chunk_id, doc_id, content, score, title}]
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    conn = _get_conn()

    # 加载 IDF
    idf_rows = conn.execute("SELECT term, idf FROM kb_idf_cache").fetchall()
    idf_map = {r["term"]: r["idf"] for r in idf_rows}

    # BM25 参数
    k1 = 1.5
    b = 0.75

    # 计算平均文档长度
    all_chunks = conn.execute("SELECT id, tokens, doc_id FROM kb_chunks").fetchall()
    if not all_chunks:
        return []

    avg_dl = sum(len(json.loads(c["tokens"])) for c in all_chunks) / len(all_chunks)

    # 评分
    scores = []
    for chunk in all_chunks:
        tokens = json.loads(chunk["tokens"])
        dl = len(tokens)
        tf_counter = Counter(tokens)
        score = 0.0

        for qt in query_tokens:
            tf = tf_counter.get(qt, 0)
            idf = idf_map.get(qt, 1.0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
            score += idf * numerator / max(denominator, 0.001)

        if score > 0:
            scores.append((chunk["id"], chunk["doc_id"], score))

    scores.sort(key=lambda x: x[2], reverse=True)
    top = scores[:top_k]

    # 获取内容
    results = []
    for chunk_id, doc_id, score in top:
        row = conn.execute("SELECT content FROM kb_chunks WHERE id=?", (chunk_id,)).fetchone()
        doc_row = conn.execute("SELECT title FROM kb_documents WHERE id=?", (doc_id,)).fetchone()
        if row:
            results.append({
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "content": row["content"],
                "score": round(score, 3),
                "title": doc_row["title"] if doc_row else "",
            })

    return results


def build_rag_context(query: str, top_k: int = 3) -> str:
    """
    构建 RAG 上下文注入文本。

    返回空字符串表示无相关知识。
    """
    results = search(query, top_k)
    if not results:
        return ""

    context_parts = ["[知识库参考]"]
    for r in results:
        src = f"（来源: {r['title']}）" if r["title"] else ""
        context_parts.append(f"- {r['content'][:300]}{src}")

    return "\n".join(context_parts)


# ── CRUD ─────────────────────────────────────────────────────────────────────

def list_documents() -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM kb_documents ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: str):
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
        conn.commit()
    _rebuild_idf()


def get_stats() -> Dict:
    conn = _get_conn()
    docs = conn.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
    terms = conn.execute("SELECT COUNT(*) FROM kb_idf_cache").fetchone()[0]
    return {"documents": docs, "chunks": chunks, "terms": terms}
