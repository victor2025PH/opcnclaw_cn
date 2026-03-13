# -*- coding: utf-8 -*-
"""
朋友圈互动追踪器

负责：
  1. 评论链跟进 — 监控微信通知中的"回复了你的评论"，AI 自动生成二次回复
  2. 朋友圈情报收集 — 定期浏览关键联系人动态，生成摘要
  3. 30天内容日历 — AI 规划 + 存储 + 定时发布

核心优化：
  不重新浏览朋友圈来检测回复，而是**监听微信系统通知消息**。
  微信在收到评论回复时会推送"xx回复了你"通知，
  我们的 WeChatAdapter 消息管道已经能捕获到这些通知。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .contact_profile import get_profile, record_interaction


# ── 评论链追踪 ────────────────────────────────────────────────────────────────────

@dataclass
class CommentRecord:
    """我的一条评论记录"""
    post_author: str
    post_text: str        # 原动态内容（截断）
    my_comment: str
    timestamp: float = field(default_factory=time.time)
    replied: bool = False
    reply_author: str = ""
    reply_text: str = ""
    my_followup: str = ""


class CommentChainTracker:
    """
    评论链追踪器

    通过监听微信通知消息检测评论回复，自动触发 AI 二次回复。
    比重新浏览朋友圈高效 10 倍。

    使用方式：
        tracker = CommentChainTracker(ai_call=backend.chat_simple)
        # 每次我们评论时记录
        tracker.record_my_comment("张三", "周末快乐！", "张三发了旅行照")
        # 每条消息都过一遍检测
        followup = await tracker.check_notification("服务通知", "张三回复了你：谢谢")
    """

    def __init__(self, ai_call: Callable = None, max_records: int = 200):
        self._ai_call = ai_call
        self._records: List[CommentRecord] = []
        self._max_records = max_records
        self.on_followup: Optional[Callable] = None  # callback(author, followup_text)

    def record_my_comment(self, post_author: str, comment: str, post_text: str = ""):
        """记录我发出的评论"""
        self._records.append(CommentRecord(
            post_author=post_author,
            post_text=post_text[:200],
            my_comment=comment,
        ))
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

    async def check_notification(self, sender: str, content: str) -> Optional[str]:
        """
        检查一条消息是否是评论回复通知。
        微信通知格式多样，常见：
          - "张三回复了你：谢谢啊"
          - "张三在朋友圈回复了你"
          - 来自"朋友圈"的系统消息
        """
        reply_match = re.search(
            r"(.+?)(?:在朋友圈)?回复了你[的的]?(?:评论)?[：:](.+)",
            content,
        )
        if not reply_match:
            return None

        reply_author = reply_match.group(1).strip()
        reply_text = reply_match.group(2).strip()

        record = self._find_matching_record(reply_author)
        if not record:
            logger.debug(f"[CommentChain] 收到回复通知但未找到匹配评论: {reply_author}")
            return None

        record.replied = True
        record.reply_author = reply_author
        record.reply_text = reply_text

        followup = await self._generate_followup(record)
        if followup:
            record.my_followup = followup
            record_interaction(reply_author, "reply", content=followup)

            if self.on_followup:
                try:
                    self.on_followup(reply_author, followup)
                except Exception:
                    pass

        return followup

    def _find_matching_record(self, author: str) -> Optional[CommentRecord]:
        """找到最近一条我对该作者的未回复评论"""
        for record in reversed(self._records):
            if record.post_author == author and not record.replied:
                age = time.time() - record.timestamp
                if age < 7 * 86400:  # 7天内的评论才跟进
                    return record
        return None

    async def _generate_followup(self, record: CommentRecord) -> str:
        """用 AI 生成二次回复"""
        if not self._ai_call:
            return ""

        try:
            from .moments_ai import MomentsAIEngine
            engine = MomentsAIEngine(ai_call=self._ai_call)
            return await engine.generate_reply_to_comment(
                original_post_text=record.post_text,
                my_comment=record.my_comment,
                their_reply=record.reply_text,
                author=record.reply_author,
            )
        except Exception as e:
            logger.warning(f"评论链回复生成失败: {e}")
            return ""

    def get_chain_stats(self) -> Dict:
        total = len(self._records)
        replied = sum(1 for r in self._records if r.replied)
        followed_up = sum(1 for r in self._records if r.my_followup)
        return {
            "total_comments": total,
            "received_replies": replied,
            "auto_followups": followed_up,
        }

    def get_recent_chains(self, limit: int = 20) -> List[Dict]:
        result = []
        for r in reversed(self._records[-limit:]):
            result.append({
                "author": r.post_author,
                "my_comment": r.my_comment[:50],
                "post_text": r.post_text[:50],
                "replied": r.replied,
                "reply_text": r.reply_text[:50] if r.reply_text else "",
                "followup": r.my_followup[:50] if r.my_followup else "",
                "time": r.timestamp,
            })
        return result


# ── 30天内容日历 ──────────────────────────────────────────────────────────────────

@dataclass
class CalendarEntry:
    """日历中一天的发圈计划"""
    date: str              # YYYY-MM-DD
    topic: str = ""
    text: str = ""         # AI 生成的文案
    style: str = ""
    media_hint: str = ""   # 配图建议
    status: str = "planned"  # planned / approved / published / skipped
    published_at: float = 0

    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "topic": self.topic,
            "text": self.text,
            "style": self.style,
            "media_hint": self.media_hint,
            "status": self.status,
            "published_at": self.published_at,
        }


class ContentCalendar:
    """
    30天朋友圈内容日历

    AI 一次性规划一个月的内容，用户可审核/编辑/跳过。
    配合工作流定时器自动发布。
    """

    CALENDAR_FILE = Path(__file__).parent.parent.parent.parent / "data" / "moments_calendar.json"

    def __init__(self, ai_call: Callable = None):
        self._ai_call = ai_call
        self._entries: List[CalendarEntry] = []
        self._load()

    async def generate_month_plan(
        self,
        user_profile: str = "",
        interests: str = "",
        style: str = "自然日常",
        posts_per_week: int = 3,
    ) -> List[CalendarEntry]:
        """AI 生成 30 天内容规划"""
        if not self._ai_call:
            return []

        from datetime import datetime, timedelta
        today = datetime.now()
        dates = []
        # 每周 N 天，选随机日期
        import random
        for week in range(5):  # 5 周
            week_start = today + timedelta(days=week * 7)
            week_days = list(range(7))
            random.shuffle(week_days)
            for d in week_days[:posts_per_week]:
                dt = week_start + timedelta(days=d)
                if dt >= today:
                    dates.append(dt.strftime("%Y-%m-%d"))
        dates = sorted(dates)[:30]

        prompt = f"""请为我规划一个月的微信朋友圈内容日历。

个人资料：{user_profile or '普通白领，喜欢科技和生活分享'}
兴趣爱好：{interests or '科技、阅读、美食、旅行'}
风格偏好：{style}

需要为以下日期各规划一条朋友圈（共{len(dates)}条）：
{', '.join(dates)}

以 JSON 数组返回，每条包含：
[
  {{"date": "YYYY-MM-DD", "topic": "主题关键词", "text": "朋友圈文案（10-80字）", "style": "文案风格", "media_hint": "配图建议"}}
]

内容策略：
- 70% 价值分享（观点/知识/感悟）
- 20% 生活记录（日常/美食/旅行）
- 10% 互动内容（提问/投票/求推荐）
- 适当结合节日/热点
- 每条风格略有变化，避免雷同
- 文案要自然，像真人发的

只返回 JSON 数组。"""

        try:
            raw = await self._ai_call([{"role": "user", "content": prompt}])
            entries = self._parse_plan(raw, dates)
            self._entries = entries
            self._save()
            return entries
        except Exception as e:
            logger.error(f"内容日历生成失败: {e}")
            return []

    def get_today_entry(self) -> Optional[CalendarEntry]:
        """获取今天的发圈计划"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        for entry in self._entries:
            if entry.date == today and entry.status == "planned":
                return entry
        return None

    def get_entries(self, status: str = "") -> List[Dict]:
        if status:
            return [e.to_dict() for e in self._entries if e.status == status]
        return [e.to_dict() for e in self._entries]

    def approve_entry(self, date: str) -> bool:
        for e in self._entries:
            if e.date == date:
                e.status = "approved"
                self._save()
                return True
        return False

    def skip_entry(self, date: str) -> bool:
        for e in self._entries:
            if e.date == date:
                e.status = "skipped"
                self._save()
                return True
        return False

    def update_entry(self, date: str, text: str = "", topic: str = "") -> bool:
        for e in self._entries:
            if e.date == date:
                if text:
                    e.text = text
                if topic:
                    e.topic = topic
                self._save()
                return True
        return False

    def mark_published(self, date: str):
        for e in self._entries:
            if e.date == date:
                e.status = "published"
                e.published_at = time.time()
                self._save()
                return

    def _parse_plan(self, raw: str, dates: List[str]) -> List[CalendarEntry]:
        raw = raw.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group())
        except json.JSONDecodeError:
            return []

        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entries.append(CalendarEntry(
                date=item.get("date", ""),
                topic=item.get("topic", ""),
                text=item.get("text", ""),
                style=item.get("style", ""),
                media_hint=item.get("media_hint", ""),
            ))
        return entries

    def _save(self):
        try:
            self.CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [e.to_dict() for e in self._entries]
            self.CALENDAR_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"日历保存失败: {e}")

    def _load(self):
        try:
            if self.CALENDAR_FILE.exists():
                data = json.loads(self.CALENDAR_FILE.read_text(encoding="utf-8"))
                self._entries = [
                    CalendarEntry(**item) for item in data if isinstance(item, dict)
                ]
        except Exception:
            self._entries = []
