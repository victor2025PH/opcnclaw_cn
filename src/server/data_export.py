# -*- coding: utf-8 -*-
"""
数据导出模块

支持导出：
  - 互动分析数据 (CSV/JSON)
  - 联系人画像 (CSV/JSON)
  - 工作流执行历史 (CSV/JSON)
  - 对话记忆 (JSON)
  - 消息路由规则 (JSON)
"""

from __future__ import annotations

import csv
import io
import json
import time
from typing import Any, Dict, List


def export_analytics_csv(days: int = 30) -> str:
    """导出互动分析数据为 CSV"""
    try:
        from .wechat.moments_analytics import get_overview, get_top_contacts, get_hourly_distribution
        overview = get_overview(days)
        contacts = get_top_contacts(days, limit=50)
        hourly = get_hourly_distribution(days)

        buf = io.StringIO()
        buf.write("# OpenClaw 互动分析报告\n")
        buf.write(f"# 导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        buf.write(f"# 统计天数: {days}\n\n")

        # Overview
        buf.write("## 概览\n")
        writer = csv.writer(buf)
        writer.writerow(["指标", "数值"])
        for k, v in overview.items():
            writer.writerow([k, v])

        # Top contacts
        buf.write("\n## 活跃联系人\n")
        writer.writerow(["联系人", "点赞", "评论", "总互动"])
        for c in contacts:
            writer.writerow([c.get("author", ""), c.get("likes", 0), c.get("comments", 0), c.get("total", 0)])

        # Hourly
        buf.write("\n## 每小时分布\n")
        writer.writerow(["小时", "点赞", "评论", "总计"])
        for h in hourly:
            writer.writerow([h.get("hour", ""), h.get("likes", 0), h.get("comments", 0), h.get("total", 0)])

        return buf.getvalue()
    except Exception as e:
        return f"导出失败: {e}"


def export_contacts_csv() -> str:
    """导出联系人画像为 CSV"""
    try:
        from .wechat.contact_profile import list_profiles
        profiles = list_profiles()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["联系人", "关系", "亲密度", "兴趣标签", "评论风格", "总点赞", "总评论", "最后互动"])
        for p in profiles:
            writer.writerow([
                p.name, p.relationship, round(p.intimacy, 1),
                ",".join(p.interests) if isinstance(p.interests, list) else str(p.interests),
                p.comment_style, p.total_likes, p.total_comments,
                time.strftime('%Y-%m-%d', time.localtime(p.last_interaction)) if p.last_interaction else "",
            ])
        return buf.getvalue()
    except Exception as e:
        return f"导出失败: {e}"


def export_workflows_json() -> str:
    """导出工作流执行历史为 JSON"""
    try:
        from .workflow.store import store
        workflows = store.list_workflows()
        executions = store.list_executions(limit=200)

        data = {
            "exported_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "workflows": [w.to_dict() for w in workflows],
            "executions": [e.to_dict() for e in executions],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def export_conversations_json(session: str = "default", limit: int = 500) -> str:
    """导出对话记忆为 JSON"""
    try:
        from . import memory
        msgs = memory.get_history_raw(session, limit=limit)
        data = {
            "exported_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "session": session,
            "message_count": len(msgs),
            "messages": msgs,
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def export_rules_json() -> str:
    """导出消息路由规则为 JSON"""
    try:
        from .wechat.msg_router import list_rules
        rules = list_rules()
        data = {
            "exported_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "rules": [r.to_dict() for r in rules],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def export_full_report_json(days: int = 30) -> str:
    """导出完整系统报告 (JSON)"""
    report = {
        "exported_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "days": days,
    }

    # Analytics
    try:
        from .wechat.moments_analytics import get_overview, get_weekly_trend
        report["analytics"] = {
            "overview": get_overview(days),
            "weekly_trend": get_weekly_trend(8),
        }
    except Exception:
        report["analytics"] = {}

    # Contact count
    try:
        from .wechat.contact_profile import list_profiles
        profiles = list_profiles()
        report["contacts_count"] = len(profiles)
        report["avg_intimacy"] = round(sum(p.intimacy for p in profiles) / max(len(profiles), 1), 1)
    except Exception:
        pass

    # Workflow stats
    try:
        from .workflow.store import store
        wfs = store.list_workflows()
        report["workflows"] = {
            "total": len(wfs),
            "enabled": sum(1 for w in wfs if w.enabled),
        }
    except Exception:
        pass

    # Memory stats
    try:
        from .long_memory import get_memory_stats
        report["memory"] = get_memory_stats()
    except Exception:
        pass

    # Msg rules stats
    try:
        from .wechat.msg_router import MessageRouter
        report["msg_rules"] = MessageRouter().get_stats()
    except Exception:
        pass

    return json.dumps(report, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# 护城河数据导出/导入
# ═══════════════════════════════════════════════════════════════

def export_moat_data() -> Dict:
    """导出所有护城河数据为 JSON（用户画像+Agent记忆+偏好+项目索引+分数）"""
    import zipfile
    from pathlib import Path

    data = {
        "version": "6.0",
        "exported_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "exported_ts": time.time(),
    }

    # 1. 用户画像
    try:
        from .user_profile_ai import get_user_profile
        data["user_profile"] = get_user_profile()
    except Exception as e:
        data["user_profile"] = {}

    # 2. Agent 记忆
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        rows = conn.execute(
            "SELECT agent_id, agent_name, task, result_preview, team_name, feedback, created_at "
            "FROM agent_memory ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        data["agent_memories"] = [
            {"agent_id": r[0], "agent_name": r[1], "task": r[2],
             "result": r[3], "team": r[4], "feedback": r[5], "time": r[6]}
            for r in rows
        ]
    except Exception:
        data["agent_memories"] = []

    # 3. 用户偏好
    try:
        from . import db as _db
        conn = _db.get_conn("main")
        rows = conn.execute("SELECT key, value, updated_at FROM user_preferences").fetchall()
        data["preferences"] = {r[0]: r[1] for r in rows}
    except Exception:
        data["preferences"] = {}

    # 4. 项目索引
    try:
        from .project_workspace import list_projects
        data["projects"] = list_projects()
    except Exception:
        data["projects"] = []

    # 5. 护城河分数
    try:
        from .moat_score import calculate_moat_score
        data["moat_score"] = calculate_moat_score()
    except Exception:
        data["moat_score"] = {}

    return data


def export_moat_zip() -> bytes:
    """导出护城河数据为 ZIP（JSON + 项目文件）"""
    import zipfile
    from pathlib import Path

    _root = Path(__file__).resolve().parent.parent.parent
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 主数据
        main_data = export_moat_data()
        zf.writestr("moat_data.json",
                     json.dumps(main_data, ensure_ascii=False, indent=2))

        # 项目文件
        proj_dir = _root / "data" / "projects"
        if proj_dir.exists():
            for d in proj_dir.iterdir():
                if not d.is_dir():
                    continue
                for f in d.iterdir():
                    if f.is_file() and f.stat().st_size < 5_000_000:
                        zf.write(f, f"projects/{d.name}/{f.name}")

    buffer.seek(0)
    return buffer.read()


def import_moat_data(data: Dict) -> Dict:
    """从 JSON 导入护城河数据（合并模式，不覆盖已有）"""
    results = {"imported": [], "skipped": [], "errors": []}

    # 1. 用户画像
    if data.get("user_profile") and isinstance(data["user_profile"], dict):
        try:
            from .user_profile_ai import get_user_profile, save_user_profile
            profile = get_user_profile()
            imported = data["user_profile"]
            merged = 0

            for field in ["company", "industry", "target_users", "brand_tone",
                         "writing_style", "budget_range", "team_size"]:
                if imported.get(field) and not profile.get(field):
                    profile[field] = imported[field]
                    merged += 1

            # 合并列表字段
            for lf in ["products"]:
                existing = {p.get("name") for p in profile.get(lf, [])}
                for item in imported.get(lf, []):
                    if item.get("name") and item["name"] not in existing:
                        profile.setdefault(lf, []).append(item)
                        merged += 1

            for lf in ["common_terms", "competitor_names", "forbidden_words"]:
                existing = set(profile.get(lf, []))
                for item in imported.get(lf, []):
                    if item and item not in existing:
                        profile.setdefault(lf, []).append(item)
                        merged += 1

            if merged:
                save_user_profile(profile)
                results["imported"].append(f"用户画像（{merged} 个字段）")
            else:
                results["skipped"].append("用户画像（无新数据）")
        except Exception as e:
            results["errors"].append(f"用户画像: {e}")

    # 2. Agent 记忆
    if data.get("agent_memories") and isinstance(data["agent_memories"], list):
        try:
            from .agent_memory import save_agent_memory
            count = 0
            for m in data["agent_memories"][:100]:
                if m.get("agent_id") and m.get("task"):
                    save_agent_memory(
                        m["agent_id"], m.get("agent_name", ""),
                        m["task"], m.get("result", ""),
                        m.get("team", ""), m.get("feedback", ""),
                    )
                    count += 1
            if count:
                results["imported"].append(f"Agent 记忆（{count} 条）")
        except Exception as e:
            results["errors"].append(f"Agent 记忆: {e}")

    return results
