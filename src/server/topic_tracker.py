# -*- coding: utf-8 -*-
"""
对话语境跟踪器

问题：用户连续讨论某个话题时（如"刚才说的那个餐厅"），
短期缓存(10条)可能已丢失，长期记忆检索又太慢/太泛。

方案：维护一个「活跃话题」栈，实时追踪对话主题切换。
当用户的消息包含指代词（"那个"、"刚才说的"、"继续"）时，
自动加载当前话题的完整上下文。

架构：
  TopicTracker 是 session 级别的，每个对话会话一个实例。
  它嵌入到 backend.py 的消息处理管道中：
    用户消息 → 话题检测 → 如果有活跃话题 → 注入上下文

  话题检测用轻量规则（关键词匹配），不用 LLM（零延迟）。
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False


@dataclass
class Topic:
    """一个对话话题"""
    name: str = ""              # 话题名/摘要
    keywords: List[str] = field(default_factory=list)
    messages: List[Dict] = field(default_factory=list)  # 该话题下的消息
    started_at: float = 0
    last_active: float = 0

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content[:300]})
        self.last_active = time.time()
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]

    def context_text(self, max_msgs: int = 6) -> str:
        """返回该话题的上下文文本"""
        recent = self.messages[-max_msgs:]
        lines = [f"[话题: {self.name}]"] if self.name else []
        for m in recent:
            prefix = "用户" if m["role"] == "user" else "AI"
            lines.append(f"{prefix}: {m['content'][:150]}")
        return "\n".join(lines)


# 指代词和话题延续信号
CONTINUATION_PATTERNS = [
    r"(那个|那件|那位|那家)",
    r"(刚才|刚刚|之前|上面)(说的|提到的|聊的)",
    r"(继续|接着|然后呢|还有呢)",
    r"(这个话题|这件事|这个问题)",
    r"(对了|补充一下|忘了说)",
    r"^(嗯|好的|对|没错|是的)[，。！]",
    r"(怎么样了|后来呢|结果呢)",
]
_CONTINUATION_RE = re.compile("|".join(CONTINUATION_PATTERNS))

# 话题切换信号
SWITCH_PATTERNS = [
    r"(换个话题|说点别的|另外)",
    r"(我想问|帮我|请问|你能不能)",
    r"^(hi|hello|你好|嗨)",
]
_SWITCH_RE = re.compile("|".join(SWITCH_PATTERNS))


def _extract_topic_keywords(text: str) -> List[str]:
    """提取话题关键词"""
    STOP = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "吗", "呢",
            "啊", "哦", "嗯", "好", "不", "会", "就", "也", "都", "还", "有",
            "没", "很", "可以", "能", "把", "被", "让", "给", "从", "到", "和",
            "请", "谢谢", "什么", "怎么", "为什么"}
    if _JIEBA:
        words = [w for w in jieba.cut(text) if len(w) > 1 and w not in STOP]
    else:
        words = [text[i:i+2] for i in range(0, max(0, len(text)-1), 2)]
    return words[:8]


class TopicTracker:
    """
    对话话题跟踪器

    用法：
        tracker = TopicTracker()
        context = tracker.process_message("user", "继续说说那个餐厅")
        # → 返回之前讨论餐厅的上下文
    """

    def __init__(self, max_topics: int = 5):
        self._topics: deque[Topic] = deque(maxlen=max_topics)
        self._current: Optional[Topic] = None

    @property
    def current_topic(self) -> Optional[Topic]:
        return self._current

    def process_message(self, role: str, content: str) -> str:
        """
        处理新消息，返回需要注入的话题上下文（空字符串 = 无需注入）。

        逻辑：
          1. 检测是否是话题延续 → 返回当前话题上下文
          2. 检测是否是话题切换 → 创建新话题
          3. 检测关键词重叠 → 恢复旧话题
          4. 默认延续当前话题
        """
        if not content or len(content) < 2:
            return ""

        inject_context = ""

        if role == "user":
            is_continuation = bool(_CONTINUATION_RE.search(content))
            is_switch = bool(_SWITCH_RE.search(content))

            if is_switch and not is_continuation:
                # 明确切换话题
                self._start_new_topic(content)
            elif is_continuation and self._current:
                # 延续当前话题，注入上下文
                inject_context = self._build_context()
            elif self._current:
                # 检查是否和当前话题相关
                new_kw = set(_extract_topic_keywords(content))
                current_kw = set(self._current.keywords)
                overlap = len(new_kw & current_kw)

                if overlap >= 2:
                    # 话题延续
                    pass
                elif overlap == 0 and not is_continuation:
                    # 可能是新话题，但也可能只是简短回应
                    if len(content) > 15:
                        old_topic = self._find_matching_topic(new_kw)
                        if old_topic:
                            # 恢复旧话题
                            self._current = old_topic
                            inject_context = self._build_context()
                        else:
                            self._start_new_topic(content)
            else:
                # 无当前话题，开始新话题
                self._start_new_topic(content)

        # 记录消息到当前话题
        if self._current:
            self._current.add_message(role, content)

        return inject_context

    def _start_new_topic(self, content: str):
        """开始一个新话题"""
        keywords = _extract_topic_keywords(content)
        topic = Topic(
            name=content[:30],
            keywords=keywords,
            started_at=time.time(),
            last_active=time.time(),
        )
        self._topics.append(topic)
        self._current = topic

    def _find_matching_topic(self, keywords: set) -> Optional[Topic]:
        """在历史话题中查找匹配的"""
        best = None
        best_score = 0
        for topic in self._topics:
            if topic is self._current:
                continue
            overlap = len(keywords & set(topic.keywords))
            if overlap > best_score and overlap >= 2:
                best = topic
                best_score = overlap
        return best

    def _build_context(self) -> str:
        """构建当前话题的上下文注入文本"""
        if not self._current or not self._current.messages:
            return ""
        ctx = self._current.context_text(max_msgs=4)
        if len(ctx) < 10:
            return ""
        return f"\n[对话语境] 你们正在讨论以下话题，请保持上下文连贯：\n{ctx}"

    def get_status(self) -> Dict:
        return {
            "current_topic": self._current.name if self._current else None,
            "topic_count": len(self._topics),
            "topics": [
                {"name": t.name[:30], "messages": len(t.messages), "keywords": t.keywords[:5]}
                for t in self._topics
            ],
        }


# session_id → TopicTracker 映射
_trackers: Dict[str, TopicTracker] = {}


def get_tracker(session_id: str = "default") -> TopicTracker:
    if session_id not in _trackers:
        _trackers[session_id] = TopicTracker()
    return _trackers[session_id]
