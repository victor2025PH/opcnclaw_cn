# -*- coding: utf-8 -*-
"""
社交画像 + 亲密度系统

为每个联系人维护一份"社交画像"，驱动差异化互动策略：
  - 关系标签（亲人/好友/同事/客户/普通）
  - 亲密度评分 0-100（基于互动频率自动衰减+增长）
  - 兴趣标签（从朋友圈内容中 AI 提取）
  - 互动历史（最近的点赞/评论/回复记录）
  - 评论风格偏好（正式/轻松/幽默）

数据持久化到 SQLite，跨模块共享：
  - 朋友圈AI引擎用它决定互动策略
  - 自动回复引擎用它调整回复风格
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from .. import db as _db


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


# ── 数据模型 ─────────────────────────────────────────────────────────────────────

RELATIONSHIP_TYPES = ["family", "close_friend", "friend", "colleague", "client", "normal"]
COMMENT_STYLES = ["formal", "casual", "humorous", "warm", "professional"]

RELATIONSHIP_CN = {
    "family": "亲人", "close_friend": "密友", "friend": "好友",
    "colleague": "同事", "client": "客户", "normal": "普通",
}

STYLE_CN = {
    "formal": "正式", "casual": "轻松", "humorous": "幽默",
    "warm": "温暖", "professional": "专业",
}


@dataclass
class ContactProfile:
    name: str
    relationship: str = "normal"
    intimacy: float = 30.0          # 0-100
    interests: List[str] = field(default_factory=list)
    comment_style: str = "casual"
    notes: str = ""
    total_likes: int = 0
    total_comments: int = 0
    total_replies: int = 0
    last_interaction: float = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def interaction_rate(self) -> str:
        """基于亲密度返回推荐互动率"""
        if self.intimacy >= 80:
            return "high"       # 80% 点赞，40% 评论
        elif self.intimacy >= 50:
            return "medium"     # 50% 点赞，15% 评论
        elif self.intimacy >= 20:
            return "low"        # 20% 点赞，5% 评论
        return "minimal"        # 偶尔点赞

    @property
    def like_probability(self) -> float:
        if self.intimacy >= 80:
            return 0.8
        elif self.intimacy >= 50:
            return 0.5
        elif self.intimacy >= 20:
            return 0.2
        return 0.05

    @property
    def comment_probability(self) -> float:
        if self.intimacy >= 80:
            return 0.4
        elif self.intimacy >= 50:
            return 0.15
        elif self.intimacy >= 20:
            return 0.05
        return 0.0

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "relationship": self.relationship,
            "relationship_cn": RELATIONSHIP_CN.get(self.relationship, "普通"),
            "intimacy": round(self.intimacy, 1),
            "interests": self.interests,
            "comment_style": self.comment_style,
            "style_cn": STYLE_CN.get(self.comment_style, "轻松"),
            "notes": self.notes,
            "total_likes": self.total_likes,
            "total_comments": self.total_comments,
            "total_replies": self.total_replies,
            "last_interaction": self.last_interaction,
            "interaction_rate": self.interaction_rate,
            "like_probability": self.like_probability,
            "comment_probability": self.comment_probability,
        }


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_profile(name: str) -> ContactProfile:
    """获取联系人画像，不存在则创建默认"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
    if row:
        return _row_to_profile(row)
    profile = ContactProfile(name=name)
    save_profile(profile)
    return profile


def save_profile(profile: ContactProfile):
    conn = _get_conn()
    profile.updated_at = time.time()
    conn.execute(
        """INSERT OR REPLACE INTO profiles
           (name, relationship, intimacy, interests, comment_style, notes,
            total_likes, total_comments, total_replies, last_interaction,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (profile.name, profile.relationship, profile.intimacy,
         json.dumps(profile.interests, ensure_ascii=False),
         profile.comment_style, profile.notes,
         profile.total_likes, profile.total_comments, profile.total_replies,
         profile.last_interaction, profile.created_at, profile.updated_at),
    )
    conn.commit()


def list_profiles(min_intimacy: float = 0) -> List[ContactProfile]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM profiles WHERE intimacy >= ? ORDER BY intimacy DESC",
        (min_intimacy,),
    ).fetchall()
    return [_row_to_profile(r) for r in rows]


def update_intimacy(name: str, delta: float):
    """增减亲密度（自动钳位到 0-100）"""
    profile = get_profile(name)
    profile.intimacy = max(0, min(100, profile.intimacy + delta))
    save_profile(profile)


def record_interaction(name: str, action: str, content: str = "", post_text: str = ""):
    """记录一次互动，同时更新画像计数和亲密度"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO interactions (contact, action, content, post_text, timestamp) VALUES (?, ?, ?, ?, ?)",
        (name, action, content, post_text, time.time()),
    )
    conn.commit()

    profile = get_profile(name)
    profile.last_interaction = time.time()
    delta = 0.0
    if action == "like":
        profile.total_likes += 1
        delta = 1.0
    elif action == "comment":
        profile.total_comments += 1
        delta = 3.0
    elif action == "reply":
        profile.total_replies += 1
        delta = 2.0
    profile.intimacy = max(0, min(100, profile.intimacy + delta))
    save_profile(profile)


def get_recent_interactions(name: str, limit: int = 20) -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM interactions WHERE contact = ? ORDER BY timestamp DESC LIMIT ?",
        (name, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def decay_all_intimacy(factor: float = 0.98):
    """
    全局亲密度衰减（每日调用一次）。
    长期不互动的联系人亲密度自然下降。
    """
    conn = _get_conn()
    conn.execute("UPDATE profiles SET intimacy = MAX(5, intimacy * ?)", (factor,))
    conn.commit()


def update_interests(name: str, new_interests: List[str]):
    """更新兴趣标签（AI 提取后调用）"""
    profile = get_profile(name)
    existing = set(profile.interests)
    existing.update(new_interests)
    profile.interests = sorted(existing)[:20]
    save_profile(profile)


def get_stats() -> Dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM profiles").fetchone()["c"]
    active = conn.execute(
        "SELECT COUNT(*) as c FROM profiles WHERE last_interaction > ?",
        (time.time() - 7 * 86400,),
    ).fetchone()["c"]
    today_interactions = conn.execute(
        "SELECT COUNT(*) as c FROM interactions WHERE timestamp > ?",
        (time.time() - 86400,),
    ).fetchone()["c"]
    return {
        "total_profiles": total,
        "active_7d": active,
        "today_interactions": today_interactions,
    }


def _row_to_profile(row) -> ContactProfile:
    interests = []
    try:
        interests = json.loads(row["interests"] or "[]")
    except Exception:
        pass
    return ContactProfile(
        name=row["name"],
        relationship=row["relationship"] or "normal",
        intimacy=row["intimacy"] or 30.0,
        interests=interests,
        comment_style=row["comment_style"] or "casual",
        notes=row["notes"] or "",
        total_likes=row["total_likes"] or 0,
        total_comments=row["total_comments"] or 0,
        total_replies=row["total_replies"] or 0,
        last_interaction=row["last_interaction"] or 0,
        created_at=row["created_at"] or 0,
        updated_at=row["updated_at"] or 0,
    )
