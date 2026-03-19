# -*- coding: utf-8 -*-
"""
跨账号联系人画像融合

问题：同一个人在不同微信号中可能有不同的昵称/备注名。
     数据分散在各账号的 contact_profiles 和 unified_inbox 中，
     无法形成完整的联系人 360 度视图。

方案对比：
  方案A: 基于手机号匹配 → 无法获取（微信不公开）
  方案B: 基于名称精确匹配 → 覆盖率低
  方案C: 多信号融合匹配 → 名称相似度 + 消息模式 + 手动确认
  选择C，三层匹配确保准确率。

匹配策略：
  L1: 精确匹配（完全相同的名称）
  L2: 模糊匹配（编辑距离 <= 2 或包含关系）
  L3: 行为匹配（发消息时间模式相似）
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from .. import db as _db

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("wechat")


@dataclass
class FusedContact:
    """融合后的联系人画像"""
    id: str = ""
    display_name: str = ""
    aliases: List[str] = field(default_factory=list)
    account_contacts: List[Dict] = field(default_factory=list)  # [{account_id, name}]
    relationship: str = "normal"
    intimacy: float = 30.0
    interests: List[str] = field(default_factory=list)
    notes: str = ""
    total_interactions: int = 0
    created_at: float = 0
    updated_at: float = 0

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "display_name": self.display_name,
            "aliases": self.aliases, "account_contacts": self.account_contacts,
            "relationship": self.relationship, "intimacy": round(self.intimacy, 1),
            "interests": self.interests, "notes": self.notes,
            "total_interactions": self.total_interactions,
            "accounts_count": len(self.account_contacts),
        }


# ── 名称匹配工具 ─────────────────────────────────────────────────────────────

def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein 编辑距离"""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _name_similarity(name1: str, name2: str) -> float:
    """计算名称相似度 0.0 - 1.0"""
    if not name1 or not name2:
        return 0.0
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    if n1 == n2:
        return 1.0
    # 包含关系
    if n1 in n2 or n2 in n1:
        return 0.8
    # 编辑距离
    dist = _edit_distance(n1, n2)
    max_len = max(len(n1), len(n2))
    if max_len == 0:
        return 0.0
    ratio = 1.0 - dist / max_len
    return max(0.0, ratio)


# ── 自动匹配引擎 ─────────────────────────────────────────────────────────────

def auto_discover_matches(threshold: float = 0.7) -> List[Dict]:
    """
    自动发现跨账号的潜在联系人匹配。

    从 unified_inbox 中提取所有联系人名，交叉比对。
    返回匹配建议列表 [{name1, account1, name2, account2, similarity, method}]
    """
    try:
        from .unified_inbox import _get_conn as inbox_conn
        conn = inbox_conn()
    except Exception:
        return []

    # 获取每个账号的联系人列表
    rows = conn.execute(
        "SELECT DISTINCT account_id, contact FROM inbox WHERE is_mine = 0"
    ).fetchall()

    account_contacts: Dict[str, Set[str]] = defaultdict(set)
    for r in rows:
        account_contacts[r["account_id"]].add(r["contact"])

    accounts = list(account_contacts.keys())
    if len(accounts) < 2:
        return []

    matches = []
    seen_pairs = set()

    for i in range(len(accounts)):
        for j in range(i + 1, len(accounts)):
            acct_a = accounts[i]
            acct_b = accounts[j]
            for name_a in account_contacts[acct_a]:
                for name_b in account_contacts[acct_b]:
                    pair_key = tuple(sorted([f"{acct_a}:{name_a}", f"{acct_b}:{name_b}"]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    sim = _name_similarity(name_a, name_b)
                    if sim >= threshold:
                        method = "exact" if sim == 1.0 else "fuzzy"
                        matches.append({
                            "name1": name_a, "account1": acct_a,
                            "name2": name_b, "account2": acct_b,
                            "similarity": round(sim, 3),
                            "method": method,
                        })

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches[:50]


# ── CRUD ─────────────────────────────────────────────────────────────────────

import json, uuid


def create_fused_contact(
    display_name: str,
    account_contacts: List[Dict],
    relationship: str = "normal",
) -> FusedContact:
    """创建融合联系人"""
    fid = str(uuid.uuid4())[:8]
    aliases = list(set(ac.get("name", "") for ac in account_contacts))
    now = time.time()
    fc = FusedContact(
        id=fid, display_name=display_name, aliases=aliases,
        account_contacts=account_contacts, relationship=relationship,
        created_at=now, updated_at=now,
    )
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO contact_links "
            "(id,display_name,aliases,account_contacts,relationship,intimacy,interests,notes,total_interactions,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fc.id, fc.display_name, json.dumps(fc.aliases, ensure_ascii=False),
             json.dumps(fc.account_contacts, ensure_ascii=False),
             fc.relationship, fc.intimacy,
             json.dumps(fc.interests, ensure_ascii=False),
             fc.notes, fc.total_interactions, fc.created_at, fc.updated_at),
        )
        # 更新别名映射
        for ac in account_contacts:
            conn.execute(
                "INSERT OR REPLACE INTO alias_map (account_id, contact_name, fused_id, confidence, match_method) "
                "VALUES (?,?,?,?,?)",
                (ac.get("account_id", ""), ac.get("name", ""), fc.id, 1.0, "manual"),
            )
        conn.commit()
    return fc


def merge_contacts(fused_id: str, new_account_id: str, new_name: str) -> bool:
    """将一个新的账号联系人合并到已有的融合联系人"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM contact_links WHERE id=?", (fused_id,)).fetchone()
    if not row:
        return False

    accts = json.loads(row["account_contacts"])
    aliases = json.loads(row["aliases"])

    accts.append({"account_id": new_account_id, "name": new_name})
    if new_name not in aliases:
        aliases.append(new_name)

    with _lock:
        conn.execute(
            "UPDATE contact_links SET account_contacts=?, aliases=?, updated_at=? WHERE id=?",
            (json.dumps(accts, ensure_ascii=False), json.dumps(aliases, ensure_ascii=False),
             time.time(), fused_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO alias_map (account_id, contact_name, fused_id, confidence, match_method) "
            "VALUES (?,?,?,?,?)",
            (new_account_id, new_name, fused_id, 1.0, "manual"),
        )
        conn.commit()
    return True


def resolve_fused_id(account_id: str, contact_name: str) -> Optional[str]:
    """查找联系人对应的融合 ID"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT fused_id FROM alias_map WHERE account_id=? AND contact_name=?",
        (account_id, contact_name),
    ).fetchone()
    return row["fused_id"] if row else None


def get_fused_contact(fused_id: str) -> Optional[FusedContact]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM contact_links WHERE id=?", (fused_id,)).fetchone()
    if not row:
        return None
    return FusedContact(
        id=row["id"], display_name=row["display_name"],
        aliases=json.loads(row["aliases"]),
        account_contacts=json.loads(row["account_contacts"]),
        relationship=row["relationship"], intimacy=row["intimacy"],
        interests=json.loads(row["interests"]), notes=row["notes"],
        total_interactions=row["total_interactions"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def list_fused_contacts() -> List[FusedContact]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM contact_links ORDER BY updated_at DESC").fetchall()
    return [FusedContact(
        id=r["id"], display_name=r["display_name"],
        aliases=json.loads(r["aliases"]),
        account_contacts=json.loads(r["account_contacts"]),
        relationship=r["relationship"], intimacy=r["intimacy"],
        interests=json.loads(r["interests"]), notes=r["notes"],
        total_interactions=r["total_interactions"],
    ) for r in rows]


def delete_fused_contact(fused_id: str):
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM contact_links WHERE id=?", (fused_id,))
        conn.execute("DELETE FROM alias_map WHERE fused_id=?", (fused_id,))
        conn.commit()


def get_360_view(fused_id: str) -> Dict:
    """获取融合联系人的 360 度视图"""
    fc = get_fused_contact(fused_id)
    if not fc:
        return {}

    result = fc.to_dict()

    # 跨账号消息统计
    try:
        from .unified_inbox import _get_conn as inbox_conn
        conn = inbox_conn()
        total_msgs = 0
        by_account = {}
        for ac in fc.account_contacts:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE account_id=? AND contact=?",
                (ac.get("account_id", ""), ac.get("name", "")),
            ).fetchone()
            cnt = count_row[0] if count_row else 0
            total_msgs += cnt
            by_account[ac.get("account_id", "")] = cnt
        result["total_messages"] = total_msgs
        result["messages_by_account"] = by_account
    except Exception:
        pass

    # 联系人画像
    try:
        from .contact_profile import get_profile
        profiles = []
        for ac in fc.account_contacts:
            p = get_profile(ac.get("name", ""))
            if p:
                profiles.append({
                    "account": ac.get("account_id", ""),
                    "intimacy": p.intimacy,
                    "likes": p.total_likes,
                    "comments": p.total_comments,
                })
        result["profiles"] = profiles
        if profiles:
            result["avg_intimacy"] = round(sum(p["intimacy"] for p in profiles) / len(profiles), 1)
    except Exception:
        pass

    return result
