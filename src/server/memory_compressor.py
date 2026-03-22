# -*- coding: utf-8 -*-
"""
对话记忆压缩器 — 自动压缩长对话历史

当对话超过阈值时，将旧消息压缩为摘要，保留最近的完整消息。

效果：
  - 减少 token 消耗（压缩后约为原始的 1/5）
  - 保留关键信息（摘要包含重要决策和上下文）
  - 对用户透明（无感知）

策略：
  - 纯文本摘要（不调用 AI，零成本）
  - 提取每条消息的关键句（首句+含关键词的句子）
  - 每次压缩保留最近 8 条完整消息
"""

from __future__ import annotations

import re
from typing import Dict, List

from loguru import logger

# 压缩阈值
COMPRESS_THRESHOLD = 25  # 超过 25 条触发压缩
KEEP_RECENT = 8          # 保留最近 8 条完整消息
MAX_SUMMARY_CHARS = 800  # 摘要最大长度


def should_compress(history: List[Dict]) -> bool:
    """是否需要压缩"""
    return len(history) > COMPRESS_THRESHOLD


def compress_history(history: List[Dict]) -> List[Dict]:
    """压缩对话历史

    Returns:
        新的历史列表：[摘要消息] + 最近 N 条完整消息
    """
    if len(history) <= COMPRESS_THRESHOLD:
        return history

    # 分割：旧消息（要压缩的）+ 新消息（保留完整的）
    old_msgs = history[:-KEEP_RECENT]
    recent_msgs = history[-KEEP_RECENT:]

    # 生成摘要
    summary = _summarize_messages(old_msgs)

    if not summary:
        return history

    # 构建新历史：摘要 + 最近消息
    compressed = [
        {"role": "system", "content": f"[对话摘要 - 之前{len(old_msgs)}条消息的要点]\n{summary}"},
    ] + recent_msgs

    logger.info(f"[MemoryCompressor] 压缩 {len(old_msgs)} 条 → 摘要 {len(summary)} 字, 保留 {len(recent_msgs)} 条")
    return compressed


def _summarize_messages(messages: List[Dict]) -> str:
    """零成本摘要 — 提取关键信息（不调用 AI）"""
    user_points = []
    ai_points = []

    # 关键词（出现这些词的句子要保留）
    keywords = [
        "公司", "产品", "品牌", "客户", "用户", "预算", "目标",
        "方案", "策略", "计划", "团队", "项目", "报告",
        "问题", "需求", "重要", "关键", "决定", "确认",
        "不要", "不行", "修改", "调整", "改为",
    ]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not content or not isinstance(content, str):
            continue

        # 提取关键句
        sentences = re.split(r'[。！？\n]', content)
        key_sentences = []

        for i, s in enumerate(sentences):
            s = s.strip()
            if not s or len(s) < 4:
                continue
            # 首句总是保留
            if i == 0 and len(s) > 5:
                key_sentences.append(s[:80])
                continue
            # 含关键词的句子保留
            if any(kw in s for kw in keywords):
                key_sentences.append(s[:80])

        if key_sentences:
            point = "; ".join(key_sentences[:3])
            if role == "user":
                user_points.append(f"用户: {point}")
            elif role == "assistant":
                ai_points.append(f"AI: {point}")

    # 组装摘要
    parts = []
    if user_points:
        parts.append("用户提到的要点：\n" + "\n".join(f"- {p}" for p in user_points[-8:]))
    if ai_points:
        parts.append("AI 回答的要点：\n" + "\n".join(f"- {p}" for p in ai_points[-5:]))

    summary = "\n\n".join(parts)
    return summary[:MAX_SUMMARY_CHARS]


def compress_for_api(history: List[Dict], max_messages: int = 10) -> List[Dict]:
    """为 API 调用准备的压缩版本（更激进）

    用于 token 紧张的场景（如免费模型 4K context）
    """
    if len(history) <= max_messages:
        return history

    old = history[:-max_messages]
    recent = history[-max_messages:]

    # 超级压缩：只保留用户的关键问题
    key_topics = []
    for msg in old:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 10:
                key_topics.append(content[:50])

    if key_topics:
        summary_text = "之前讨论过的话题：" + "、".join(key_topics[-5:])
        return [{"role": "system", "content": f"[历史摘要] {summary_text}"}] + recent

    return recent
