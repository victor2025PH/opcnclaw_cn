# -*- coding: utf-8 -*-
"""
多账号统一收件箱 + 跨账号消息转发

设计决策：
  方案A: 各账号消息独立存储，查询时实时聚合 → 延迟高
  方案B: 统一写入一张表，account_id 字段区分 → 查询快，选这个

  收件箱和转发引擎合并到一个模块，因为两者共享消息入口管道。
  消息入口 → 写入统一收件箱 → 检查转发规则 → 执行转发
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .. import db as _db

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


# ── 统一收件箱 ────────────────────────────────────────────────────────────────

def ingest_message(
    account_id: str,
    contact: str,
    sender: str,
    content: str,
    is_group: bool = False,
    is_mine: bool = False,
    timestamp: float = 0,
) -> int:
    """
    将消息写入统一收件箱。

    由各账号的消息监听器调用。返回消息ID。
    同时触发转发规则检查。
    """
    ts = timestamp or time.time()
    conn = _get_conn()
    with _lock:
        cur = conn.execute(
            "INSERT INTO inbox (account_id,contact,sender,content,is_group,is_mine,timestamp) "
            "VALUES (?,?,?,?,?,?,?)",
            (account_id, contact, sender, content,
             1 if is_group else 0, 1 if is_mine else 0, ts),
        )
        conn.commit()
        msg_id = cur.lastrowid

    # 异步检查转发（不阻塞消息入库）
    try:
        _check_forward_rules(account_id, contact, sender, content, is_group)
    except Exception as e:
        logger.debug(f"[Inbox] 转发检查异常: {e}")

    # 发布 SSE 事件
    try:
        from ..event_bus import publish
        publish("inbox_message", {
            "account_id": account_id,
            "contact": contact,
            "sender": sender,
            "content": content[:80],
            "is_mine": is_mine,
        })
    except Exception:
        pass

    return msg_id


def query_inbox(
    account_id: str = "",
    contact: str = "",
    unread_only: bool = False,
    starred_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict]:
    """查询收件箱消息"""
    conn = _get_conn()
    conditions = []
    params = []

    if account_id:
        conditions.append("account_id = ?")
        params.append(account_id)
    if contact:
        conditions.append("contact = ?")
        params.append(contact)
    if unread_only:
        conditions.append("read = 0")
    if starred_only:
        conditions.append("starred = 1")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM inbox {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return [dict(r) for r in rows]


def mark_read(msg_ids: List[int] = None, account_id: str = "", contact: str = ""):
    """标记消息已读"""
    conn = _get_conn()
    with _lock:
        if msg_ids:
            placeholders = ",".join("?" * len(msg_ids))
            conn.execute(f"UPDATE inbox SET read=1 WHERE id IN ({placeholders})", msg_ids)
        elif account_id and contact:
            conn.execute("UPDATE inbox SET read=1 WHERE account_id=? AND contact=?", (account_id, contact))
        elif account_id:
            conn.execute("UPDATE inbox SET read=1 WHERE account_id=?", (account_id,))
        conn.commit()


def toggle_star(msg_id: int) -> bool:
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT starred FROM inbox WHERE id=?", (msg_id,)).fetchone()
        if not row:
            return False
        new_val = 0 if row["starred"] else 1
        conn.execute("UPDATE inbox SET starred=? WHERE id=?", (new_val, msg_id))
        conn.commit()
    return bool(new_val)


def get_inbox_stats(account_id: str = "") -> Dict:
    """收件箱统计"""
    conn = _get_conn()
    where = "WHERE account_id = ?" if account_id else ""
    params = [account_id] if account_id else []

    total = conn.execute(f"SELECT COUNT(*) FROM inbox {where}", params).fetchone()[0]
    unread = conn.execute(f"SELECT COUNT(*) FROM inbox {where} {'AND' if where else 'WHERE'} read=0", params).fetchone()[0]
    starred = conn.execute(f"SELECT COUNT(*) FROM inbox {where} {'AND' if where else 'WHERE'} starred=1", params).fetchone()[0]

    # 按账号分组的未读数
    acct_rows = conn.execute(
        "SELECT account_id, COUNT(*) as cnt FROM inbox WHERE read=0 GROUP BY account_id"
    ).fetchall()
    by_account = {r["account_id"]: r["cnt"] for r in acct_rows}

    # 最近活跃联系人
    recent = conn.execute(
        f"SELECT account_id, contact, MAX(timestamp) as last_ts, COUNT(*) as cnt "
        f"FROM inbox {where} GROUP BY account_id, contact ORDER BY last_ts DESC LIMIT 10",
        params,
    ).fetchall()

    return {
        "total": total,
        "unread": unread,
        "starred": starred,
        "unread_by_account": by_account,
        "recent_contacts": [dict(r) for r in recent],
    }


def get_conversations(account_id: str = "", limit: int = 30) -> List[Dict]:
    """获取会话列表（按最后消息时间排序）"""
    conn = _get_conn()
    where = "WHERE account_id = ?" if account_id else ""
    params = [account_id] if account_id else []

    rows = conn.execute(f"""
        SELECT account_id, contact, is_group,
               MAX(timestamp) as last_ts,
               COUNT(*) as msg_count,
               SUM(CASE WHEN read=0 THEN 1 ELSE 0 END) as unread_count
        FROM inbox {where}
        GROUP BY account_id, contact
        ORDER BY last_ts DESC LIMIT ?
    """, params + [limit]).fetchall()

    result = []
    for r in rows:
        last_msg = conn.execute(
            "SELECT content FROM inbox WHERE account_id=? AND contact=? ORDER BY timestamp DESC LIMIT 1",
            (r["account_id"], r["contact"]),
        ).fetchone()
        result.append({
            **dict(r),
            "last_msg": last_msg["content"][:60] if last_msg else "",
        })
    return result


# ── 跨账号消息转发 ────────────────────────────────────────────────────────────

@dataclass
class ForwardRule:
    id: str = ""
    name: str = ""
    enabled: bool = True
    src_account: str = ""
    src_contact: str = ""      # 空 = 所有联系人
    dst_account: str = ""
    dst_contact: str = ""
    keyword_filter: str = ""   # 逗号分隔，空 = 不过滤
    transform: str = "plain"   # plain / prefix / ai_rewrite

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "name": self.name, "enabled": self.enabled,
            "src_account": self.src_account, "src_contact": self.src_contact,
            "dst_account": self.dst_account, "dst_contact": self.dst_contact,
            "keyword_filter": self.keyword_filter, "transform": self.transform,
        }


def save_forward_rule(rule: ForwardRule):
    import uuid
    if not rule.id:
        rule.id = str(uuid.uuid4())[:8]
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO forward_rules "
            "(id,name,enabled,src_account,src_contact,dst_account,dst_contact,keyword_filter,transform,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rule.id, rule.name, 1 if rule.enabled else 0,
             rule.src_account, rule.src_contact, rule.dst_account, rule.dst_contact,
             rule.keyword_filter, rule.transform, time.time()),
        )
        conn.commit()


def list_forward_rules() -> List[ForwardRule]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM forward_rules ORDER BY created_at DESC").fetchall()
    return [ForwardRule(
        id=r["id"], name=r["name"], enabled=bool(r["enabled"]),
        src_account=r["src_account"], src_contact=r["src_contact"],
        dst_account=r["dst_account"], dst_contact=r["dst_contact"],
        keyword_filter=r["keyword_filter"], transform=r["transform"],
    ) for r in rows]


def delete_forward_rule(rule_id: str):
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM forward_rules WHERE id=?", (rule_id,))
        conn.commit()


def _check_forward_rules(account_id: str, contact: str, sender: str, content: str, is_group: bool):
    """检查并执行转发规则"""
    rules = list_forward_rules()
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.src_account and rule.src_account != account_id:
            continue
        if rule.src_contact and rule.src_contact != contact:
            continue
        if rule.keyword_filter:
            keywords = [k.strip() for k in rule.keyword_filter.split(",") if k.strip()]
            if not any(kw in content for kw in keywords):
                continue

        # 匹配成功，执行转发
        _execute_forward(rule, contact, sender, content)


def _execute_forward(rule: ForwardRule, original_contact: str, sender: str, content: str):
    """执行一条转发"""
    try:
        from .account_manager import get_wx

        wx = get_wx(rule.dst_account)
        if not wx:
            logger.warning(f"[Forward] 目标账号 {rule.dst_account} 未连接")
            return

        if rule.transform == "prefix":
            msg = f"[转发自 {original_contact}/{sender}] {content}"
        elif rule.transform == "ai_rewrite":
            msg = f"[{sender}] {content}"
        else:
            msg = content

        wx.SendMsg(msg, rule.dst_contact)

        # 标记已转发
        conn = _get_conn()
        with _lock:
            conn.execute(
                "UPDATE inbox SET forwarded=1 WHERE account_id=? AND contact=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (rule.src_account or "", original_contact),
            )
            conn.commit()

        logger.info(f"[Forward] {rule.name}: {original_contact} → {rule.dst_contact}")

        try:
            from ..event_bus import publish
            publish("forward_event", {
                "rule": rule.name,
                "from": original_contact,
                "to": rule.dst_contact,
                "content": content[:50],
            })
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"[Forward] 转发失败: {e}")
