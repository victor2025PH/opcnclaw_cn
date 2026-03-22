# -*- coding: utf-8 -*-
"""
对话质量守卫 — 检测并修复低质量 AI 回复

检测场景：
  1. 空洞回复：AI 只说"好的我来帮你"但没有实际行动
  2. 重复回复：连续多次回复雷同内容
  3. 答非所问：用户问具体问题，AI 给泛泛回答
  4. 遗漏工具调用：用户要求执行操作但 AI 只口头答应

对策：
  - 注入"行动力提示"到 system prompt
  - 检测到空洞回复后自动追加补充提示
  - 反馈学习：记录空洞模式，逐步改善

v1.0: 零 AI 调用，纯规则检测
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

from loguru import logger


# ── 空洞模式检测 ──

# 空洞开头（AI 常见的敷衍开头）
HOLLOW_STARTS = [
    "好的", "没问题", "当然可以", "收到", "明白了", "了解",
    "好的，我来", "好的，让我", "好的！我来", "好的！让我",
    "没问题，我", "当然，我", "我这就", "马上",
]

# 空洞短语（在回复中间出现的无实质内容）
HOLLOW_PHRASES = [
    "我会尽力", "请稍等", "让我想想", "我来帮你",
    "这是一个很好的问题", "这个问题很好", "感谢你的信任",
    "我会认真对待", "请放心", "交给我",
]

# 用户请求行动的关键词
ACTION_KEYWORDS = [
    "帮我写", "帮我做", "给我做", "做一个", "写一个", "生成",
    "帮我分析", "帮我整理", "帮我制作", "帮我策划",
    "创建", "设计", "规划", "制定", "编写", "起草",
]


def check_response_quality(user_message: str, ai_response: str) -> Dict:
    """检查 AI 回复质量

    Returns:
        {
            "quality": "good" | "hollow" | "short" | "repetitive",
            "score": 0-100,
            "issues": ["描述"],
            "suggestion": "补充提示（可注入到下一轮）"
        }
    """
    result = {
        "quality": "good",
        "score": 80,
        "issues": [],
        "suggestion": "",
    }

    msg = user_message.strip()
    resp = ai_response.strip()

    if not resp:
        return {"quality": "hollow", "score": 0,
                "issues": ["AI 返回空内容"], "suggestion": ""}

    # ── 1. 检测空洞回复 ──
    is_action_request = any(k in msg for k in ACTION_KEYWORDS)

    if is_action_request:
        # 用户要求行动，但 AI 回复太短
        if len(resp) < 100:
            # 检查是否只是口头答应
            resp_lower = resp.lower().replace("！", "").replace("。", "")
            hollow_count = sum(1 for p in HOLLOW_STARTS if resp_lower.startswith(p))
            hollow_count += sum(1 for p in HOLLOW_PHRASES if p in resp)

            if hollow_count > 0 and "[TOOL_CALL]" not in resp:
                result["quality"] = "hollow"
                result["score"] = 20
                result["issues"].append("用户要求行动但 AI 只口头答应，没有实际执行")
                result["suggestion"] = (
                    "用户要求你做具体工作，不要只说'好的'。"
                    "请立即执行：调用 deploy_team 组建团队，或直接给出方案内容。"
                    "用户不需要你的承诺，需要你的行动。"
                )
                return result

    # ── 2. 检测回复过短 ──
    if is_action_request and len(resp) < 50 and "[TOOL_CALL]" not in resp:
        result["quality"] = "short"
        result["score"] = 40
        result["issues"].append(f"回复太短（{len(resp)}字），用户期望具体方案")
        result["suggestion"] = "请提供更详细的回答，包含具体方案、步骤或调用工具执行。"
        return result

    # ── 3. 检测是否包含工具调用（行动请求时应该调用工具）──
    team_keywords = ["团队", "方案", "报告", "策划", "营销"]
    if is_action_request and any(k in msg for k in team_keywords):
        if "[TOOL_CALL]" not in resp and "deploy_team" not in resp:
            # AI 没有调用工具，但回复够长（可能自己写了方案）
            if len(resp) > 200:
                result["score"] = 70  # 可接受但非最优
                result["issues"].append("建议使用团队协作模式获得更全面的方案")
            else:
                result["score"] = 50
                result["issues"].append("用户需要完整方案，建议调用 deploy_team")
                result["suggestion"] = "这个需求适合团队协作，请调用 deploy_team 组建团队来完成。"

    # ── 4. 质量加分项 ──
    if len(resp) > 300:
        result["score"] = min(result["score"] + 10, 100)
    if "```" in resp:  # 包含代码块
        result["score"] = min(result["score"] + 5, 100)
    if re.search(r'[1-9]\.\s', resp):  # 包含编号列表
        result["score"] = min(result["score"] + 5, 100)
    if "[TOOL_CALL]" in resp:  # 调用了工具
        result["score"] = min(result["score"] + 15, 100)

    return result


def get_quality_prompt_boost(user_message: str) -> str:
    """根据用户消息类型，生成质量增强提示（注入到 system prompt）"""
    msg = user_message.strip()

    # 检测是否是行动请求
    is_action = any(k in msg for k in ACTION_KEYWORDS)

    if not is_action:
        return ""

    # 检测是否请求团队任务
    team_keywords = ["方案", "策划", "报告", "分析", "营销", "计划", "规划"]
    is_team_task = any(k in msg for k in team_keywords)

    parts = []

    if is_team_task:
        parts.append(
            "⚡ 行动指令：用户要你做具体工作。立即调用 deploy_team 组建团队执行。"
            "不要只说'好的我来帮你'——用户需要看到结果，不是承诺。"
        )
    else:
        parts.append(
            "⚡ 用户要求执行操作。请直接给出结果，不要空话。"
        )

    return "\n".join(parts)


# ── 反馈闭环：Agent 主动提及改进 ──

def get_feedback_reminder(agent_id: str) -> str:
    """检查 Agent 是否有之前的负面反馈，生成改进提醒"""
    try:
        from .agent_memory import get_agent_feedback_summary
        fb = get_agent_feedback_summary(agent_id)
        if not fb:
            return ""

        return (
            "\n\n## 改进提醒\n"
            "你之前收到过老板的反馈，这次请特别注意改进。"
            "在回复开头简要提一句你的改进（如'这次我精简了文案长度'），"
            "让老板知道你在进步。\n" + fb
        )
    except Exception:
        return ""
