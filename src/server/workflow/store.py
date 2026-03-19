# -*- coding: utf-8 -*-
"""
工作流持久化层 — SQLite

表结构：
  workflows:  工作流定义
  executions: 执行历史
"""

import json
import sqlite3
import time
from typing import Dict, List, Optional

from loguru import logger

from .. import db as _db
from .models import Execution, ExecStatus, NodeResult, Workflow


def _get_conn() -> sqlite3.Connection:
    return _db.get_conn("main")


# ── Workflow CRUD ──────────────────────────────────────────────────────────────

def save_workflow(wf: Workflow):
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO workflows
           (id, name, definition, enabled, category, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (wf.id, wf.name, json.dumps(wf.to_dict(), ensure_ascii=False),
         int(wf.enabled), wf.category, wf.created_at, time.time()),
    )
    conn.commit()


def get_workflow(wf_id: str) -> Optional[Workflow]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT definition FROM workflows WHERE id = ?", (wf_id,)
    ).fetchone()
    if not row:
        return None
    try:
        return Workflow.from_dict(json.loads(row["definition"]))
    except Exception as e:
        logger.warning(f"Parse workflow {wf_id} failed: {e}")
        return None


def list_workflows(category: Optional[str] = None) -> List[Workflow]:
    conn = _get_conn()
    if category:
        rows = conn.execute(
            "SELECT definition FROM workflows WHERE category = ? ORDER BY updated_at DESC",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT definition FROM workflows ORDER BY updated_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        try:
            result.append(Workflow.from_dict(json.loads(r["definition"])))
        except Exception:
            continue
    return result


def delete_workflow(wf_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))
    conn.commit()
    return cur.rowcount > 0


def toggle_workflow(wf_id: str, enabled: bool) -> bool:
    wf = get_workflow(wf_id)
    if not wf:
        return False
    wf.enabled = enabled
    wf.updated_at = time.time()
    save_workflow(wf)
    return True


# ── Execution CRUD ──────────────────────────────────────────────────────────────

def save_execution(ex: Execution):
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO workflow_executions
           (id, workflow_id, workflow_name, status, trigger_type,
            started_at, finished_at, node_results, context_json, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ex.id, ex.workflow_id, ex.workflow_name,
         ex.status.value, ex.trigger_type,
         ex.started_at, ex.finished_at,
         json.dumps([r.to_dict() for r in ex.node_results], ensure_ascii=False),
         json.dumps(ex.context, ensure_ascii=False, default=str),
         ex.error),
    )
    conn.commit()


def get_execution(ex_id: str) -> Optional[Execution]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM workflow_executions WHERE id = ?", (ex_id,)
    ).fetchone()
    if not row:
        return None
    return _row_to_execution(row)


def list_executions(
    workflow_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Execution]:
    conn = _get_conn()
    if workflow_id:
        rows = conn.execute(
            "SELECT * FROM workflow_executions WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (workflow_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workflow_executions ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_execution(r) for r in rows]


def count_executions(workflow_id: Optional[str] = None) -> int:
    conn = _get_conn()
    if workflow_id:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM workflow_executions WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) as c FROM workflow_executions").fetchone()
    return row["c"] if row else 0


def cleanup_old_executions(days: int = 30):
    conn = _get_conn()
    cutoff = time.time() - days * 86400
    conn.execute("DELETE FROM workflow_executions WHERE started_at < ?", (cutoff,))
    conn.commit()


def _row_to_execution(row) -> Execution:
    node_results = []
    try:
        for nr in json.loads(row["node_results"] or "[]"):
            node_results.append(NodeResult(
                node_id=nr.get("node_id", ""),
                status=ExecStatus(nr.get("status", "pending")),
                output=nr.get("output"),
                error=nr.get("error", ""),
                started_at=nr.get("started_at", 0),
                finished_at=nr.get("finished_at", 0),
                duration_ms=nr.get("duration_ms", 0),
            ))
    except Exception:
        pass

    return Execution(
        id=row["id"],
        workflow_id=row["workflow_id"],
        workflow_name=row["workflow_name"] or "",
        status=ExecStatus(row["status"]),
        trigger_type=row["trigger_type"] or "manual",
        started_at=row["started_at"] or 0,
        finished_at=row["finished_at"] or 0,
        node_results=node_results,
        error=row["error"] or "",
    )


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_stats() -> Dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM workflows").fetchone()["c"]
    enabled = conn.execute(
        "SELECT COUNT(*) as c FROM workflows WHERE enabled = 1"
    ).fetchone()["c"]

    today_start = time.time() - (time.time() % 86400)
    today_runs = conn.execute(
        "SELECT COUNT(*) as c FROM workflow_executions WHERE started_at >= ?",
        (today_start,),
    ).fetchone()["c"]
    today_success = conn.execute(
        "SELECT COUNT(*) as c FROM workflow_executions WHERE started_at >= ? AND status = 'success'",
        (today_start,),
    ).fetchone()["c"]
    today_failed = conn.execute(
        "SELECT COUNT(*) as c FROM workflow_executions WHERE started_at >= ? AND status = 'failed'",
        (today_start,),
    ).fetchone()["c"]

    return {
        "total_workflows": total,
        "enabled_workflows": enabled,
        "today_runs": today_runs,
        "today_success": today_success,
        "today_failed": today_failed,
    }
