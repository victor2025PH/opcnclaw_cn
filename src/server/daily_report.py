# -*- coding: utf-8 -*-
"""
智能日报系统

每天定时（默认 18:00）自动汇总全天数据，生成结构化日报。

数据源（全部就地采集，不额外存储）：
  - unified_inbox: 消息量统计
  - account_health: 各账号健康指标
  - workflow.store: 工作流执行情况
  - moments_analytics: 朋友圈互动数据
  - contact_profile: 联系人互动变化

设计决策：
  方案A: 各模块分别生成报告段落 → 格式不统一
  方案B: 统一采集原始指标 → LLM 一次性生成自然语言日报 → 选这个
  方案C: 纯模板 → 无需 LLM，速度最快，但不智能

  最终选择 B+C 混合：先用模板生成结构化数据报告，
  再可选让 LLM 追加一段"今日洞察"（深度分析）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class DailyReport:
    """日报数据结构"""
    date: str = ""
    generated_at: float = 0
    sections: Dict[str, Any] = field(default_factory=dict)
    ai_insight: str = ""    # LLM 生成的洞察
    score: int = 0          # 今日综合评分 0-100

    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "sections": self.sections,
            "ai_insight": self.ai_insight,
            "score": self.score,
        }

    def to_text(self) -> str:
        """生成可 TTS 播报的纯文本"""
        lines = [f"今日日报 — {self.date}"]
        s = self.sections

        msg = s.get("messages", {})
        if msg:
            lines.append(f"消息：收到 {msg.get('received', 0)} 条，发送 {msg.get('sent', 0)} 条，未读 {msg.get('unread', 0)} 条")

        accts = s.get("accounts", {})
        if accts:
            lines.append(f"账号：{accts.get('connected', 0)} 个在线，平均健康 {accts.get('avg_health', 0)} 分")

        wf = s.get("workflows", {})
        if wf:
            lines.append(f"工作流：今日执行 {wf.get('runs', 0)} 次，成功 {wf.get('success', 0)}，失败 {wf.get('failed', 0)}")

        moments = s.get("moments", {})
        if moments:
            lines.append(f"朋友圈：点赞 {moments.get('likes', 0)} 次，评论 {moments.get('comments', 0)} 条")

        if self.ai_insight:
            lines.append(f"AI 洞察：{self.ai_insight}")

        lines.append(f"综合评分：{self.score} 分")
        return "。".join(lines) + "。"


def collect_metrics() -> Dict[str, Any]:
    """采集全系统指标"""
    sections = {}

    # 1. 消息统计
    try:
        from .wechat.unified_inbox import get_inbox_stats
        stats = get_inbox_stats()
        sections["messages"] = {
            "total": stats.get("total", 0),
            "unread": stats.get("unread", 0),
            "received": stats.get("total", 0),
            "sent": 0,
            "starred": stats.get("starred", 0),
        }
    except Exception:
        sections["messages"] = {"total": 0, "unread": 0}

    # 2. 账号健康
    try:
        from .wechat.account_health import get_health_monitor
        ov = get_health_monitor().get_overview()
        sections["accounts"] = {
            "total": ov.get("total", 0),
            "connected": ov.get("connected", 0),
            "avg_health": ov.get("avg_health", 0),
            "danger_count": ov.get("danger_count", 0),
            "total_sent": ov.get("total_sent", 0),
            "total_errors": ov.get("total_errors", 0),
        }
        if sections["messages"]:
            sections["messages"]["sent"] = ov.get("total_sent", 0)
    except Exception:
        sections["accounts"] = {}

    # 3. 工作流执行
    try:
        from .workflow.store import get_stats as wf_stats
        ws = wf_stats()
        sections["workflows"] = {
            "total": ws.get("total_workflows", 0),
            "enabled": ws.get("enabled_workflows", 0),
            "runs": ws.get("today_runs", 0),
            "success": ws.get("today_success", 0),
            "failed": ws.get("today_failed", 0),
        }
    except Exception:
        sections["workflows"] = {}

    # 4. 朋友圈互动
    try:
        from .wechat.moments_analytics import get_overview
        mo = get_overview(days=1)
        sections["moments"] = {
            "likes": mo.get("total_likes", 0),
            "comments": mo.get("total_comments", 0),
            "posts": mo.get("total_posts", 0),
        }
    except Exception:
        sections["moments"] = {}

    # 5. 联系人活跃度
    try:
        from .wechat.contact_profile import get_stats as cp_stats
        cs = cp_stats()
        sections["contacts"] = {
            "total": cs.get("total", 0),
            "active_today": cs.get("active_today", 0) if "active_today" in cs else 0,
        }
    except Exception:
        sections["contacts"] = {}

    # 6. 通知聚合
    try:
        from .notification_aggregator import get_aggregator
        ns = get_aggregator().get_unread_summary()
        sections["notifications"] = {
            "total_groups": ns.get("total_groups", 0),
            "high_priority": ns.get("high_priority", 0),
        }
    except Exception:
        sections["notifications"] = {}

    return sections


def calculate_score(sections: Dict) -> int:
    """计算今日综合评分"""
    score = 60  # 基础分

    # 消息活跃度加分
    msgs = sections.get("messages", {})
    if msgs.get("received", 0) > 10:
        score += 5
    if msgs.get("sent", 0) > 5:
        score += 5

    # 健康度
    accts = sections.get("accounts", {})
    avg_h = accts.get("avg_health", 0)
    if avg_h >= 80:
        score += 10
    elif avg_h >= 50:
        score += 5
    if accts.get("danger_count", 0) > 0:
        score -= 15

    # 工作流成功率
    wf = sections.get("workflows", {})
    runs = wf.get("runs", 0)
    if runs > 0:
        success_rate = wf.get("success", 0) / runs
        score += int(success_rate * 10)
    if wf.get("failed", 0) > 0:
        score -= 5

    # 朋友圈互动
    moments = sections.get("moments", {})
    if moments.get("likes", 0) + moments.get("comments", 0) > 5:
        score += 5

    return max(0, min(100, score))


async def generate_report(ai_call=None) -> DailyReport:
    """
    生成今日日报。

    ai_call: 可选 LLM 调用 async (messages: list) -> str
    """
    from datetime import datetime
    sections = collect_metrics()
    score = calculate_score(sections)

    report = DailyReport(
        date=datetime.now().strftime("%Y年%m月%d日"),
        generated_at=time.time(),
        sections=sections,
        score=score,
    )

    # 用 LLM 生成洞察（可选）
    if ai_call:
        try:
            import json
            metrics_text = json.dumps(sections, ensure_ascii=False, indent=2)
            prompt = [
                {"role": "system", "content": "你是数据分析师。根据以下系统运行指标，用 1-2 句中文给出今日运营洞察和改进建议（不超过60字）。"},
                {"role": "user", "content": f"今日指标：\n{metrics_text}\n综合评分：{score}/100"},
            ]
            insight = await ai_call(prompt)
            if insight:
                report.ai_insight = insight.strip()[:100]
        except Exception as e:
            logger.debug(f"[DailyReport] AI insight failed: {e}")

    # 发布事件
    try:
        from .event_bus import publish
        publish("daily_report", report.to_dict())
    except Exception:
        pass

    logger.info(f"[DailyReport] 日报已生成: {report.date}, 评分 {score}")
    return report


# 缓存最近的日报
_last_report: Optional[DailyReport] = None


def get_last_report() -> Optional[DailyReport]:
    return _last_report


async def generate_and_cache(ai_call=None) -> DailyReport:
    global _last_report
    _last_report = await generate_report(ai_call)
    return _last_report
