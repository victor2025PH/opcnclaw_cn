# -*- coding: utf-8 -*-
"""
护城河分数 — 量化用户的不可替代程度

0-100 分，越高越难被替代。
分为 6 个维度，每维度最高 ~17 分。

用于：
  1. 欢迎页状态条（一进来就看到价值）
  2. 设置页画像 tab 详细展示
  3. 产品运营数据分析
"""

from __future__ import annotations

import json
import time
from typing import Dict

from loguru import logger

# 缓存（避免频繁 DB 查询）
_cache: Dict = {}
_cache_time: float = 0
_CACHE_TTL = 30  # 30 秒


def calculate_moat_score() -> Dict:
    global _cache, _cache_time
    if time.time() - _cache_time < _CACHE_TTL and _cache:
        return _cache
    """计算护城河综合分数"""
    scores = {
        "profile": 0,       # 用户画像完整度
        "memory": 0,        # Agent 记忆深度
        "projects": 0,      # 项目积累
        "evolution": 0,     # Agent 进化程度
        "feedback": 0,      # 反馈学习
        "interaction": 0,   # 交互深度
    }
    details = {}
    total_max = 100

    # ── 1. 用户画像完整度 (0-20) ──
    try:
        from .user_profile_ai import get_user_profile
        p = get_user_profile()
        filled = 0
        fields = ["company", "industry", "target_users", "brand_tone",
                  "writing_style", "budget_range", "team_size"]
        for f in fields:
            if p.get(f):
                filled += 1
        if p.get("products"):
            filled += min(len(p["products"]), 3)  # 最多 +3
        if p.get("common_terms"):
            filled += min(len(p["common_terms"]) // 3, 2)  # 最多 +2
        if p.get("competitor_names"):
            filled += 1
        if p.get("auto_style"):
            filled += 1

        scores["profile"] = min(round(filled / 14 * 20), 20)
        details["profile"] = {
            "label": "用户画像",
            "score": scores["profile"],
            "max": 20,
            "tip": f"已填写 {filled}/14 个字段" if filled < 10 else "画像丰富",
        }
    except Exception:
        details["profile"] = {"label": "用户画像", "score": 0, "max": 20, "tip": "未开始"}

    # ── 2. Agent 记忆深度 (0-20) ──
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        row = conn.execute("SELECT COUNT(*) FROM agent_memory").fetchone()
        mem_count = row[0] if row else 0
        scores["memory"] = min(round(mem_count / 50 * 20), 20)
        details["memory"] = {
            "label": "Agent 记忆",
            "score": scores["memory"],
            "max": 20,
            "tip": f"{mem_count} 条记忆",
        }
    except Exception:
        details["memory"] = {"label": "Agent 记忆", "score": 0, "max": 20, "tip": "0 条"}

    # ── 3. 项目积累 (0-20) ──
    try:
        from .project_workspace import list_projects
        projects = list_projects()
        proj_count = len(projects)
        total_files = sum(len(p.get("artifacts", [])) for p in projects)
        scores["projects"] = min(round(proj_count / 10 * 15 + total_files / 20 * 5), 20)
        details["projects"] = {
            "label": "项目积累",
            "score": scores["projects"],
            "max": 20,
            "tip": f"{proj_count} 个项目，{total_files} 个文件",
        }
    except Exception:
        details["projects"] = {"label": "项目积累", "score": 0, "max": 20, "tip": "0 个项目"}

    # ── 4. Agent 进化程度 (0-15) ──
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        # 统计有多少个不同 Agent 工作过
        row = conn.execute("SELECT COUNT(DISTINCT agent_id) FROM agent_memory").fetchone()
        agents_active = row[0] if row else 0
        # 统计最高任务数的 Agent
        row2 = conn.execute("SELECT MAX(cnt) FROM (SELECT COUNT(*) as cnt FROM agent_memory GROUP BY agent_id)").fetchone()
        max_tasks = row2[0] if row2 and row2[0] else 0
        scores["evolution"] = min(round(agents_active / 10 * 8 + max_tasks / 10 * 7), 15)
        details["evolution"] = {
            "label": "Agent 进化",
            "score": scores["evolution"],
            "max": 15,
            "tip": f"{agents_active} 个 Agent 有经验，最高 {max_tasks} 次任务",
        }
    except Exception:
        details["evolution"] = {"label": "Agent 进化", "score": 0, "max": 15, "tip": "未开始"}

    # ── 5. 反馈学习 (0-10) ──
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        row = conn.execute("SELECT COUNT(*) FROM agent_memory WHERE feedback != '' AND feedback IS NOT NULL").fetchone()
        fb_count = row[0] if row else 0
        scores["feedback"] = min(round(fb_count / 10 * 10), 10)
        details["feedback"] = {
            "label": "反馈学习",
            "score": scores["feedback"],
            "max": 10,
            "tip": f"已提供 {fb_count} 次反馈",
        }
    except Exception:
        details["feedback"] = {"label": "反馈学习", "score": 0, "max": 10, "tip": "0 次"}

    # ── 6. 交互深度 (0-15) ──
    try:
        from .user_profile_ai import get_user_profile
        p = get_user_profile()
        interactions = p.get("interaction_count", 0)
        scores["interaction"] = min(round(interactions / 100 * 15), 15)
        details["interaction"] = {
            "label": "交互深度",
            "score": scores["interaction"],
            "max": 15,
            "tip": f"已交互 {interactions} 次",
        }
    except Exception:
        details["interaction"] = {"label": "交互深度", "score": 0, "max": 15, "tip": "0 次"}

    total = sum(scores.values())
    # 等级映射
    if total >= 80:
        level = "深度绑定"
        level_icon = "🏆"
        level_desc = "AI 已成为你业务的核心助手，换工具成本极高"
    elif total >= 60:
        level = "高度依赖"
        level_icon = "🥇"
        level_desc = "Agent 团队已非常了解你的业务"
    elif total >= 40:
        level = "持续积累"
        level_icon = "🥈"
        level_desc = "AI 正在学习你的业务，继续使用会越来越强"
    elif total >= 20:
        level = "初步了解"
        level_icon = "🥉"
        level_desc = "AI 开始认识你了，多聊几句效果更好"
    else:
        level = "刚刚开始"
        level_icon = "🌱"
        level_desc = "告诉 AI 你的公司和产品，AI 会越来越懂你"

    # 生成增长任务
    tasks = _generate_growth_tasks(scores, details)

    result = {
        "total": total,
        "max": total_max,
        "percentage": round(total / total_max * 100),
        "level": level,
        "level_icon": level_icon,
        "level_desc": level_desc,
        "scores": scores,
        "details": details,
        "growth_tasks": tasks,
    }

    _cache = result
    _cache_time = time.time()
    return result


def _generate_growth_tasks(scores: Dict, details: Dict) -> list:
    """根据当前分数生成具体的增长任务"""
    tasks = []

    # 画像任务
    if scores["profile"] < 10:
        tip = details.get("profile", {}).get("tip", "")
        tasks.append({
            "id": "fill_profile",
            "icon": "🏢",
            "title": "填写公司信息",
            "desc": "在设置→我的画像中填写公司名和行业",
            "reward": "+5 分",
            "action": "open_profile",
            "done": scores["profile"] >= 10,
        })
    if scores["profile"] < 15:
        tasks.append({
            "id": "add_product",
            "icon": "📦",
            "title": "添加产品信息",
            "desc": "添加你的产品名称，AI 才能精准推荐",
            "reward": "+3 分",
            "action": "open_profile",
            "done": scores["profile"] >= 15,
        })

    # 交互任务
    if scores["interaction"] < 5:
        tasks.append({
            "id": "chat_10",
            "icon": "💬",
            "title": "与 AI 聊 10 次",
            "desc": "多聊几句，AI 会自动学习你的风格",
            "reward": "+3 分",
            "action": "chat",
            "done": scores["interaction"] >= 5,
        })

    # 团队任务
    if scores["memory"] < 5:
        tasks.append({
            "id": "first_team",
            "icon": "👥",
            "title": "部署第一个团队任务",
            "desc": "说'帮我写一个营销方案'试试",
            "reward": "+5 分",
            "action": "chat",
            "done": scores["memory"] >= 5,
        })

    # 项目任务
    if scores["projects"] < 5:
        tasks.append({
            "id": "first_project",
            "icon": "📁",
            "title": "完成第一个项目",
            "desc": "团队完成后会生成项目文件夹",
            "reward": "+5 分",
            "action": "chat",
            "done": scores["projects"] >= 5,
        })

    # 反馈任务
    if scores["feedback"] < 3:
        tasks.append({
            "id": "first_feedback",
            "icon": "👍",
            "title": "给团队一次反馈",
            "desc": "团队完成后点👍或👎，Agent 会记住",
            "reward": "+3 分",
            "action": "chat",
            "done": scores["feedback"] >= 3,
        })

    # 进化任务
    if scores["evolution"] < 5:
        tasks.append({
            "id": "agent_evolve",
            "icon": "⭐",
            "title": "让 Agent 进化",
            "desc": "同一个 Agent 做 3 次以上任务就会进化",
            "reward": "+4 分",
            "action": "chat",
            "done": scores["evolution"] >= 5,
        })

    # 高级任务
    if scores["profile"] >= 10 and scores["memory"] >= 5:
        tasks.append({
            "id": "backup",
            "icon": "💾",
            "title": "备份 AI 数据",
            "desc": "导出数据防止丢失",
            "reward": "安心",
            "action": "open_profile",
            "done": False,
        })

    return tasks[:6]  # 最多显示 6 个
