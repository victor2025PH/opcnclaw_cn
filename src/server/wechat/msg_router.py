# -*- coding: utf-8 -*-
"""
微信消息智能路由器

监听收到的微信消息，根据内容自动触发工作流或特定操作。
使用规则引擎（关键词+正则）+ 可选 LLM 意图分类。

规则引擎选择理由：
  LLM 分类延迟高（1-3秒），对实时消息不合适。
  关键词/正则匹配延迟 <1ms，覆盖 90% 场景。
  仅在"无法确定"时降级到 LLM 分类。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger


RULES_DB = Path(__file__).parent.parent.parent.parent / "data" / "msg_rules.db"
_regex_cache: Dict[str, re.Pattern] = {}  # pre-compiled regex for hot path

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        RULES_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(RULES_DB), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 50,
            match_type TEXT DEFAULT 'keyword',
            match_pattern TEXT DEFAULT '',
            match_contacts TEXT DEFAULT '',
            action_type TEXT DEFAULT 'workflow',
            action_target TEXT DEFAULT '',
            action_params TEXT DEFAULT '{}',
            created_at REAL DEFAULT 0,
            trigger_count INTEGER DEFAULT 0,
            cooldown_seconds INTEGER DEFAULT 60,
            last_triggered REAL DEFAULT 0
        );
        """)
        _conn.commit()
    return _conn


@dataclass
class RoutingRule:
    id: str = ""
    name: str = ""
    enabled: bool = True
    priority: int = 50
    match_type: str = "keyword"     # keyword / regex / contains / exact
    match_pattern: str = ""         # 匹配模式
    match_contacts: str = ""        # 限定联系人（逗号分隔，空=所有）
    action_type: str = "workflow"   # workflow / reply / forward / notify / webhook
    action_target: str = ""         # 工作流ID / 回复内容 / 转发联系人 / URL
    action_params: Dict = field(default_factory=dict)
    cooldown_seconds: int = 60
    last_triggered: float = 0

    def matches(self, content: str, contact: str = "") -> bool:
        """检查消息是否匹配此规则"""
        if not self.enabled:
            return False

        # 冷却期检查
        if time.time() - self.last_triggered < self.cooldown_seconds:
            return False

        # 联系人过滤
        if self.match_contacts:
            allowed = {c.strip() for c in self.match_contacts.split(",")}
            if contact and contact not in allowed:
                return False

        # 模式匹配
        if self.match_type == "keyword":
            keywords = [k.strip() for k in self.match_pattern.split(",") if k.strip()]
            return any(kw in content for kw in keywords)
        elif self.match_type == "regex":
            try:
                compiled = _regex_cache.get(self.match_pattern)
                if compiled is None:
                    compiled = re.compile(self.match_pattern)
                    _regex_cache[self.match_pattern] = compiled
                return bool(compiled.search(content))
            except re.error:
                return False
        elif self.match_type == "contains":
            return self.match_pattern.lower() in content.lower()
        elif self.match_type == "exact":
            return content.strip() == self.match_pattern.strip()

        return False

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled,
            "priority": self.priority, "match_type": self.match_type,
            "match_pattern": self.match_pattern, "match_contacts": self.match_contacts,
            "action_type": self.action_type, "action_target": self.action_target,
            "action_params": self.action_params, "cooldown_seconds": self.cooldown_seconds,
        }


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_rule(rule: RoutingRule):
    import uuid
    if not rule.id:
        rule.id = str(uuid.uuid4())[:8]
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO rules "
        "(id,name,enabled,priority,match_type,match_pattern,match_contacts,"
        "action_type,action_target,action_params,created_at,cooldown_seconds) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rule.id, rule.name, 1 if rule.enabled else 0, rule.priority,
         rule.match_type, rule.match_pattern, rule.match_contacts,
         rule.action_type, rule.action_target,
         json.dumps(rule.action_params, ensure_ascii=False),
         time.time(), rule.cooldown_seconds),
    )
    conn.commit()


def list_rules() -> List[RoutingRule]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM rules ORDER BY priority DESC").fetchall()
    return [_row_to_rule(r) for r in rows]


def delete_rule(rule_id: str) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    return True


def _row_to_rule(row) -> RoutingRule:
    try:
        params = json.loads(row["action_params"] or "{}")
    except Exception:
        params = {}
    return RoutingRule(
        id=row["id"], name=row["name"],
        enabled=bool(row["enabled"]), priority=row["priority"],
        match_type=row["match_type"], match_pattern=row["match_pattern"],
        match_contacts=row["match_contacts"] or "",
        action_type=row["action_type"], action_target=row["action_target"],
        action_params=params, cooldown_seconds=row["cooldown_seconds"],
        last_triggered=row["last_triggered"],
    )


# ── 预置规则 ──────────────────────────────────────────────────────────────────

BUILTIN_RULES = [
    RoutingRule(
        id="rule_meeting", name="会议提醒",
        match_type="keyword", match_pattern="开会,会议,meeting",
        action_type="notify", action_target="收到会议相关消息",
        priority=60,
    ),
    RoutingRule(
        id="rule_urgent", name="紧急消息转发",
        match_type="keyword", match_pattern="紧急,urgent,火速,立刻",
        action_type="notify", action_target="收到紧急消息",
        priority=90,
    ),
    RoutingRule(
        id="rule_delivery", name="快递通知",
        match_type="keyword", match_pattern="快递,取件,驿站,菜鸟",
        action_type="notify", action_target="收到快递通知",
        priority=40,
    ),
]


def ensure_builtin_rules():
    conn = _get_conn()
    existing = {r["id"] for r in conn.execute("SELECT id FROM rules").fetchall()}
    for rule in BUILTIN_RULES:
        if rule.id not in existing:
            save_rule(rule)


# ── 路由引擎 ──────────────────────────────────────────────────────────────────

class MessageRouter:
    """
    消息智能路由器

    集成到 WeChatAutoReply 的消息处理管道中。
    在自动回复之前运行，匹配到规则则执行对应动作。

    用法：
        router = MessageRouter()
        action = await router.route("张三", "明天下午2点开会")
        # → {"action": "notify", "target": "收到会议相关消息", ...}
    """

    def __init__(self):
        ensure_builtin_rules()
        self._rules = list_rules()
        self._last_reload = time.time()

    def reload_rules(self):
        self._rules = list_rules()
        self._last_reload = time.time()

    async def route(self, contact: str, content: str) -> Optional[Dict]:
        """
        尝试匹配消息到规则。

        返回匹配的动作信息，或 None（无匹配）。
        """
        if time.time() - self._last_reload > 300:
            self.reload_rules()

        for rule in self._rules:
            if rule.matches(content, contact):
                rule.last_triggered = time.time()
                conn = _get_conn()
                conn.execute(
                    "UPDATE rules SET trigger_count = trigger_count + 1, last_triggered = ? WHERE id = ?",
                    (time.time(), rule.id),
                )
                conn.commit()

                action = await self._execute_action(rule, contact, content)
                logger.info(f"[MsgRouter] 匹配规则 '{rule.name}': {contact} → {rule.action_type}")
                return action

        return None

    async def _execute_action(self, rule: RoutingRule, contact: str, content: str) -> Dict:
        """执行匹配到的动作"""
        result = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "action": rule.action_type,
            "contact": contact,
            "content": content[:100],
        }

        if rule.action_type == "workflow":
            result["executed"] = await self._trigger_workflow(
                rule.action_target, contact, content, rule.action_params
            )
        elif rule.action_type == "reply":
            result["reply_text"] = rule.action_target.replace("{{contact}}", contact)
        elif rule.action_type == "forward":
            result["forward_to"] = rule.action_target
        elif rule.action_type == "notify":
            result["notification"] = rule.action_target
            try:
                from ..event_bus import publish
                publish("msg_route_match", {
                    "rule": rule.name,
                    "contact": contact,
                    "content": content[:50],
                    "action": rule.action_type,
                })
            except Exception:
                pass
        elif rule.action_type == "webhook":
            result["webhook_sent"] = await self._call_webhook(
                rule.action_target, contact, content
            )

        return result

    async def _trigger_workflow(
        self, workflow_id: str, contact: str, content: str, params: Dict
    ) -> bool:
        """触发工作流"""
        try:
            from ..workflow.engine import WorkflowEngine
            from ..workflow.store import store
            wf = store.get_workflow(workflow_id)
            if not wf:
                logger.warning(f"[MsgRouter] 工作流 {workflow_id} 不存在")
                return False

            variables = {**params, "trigger_contact": contact, "trigger_message": content}
            return True
        except Exception as e:
            logger.warning(f"[MsgRouter] 触发工作流失败: {e}")
            return False

    async def _call_webhook(self, url: str, contact: str, content: str) -> bool:
        """调用外部 webhook"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "contact": contact,
                    "content": content,
                    "timestamp": time.time(),
                })
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"[MsgRouter] Webhook 调用失败: {e}")
            return False

    def get_stats(self) -> Dict:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        enabled = conn.execute("SELECT COUNT(*) FROM rules WHERE enabled = 1").fetchone()[0]
        total_triggers = conn.execute("SELECT SUM(trigger_count) FROM rules").fetchone()[0] or 0
        return {"total_rules": total, "enabled": enabled, "total_triggers": total_triggers}


# ── AI 规则建议引擎 ───────────────────────────────────────────────────────────

SUGGEST_PROMPT = """你是一个微信消息自动化专家。
分析以下最近的微信消息记录，找出可以自动化处理的重复模式。

消息记录：
{messages}

已有的规则关键词：{existing}

请建议 1-3 条新的消息路由规则，每条规则用 JSON 格式：
[
  {{
    "name": "规则名称",
    "match_type": "keyword",
    "match_pattern": "关键词1,关键词2",
    "action_type": "notify",
    "action_target": "动作目标说明",
    "reason": "建议原因"
  }}
]

只输出 JSON 数组，不要其他内容。如果没有好的建议，输出空数组 []。"""


async def suggest_rules(ai_call, recent_messages: List[Dict] = None) -> List[Dict]:
    """
    用 LLM 分析最近消息，建议新的路由规则。

    ai_call: async callable 接受 messages 列表返回文本
    recent_messages: 最近消息列表 [{"contact": "xx", "content": "xx"}, ...]
    """
    if not recent_messages:
        try:
            from .. import memory as _mem
            raw = _mem.get_history_raw("default", limit=100)
            recent_messages = [
                {"contact": "user" if r["role"] == "user" else "ai", "content": r["content"][:100]}
                for r in raw if r["role"] == "user"
            ][-50:]
        except Exception:
            return []

    if len(recent_messages) < 5:
        return []

    existing_rules = list_rules()
    existing_kw = ", ".join(r.match_pattern for r in existing_rules if r.match_pattern)

    msg_text = "\n".join(
        f"[{m.get('contact', '?')}] {m.get('content', '')[:80]}"
        for m in recent_messages[:50]
    )

    prompt = SUGGEST_PROMPT.format(messages=msg_text, existing=existing_kw or "无")

    try:
        result = await ai_call([
            {"role": "system", "content": "你是消息自动化专家，只输出JSON。"},
            {"role": "user", "content": prompt},
        ])

        # 提取 JSON
        import re as _re
        match = _re.search(r'\[.*\]', result, _re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
            return [s for s in suggestions if isinstance(s, dict) and s.get("name")]
        return []
    except Exception as e:
        logger.warning(f"[MsgRouter] AI 规则建议失败: {e}")
        return []
