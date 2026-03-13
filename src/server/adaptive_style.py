# -*- coding: utf-8 -*-
"""
对话场景自适应引擎

问题：AI 回复风格一成不变，不区分对象、时间、场景。
     VIP 客户收到口语化回复 → 不专业
     深夜好友收到公式化回复 → 不自然

方案：多信号融合，动态生成风格指令注入 system prompt。

信号源（按优先级）：
  1. 联系人画像 (contact_profile) → 关系类型 + 偏好风格
  2. 时间段 → 工作时间/午休/晚间/深夜
  3. 话题类型 (topic_tracker) → 工作/生活/情感
  4. 消息紧急度 → 包含"紧急""ASAP"等关键词

输出：一段 system prompt 补丁，如：
  "当前场景：晚间与密友聊天。请用轻松幽默的语气回复，可以用表情。"

设计决策：
  不调 LLM 做风格判断 → 用规则引擎，零延迟。
  风格切换是渐进的，不是突变（避免用户感到突兀）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional

from loguru import logger


@dataclass
class StyleContext:
    """风格上下文"""
    contact_name: str = ""
    relationship: str = "normal"    # family/close_friend/friend/colleague/client/normal
    comment_style: str = "casual"   # formal/casual/humorous/warm/professional
    intimacy: float = 30.0
    time_period: str = ""           # morning/work/lunch/afternoon/evening/night
    topic_type: str = ""            # work/life/emotion/tech/casual
    is_urgent: bool = False

    @property
    def style_prompt(self) -> str:
        """生成风格指令"""
        parts = []

        # 时间段风格
        period_style = {
            "morning": "早晨，语气积极清新",
            "work": "工作时间，回复专业高效",
            "lunch": "午休时间，可以轻松些",
            "afternoon": "下午，保持专注但友好",
            "evening": "傍晚，语气温和放松",
            "night": "深夜，简短温柔，不要太啰嗦",
        }
        if self.time_period:
            parts.append(period_style.get(self.time_period, ""))

        # 关系风格
        rel_style = {
            "family": "对方是家人，用关心温暖的语气",
            "close_friend": "对方是密友，可以开玩笑，用口语化表达",
            "friend": "对方是朋友，友好自然",
            "colleague": "对方是同事，保持适度专业",
            "client": "对方是客户，礼貌专业，注意措辞",
            "normal": "",
        }
        rel_text = rel_style.get(self.relationship, "")
        if rel_text:
            parts.append(rel_text)

        # 亲密度调整
        if self.intimacy >= 80:
            parts.append("你们关系很好，可以更随意")
        elif self.intimacy <= 15:
            parts.append("你们不太熟，保持礼貌距离")

        # 紧急度
        if self.is_urgent:
            parts.append("消息紧急，请简洁快速回复，先给结论")

        # 话题风格
        topic_style = {
            "work": "话题是工作相关，条理清晰",
            "emotion": "对方在倾诉情感，先共情再建议",
            "tech": "技术话题，可以用术语",
        }
        if self.topic_type and self.topic_type in topic_style:
            parts.append(topic_style[self.topic_type])

        parts = [p for p in parts if p]
        if not parts:
            return ""

        return "[场景自适应] " + "。".join(parts) + "。"


# ── 时间段检测 ───────────────────────────────────────────────────────────────

def _detect_time_period() -> str:
    hour = time.localtime().tm_hour
    if 6 <= hour < 9:
        return "morning"
    elif 9 <= hour < 12:
        return "work"
    elif 12 <= hour < 14:
        return "lunch"
    elif 14 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    else:
        return "night"


# ── 紧急度检测 ───────────────────────────────────────────────────────────────

_URGENT_KEYWORDS = ["紧急", "urgent", "asap", "马上", "立刻", "赶紧", "急", "快", "fire", "帮帮"]

def _detect_urgency(message: str) -> bool:
    if not message:
        return False
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _URGENT_KEYWORDS)


# ── 话题类型推断 ─────────────────────────────────────────────────────────────

import re

_TOPIC_PATTERNS = {
    "work": re.compile(r"会议|项目|报告|工作|任务|进度|客户|合同|方案|需求|排期"),
    "emotion": re.compile(r"心情|难过|开心|烦|累|压力|焦虑|孤独|伤心|生气|郁闷"),
    "tech": re.compile(r"代码|bug|编程|python|java|api|数据库|服务器|部署|算法"),
}

def _detect_topic(message: str) -> str:
    for topic, pattern in _TOPIC_PATTERNS.items():
        if pattern.search(message):
            return topic
    return "casual"


# ── 主入口 ───────────────────────────────────────────────────────────────────

def build_style_context(
    contact_name: str = "",
    message: str = "",
) -> StyleContext:
    """
    构建完整的风格上下文。

    从联系人画像获取关系+风格，结合时间+消息内容。
    """
    ctx = StyleContext(
        contact_name=contact_name,
        time_period=_detect_time_period(),
        is_urgent=_detect_urgency(message),
        topic_type=_detect_topic(message),
    )

    # 查询联系人画像
    if contact_name:
        try:
            from .wechat.contact_profile import get_profile
            profile = get_profile(contact_name)
            if profile:
                ctx.relationship = profile.relationship
                ctx.comment_style = profile.comment_style
                ctx.intimacy = profile.intimacy
        except Exception:
            pass

    return ctx


def get_style_prompt(contact_name: str = "", message: str = "") -> str:
    """
    便捷函数：直接返回风格补丁文本。

    返回空字符串表示使用默认风格。
    """
    ctx = build_style_context(contact_name, message)
    return ctx.style_prompt
