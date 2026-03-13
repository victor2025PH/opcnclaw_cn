# -*- coding: utf-8 -*-
"""
安全审计日志

记录所有敏感操作，支持查询和导出。

记录的操作类型：
  - wechat_send: 发送微信消息
  - wechat_config: 修改微信配置
  - workflow_run: 工作流执行
  - plugin_toggle: 插件启用/禁用
  - data_delete: 数据删除
  - broadcast_send: 群发消息
  - account_manage: 账号管理操作
  - knowledge_import: 知识库导入
  - system_config: 系统配置变更
  - circuit_breaker: 熔断器操作

设计：SQLite 持久化，自动轮转（保留最近 10000 条）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

DB_PATH = Path("data/audit.db")
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()
MAX_RECORDS = 10000


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            actor TEXT DEFAULT 'system',
            target TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            severity TEXT DEFAULT 'info',
            ip TEXT DEFAULT '',
            timestamp REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
        """)
        _conn.commit()
    return _conn


def log(
    action: str,
    actor: str = "system",
    target: str = "",
    detail: str = "",
    severity: str = "info",
    ip: str = "",
):
    """
    记录一条审计日志。

    severity: info / warning / critical
    """
    conn = _get_conn()
    ts = time.time()

    with _lock:
        conn.execute(
            "INSERT INTO audit_log (action, actor, target, detail, severity, ip, timestamp) VALUES (?,?,?,?,?,?,?)",
            (action, actor, target, detail[:1000], severity, ip, ts),
        )

        # 自动轮转
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        if count > MAX_RECORDS:
            conn.execute(
                f"DELETE FROM audit_log WHERE id IN (SELECT id FROM audit_log ORDER BY id ASC LIMIT {count - MAX_RECORDS})"
            )

        conn.commit()

    if severity == "critical":
        logger.warning(f"[AUDIT] CRITICAL: {action} by {actor} → {target}: {detail[:100]}")


def query(
    action: str = "",
    actor: str = "",
    severity: str = "",
    start_time: float = 0,
    end_time: float = 0,
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    """查询审计日志"""
    conn = _get_conn()
    conditions = []
    params = []

    if action:
        conditions.append("action = ?")
        params.append(action)
    if actor:
        conditions.append("actor = ?")
        params.append(actor)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)

    where = " AND ".join(conditions) if conditions else "1=1"

    total = conn.execute(f"SELECT COUNT(*) FROM audit_log WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {
        "logs": [_row_to_dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def get_stats() -> Dict:
    """审计统计"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    since_24h = time.time() - 86400

    today = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE timestamp >= ?", (since_24h,)
    ).fetchone()[0]

    critical = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE severity = 'critical' AND timestamp >= ?",
        (since_24h,),
    ).fetchone()[0]

    # 操作类型分布
    action_rows = conn.execute(
        "SELECT action, COUNT(*) as cnt FROM audit_log WHERE timestamp >= ? GROUP BY action ORDER BY cnt DESC LIMIT 10",
        (since_24h,),
    ).fetchall()

    return {
        "total": total,
        "today": today,
        "critical_today": critical,
        "action_distribution": {r["action"]: r["cnt"] for r in action_rows},
    }


def _row_to_dict(row) -> Dict:
    from datetime import datetime
    ts = row["timestamp"]
    return {
        "id": row["id"],
        "action": row["action"],
        "actor": row["actor"],
        "target": row["target"],
        "detail": row["detail"],
        "severity": row["severity"],
        "ip": row["ip"],
        "timestamp": ts,
        "time_str": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "",
    }
