# -*- coding: utf-8 -*-
"""
Agent 记忆系统 — 让 Agent 越用越聪明

每个 Agent 记住：
  1. 历史任务和成果（知道自己做过什么）
  2. 用户偏好（老板喜欢什么风格）
  3. 团队协作记录（跟谁合作过，什么效果好）

存储：SQLite agent_memory 表
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from loguru import logger


def save_agent_memory(agent_id: str, agent_name: str, task: str,
                      result: str, team_name: str = "", feedback: str = ""):
    """保存 Agent 的工作记忆"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT, agent_name TEXT,
                task TEXT, result_preview TEXT,
                team_name TEXT, feedback TEXT,
                created_at REAL
            )
        """)
        conn.execute(
            "INSERT INTO agent_memory (agent_id, agent_name, task, result_preview, team_name, feedback, created_at) VALUES (?,?,?,?,?,?,?)",
            (agent_id, agent_name, task[:200], result[:500], team_name, feedback, time.time()),
        )
        # 保留最近 100 条记忆
        conn.execute("DELETE FROM agent_memory WHERE id NOT IN (SELECT id FROM agent_memory ORDER BY created_at DESC LIMIT 100)")
        conn.commit()
    except Exception as e:
        logger.debug(f"[AgentMemory] save failed: {e}")


def get_agent_memory(agent_id: str, limit: int = 5) -> List[Dict]:
    """获取 Agent 的历史记忆"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        rows = conn.execute(
            "SELECT task, result_preview, team_name, feedback, created_at FROM agent_memory WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [
            {"task": r[0], "result": r[1], "team": r[2], "feedback": r[3], "time": r[4]}
            for r in rows
        ]
    except Exception:
        return []


def get_agent_context(agent_id: str) -> str:
    """获取 Agent 的记忆上下文（注入到 system prompt）"""
    memories = get_agent_memory(agent_id, 3)
    if not memories:
        # 即使没有历史记忆，也检查是否有反馈
        fb = get_agent_feedback_summary(agent_id)
        return fb

    ctx = "\n\n## 你的历史记忆（之前做过的工作）\n"
    for m in memories:
        ctx += f"- 任务：{m['task']}，成果摘要：{m['result'][:100]}\n"
        if m.get('feedback'):
            ctx += f"  [!] 老板反馈：{m['feedback']}\n"

    # 追加反馈汇总（确保负面反馈被强调）
    fb = get_agent_feedback_summary(agent_id)
    if fb:
        ctx += fb

    return ctx


def save_feedback(agent_id: str, feedback: str, task_hint: str = ""):
    """保存用户对 Agent 工作的反馈（更新最近一条记忆的 feedback 字段）"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        if task_hint:
            # 找到匹配任务的最近记录 ID
            row = conn.execute(
                "SELECT id FROM agent_memory WHERE agent_id=? AND task LIKE ? ORDER BY created_at DESC LIMIT 1",
                (agent_id, f"%{task_hint[:50]}%"),
            ).fetchone()
            if row:
                conn.execute("UPDATE agent_memory SET feedback=? WHERE id=?", (feedback, row[0]))
        else:
            # 找到该 Agent 最近一条记忆 ID
            row = conn.execute(
                "SELECT id FROM agent_memory WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row:
                conn.execute("UPDATE agent_memory SET feedback=? WHERE id=?", (feedback, row[0]))
        conn.commit()
        logger.info(f"[AgentMemory] 保存反馈: {agent_id} <- {feedback[:50]}")
    except Exception as e:
        logger.debug(f"[AgentMemory] save_feedback failed: {e}")


def get_agent_feedback_summary(agent_id: str) -> str:
    """获取 Agent 收到的负面反馈摘要（用于 prompt 注入避免重复错误）"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        rows = conn.execute(
            "SELECT task, feedback FROM agent_memory WHERE agent_id=? AND feedback!='' AND feedback IS NOT NULL ORDER BY created_at DESC LIMIT 5",
            (agent_id,),
        ).fetchall()
        if not rows:
            return ""
        lines = []
        for task, fb in rows:
            lines.append(f"- 任务「{task[:30]}」：老板说「{fb[:80]}」")
        return "\n\n## 老板之前的反馈（务必注意）\n" + "\n".join(lines)
    except Exception:
        return ""


def save_user_preference(key: str, value: str):
    """保存用户偏好"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY, value TEXT, updated_at REAL
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?,?,?)",
            (key, value, time.time()),
        )
        conn.commit()
    except Exception:
        pass


def get_user_preference(key: str, default: str = "") -> str:
    """获取用户偏好"""
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        row = conn.execute("SELECT value FROM user_preferences WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default
