# -*- coding: utf-8 -*-
"""
朋友圈数据分析引擎

功能：
  1. 互动数据采集 — 所有点赞/评论/发布自动记录
  2. 内容效果分析 — 哪些类型内容获得最多互动
  3. 最佳发布时间 — 分析不同时段的互动率
  4. 联系人活跃度 — 分析谁最活跃、互动频率
  5. AI 策略建议 — 基于数据生成内容优化建议

优化思考：
  不做重量级的数据仓库，用 SQLite + 简单聚合即可。
  关键是让数据采集零侵入——嵌入到 moments_actor 和 moments_ai 的现有流程。
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .. import db as _db


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


# ── 数据采集 ──────────────────────────────────────────────────────────────────

def record_event(
    event_type: str,
    target_author: str = "",
    content_text: str = "",
    content_category: str = "",
    content_tags: List[str] = None,
    extra: Dict = None,
):
    """
    记录一次互动事件。

    event_type: like / comment / publish / browse / reply_received / like_received
    """
    now = datetime.now()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO events (event_type, target_author, content_text, content_category, "
        "content_tags, hour, weekday, timestamp, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            target_author,
            content_text[:200],
            content_category,
            json.dumps(content_tags or [], ensure_ascii=False),
            now.hour,
            now.weekday(),
            time.time(),
            json.dumps(extra or {}, ensure_ascii=False),
        ),
    )
    conn.commit()


def record_publish(text: str, category: str = "", tags: List[str] = None):
    """记录我发布的朋友圈"""
    now = datetime.now()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO moments_stats (text, category, tags, published_at, hour, weekday) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (text[:500], category, json.dumps(tags or [], ensure_ascii=False),
         time.time(), now.hour, now.weekday()),
    )
    conn.commit()
    record_event("publish", content_text=text, content_category=category, content_tags=tags)


def update_publish_engagement(publish_id: int, likes: int = 0, comments: int = 0):
    """更新一条发布的互动数据"""
    conn = _get_conn()
    score = likes * 1.0 + comments * 2.5
    conn.execute(
        "UPDATE moments_stats SET likes_received = ?, comments_received = ?, "
        "engagement_score = ? WHERE id = ?",
        (likes, comments, score, publish_id),
    )
    conn.commit()


# ── 分析报告 ──────────────────────────────────────────────────────────────────

def get_overview(days: int = 30) -> Dict:
    """总览：最近 N 天的互动统计"""
    conn = _get_conn()
    since = time.time() - days * 86400

    counts = {}
    for et in ["like", "comment", "publish", "browse", "reply_received"]:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ? AND timestamp > ?",
            (et, since),
        ).fetchone()
        counts[et] = row[0] if row else 0

    pub_count = conn.execute(
        "SELECT COUNT(*) FROM moments_stats WHERE published_at > ?", (since,)
    ).fetchone()[0]
    avg_eng = conn.execute(
        "SELECT AVG(engagement_score) FROM moments_stats WHERE published_at > ?", (since,)
    ).fetchone()[0] or 0

    return {
        "period_days": days,
        "total_likes_given": counts.get("like", 0),
        "total_comments_given": counts.get("comment", 0),
        "total_publishes": counts.get("publish", 0),
        "total_browses": counts.get("browse", 0),
        "replies_received": counts.get("reply_received", 0),
        "publish_count": pub_count,
        "avg_engagement": round(avg_eng, 1),
    }


def get_hourly_distribution(days: int = 30) -> List[Dict]:
    """分时段互动分布——找出最佳发布时间"""
    conn = _get_conn()
    since = time.time() - days * 86400

    rows = conn.execute(
        "SELECT hour, event_type, COUNT(*) as cnt "
        "FROM events WHERE timestamp > ? GROUP BY hour, event_type",
        (since,),
    ).fetchall()

    dist = defaultdict(lambda: {"likes": 0, "comments": 0, "total": 0})
    for r in rows:
        h = r["hour"]
        if r["event_type"] == "like":
            dist[h]["likes"] += r["cnt"]
        elif r["event_type"] == "comment":
            dist[h]["comments"] += r["cnt"]
        dist[h]["total"] += r["cnt"]

    result = []
    for h in range(24):
        d = dist[h]
        result.append({"hour": h, **d})
    return result


def get_top_contacts(days: int = 30, limit: int = 10) -> List[Dict]:
    """最活跃互动联系人"""
    conn = _get_conn()
    since = time.time() - days * 86400

    rows = conn.execute(
        "SELECT target_author, "
        "SUM(CASE WHEN event_type='like' THEN 1 ELSE 0 END) as likes, "
        "SUM(CASE WHEN event_type='comment' THEN 1 ELSE 0 END) as comments, "
        "COUNT(*) as total "
        "FROM events WHERE target_author != '' AND timestamp > ? "
        "GROUP BY target_author ORDER BY total DESC LIMIT ?",
        (since, limit),
    ).fetchall()

    return [{"author": r["target_author"], "likes": r["likes"],
             "comments": r["comments"], "total": r["total"]} for r in rows]


def get_content_performance(days: int = 30) -> List[Dict]:
    """各分类内容的表现分析"""
    conn = _get_conn()
    since = time.time() - days * 86400

    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt, "
        "AVG(engagement_score) as avg_eng, "
        "SUM(likes_received) as total_likes, "
        "SUM(comments_received) as total_comments "
        "FROM moments_stats WHERE published_at > ? AND category != '' "
        "GROUP BY category ORDER BY avg_eng DESC",
        (since,),
    ).fetchall()

    return [{"category": r["category"], "count": r["cnt"],
             "avg_engagement": round(r["avg_eng"] or 0, 1),
             "total_likes": r["total_likes"] or 0,
             "total_comments": r["total_comments"] or 0} for r in rows]


def get_best_posting_times(days: int = 30) -> Dict:
    """推荐最佳发布时间段"""
    conn = _get_conn()
    since = time.time() - days * 86400

    rows = conn.execute(
        "SELECT hour, AVG(engagement_score) as avg_eng, COUNT(*) as cnt "
        "FROM moments_stats WHERE published_at > ? "
        "GROUP BY hour HAVING cnt >= 1 ORDER BY avg_eng DESC",
        (since,),
    ).fetchall()

    if not rows:
        return {"best_hours": [9, 12, 18, 21], "source": "default"}

    best = [r["hour"] for r in rows[:4]]
    return {
        "best_hours": best,
        "details": [{"hour": r["hour"], "avg_engagement": round(r["avg_eng"], 1),
                      "sample_count": r["cnt"]} for r in rows],
        "source": "data",
    }


def get_weekly_trend(weeks: int = 8) -> List[Dict]:
    """周趋势：最近 N 周的互动量"""
    conn = _get_conn()
    results = []
    now = time.time()

    for w in range(weeks):
        end = now - w * 7 * 86400
        start = end - 7 * 86400
        row = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN event_type='like' THEN 1 ELSE 0 END) as likes, "
            "SUM(CASE WHEN event_type='comment' THEN 1 ELSE 0 END) as comments "
            "FROM events WHERE timestamp BETWEEN ? AND ?",
            (start, end),
        ).fetchone()
        week_label = datetime.fromtimestamp(start).strftime("%m/%d")
        results.append({
            "week": week_label,
            "total": row["total"] or 0,
            "likes": row["likes"] or 0,
            "comments": row["comments"] or 0,
        })

    return list(reversed(results))


async def generate_strategy_report(ai_call: Callable, days: int = 30) -> str:
    """AI 生成内容策略优化报告"""
    overview = get_overview(days)
    hourly = get_hourly_distribution(days)
    top_contacts = get_top_contacts(days, 5)
    performance = get_content_performance(days)
    best_times = get_best_posting_times(days)

    peak_hours = [h for h in hourly if h["total"] > 0]
    peak_hours.sort(key=lambda x: x["total"], reverse=True)

    prompt = f"""基于以下朋友圈互动数据，生成一份简洁的内容策略优化建议：

## 互动概览（近{days}天）
- 点赞: {overview['total_likes_given']} 次
- 评论: {overview['total_comments_given']} 次
- 发布: {overview['total_publishes']} 条
- 平均互动分: {overview['avg_engagement']}

## 最活跃联系人
{json.dumps(top_contacts, ensure_ascii=False, indent=2)}

## 内容分类表现
{json.dumps(performance, ensure_ascii=False, indent=2)}

## 推荐发布时间
{json.dumps(best_times, ensure_ascii=False, indent=2)}

## 高互动时段 (Top 5)
{json.dumps(peak_hours[:5], ensure_ascii=False, indent=2)}

请给出：
1. 内容策略调整（什么类型内容应该增加/减少）
2. 发布时间优化
3. 互动策略（与谁互动更多、互动风格调整）
4. 一句话总结

简洁实用，中文回答。"""

    if not ai_call:
        return "需要 AI 后端才能生成策略报告"

    try:
        return await ai_call([{"role": "user", "content": prompt}])
    except Exception as e:
        return f"报告生成失败: {e}"
