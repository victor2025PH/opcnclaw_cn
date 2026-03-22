# -*- coding: utf-8 -*-
"""
轻量级定时任务调度器

任务：
  1. 每日早报（8:30）— Agent 团队昨日工作总结
  2. 每周护城河报告（周一 9:00）— 分数变化+成长建议
  3. 画像自动保存（每 30 分钟）— 确保数据不丢失

设计：
  - 纯 asyncio，无外部依赖
  - 非阻塞，不影响主服务
  - 通过 EventBus 发布事件，前端通过 SSE/WebSocket 接收
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from loguru import logger


class Scheduler:
    """轻量级 cron 调度器"""

    def __init__(self):
        self._tasks: List[Dict] = []
        self._running = False
        self._task_handle = None

    def add(self, name: str, hour: int, minute: int, func: Callable,
            weekday: int = -1):
        """添加定时任务
        weekday: 0=周一 ... 6=周日, -1=每天
        """
        self._tasks.append({
            "name": name,
            "hour": hour,
            "minute": minute,
            "weekday": weekday,
            "func": func,
            "last_run": 0,
        })

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_event_loop()
            self._task_handle = loop.create_task(self._loop())
        except RuntimeError:
            pass
        logger.info(f"[Scheduler] 启动，{len(self._tasks)} 个定时任务")

    def stop(self):
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()

    async def _loop(self):
        while self._running:
            try:
                now = datetime.now()
                for task in self._tasks:
                    if self._should_run(task, now):
                        task["last_run"] = time.time()
                        try:
                            result = task["func"]()
                            if asyncio.iscoroutine(result):
                                await result
                            logger.info(f"[Scheduler] 执行: {task['name']}")
                        except Exception as e:
                            logger.warning(f"[Scheduler] {task['name']} 失败: {e}")
            except Exception:
                pass
            await asyncio.sleep(60)  # 每分钟检查一次

    def _should_run(self, task: Dict, now: datetime) -> bool:
        if now.hour != task["hour"] or now.minute != task["minute"]:
            return False
        if task["weekday"] >= 0 and now.weekday() != task["weekday"]:
            return False
        # 防止同一分钟重复执行
        if time.time() - task["last_run"] < 120:
            return False
        return True


# ── 定时任务函数 ──

async def daily_brief():
    """每日早报 — 推送到 EventBus"""
    try:
        from .event_bus import get_bus
        bus = get_bus()

        # 收集昨日数据
        brief_parts = []

        # 1. 护城河分数
        try:
            from .moat_score import calculate_moat_score
            score = calculate_moat_score()
            brief_parts.append(f"护城河分数：{score['total']}/100 ({score['level']})")
        except Exception:
            pass

        # 2. 项目统计
        try:
            from .project_workspace import list_projects
            projects = list_projects()
            brief_parts.append(f"累计项目：{len(projects)} 个")
        except Exception:
            pass

        # 3. Agent 活跃度
        try:
            from . import db as _db
            conn = _db.get_conn("main")
            row = conn.execute(
                "SELECT COUNT(*) FROM agent_memory WHERE created_at > ?",
                (time.time() - 86400,)
            ).fetchone()
            yesterday_tasks = row[0] if row else 0
            brief_parts.append(f"昨日完成：{yesterday_tasks} 个任务")
        except Exception:
            pass

        # 4. 用户画像
        try:
            from .user_profile_ai import get_user_profile
            p = get_user_profile()
            brief_parts.append(f"累计交互：{p.get('interaction_count', 0)} 次")
        except Exception:
            pass

        if brief_parts:
            bus.publish("daily_brief", {
                "title": "早安！今日团队简报",
                "content": "\n".join(f"• {p}" for p in brief_parts),
                "timestamp": time.time(),
            })
    except Exception as e:
        logger.debug(f"[Scheduler] daily_brief error: {e}")


async def weekly_moat_report():
    """每周护城河报告"""
    try:
        from .event_bus import get_bus
        from .moat_score import calculate_moat_score

        bus = get_bus()
        score = calculate_moat_score()

        # 生成增长建议
        tips = []
        for task in score.get("growth_tasks", []):
            if not task.get("done"):
                tips.append(f"• {task['icon']} {task['title']} → {task['reward']}")

        bus.publish("weekly_report", {
            "title": "本周护城河报告",
            "score": score["total"],
            "level": score["level"],
            "tips": tips[:3],
            "timestamp": time.time(),
        })
    except Exception as e:
        logger.debug(f"[Scheduler] weekly_report error: {e}")


async def auto_save_profile():
    """自动保存画像（防数据丢失）"""
    try:
        from .user_profile_ai import get_user_profile, save_user_profile
        profile = get_user_profile()
        if profile.get("interaction_count", 0) > 0:
            save_user_profile(profile)
    except Exception:
        pass


# ── 全局调度器 ──

_scheduler: Scheduler = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
        _scheduler.add("每日早报", 8, 30, daily_brief)
        _scheduler.add("每周护城河报告", 9, 0, weekly_moat_report, weekday=0)  # 周一
        _scheduler.add("自动保存画像(上午)", 10, 0, auto_save_profile)
        _scheduler.add("自动保存画像(下午)", 15, 0, auto_save_profile)
    return _scheduler
