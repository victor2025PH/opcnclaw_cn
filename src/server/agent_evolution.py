# -*- coding: utf-8 -*-
"""
Agent 专长进化 — 根据历史任务和反馈自动微调 Agent 能力描述

每个 Agent 完成足够多任务后（>=5次），自动分析其擅长领域，
生成"专家标签"注入到 system prompt，让 Agent 越用越专业。

进化逻辑：
  1. 统计 Agent 历史任务的关键词频率
  2. 统计正面/负面反馈模式
  3. 生成专长描述（如"电商营销专家"、"擅长简洁文案"）
  4. 注入到 Agent prompt，影响下次产出风格

护城河：Agent 的专长和用户画像是配套的 —
换工具后 Agent 不认识你的业务，也不知道你喜欢什么风格。
"""

from __future__ import annotations

import re
import json
import time
from collections import Counter
from typing import Dict, List, Optional

from loguru import logger


def get_agent_expertise(agent_id: str) -> str:
    """获取 Agent 的专长标签（注入到 system prompt）"""
    try:
        from .agent_memory import get_agent_memory

        memories = get_agent_memory(agent_id, limit=20)
        if len(memories) < 3:
            return ""  # 数据不足

        # 统计任务关键词
        task_words = Counter()
        feedback_positive = []
        feedback_negative = []

        # 停用词（无意义的词）
        stop_words = {"方案第", "帮我写", "帮我做", "一个", "第一", "第二", "第三",
                       "还有", "以及", "一下", "之前", "上次", "这次", "那个", "可以"}

        for m in memories:
            task = m.get("task", "")
            # 提取 2-4 字中文词
            words = [w for w in re.findall(r'[\u4e00-\u9fff]{2,4}', task) if w not in stop_words]
            task_words.update(words)

            fb = m.get("feedback", "")
            if fb:
                # 简单情感判断
                negative_words = ["不好", "不行", "太差", "重写", "不满意", "太长", "太短", "偏了"]
                if any(w in fb for w in negative_words):
                    feedback_negative.append(fb[:50])
                else:
                    feedback_positive.append(fb[:50])

        # 生成专长标签
        parts = []

        # 最常做的任务类型（top 3 关键词）
        common_tasks = [w for w, c in task_words.most_common(5) if c >= 2]
        if common_tasks:
            parts.append(f"你最擅长的领域：{'、'.join(common_tasks[:3])}")

        # 完成任务数
        parts.append(f"已完成 {len(memories)} 次任务")

        # 正面反馈总结
        if feedback_positive:
            parts.append(f"老板表扬过的：{feedback_positive[0]}")

        # 负面反馈教训
        if feedback_negative:
            parts.append(f"需要避免的：{feedback_negative[0]}")

        # 行业专长（从用户画像获取）
        try:
            from .user_profile_ai import get_user_profile
            up = get_user_profile()
            if up.get("industry"):
                parts.append(f"老板的行业是{up['industry']}，你已经是{up['industry']}领域的专家")
        except Exception:
            pass

        if not parts:
            return ""

        return "\n\n## 你的专长（越用越专业）\n" + "\n".join(f"- {p}" for p in parts)

    except Exception as e:
        logger.debug(f"[AgentEvolution] get_expertise failed: {e}")
        return ""


def get_evolution_stats() -> Dict:
    """获取所有 Agent 的进化统计（用于前端展示）"""
    try:
        from .agent_memory import get_agent_memory
        from .agent_templates import AGENT_ROLES

        stats = {}
        for role_id in list(AGENT_ROLES.keys())[:20]:  # 只查前 20 个
            memories = get_agent_memory(role_id, limit=20)
            if not memories:
                continue

            fb_count = sum(1 for m in memories if m.get("feedback"))
            positive = sum(1 for m in memories if m.get("feedback") and
                          not any(w in m["feedback"] for w in ["不好", "不行", "太差"]))

            stats[role_id] = {
                "tasks_done": len(memories),
                "feedback_count": fb_count,
                "positive_rate": round(positive / fb_count * 100) if fb_count else 0,
                "expertise": get_agent_expertise(role_id)[:100],
            }

        return stats
    except Exception:
        return {}
