# -*- coding: utf-8 -*-
"""
多账号朋友圈协作调度器

核心问题：多个账号同时刷朋友圈/点赞/评论会触发风控。
解决方案：时序调度 + 互斥锁 + 随机抖动

调度策略：
  1. 同一时刻只允许一个账号执行朋友圈操作（互斥锁）
  2. 各账号操作间隔随机 3-8 分钟（防撞车）
  3. 同一条动态不会被多个号重复互动（指纹去重）
  4. 支持"协作发圈"：多个号按计划依次转发/发布
"""

from __future__ import annotations

import asyncio
import random
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger


@dataclass
class CoopTask:
    """一个协作任务"""
    id: str = ""
    account_id: str = ""
    action: str = ""           # browse / like / comment / publish
    target: str = ""           # 目标（帖子作者/主题）
    params: Dict = field(default_factory=dict)
    scheduled_at: float = 0
    executed_at: float = 0
    status: str = "pending"    # pending / running / done / failed


class MomentsCoordinator:
    """
    多账号朋友圈协作调度器

    用法：
        coord = MomentsCoordinator()
        await coord.schedule_browse(["acct1", "acct2", "acct3"])
        await coord.schedule_coop_publish(["acct1", "acct2"], topic="好文分享")
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._account_last_action: Dict[str, float] = {}
        self._interacted_posts: Set[str] = set()  # fingerprint → 已互动
        self._task_queue: List[CoopTask] = []
        self._min_gap = 180   # 同账号最小间隔 3 分钟
        self._max_gap = 480   # 最大间隔 8 分钟
        self._running = False

    async def schedule_browse(
        self,
        account_ids: List[str],
        max_posts: int = 5,
        auto_interact: bool = True,
    ) -> List[CoopTask]:
        """
        安排多个账号依次浏览朋友圈。

        账号之间随机间隔 3-8 分钟，避免同时操作。
        """
        tasks = []
        base_time = time.time()

        # 随机打乱账号顺序，避免固定模式
        shuffled = list(account_ids)
        random.shuffle(shuffled)

        for i, acct_id in enumerate(shuffled):
            gap = random.uniform(self._min_gap, self._max_gap) if i > 0 else 0
            scheduled = base_time + sum(
                random.uniform(self._min_gap, self._max_gap) for _ in range(i)
            )
            task = CoopTask(
                id=f"browse_{acct_id}_{int(time.time())}",
                account_id=acct_id,
                action="browse",
                params={"max_posts": max_posts, "auto_interact": auto_interact},
                scheduled_at=scheduled,
            )
            tasks.append(task)
            self._task_queue.append(task)

        logger.info(f"[MomentsCoop] 安排 {len(tasks)} 个账号浏览朋友圈")
        asyncio.create_task(self._process_queue())
        return tasks

    async def schedule_coop_publish(
        self,
        account_ids: List[str],
        topic: str = "",
        text: str = "",
        stagger_minutes: int = 30,
    ) -> List[CoopTask]:
        """
        协作发圈：多个账号按计划依次发布内容。

        每个账号发布的内容会由 AI 改写以避免完全相同。
        """
        tasks = []
        base_time = time.time()
        shuffled = list(account_ids)
        random.shuffle(shuffled)

        for i, acct_id in enumerate(shuffled):
            scheduled = base_time + i * stagger_minutes * 60
            task = CoopTask(
                id=f"publish_{acct_id}_{int(time.time())}",
                account_id=acct_id,
                action="publish",
                target=topic,
                params={"text": text, "topic": topic, "need_rewrite": i > 0},
                scheduled_at=scheduled,
            )
            tasks.append(task)
            self._task_queue.append(task)

        logger.info(f"[MomentsCoop] 安排 {len(tasks)} 个账号协作发圈，间隔 {stagger_minutes} 分钟")
        asyncio.create_task(self._process_queue())
        return tasks

    def can_interact(self, account_id: str, post_fingerprint: str) -> bool:
        """检查某个账号是否可以对某条动态互动"""
        # 全局去重：同一条动态只被一个账号互动
        if post_fingerprint in self._interacted_posts:
            return False
        # 时间间隔检查
        last = self._account_last_action.get(account_id, 0)
        if time.time() - last < self._min_gap:
            return False
        return True

    def record_interaction(self, account_id: str, post_fingerprint: str):
        """记录互动，用于去重和间隔控制"""
        self._interacted_posts.add(post_fingerprint)
        self._account_last_action[account_id] = time.time()
        # 清理旧指纹（保持合理大小）
        if len(self._interacted_posts) > 5000:
            self._interacted_posts = set(list(self._interacted_posts)[-2500:])

    async def _process_queue(self):
        """后台处理任务队列"""
        if self._running:
            return
        self._running = True

        try:
            while self._task_queue:
                # 按计划时间排序
                self._task_queue.sort(key=lambda t: t.scheduled_at)
                task = self._task_queue[0]

                # 等待到计划时间
                wait = task.scheduled_at - time.time()
                if wait > 0:
                    await asyncio.sleep(min(wait, 60))
                    if wait > 60:
                        continue

                self._task_queue.pop(0)

                # 互斥执行
                async with self._lock:
                    task.status = "running"
                    try:
                        await self._execute_task(task)
                        task.status = "done"
                        task.executed_at = time.time()
                    except Exception as e:
                        task.status = "failed"
                        logger.warning(f"[MomentsCoop] 任务失败 {task.id}: {e}")

                    self._account_last_action[task.account_id] = time.time()

                # 随机休息
                await asyncio.sleep(random.uniform(5, 15))

        finally:
            self._running = False

    async def _execute_task(self, task: CoopTask):
        """执行一个协作任务"""
        logger.info(f"[MomentsCoop] 执行: {task.action} @ {task.account_id}")

        try:
            from ..event_bus import publish
            publish("moments_coop", {
                "action": task.action,
                "account": task.account_id,
                "status": "started",
            })
        except Exception:
            pass

        if task.action == "browse":
            await self._exec_browse(task)
        elif task.action == "publish":
            await self._exec_publish(task)

    async def _exec_browse(self, task: CoopTask):
        """执行浏览任务"""
        try:
            from .moments_reader import MomentsReader
            reader = MomentsReader()
            page = await reader.browse(max_posts=task.params.get("max_posts", 5))
            if page and page.posts:
                logger.info(f"[MomentsCoop] {task.account_id} 浏览了 {len(page.posts)} 条动态")
        except Exception as e:
            logger.warning(f"[MomentsCoop] 浏览失败: {e}")

    async def _exec_publish(self, task: CoopTask):
        """执行发布任务"""
        try:
            text = task.params.get("text", "")
            topic = task.params.get("topic", "")
            need_rewrite = task.params.get("need_rewrite", False)

            if need_rewrite and text:
                try:
                    from .moments_ai import MomentsAIEngine
                    engine = MomentsAIEngine()
                    drafts = await engine.generate_moment_text(
                        topic=topic or "改写以下内容", style="日常"
                    )
                    if drafts:
                        text = drafts[0].get("text", text)
                except Exception:
                    pass

            if not text and topic:
                try:
                    from .moments_ai import MomentsAIEngine
                    engine = MomentsAIEngine()
                    drafts = await engine.generate_moment_text(topic=topic, style="日常")
                    if drafts:
                        text = drafts[0].get("text", "")
                except Exception:
                    pass

            if text:
                from .moments_actor import MomentsActor
                from .moments_guard import MomentsGuard
                actor = MomentsActor(guard=MomentsGuard())
                await actor.publish_moment(text=text)
                logger.info(f"[MomentsCoop] {task.account_id} 发布朋友圈成功")
        except Exception as e:
            logger.warning(f"[MomentsCoop] 发布失败: {e}")

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "pending_tasks": len(self._task_queue),
            "tracked_accounts": len(self._account_last_action),
            "interacted_posts": len(self._interacted_posts),
            "tasks": [
                {"id": t.id, "account": t.account_id, "action": t.action,
                 "status": t.status, "scheduled_at": t.scheduled_at}
                for t in self._task_queue[:20]
            ],
        }


# 全局单例
_coordinator: Optional[MomentsCoordinator] = None


def get_coordinator() -> MomentsCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = MomentsCoordinator()
    return _coordinator
