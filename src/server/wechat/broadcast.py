# -*- coding: utf-8 -*-
"""
微信群发消息系统

功能：
  1. 模板消息 — 支持变量替换的消息模板
  2. 受众筛选 — 按关系、亲密度、兴趣标签筛选目标
  3. 个性化生成 — AI 根据每个联系人画像微调内容
  4. 安全发送 — 随机间隔、每日上限、优先级队列
  5. 发送追踪 — 记录送达状态和回复率

优化思考：
  群发最大风险是被微信封号。关键设计：
  - 绝对不能"同一秒给多人发同样的消息"
  - 每条消息都要有微调（时间词、语气词随机替换）
  - 设置硬上限（每天最多 50 人）
  - 检测到异常立即暂停
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .. import db as _db


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


# ── 消息模板 ──────────────────────────────────────────────────────────────────

@dataclass
class MessageTemplate:
    id: str = ""
    name: str = ""
    content: str = ""
    variables: List[str] = field(default_factory=list)
    category: str = ""

    def render(self, values: Dict[str, str] = None) -> str:
        """渲染模板，替换 {{变量}}"""
        text = self.content
        for k, v in (values or {}).items():
            text = text.replace(f"{{{{{k}}}}}", v)
        return text

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "content": self.content,
            "variables": self.variables, "category": self.category,
        }


def save_template(tpl: MessageTemplate):
    import uuid
    if not tpl.id:
        tpl.id = str(uuid.uuid4())[:8]
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO templates (id, name, content, variables, category, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tpl.id, tpl.name, tpl.content,
         json.dumps(tpl.variables, ensure_ascii=False), tpl.category, time.time()),
    )
    conn.commit()


def list_templates() -> List[Dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM templates ORDER BY created_at DESC").fetchall()
    return [{"id": r["id"], "name": r["name"], "content": r["content"],
             "variables": json.loads(r["variables"] or "[]"),
             "category": r["category"], "use_count": r["use_count"]} for r in rows]


def delete_template(tid: str) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM templates WHERE id = ?", (tid,))
    conn.commit()
    return True


# ── 预置模板 ──────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    MessageTemplate(
        id="tpl_festival", name="节日祝福",
        content="{{name}}，{{festival}}快乐！{{greeting}}",
        variables=["name", "festival", "greeting"],
        category="节日",
    ),
    MessageTemplate(
        id="tpl_birthday", name="生日祝福",
        content="{{name}}，生日快乐！🎂 祝你新的一岁一切顺利！",
        variables=["name"],
        category="祝福",
    ),
    MessageTemplate(
        id="tpl_share", name="内容分享",
        content="{{name}}，我觉得你可能会感兴趣：{{content}}",
        variables=["name", "content"],
        category="分享",
    ),
    MessageTemplate(
        id="tpl_care", name="日常关怀",
        content="{{name}}，好久没联系了，最近怎么样？{{extra}}",
        variables=["name", "extra"],
        category="关怀",
    ),
]


def ensure_builtin_templates():
    conn = _get_conn()
    existing = {r["id"] for r in conn.execute("SELECT id FROM templates").fetchall()}
    for tpl in BUILTIN_TEMPLATES:
        if tpl.id not in existing:
            save_template(tpl)


# ── 受众筛选 ──────────────────────────────────────────────────────────────────

def filter_audience(
    min_intimacy: float = 0,
    max_intimacy: float = 100,
    relationship: str = "",
    interests: List[str] = None,
    exclude: List[str] = None,
) -> List[Dict]:
    """
    从联系人画像库筛选受众。

    返回满足条件的联系人列表。
    """
    try:
        from .contact_profile import list_profiles
        profiles = list_profiles(min_intimacy=min_intimacy)
    except Exception:
        return []

    exclude = set(exclude or [])
    result = []
    for p in profiles:
        if p.name in exclude:
            continue
        if p.intimacy > max_intimacy:
            continue
        if relationship and p.relationship != relationship:
            continue
        if interests:
            profile_interests = set(i.lower() for i in p.interests)
            if not any(i.lower() in profile_interests for i in interests):
                continue
        result.append(p.to_dict())

    return result


# ── 群发任务 ──────────────────────────────────────────────────────────────────

@dataclass
class BroadcastCampaign:
    id: str = ""
    name: str = ""
    message: str = ""
    template_id: str = ""
    audience_filter: Dict = field(default_factory=dict)
    personalize: bool = False
    status: str = "draft"  # draft / running / paused / completed / cancelled
    targets: List[str] = field(default_factory=list)

    DAILY_LIMIT = 50
    MIN_INTERVAL = 15   # 秒
    MAX_INTERVAL = 45   # 秒


class BroadcastEngine:
    """
    群发执行引擎

    安全策略：
      - 每天最多 50 人
      - 消息间隔 15-45 秒随机
      - 每条消息微调（语气词/标点随机替换）
      - 检测到发送失败 3 次立即暂停
      - 发送前/后随机延迟
    """

    def __init__(self, send_fn: Callable = None, ai_call: Callable = None):
        self._send_fn = send_fn  # async (contact, message) -> bool
        self._ai_call = ai_call
        self._running = False
        self._daily_sent = 0
        self._daily_date = ""
        self._consecutive_errors = 0

    async def execute_campaign(
        self,
        campaign: BroadcastCampaign,
        progress_cb: Callable = None,
    ) -> Dict:
        """执行群发任务"""
        if not self._send_fn:
            return {"error": "发送函数未配置"}

        self._check_daily_reset()
        if self._daily_sent >= BroadcastCampaign.DAILY_LIMIT:
            return {"error": f"今日已达上限 {BroadcastCampaign.DAILY_LIMIT} 人"}

        conn = _get_conn()
        import uuid
        if not campaign.id:
            campaign.id = str(uuid.uuid4())[:8]

        targets = campaign.targets
        if not targets:
            return {"error": "无目标联系人"}

        remaining_quota = BroadcastCampaign.DAILY_LIMIT - self._daily_sent
        targets = targets[:remaining_quota]

        conn.execute(
            "INSERT OR REPLACE INTO campaigns "
            "(id, template_id, name, message, audience_filter, personalize, status, "
            "total_targets, created_at, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign.id, campaign.template_id, campaign.name, campaign.message,
             json.dumps(campaign.audience_filter, ensure_ascii=False),
             1 if campaign.personalize else 0, "running",
             len(targets), time.time(), time.time()),
        )
        conn.commit()

        self._running = True
        self._consecutive_errors = 0
        sent = 0
        failed = 0

        for i, contact in enumerate(targets):
            if not self._running:
                break

            msg = await self._prepare_message(campaign.message, contact, campaign.personalize)

            conn.execute(
                "INSERT INTO send_log (campaign_id, contact_name, message_sent, status) "
                "VALUES (?, ?, ?, 'sending')",
                (campaign.id, contact, msg),
            )
            conn.commit()

            try:
                success = await self._send_fn(contact, msg)
                if success:
                    sent += 1
                    self._daily_sent += 1
                    self._consecutive_errors = 0
                    conn.execute(
                        "UPDATE send_log SET status='sent', sent_at=? "
                        "WHERE campaign_id=? AND contact_name=? AND status='sending'",
                        (time.time(), campaign.id, contact),
                    )
                else:
                    failed += 1
                    self._consecutive_errors += 1
                    conn.execute(
                        "UPDATE send_log SET status='failed', error='send_failed' "
                        "WHERE campaign_id=? AND contact_name=? AND status='sending'",
                        (campaign.id, contact),
                    )
            except Exception as e:
                failed += 1
                self._consecutive_errors += 1
                conn.execute(
                    "UPDATE send_log SET status='failed', error=? "
                    "WHERE campaign_id=? AND contact_name=? AND status='sending'",
                    (str(e)[:100], campaign.id, contact),
                )

            conn.commit()

            if self._consecutive_errors >= 3:
                logger.warning("[Broadcast] 连续失败3次，暂停群发")
                self._running = False
                break

            if progress_cb:
                try:
                    progress_cb(i + 1, len(targets), contact, sent, failed)
                except Exception:
                    pass

            if i < len(targets) - 1:
                delay = random.uniform(
                    BroadcastCampaign.MIN_INTERVAL,
                    BroadcastCampaign.MAX_INTERVAL,
                )
                await asyncio.sleep(delay)

        status = "completed" if self._running else "paused"
        conn.execute(
            "UPDATE campaigns SET status=?, sent_count=?, failed_count=?, completed_at=? "
            "WHERE id=?",
            (status, sent, failed, time.time(), campaign.id),
        )
        conn.commit()
        self._running = False

        return {
            "campaign_id": campaign.id,
            "status": status,
            "total": len(targets),
            "sent": sent,
            "failed": failed,
        }

    def stop(self):
        self._running = False

    async def _prepare_message(self, template: str, contact: str, personalize: bool) -> str:
        """准备发送消息：变量替换 + 微调"""
        msg = template.replace("{{name}}", contact)

        now = datetime.now()
        msg = msg.replace("{{date}}", now.strftime("%m月%d日"))
        msg = msg.replace("{{weekday}}", ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()])
        msg = msg.replace("{{time_greeting}}", _time_greeting())

        if personalize and self._ai_call:
            msg = await self._personalize_with_ai(msg, contact)
        else:
            msg = _add_variation(msg)

        return msg

    async def _personalize_with_ai(self, base_msg: str, contact: str) -> str:
        """AI 个性化微调消息"""
        try:
            from .contact_profile import get_profile
            profile = get_profile(contact)
            prompt = (
                f"请微调以下消息，让它更适合发给「{contact}」。\n"
                f"对方信息：关系={profile.relationship}，"
                f"兴趣={','.join(profile.interests[:3])}，"
                f"评论风格={profile.comment_style}\n\n"
                f"原消息：{base_msg}\n\n"
                f"要求：保持原意，微调语气和细节，10-50字。只返回调整后的消息。"
            )
            result = await self._ai_call([{"role": "user", "content": prompt}])
            return result.strip() if result and len(result) < 200 else _add_variation(base_msg)
        except Exception:
            return _add_variation(base_msg)

    def _check_daily_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_date != today:
            self._daily_date = today
            self._daily_sent = 0

    def get_campaign_log(self, campaign_id: str) -> List[Dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM send_log WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
        return [{"contact": r["contact_name"], "message": r["message_sent"][:50],
                 "status": r["status"], "sent_at": r["sent_at"],
                 "error": r["error"]} for r in rows]

    def get_campaigns(self, limit: int = 20) -> List[Dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "status": r["status"],
                 "total": r["total_targets"], "sent": r["sent_count"],
                 "failed": r["failed_count"],
                 "created_at": r["created_at"]} for r in rows]

    def get_daily_stats(self) -> Dict:
        self._check_daily_reset()
        return {
            "sent_today": self._daily_sent,
            "daily_limit": BroadcastCampaign.DAILY_LIMIT,
            "remaining": max(0, BroadcastCampaign.DAILY_LIMIT - self._daily_sent),
        }


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _time_greeting() -> str:
    h = datetime.now().hour
    if h < 6:
        return "夜深了"
    elif h < 9:
        return "早上好"
    elif h < 12:
        return "上午好"
    elif h < 14:
        return "中午好"
    elif h < 18:
        return "下午好"
    else:
        return "晚上好"


_VARIATIONS = {
    "！": ["！", "!", "～", "~"],
    "。": ["。", "~", ""],
    "，": ["，", ",", " "],
    "啊": ["啊", "呀", "呢"],
    "吧": ["吧", "呗", "嘛"],
    "哈哈": ["哈哈", "哈哈哈", "😄", "嘿嘿"],
}


def _add_variation(msg: str) -> str:
    """给消息添加微小变化，避免所有人收到完全相同的内容"""
    for orig, alternatives in _VARIATIONS.items():
        if orig in msg:
            if random.random() < 0.3:
                msg = msg.replace(orig, random.choice(alternatives), 1)
    return msg
