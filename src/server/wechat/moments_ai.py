# -*- coding: utf-8 -*-
"""
朋友圈 AI 智能互动引擎

核心设计：单次 LLM 调用完成 理解→决策→生成 全流程
  - 结合社交画像（亲密度/关系/兴趣/风格）做差异化决策
  - 多模态：文字由 LLM 分析，图片描述来自 Vision AI（MomentsReader 已提取）
  - 评论去模板化：每条评论都是针对具体内容的个性化生成
  - 评论链跟进：检测别人对我评论的回复，AI 接续对话
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from .moments_reader import MomentPost
from .contact_profile import (
    ContactProfile, get_profile, record_interaction, update_interests,
    RELATIONSHIP_CN, STYLE_CN,
)


# ── AI 分析结果 ──────────────────────────────────────────────────────────────────

class MomentAnalysis:
    """单条朋友圈的 AI 分析结果"""
    __slots__ = (
        "post_id", "should_like", "should_comment", "comment_text",
        "content_summary", "mood", "topics", "reason",
    )

    def __init__(
        self,
        post_id: str = "",
        should_like: bool = False,
        should_comment: bool = False,
        comment_text: str = "",
        content_summary: str = "",
        mood: str = "",
        topics: List[str] = None,
        reason: str = "",
    ):
        self.post_id = post_id
        self.should_like = should_like
        self.should_comment = should_comment
        self.comment_text = comment_text
        self.content_summary = content_summary
        self.mood = mood
        self.topics = topics or []
        self.reason = reason

    def to_dict(self) -> Dict:
        return {
            "post_id": self.post_id,
            "should_like": self.should_like,
            "should_comment": self.should_comment,
            "comment_text": self.comment_text,
            "content_summary": self.content_summary,
            "mood": self.mood,
            "topics": self.topics,
            "reason": self.reason,
        }


# ── Prompt 模板 ──────────────────────────────────────────────────────────────────

ANALYSIS_PROMPT = """你是一个社交互动助手，需要分析一条微信朋友圈动态并决定如何互动。

## 动态内容
- 发布者：{author}
- 文字：{text}
- 图片描述：{image_desc}
- 发布时间：{time_str}
- 位置：{location}

## 我与 {author} 的关系
- 关系类型：{relationship}
- 亲密度：{intimacy}/100
- 对方兴趣：{interests}
- 评论风格偏好：{comment_style}
- 最近互动：{recent_interaction}

## 互动概率参考
- 点赞概率：{like_prob}%（基于亲密度）
- 评论概率：{comment_prob}%（基于亲密度）

## 要求
请分析这条动态，并以 JSON 格式返回决策：
{{
  "should_like": true/false,
  "should_comment": true/false,
  "comment_text": "评论内容（如果 should_comment 为 true）",
  "content_summary": "动态内容一句话概括",
  "mood": "发布者情绪（开心/感慨/炫耀/日常/求助/吐槽/怀旧/正能量）",
  "topics": ["话题标签1", "话题标签2"],
  "reason": "决策原因（简短）"
}}

## 评论规则
1. 评论要自然、个性化，像真人朋友的回复
2. 根据关系类型调整语气：{style_hint}
3. 如果有图片，评论应体现对图片内容的理解
4. 长度控制在 5-30 字，不要太长
5. 不要使用 emoji 表情过多（最多1个）
6. 不要过于模板化（"拍得真好看"这类通用评论要避免）
7. 如果动态内容空洞或你不确定如何评论，设 should_comment 为 false

只返回 JSON，不要其他文字。"""

PUBLISH_PROMPT = """你是一个朋友圈文案助手。请根据以下要求生成朋友圈文案：

主题/关键词：{topic}
风格：{style}
心情：{mood}
场景：{scene}
附加要求：{extra}

请生成 3 个不同风格的文案选项，以 JSON 数组返回：
[
  {{"text": "文案1", "style": "风格描述"}},
  {{"text": "文案2", "style": "风格描述"}},
  {{"text": "文案3", "style": "风格描述"}}
]

文案规则：
1. 简洁自然，像真人发的（不要太文艺做作）
2. 长度 10-100 字
3. 可适当用 1-2 个 emoji
4. 不要使用 # 话题标签

只返回 JSON 数组。"""


# ── AI 引擎 ──────────────────────────────────────────────────────────────────────

class MomentsAIEngine:
    """
    朋友圈 AI 互动引擎

    使用方式：
        ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
        analysis = await ai_engine.analyze_post(post, profile)
        drafts = await ai_engine.generate_moment_text(topic="周末", mood="开心")
    """

    def __init__(self, ai_call: Callable = None):
        """
        ai_call: async function(messages: list) -> str
            与 AIBackend.chat_simple 签名一致
        """
        self._ai_call = ai_call

    async def analyze_post(
        self,
        post: MomentPost,
        profile: Optional[ContactProfile] = None,
    ) -> MomentAnalysis:
        """
        分析一条朋友圈动态：理解内容 → 决策互动 → 生成评论
        单次 LLM 调用完成全部工作
        """
        if not self._ai_call:
            return MomentAnalysis(post_id=post.fingerprint())

        if profile is None:
            profile = get_profile(post.author)

        style_hints = {
            "family": "用亲切温暖的语气",
            "close_friend": "用轻松随意的语气，可以开玩笑",
            "friend": "用友好的语气",
            "colleague": "用礼貌但不过于正式的语气",
            "client": "用专业热情的语气",
            "normal": "用礼貌简短的语气",
        }

        recent = ""
        if profile.last_interaction > 0:
            days_ago = ((__import__("time").time() - profile.last_interaction) / 86400)
            recent = f"{days_ago:.0f}天前"
        else:
            recent = "暂无"

        prompt = ANALYSIS_PROMPT.format(
            author=post.author,
            text=post.text or "(纯图片/视频)",
            image_desc=post.image_desc or "无图片",
            time_str=post.time_str or "未知",
            location=post.location or "无",
            relationship=RELATIONSHIP_CN.get(profile.relationship, "普通"),
            intimacy=f"{profile.intimacy:.0f}",
            interests="、".join(profile.interests[:5]) if profile.interests else "未知",
            comment_style=STYLE_CN.get(profile.comment_style, "轻松"),
            recent_interaction=recent,
            like_prob=f"{profile.like_probability * 100:.0f}",
            comment_prob=f"{profile.comment_probability * 100:.0f}",
            style_hint=style_hints.get(profile.relationship, "用友好的语气"),
        )

        try:
            raw = await self._ai_call([{"role": "user", "content": prompt}])
            analysis = self._parse_analysis(raw, post)

            if analysis.topics:
                update_interests(post.author, analysis.topics)

            # 基于亲密度做概率性调整（AI 可能过于热情）
            if analysis.should_like and random.random() > profile.like_probability:
                analysis.should_like = False
                analysis.reason += " (亲密度概率过滤)"
            if analysis.should_comment and random.random() > profile.comment_probability:
                analysis.should_comment = False
                analysis.reason += " (亲密度概率过滤)"

            return analysis

        except Exception as e:
            logger.warning(f"朋友圈 AI 分析失败: {e}")
            return MomentAnalysis(post_id=post.fingerprint())

    async def generate_moment_text(
        self,
        topic: str = "",
        style: str = "日常",
        mood: str = "平常",
        scene: str = "",
        extra: str = "",
    ) -> List[Dict[str, str]]:
        """生成朋友圈发布文案（3个选项）"""
        if not self._ai_call:
            return [{"text": topic or "分享一下", "style": "默认"}]

        prompt = PUBLISH_PROMPT.format(
            topic=topic or "日常分享",
            style=style,
            mood=mood,
            scene=scene or "无特定场景",
            extra=extra or "无",
        )

        try:
            raw = await self._ai_call([{"role": "user", "content": prompt}])
            return self._parse_drafts(raw)
        except Exception as e:
            logger.warning(f"文案生成失败: {e}")
            return [{"text": topic or "分享一下", "style": "默认"}]

    async def generate_reply_to_comment(
        self,
        original_post_text: str,
        my_comment: str,
        their_reply: str,
        author: str,
    ) -> str:
        """生成对他人回复我评论的二次回复（评论链跟进）"""
        if not self._ai_call:
            return ""

        profile = get_profile(author)
        prompt = f"""在微信朋友圈中，我对 {author} 的动态评论了"{my_comment}"，对方回复了"{their_reply}"。
原动态内容：{original_post_text[:200]}
我与对方的关系：{RELATIONSHIP_CN.get(profile.relationship, '普通')}

请生成一条自然的回复（5-20字），保持对话的自然延续。只返回回复文字，不要其他内容。"""

        try:
            raw = await self._ai_call([{"role": "user", "content": prompt}])
            reply = raw.strip().strip('"').strip("'")
            return reply[:50]
        except Exception as e:
            logger.debug(f"评论链回复生成失败: {e}")
            return ""

    # ── 解析 ─────────────────────────────────────────────────────────────────────

    def _parse_analysis(self, raw: str, post: MomentPost) -> MomentAnalysis:
        raw = raw.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return MomentAnalysis(post_id=post.fingerprint())

        try:
            d = json.loads(json_match.group())
        except json.JSONDecodeError:
            return MomentAnalysis(post_id=post.fingerprint())

        return MomentAnalysis(
            post_id=post.fingerprint(),
            should_like=bool(d.get("should_like", False)),
            should_comment=bool(d.get("should_comment", False)),
            comment_text=str(d.get("comment_text", "")),
            content_summary=str(d.get("content_summary", "")),
            mood=str(d.get("mood", "")),
            topics=d.get("topics", []) if isinstance(d.get("topics"), list) else [],
            reason=str(d.get("reason", "")),
        )

    def _parse_drafts(self, raw: str) -> List[Dict[str, str]]:
        raw = raw.strip()
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return [{"text": raw[:200], "style": "AI"}]

        try:
            items = json.loads(json_match.group())
            result = []
            for item in items:
                if isinstance(item, dict) and "text" in item:
                    result.append({
                        "text": item["text"],
                        "style": item.get("style", ""),
                    })
            return result if result else [{"text": raw[:200], "style": "AI"}]
        except json.JSONDecodeError:
            return [{"text": raw[:200], "style": "AI"}]
