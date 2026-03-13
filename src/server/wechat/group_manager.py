# -*- coding: utf-8 -*-
"""
群聊智能管理器

功能：
  1. 话题自动分类 — 按消息内容将群聊讨论归类
  2. 群活跃度追踪 — 统计各群的消息频率、活跃成员
  3. 新成员欢迎 — 检测入群消息，自动生成欢迎语
  4. 关键消息提取 — 从大量群消息中筛选重要内容
  5. 群聊摘要 — 定时生成群聊内容摘要

设计决策：
  方案A: 每条群消息过 LLM 分类 → 成本高、延迟大
  方案B: 正则 + 规则分类 + 按需 LLM 摘要 → 选这个
  话题分类和关键消息提取用规则引擎（零 LLM 成本），
  只在生成群摘要时可选调用 LLM。
"""

from __future__ import annotations

import re
import time
import threading
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


# ── 话题分类器 ───────────────────────────────────────────────────────────────

TOPIC_PATTERNS = {
    "notice": re.compile(r"通知|公告|注意|重要|@所有人|@all|必须|截止|务必"),
    "question": re.compile(r"[？?]|怎么[办样]|如何|为什么|谁知道|有没有|哪里|多少"),
    "discussion": re.compile(r"觉得|认为|看法|观点|怎么看|支持|反对|同意|讨论"),
    "tech": re.compile(r"代码|bug|部署|服务器|数据库|api|python|java|前端|后端|git"),
    "work": re.compile(r"项目|需求|排期|会议|汇报|进度|方案|合同|客户|deadline|提测"),
    "share": re.compile(r"分享|推荐|安利|链接|http|www|文章|视频|教程"),
    "social": re.compile(r"吃|喝|玩|电影|旅游|周末|放假|约|聚|生日|红包"),
}


def classify_topic(text: str) -> str:
    """零成本话题分类"""
    if not text:
        return "casual"
    for topic, pattern in TOPIC_PATTERNS.items():
        if pattern.search(text):
            return topic
    return "casual"


# ── 新成员检测 ───────────────────────────────────────────────────────────────

_JOIN_PATTERNS = [
    re.compile(r'["""]?(.+?)["""]?邀请["""]?(.+?)["""]?加入了群聊'),
    re.compile(r'["""]?(.+?)["""]?通过扫描.*二维码加入群聊'),
    re.compile(r'["""]?(.+?)["""]?加入了群聊'),
]


def detect_new_member(message: str) -> Optional[str]:
    """检测入群消息，返回新成员名称（优先返回被邀请者）"""
    for i, p in enumerate(_JOIN_PATTERNS):
        m = p.search(message)
        if m:
            # 邀请模式：返回被邀请者（第2个捕获组）
            if i == 0 and m.lastindex and m.lastindex >= 2:
                return m.group(2).strip('" "')
            return m.group(1).strip('" "')
    return None


# ── 关键消息评分 ─────────────────────────────────────────────────────────────

_IMPORTANT_PATTERNS = [
    (re.compile(r"@所有人|@all", re.I), 5),
    (re.compile(r"通知|公告|重要|紧急"), 4),
    (re.compile(r"截止|deadline|ddl", re.I), 4),
    (re.compile(r"决定|确认|最终"), 3),
    (re.compile(r"请|务必|必须"), 3),
    (re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"), 2),  # 日期
    (re.compile(r"http[s]?://"), 2),                     # 链接
    (re.compile(r"[？?]"), 1),                            # 问题
]


def score_importance(text: str) -> int:
    """对消息重要性打分 (0-10)"""
    score = 0
    for pattern, weight in _IMPORTANT_PATTERNS:
        if pattern.search(text):
            score += weight
    return min(score, 10)


# ── 群状态追踪 ───────────────────────────────────────────────────────────────

@dataclass
class GroupStats:
    """单个群的运行统计"""
    group_name: str = ""
    total_messages: int = 0
    active_members: Counter = field(default_factory=Counter)
    topic_distribution: Counter = field(default_factory=Counter)
    recent_messages: deque = field(default_factory=lambda: deque(maxlen=100))
    important_messages: List[Dict] = field(default_factory=list)
    last_activity: float = 0
    new_members: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "group_name": self.group_name,
            "total_messages": self.total_messages,
            "active_members_count": len(self.active_members),
            "top_members": self.active_members.most_common(10),
            "topic_distribution": dict(self.topic_distribution),
            "important_count": len(self.important_messages),
            "new_members_count": len(self.new_members),
            "last_activity": self.last_activity,
        }


class GroupManager:
    """
    群聊智能管理器

    用法：
        mgr = GroupManager()
        result = mgr.process_message("技术交流群", "张三", "项目部署遇到bug了")
        # result = {"topic": "tech", "importance": 2, "new_member": None, "welcome": ""}
    """

    def __init__(self, welcome_enabled: bool = True, importance_threshold: int = 3):
        self._groups: Dict[str, GroupStats] = {}
        self._lock = threading.Lock()
        self._welcome_enabled = welcome_enabled
        self._importance_threshold = importance_threshold
        # 欢迎语模板
        self._welcome_templates = [
            "欢迎 {name} 加入！有问题随时提问",
            "Hi {name}，欢迎进群！",
            "欢迎新朋友 {name}，请多多交流",
        ]

    def _ensure_group(self, group_name: str) -> GroupStats:
        if group_name not in self._groups:
            self._groups[group_name] = GroupStats(group_name=group_name)
        return self._groups[group_name]

    def process_message(
        self,
        group_name: str,
        sender: str,
        content: str,
        timestamp: float = 0,
    ) -> Dict[str, Any]:
        """
        处理一条群消息。

        返回: {topic, importance, new_member, welcome, is_important}
        """
        ts = timestamp or time.time()
        result = {
            "topic": "casual",
            "importance": 0,
            "new_member": None,
            "welcome": "",
            "is_important": False,
        }

        with self._lock:
            gs = self._ensure_group(group_name)
            gs.total_messages += 1
            gs.last_activity = ts
            gs.active_members[sender] += 1

        # 检测新成员
        new_member = detect_new_member(content)
        if new_member:
            result["new_member"] = new_member
            with self._lock:
                gs.new_members.append({"name": new_member, "time": ts})
                if len(gs.new_members) > 50:
                    gs.new_members = gs.new_members[-50:]
            if self._welcome_enabled:
                import random
                tpl = random.choice(self._welcome_templates)
                result["welcome"] = tpl.format(name=new_member)
            return result

        # 话题分类
        topic = classify_topic(content)
        result["topic"] = topic
        with self._lock:
            gs.topic_distribution[topic] += 1

        # 重要性评分
        importance = score_importance(content)
        result["importance"] = importance
        result["is_important"] = importance >= self._importance_threshold

        # 记录
        msg_record = {
            "sender": sender,
            "content": content[:300],
            "topic": topic,
            "importance": importance,
            "time": ts,
        }
        with self._lock:
            gs.recent_messages.append(msg_record)
            if importance >= self._importance_threshold:
                gs.important_messages.append(msg_record)
                if len(gs.important_messages) > 100:
                    gs.important_messages = gs.important_messages[-100:]

        return result

    def get_group_stats(self, group_name: str) -> Optional[Dict]:
        gs = self._groups.get(group_name)
        return gs.to_dict() if gs else None

    def get_all_groups(self) -> List[Dict]:
        return [gs.to_dict() for gs in self._groups.values()]

    def get_important_messages(self, group_name: str, limit: int = 20) -> List[Dict]:
        gs = self._groups.get(group_name)
        if not gs:
            return []
        return gs.important_messages[-limit:]

    async def generate_summary(self, group_name: str, ai_call=None) -> str:
        """生成群聊摘要"""
        gs = self._groups.get(group_name)
        if not gs or not gs.recent_messages:
            return "暂无群聊记录"

        msgs = list(gs.recent_messages)

        # 无 LLM：纯规则摘要
        if not ai_call:
            return self._rule_summary(gs, msgs)

        # 有 LLM：生成式摘要
        conv_text = "\n".join(
            f"{m['sender']}: {m['content'][:100]}" for m in msgs[-30:]
        )
        prompt = [
            {"role": "system", "content": "你是群聊助手。根据以下群聊消息，生成一段简洁的群聊摘要（80-120字），概括讨论了什么话题、得出了什么结论、有什么重要事项。不要逐条复述。"},
            {"role": "user", "content": f"群名: {group_name}\n\n{conv_text}"},
        ]
        try:
            summary = await ai_call(prompt)
            return summary.strip()[:200] if summary else self._rule_summary(gs, msgs)
        except Exception:
            return self._rule_summary(gs, msgs)

    def _rule_summary(self, gs: GroupStats, msgs: List[Dict]) -> str:
        """纯规则摘要"""
        parts = [f"群「{gs.group_name}」- 共 {gs.total_messages} 条消息"]

        # 话题分布
        top_topics = gs.topic_distribution.most_common(3)
        topic_cn = {"work": "工作", "tech": "技术", "share": "分享", "discussion": "讨论",
                     "social": "社交", "notice": "通知", "question": "提问", "casual": "闲聊"}
        if top_topics:
            t_str = "、".join(f"{topic_cn.get(t, t)}({c})" for t, c in top_topics)
            parts.append(f"话题分布: {t_str}")

        # 活跃成员
        top_members = gs.active_members.most_common(3)
        if top_members:
            m_str = "、".join(f"{n}({c}条)" for n, c in top_members)
            parts.append(f"活跃: {m_str}")

        # 重要消息数
        imp = [m for m in msgs if m["importance"] >= self._importance_threshold]
        if imp:
            parts.append(f"重要消息 {len(imp)} 条")

        return "。".join(parts) + "。"

    def set_welcome_templates(self, templates: List[str]):
        self._welcome_templates = templates if templates else self._welcome_templates


# 全局单例
_manager: Optional[GroupManager] = None


def get_group_manager() -> GroupManager:
    global _manager
    if _manager is None:
        _manager = GroupManager()
    return _manager
