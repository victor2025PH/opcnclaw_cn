# -*- coding: utf-8 -*-
"""
消息导出报表

支持格式：
  - CSV: 通用表格（Excel / WPS 可直接打开）
  - HTML: 可打印为 PDF 的美化报表（含情感分析摘要）
  - JSON: 结构化原始数据

设计决策：
  方案A: 服务端生成 PDF (reportlab/weasyprint) → 需要大依赖、字体问题多
  方案B: CSV + HTML 报表 → 零依赖、浏览器直接打印 PDF、选这个
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


def export_conversations(
    source: str = "memory",
    session: str = "",
    contact: str = "",
    account_id: str = "",
    start_time: str = "",
    end_time: str = "",
    fmt: str = "csv",
    include_sentiment: bool = False,
) -> Dict:
    """
    导出对话记录。

    返回: {"content": str, "filename": str, "mime": str}
    """
    messages = _fetch_messages(source, session, contact, account_id, start_time, end_time)

    sentiment_summary = {}
    if include_sentiment and messages:
        sentiment_summary = _compute_sentiment_summary(messages)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    label = contact or session or "all"

    if fmt == "csv":
        return {
            "content": _to_csv(messages),
            "filename": f"chat_{label}_{ts}.csv",
            "mime": "text/csv; charset=utf-8-sig",
        }
    elif fmt == "html":
        return {
            "content": _to_html(messages, label, sentiment_summary),
            "filename": f"report_{label}_{ts}.html",
            "mime": "text/html; charset=utf-8",
        }
    else:
        return {
            "content": json.dumps(messages, ensure_ascii=False, indent=2),
            "filename": f"data_{label}_{ts}.json",
            "mime": "application/json",
        }


def _fetch_messages(source, session, contact, account_id, start_time, end_time) -> List[Dict]:
    """从不同来源获取消息"""
    messages = []

    if source == "inbox":
        try:
            from .wechat.unified_inbox import query_inbox
            raw = query_inbox(account_id, contact, limit=5000)
            for m in raw:
                messages.append({
                    "time": m.get("time_str", ""),
                    "sender": m.get("sender", ""),
                    "content": m.get("content", ""),
                    "direction": m.get("direction", ""),
                    "account": m.get("account_id", ""),
                })
        except Exception as e:
            logger.warning(f"Inbox export failed: {e}")
    else:
        try:
            from . import db as _db
            conn = _db.get_conn("main")
            conditions = []
            params = []
            if session:
                conditions.append("session = ?")
                params.append(session)
            if start_time:
                conditions.append("ts >= ?")
                params.append(start_time)
            if end_time:
                conditions.append("ts <= ?")
                params.append(end_time)
            where = " AND ".join(conditions) if conditions else "1=1"
            rows = conn.execute(
                f"SELECT role, content, ts FROM messages WHERE {where} ORDER BY ts ASC LIMIT 10000",
                params,
            ).fetchall()
            for r in rows:
                messages.append({
                    "time": r["ts"],
                    "sender": "User" if r["role"] == "user" else "AI",
                    "content": r["content"][:2000],
                    "direction": "in" if r["role"] == "user" else "out",
                })
        except Exception as e:
            logger.warning(f"Memory export failed: {e}")

    return messages


def _compute_sentiment_summary(messages: List[Dict]) -> Dict:
    """计算情感分析摘要"""
    try:
        from .sentiment_analyzer import analyze
        scores = []
        pos = neg = neu = 0
        for m in messages:
            result = analyze(m.get("content", ""))
            scores.append(result.score)
            if result.label == "positive":
                pos += 1
            elif result.label == "negative":
                neg += 1
            else:
                neu += 1
        avg = sum(scores) / len(scores) if scores else 0
        return {
            "avg_score": round(avg, 2),
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "total": len(scores),
        }
    except Exception:
        return {}


def _to_csv(messages: List[Dict]) -> str:
    output = io.StringIO()
    # BOM for Excel UTF-8
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["Time", "Sender", "Content", "Direction"])
    for m in messages:
        writer.writerow([m.get("time", ""), m.get("sender", ""), m.get("content", ""), m.get("direction", "")])
    return output.getvalue()


def _to_html(messages: List[Dict], label: str, sentiment: Dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(messages)

    sent_html = ""
    if sentiment:
        sent_html = f"""
        <div style="background:#f0f9ff;padding:16px;border-radius:8px;margin:16px 0">
          <h3 style="margin:0 0 8px">Sentiment Summary</h3>
          <div style="display:flex;gap:24px">
            <div>Avg Score: <b>{sentiment.get('avg_score', 0)}</b></div>
            <div style="color:#22c55e">Positive: {sentiment.get('positive', 0)}</div>
            <div style="color:#888">Neutral: {sentiment.get('neutral', 0)}</div>
            <div style="color:#ef4444">Negative: {sentiment.get('negative', 0)}</div>
          </div>
        </div>"""

    rows = []
    for m in messages:
        sender = m.get("sender", "")
        bg = "#f0fdf4" if m.get("direction") == "out" else "#fff"
        rows.append(f'<tr style="background:{bg}"><td style="padding:6px;white-space:nowrap;color:#888;font-size:12px">{m.get("time","")}</td>'
                     f'<td style="padding:6px;font-weight:600">{sender}</td>'
                     f'<td style="padding:6px">{m.get("content","")[:500]}</td></tr>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Chat Report - {label}</title>
<style>
  body {{ font-family:system-ui,sans-serif; max-width:900px; margin:0 auto; padding:20px; color:#1a1a1a; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ background:#f1f5f9; padding:8px; text-align:left; border-bottom:2px solid #e2e8f0; }}
  tr:hover {{ background:#f8fafc !important; }}
  @media print {{ body {{ font-size:11px; }} }}
</style></head><body>
<h1>Chat Report: {label}</h1>
<p style="color:#666">Generated: {now} | Messages: {total}</p>
{sent_html}
<table>
<thead><tr><th>Time</th><th>Sender</th><th>Content</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<footer style="margin-top:32px;padding-top:12px;border-top:1px solid #e2e8f0;color:#999;font-size:11px">
OpenClaw AI Voice Assistant - Auto-generated report
</footer>
</body></html>"""
