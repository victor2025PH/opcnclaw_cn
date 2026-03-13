# -*- coding: utf-8 -*-
"""
智能通知聚合器

问题：多账号消息量爆炸，用户被通知淹没。
方案：两级聚合架构，零 LLM 开销实现高效降噪。

  Tier-1（实时，纯规则）：
    - 按 account + contact 分组
    - 连续消息合并为一条摘要（"Alice 发了 5 条消息"）
    - 群消息只保留最后 N 条 + @我的

  Tier-2（按需，LLM 摘要）：
    - 用户手动触发 或 未读超阈值时启动
    - 用 LLM 为每个分组生成一句话摘要
    - 结果缓存 5 分钟避免重复调用

设计决策变更记录：
  初版方案：每条消息都过 LLM → 成本高、延迟大
  优化方案：Tier-1 规则聚合 + Tier-2 按需 LLM → 成本降 95%
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class NotificationGroup:
    """一个聚合通知组"""
    account_id: str = ""
    contact: str = ""
    is_group: bool = False
    messages: List[Dict] = field(default_factory=list)
    first_ts: float = 0
    last_ts: float = 0
    has_at_me: bool = False
    summary: str = ""       # LLM 生成的摘要
    summary_ts: float = 0   # 摘要生成时间

    @property
    def count(self) -> int:
        return len(self.messages)

    @property
    def priority(self) -> int:
        """优先级：0=低 1=中 2=高"""
        if self.has_at_me:
            return 2
        if not self.is_group and self.count >= 3:
            return 2
        if self.count >= 5:
            return 1
        return 0

    @property
    def priority_label(self) -> str:
        return ["low", "medium", "high"][self.priority]

    def brief(self) -> str:
        """Tier-1 规则摘要（零 LLM）"""
        if self.summary and time.time() - self.summary_ts < 300:
            return self.summary
        if self.count == 1:
            return self.messages[0].get("content", "")[:60]
        last = self.messages[-1].get("content", "")[:40]
        if self.is_group:
            senders = set(m.get("sender", "") for m in self.messages if m.get("sender"))
            return f"{len(senders)} 人发了 {self.count} 条消息，最新: {last}"
        return f"{self.count} 条消息，最新: {last}"

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "contact": self.contact,
            "is_group": self.is_group,
            "count": self.count,
            "priority": self.priority_label,
            "brief": self.brief(),
            "has_at_me": self.has_at_me,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "summary": self.summary,
        }


class NotificationAggregator:
    """
    智能通知聚合器

    用法：
        agg = NotificationAggregator()
        agg.ingest(account_id, contact, sender, content, is_group, at_me)
        groups = agg.get_digest()
        await agg.generate_summaries(ai_call)
    """

    def __init__(self, group_window: float = 300, max_per_group: int = 50):
        self._groups: Dict[str, NotificationGroup] = {}
        self._group_window = group_window   # 分组时间窗口（秒）
        self._max_per_group = max_per_group
        self._last_digest_ts: float = 0

    def ingest(
        self,
        account_id: str,
        contact: str,
        sender: str,
        content: str,
        is_group: bool = False,
        at_me: bool = False,
        timestamp: float = 0,
    ):
        """接收一条新消息，自动聚合到对应分组"""
        ts = timestamp or time.time()
        key = f"{account_id}::{contact}"

        if key not in self._groups:
            self._groups[key] = NotificationGroup(
                account_id=account_id,
                contact=contact,
                is_group=is_group,
                first_ts=ts,
            )

        g = self._groups[key]
        g.last_ts = ts
        if at_me:
            g.has_at_me = True

        g.messages.append({
            "sender": sender,
            "content": content[:200],
            "timestamp": ts,
        })

        # 保持消息在合理范围
        if len(g.messages) > self._max_per_group:
            g.messages = g.messages[-self._max_per_group:]

    def get_digest(self, min_priority: int = 0, limit: int = 20) -> List[Dict]:
        """
        获取聚合后的通知摘要。

        Tier-1：纯规则聚合，即时返回。
        按优先级降序 + 时间倒序排列。
        """
        groups = sorted(
            self._groups.values(),
            key=lambda g: (g.priority, g.last_ts),
            reverse=True,
        )
        result = [g.to_dict() for g in groups if g.priority >= min_priority]
        self._last_digest_ts = time.time()
        return result[:limit]

    def get_unread_summary(self) -> Dict:
        """整体未读摘要"""
        total = sum(g.count for g in self._groups.values())
        high = sum(1 for g in self._groups.values() if g.priority == 2)
        by_account = defaultdict(int)
        for g in self._groups.values():
            by_account[g.account_id] += g.count

        return {
            "total_messages": total,
            "total_groups": len(self._groups),
            "high_priority": high,
            "by_account": dict(by_account),
        }

    async def generate_summaries(self, ai_call=None, force: bool = False):
        """
        Tier-2：用 LLM 为高优先级分组生成一句话摘要。

        ai_call 签名: async (messages: list) -> str
        只对 count >= 3 且 摘要过期的分组生成。
        """
        if not ai_call:
            return

        for g in self._groups.values():
            if g.count < 3:
                continue
            if not force and g.summary and time.time() - g.summary_ts < 300:
                continue

            # 构造给 LLM 的压缩消息
            sample = g.messages[-8:]  # 最多取最近 8 条
            msgs_text = "\n".join(
                f"{m.get('sender', '?')}: {m['content'][:80]}"
                for m in sample
            )

            prompt = [
                {"role": "system", "content": "你是消息摘要助手。用一句简洁的中文总结以下聊天内容的主题和要点（不超过 40 字）。"},
                {"role": "user", "content": f"来自「{g.contact}」的 {g.count} 条消息：\n{msgs_text}"},
            ]

            try:
                summary = await ai_call(prompt)
                if summary:
                    g.summary = summary.strip()[:80]
                    g.summary_ts = time.time()
            except Exception as e:
                logger.debug(f"[NotifAgg] 摘要生成失败: {e}")

    def clear_group(self, account_id: str = "", contact: str = ""):
        """清除指定分组"""
        if account_id and contact:
            key = f"{account_id}::{contact}"
            self._groups.pop(key, None)
        elif account_id:
            to_del = [k for k in self._groups if k.startswith(f"{account_id}::")]
            for k in to_del:
                del self._groups[k]
        else:
            self._groups.clear()

    def clear_stale(self, max_age: float = 3600):
        """清理超过 max_age 秒没有新消息的分组"""
        cutoff = time.time() - max_age
        to_del = [k for k, g in self._groups.items() if g.last_ts < cutoff]
        for k in to_del:
            del self._groups[k]


# 全局单例
_aggregator: Optional[NotificationAggregator] = None


def get_aggregator() -> NotificationAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = NotificationAggregator()
    return _aggregator
