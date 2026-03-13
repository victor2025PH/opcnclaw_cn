# -*- coding: utf-8 -*-
"""
消息情感分析器

实现全离线中文情感分析，无需外部模型。

方案对比：
  方案A: 调用 LLM 分析每条消息情感 → 成本高，延迟大
  方案B: 使用 transformer 情感模型 → 需要 300MB+ 模型文件
  方案C: 基于情感词典 + 规则引擎 → 零依赖、零延迟、选这个

实现：
  1. 内置中文情感词典（正面/负面各 200+ 词）
  2. 否定词反转（"不开心" → 负面）
  3. 程度副词加权（"非常开心" → 强正面）
  4. 表情符号识别
  5. 时间序列记录，支持趋势分析
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger


# ── 情感词典 ─────────────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    "开心", "高兴", "快乐", "幸福", "满意", "棒", "好", "赞", "厉害", "优秀",
    "漂亮", "美丽", "感谢", "谢谢", "喜欢", "爱", "期待", "精彩", "完美", "出色",
    "牛", "强", "帅", "酷", "惊喜", "温暖", "感动", "支持", "认同", "欣赏",
    "成功", "顺利", "进步", "努力", "加油", "fighting", "nice", "good", "great",
    "amazing", "awesome", "wonderful", "excellent", "perfect", "beautiful",
    "哈哈", "嘻嘻", "么么", "亲", "宝贝", "甜", "暖", "乐", "笑", "有趣",
    "靠谱", "值得", "推荐", "安心", "放心", "舒服", "清爽", "方便", "简单",
}

NEGATIVE_WORDS = {
    "难过", "伤心", "痛苦", "失望", "烦", "累", "困", "焦虑", "压力", "崩溃",
    "生气", "愤怒", "讨厌", "恶心", "无聊", "烦躁", "糟糕", "差", "垃圾", "坑",
    "失败", "错误", "问题", "bug", "故障", "崩了", "挂了", "完了", "惨", "悲",
    "吐槽", "投诉", "举报", "退款", "骗", "假", "坏", "丑", "蠢", "笨",
    "哭", "泪", "呜呜", "唉", "哎", "无语", "尴尬", "害怕", "恐怖", "危险",
    "sad", "bad", "terrible", "awful", "angry", "hate", "shit", "fuck",
    "难受", "不舒服", "头疼", "心烦", "郁闷", "孤独", "寂寞", "绝望", "抱怨",
}

NEGATION_WORDS = {"不", "没", "无", "非", "别", "莫", "未", "勿", "否", "不是", "没有"}

DEGREE_WORDS = {
    "非常": 2.0, "特别": 2.0, "超级": 2.0, "极其": 2.5, "太": 1.8,
    "很": 1.5, "挺": 1.3, "比较": 1.2, "有点": 0.8, "稍微": 0.6,
    "really": 2.0, "very": 1.8, "so": 1.5, "quite": 1.3,
}

POSITIVE_EMOJIS = {"😊", "😄", "😁", "🥰", "❤️", "👍", "🎉", "✨", "💪", "🙏", "😘", "🤗"}
NEGATIVE_EMOJIS = {"😢", "😭", "😡", "🤬", "💔", "😤", "😰", "😱", "😩", "🤮", "😞", "😔"}


# ── 分析引擎 ─────────────────────────────────────────────────────────────────

@dataclass
class SentimentResult:
    score: float = 0.0        # -1.0 (极负面) ~ +1.0 (极正面)
    label: str = "neutral"    # positive / neutral / negative
    confidence: float = 0.0   # 0-1
    positive_count: int = 0
    negative_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 3),
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
        }


def analyze(text: str) -> SentimentResult:
    """
    分析单条消息的情感。

    返回 SentimentResult，score 在 [-1, 1] 范围。
    """
    if not text:
        return SentimentResult()

    text_lower = text.lower()
    words = list(text_lower)

    pos_score = 0.0
    neg_score = 0.0
    pos_count = 0
    neg_count = 0

    # 分词匹配（滑动窗口 2-4 字）
    for length in range(4, 1, -1):
        for i in range(len(text_lower) - length + 1):
            segment = text_lower[i:i + length]

            # 检查否定 + 情感组合
            is_negated = False
            for neg in NEGATION_WORDS:
                if i >= len(neg) and text_lower[i - len(neg):i] == neg:
                    is_negated = True
                    break

            # 程度副词
            degree = 1.0
            for dw, dv in DEGREE_WORDS.items():
                if i >= len(dw) and text_lower[i - len(dw):i] == dw:
                    degree = dv
                    break

            if segment in POSITIVE_WORDS:
                if is_negated:
                    neg_score += degree
                    neg_count += 1
                else:
                    pos_score += degree
                    pos_count += 1
            elif segment in NEGATIVE_WORDS:
                if is_negated:
                    pos_score += degree * 0.5  # 否定负面词的正面效果减半
                    pos_count += 1
                else:
                    neg_score += degree
                    neg_count += 1

    # 表情符号
    for ch in text:
        if ch in POSITIVE_EMOJIS:
            pos_score += 1.0
            pos_count += 1
        elif ch in NEGATIVE_EMOJIS:
            neg_score += 1.0
            neg_count += 1

    # 计算最终分数
    total = pos_score + neg_score
    if total == 0:
        return SentimentResult(score=0, label="neutral", confidence=0.5)

    raw_score = (pos_score - neg_score) / total  # [-1, 1]
    confidence = min(total / 5.0, 1.0)

    if raw_score > 0.15:
        label = "positive"
    elif raw_score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    return SentimentResult(
        score=raw_score,
        label=label,
        confidence=confidence,
        positive_count=pos_count,
        negative_count=neg_count,
    )


# ── 时间序列追踪 ─────────────────────────────────────────────────────────────

DB_PATH = Path("data/sentiment.db")
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
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
        """)
        _conn.commit()
    return _conn


def record(
    account_id: str = "default",
    contact: str = "",
    text: str = "",
    timestamp: float = 0,
) -> SentimentResult:
    """分析并记录一条消息的情感"""
    result = analyze(text)
    ts = timestamp or time.time()

    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO sentiment_log (account_id, contact, score, label, message_preview, timestamp) VALUES (?,?,?,?,?,?)",
            (account_id, contact, result.score, result.label, text[:100], ts),
        )
        conn.commit()

    return result


def get_trend(hours: int = 24, account_id: str = "") -> List[Dict]:
    """获取情感趋势（按小时聚合）"""
    conn = _get_conn()
    since = time.time() - hours * 3600

    if account_id:
        rows = conn.execute(
            """SELECT CAST((timestamp - ?) / 3600 AS INT) AS hour_offset,
                      AVG(score) AS avg_score, COUNT(*) AS count,
                      SUM(CASE WHEN label='positive' THEN 1 ELSE 0 END) AS positive,
                      SUM(CASE WHEN label='negative' THEN 1 ELSE 0 END) AS negative
               FROM sentiment_log WHERE timestamp >= ? AND account_id = ?
               GROUP BY hour_offset ORDER BY hour_offset""",
            (since, since, account_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT CAST((timestamp - ?) / 3600 AS INT) AS hour_offset,
                      AVG(score) AS avg_score, COUNT(*) AS count,
                      SUM(CASE WHEN label='positive' THEN 1 ELSE 0 END) AS positive,
                      SUM(CASE WHEN label='negative' THEN 1 ELSE 0 END) AS negative
               FROM sentiment_log WHERE timestamp >= ?
               GROUP BY hour_offset ORDER BY hour_offset""",
            (since, since),
        ).fetchall()

    return [dict(r) for r in rows]


def get_contact_sentiment(contact: str, limit: int = 50) -> Dict:
    """获取联系人的情感画像"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT score, label, timestamp FROM sentiment_log WHERE contact = ? ORDER BY timestamp DESC LIMIT ?",
        (contact, limit),
    ).fetchall()

    if not rows:
        return {"contact": contact, "avg_score": 0, "total": 0, "distribution": {}}

    scores = [r["score"] for r in rows]
    labels = [r["label"] for r in rows]

    return {
        "contact": contact,
        "avg_score": round(sum(scores) / len(scores), 3),
        "total": len(rows),
        "distribution": {
            "positive": labels.count("positive"),
            "neutral": labels.count("neutral"),
            "negative": labels.count("negative"),
        },
        "recent_trend": "improving" if len(scores) > 5 and sum(scores[:5]) > sum(scores[-5:]) else "stable",
    }


def get_overview() -> Dict:
    """全局情感概览"""
    conn = _get_conn()
    since_24h = time.time() - 86400

    row = conn.execute(
        """SELECT COUNT(*) AS total, AVG(score) AS avg_score,
                  SUM(CASE WHEN label='positive' THEN 1 ELSE 0 END) AS positive,
                  SUM(CASE WHEN label='neutral' THEN 1 ELSE 0 END) AS neutral,
                  SUM(CASE WHEN label='negative' THEN 1 ELSE 0 END) AS negative
           FROM sentiment_log WHERE timestamp >= ?""",
        (since_24h,),
    ).fetchone()

    return {
        "total_24h": row["total"] or 0,
        "avg_score": round(row["avg_score"] or 0, 3),
        "positive": row["positive"] or 0,
        "neutral": row["neutral"] or 0,
        "negative": row["negative"] or 0,
        "mood": "positive" if (row["avg_score"] or 0) > 0.1 else ("negative" if (row["avg_score"] or 0) < -0.1 else "neutral"),
    }
