"""
技能使用统计模块

深度思考：
  原方案：单独的 stats.json 文件（存在并发写入问题）
  
  优化方案：SQLite + WAL 模式（并发安全，查询灵活）
  
  进一步优化：
  - 不仅记录"调用次数"，还记录"调用时间分布"（用于分析高峰时段）
  - 添加"满意度"字段（未来可扩展用户反馈）
  - 提供"推荐算法"：基于使用频率 + 时间衰减（最近的更重要）
  
  推荐算法（时间加权热度）：
    score = Σ (1 / (1 + age_hours)) 
    其中 age_hours 是每次调用距今的小时数
    
  效果：最近调用的技能权重高，长久不用的技能会"冷却"
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DB_PATH = Path("data/stats.db")


@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skill_usage (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id  TEXT    NOT NULL,
                ts        REAL    NOT NULL,       -- Unix 时间戳
                session   TEXT,                   -- 会话 ID（可空）
                input     TEXT,                   -- 用户输入（脱敏截断）
                success   INTEGER DEFAULT 1       -- 是否成功
            );
            CREATE INDEX IF NOT EXISTS idx_skill_ts ON skill_usage(skill_id, ts);

            CREATE TABLE IF NOT EXISTS skill_meta_cache (
                skill_id   TEXT PRIMARY KEY,
                name_zh    TEXT,
                category   TEXT,
                icon       TEXT,
                updated_at REAL
            );
        """)


_ensure_tables()


# ──────────────────────────────────────────────────────────
# 写入
# ──────────────────────────────────────────────────────────

def record_usage(
    skill_id: str,
    session_id: str = None,
    user_input: str = "",
    success: bool = True,
):
    """记录一次技能调用"""
    truncated_input = (user_input or "")[:100]  # 截断保护隐私
    with _db() as conn:
        conn.execute(
            "INSERT INTO skill_usage (skill_id, ts, session, input, success) VALUES (?,?,?,?,?)",
            (skill_id, time.time(), session_id, truncated_input, 1 if success else 0),
        )


# ──────────────────────────────────────────────────────────
# 读取 & 分析
# ──────────────────────────────────────────────────────────

def get_skill_stats(limit: int = 20) -> List[Dict]:
    """
    获取技能热度排行（时间衰减加权）
    
    热度公式：score = Σ decay(age_hours)
    其中 decay(h) = 1 / (1 + h/24)  （24小时半衰期）
    """
    with _db() as conn:
        now = time.time()
        rows = conn.execute("""
            SELECT skill_id,
                   COUNT(*) as total,
                   MAX(ts)  as last_used,
                   SUM(CASE WHEN (? - ts) < 86400 THEN 1 ELSE 0 END) as today
            FROM skill_usage
            GROUP BY skill_id
            ORDER BY total DESC
            LIMIT ?
        """, (now, limit * 2)).fetchall()

    # 计算时间加权分数
    results = []
    for row in rows:
        skill_id, total, last_used, today = row
        # 获取最近50次的时间戳算热度
        with _db() as conn:
            timestamps = conn.execute(
                "SELECT ts FROM skill_usage WHERE skill_id=? ORDER BY ts DESC LIMIT 50",
                (skill_id,),
            ).fetchall()

        score = sum(1.0 / (1.0 + (now - t[0]) / 3600 / 24) for t in timestamps)

        results.append({
            "skill_id": skill_id,
            "total_calls": total,
            "today_calls": today,
            "last_used": last_used,
            "last_used_ago": _ago(last_used),
            "heat_score": round(score, 2),
        })

    results.sort(key=lambda x: x["heat_score"], reverse=True)
    return results[:limit]


def get_recent_skills(limit: int = 5) -> List[str]:
    """获取最近使用的技能 ID 列表（去重）"""
    with _db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT skill_id
            FROM skill_usage
            ORDER BY ts DESC
            LIMIT ?
        """, (limit * 3,)).fetchall()

    seen = []
    for (skill_id,) in rows:
        if skill_id not in seen:
            seen.append(skill_id)
        if len(seen) >= limit:
            break
    return seen


def get_popular_skills(limit: int = 6) -> List[str]:
    """获取最热门的技能（用于首屏推荐）"""
    stats = get_skill_stats(limit)
    return [s["skill_id"] for s in stats]


def get_summary() -> Dict:
    """获取统计摘要"""
    with _db() as conn:
        total_calls = conn.execute("SELECT COUNT(*) FROM skill_usage").fetchone()[0]
        today_calls = conn.execute(
            "SELECT COUNT(*) FROM skill_usage WHERE ts > ?",
            (time.time() - 86400,),
        ).fetchone()[0]
        top_skill = conn.execute(
            "SELECT skill_id, COUNT(*) as c FROM skill_usage GROUP BY skill_id ORDER BY c DESC LIMIT 1"
        ).fetchone()
        unique_skills = conn.execute(
            "SELECT COUNT(DISTINCT skill_id) FROM skill_usage"
        ).fetchone()[0]

    return {
        "total_calls": total_calls,
        "today_calls": today_calls,
        "top_skill": top_skill[0] if top_skill else None,
        "unique_skills_used": unique_skills,
    }


def get_usage_heatmap(days: int = 7) -> List[Dict]:
    """获取近N天每天的调用量（用于热力图）"""
    now = time.time()
    with _db() as conn:
        rows = conn.execute("""
            SELECT DATE(ts, 'unixepoch', 'localtime') as day,
                   COUNT(*) as calls
            FROM skill_usage
            WHERE ts > ?
            GROUP BY day
            ORDER BY day
        """, (now - days * 86400,)).fetchall()
    return [{"date": r[0], "calls": r[1]} for r in rows]


def _ago(ts: float) -> str:
    """时间戳转人类可读时间（如：5分钟前）"""
    diff = time.time() - ts
    if diff < 60:
        return "刚才"
    if diff < 3600:
        return f"{int(diff/60)}分钟前"
    if diff < 86400:
        return f"{int(diff/3600)}小时前"
    return f"{int(diff/86400)}天前"
