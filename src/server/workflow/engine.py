# -*- coding: utf-8 -*-
"""
工作流执行引擎 + 调度器

职责：
  1. 按节点顺序执行工作流，管理上下文传递与错误处理
  2. 基于 schedule / interval / event 触发器的自动调度
  3. 内置场景自动注册
"""

from __future__ import annotations

import asyncio
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .models import (
    ExecStatus, Execution, NodeDef, NodeResult,
    TriggerType, Workflow,
)
from .nodes import ExecContext, NODE_REGISTRY, interpolate_params
from . import store


class WorkflowEngine:
    """核心工作流执行引擎"""

    def __init__(self):
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._active_executions: Dict[str, Execution] = {}
        self._running_workflows: set = set()  # 防止同一工作流并发执行
        self._event_listeners: Dict[str, List[str]] = {}  # event_name → [workflow_id]
        self._interval_tasks: Dict[str, asyncio.Task] = {}

        # 外部服务引用，由 start() 时注入
        self.ai_backend: Any = None
        self.tts_engine: Any = None
        self.wechat_adapter: Any = None
        self.wechat_engine: Any = None
        self.desktop: Any = None

        # 回调：执行完成时通知
        self.on_execution_done: Optional[Callable] = None

    # ── 生命周期 ─────────────────────────────────────────────────────────────────

    async def start(
        self,
        ai_backend=None,
        tts_engine=None,
        wechat_adapter=None,
        wechat_engine=None,
        desktop=None,
    ):
        if self._running:
            return

        self.ai_backend = ai_backend
        self.tts_engine = tts_engine
        self.wechat_adapter = wechat_adapter
        self.wechat_engine = wechat_engine
        self.desktop = desktop

        self._running = True
        self._load_event_listeners()

        from .builtins import ensure_builtins
        ensure_builtins()

        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        self._restart_interval_tasks()
        logger.info("✅ 工作流引擎已启动")

    async def stop(self):
        self._running = False
        for tid, task in self._interval_tasks.items():
            task.cancel()
        self._interval_tasks.clear()
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        logger.info("⏹️ 工作流引擎已停止")

    # ── 执行工作流 ────────────────────────────────────────────────────────────────

    async def execute(
        self,
        workflow_id: str,
        trigger_type: str = "manual",
        event_data: Optional[Dict] = None,
    ) -> Execution:
        """执行指定工作流，返回 Execution 记录"""
        wf = store.get_workflow(workflow_id)
        if not wf:
            ex = Execution(
                workflow_id=workflow_id,
                status=ExecStatus.FAILED,
                error=f"Workflow {workflow_id} not found",
                started_at=time.time(),
                finished_at=time.time(),
            )
            return ex

        return await self._run_workflow(wf, trigger_type, event_data)

    async def execute_workflow_obj(
        self,
        wf: Workflow,
        trigger_type: str = "manual",
        event_data: Optional[Dict] = None,
    ) -> Execution:
        """直接执行 Workflow 对象（用于临时/测试运行）"""
        return await self._run_workflow(wf, trigger_type, event_data)

    async def _run_workflow(
        self,
        wf: Workflow,
        trigger_type: str,
        event_data: Optional[Dict],
    ) -> Execution:
        if wf.id in self._running_workflows and trigger_type != "manual":
            logger.debug(f"Workflow {wf.id} already running, skipping")
            return Execution(
                workflow_id=wf.id, workflow_name=wf.name,
                status=ExecStatus.CANCELLED, error="Already running",
                started_at=time.time(), finished_at=time.time(),
            )

        self._running_workflows.add(wf.id)

        ex = Execution(
            workflow_id=wf.id,
            workflow_name=wf.name,
            trigger_type=trigger_type,
            started_at=time.time(),
            status=ExecStatus.RUNNING,
        )
        self._active_executions[ex.id] = ex

        ctx = ExecContext(
            workflow_id=wf.id,
            workflow_name=wf.name,
            variables=dict(wf.variables),
            ai_backend=self.ai_backend,
            tts_engine=self.tts_engine,
            wechat_adapter=self.wechat_adapter,
            wechat_engine=self.wechat_engine,
            desktop=self.desktop,
            event_data=event_data or {},
        )

        try:
            for node_def in wf.nodes:
                if ctx.cancelled:
                    ex.status = ExecStatus.CANCELLED
                    break

                nr = await self._execute_node(node_def, ctx)
                ex.node_results.append(nr)

                if nr.status == ExecStatus.FAILED:
                    if node_def.on_error == "stop":
                        ex.status = ExecStatus.FAILED
                        ex.error = f"Node '{node_def.id}' failed: {nr.error}"
                        break
                    elif node_def.on_error == "skip":
                        continue

            if ex.status == ExecStatus.RUNNING:
                ex.status = ExecStatus.SUCCESS

        except asyncio.CancelledError:
            ex.status = ExecStatus.CANCELLED
        except Exception as e:
            ex.status = ExecStatus.FAILED
            ex.error = str(e)
            logger.error(f"Workflow {wf.id} error: {traceback.format_exc()}")
        finally:
            ex.finished_at = time.time()
            ex.context = {
                k: str(v)[:500] if not isinstance(v, (int, float, bool)) else v
                for k, v in ctx.outputs.items()
            }
            self._active_executions.pop(ex.id, None)
            self._running_workflows.discard(wf.id)
            store.save_execution(ex)

            if self.on_execution_done:
                try:
                    self.on_execution_done(ex)
                except Exception:
                    pass

        logger.info(
            f"工作流 [{wf.name}] 执行完成: {ex.status.value} "
            f"({ex.duration_ms:.0f}ms, {len(ex.node_results)} nodes)"
        )
        return ex

    async def _execute_node(self, node_def: NodeDef, ctx: ExecContext) -> NodeResult:
        """执行单个节点"""
        nr = NodeResult(node_id=node_def.id, started_at=time.time())

        handler = NODE_REGISTRY.get(node_def.type)
        if not handler:
            nr.status = ExecStatus.FAILED
            nr.error = f"Unknown node type: {node_def.type}"
            nr.finished_at = time.time()
            nr.duration_ms = (nr.finished_at - nr.started_at) * 1000
            return nr

        params = interpolate_params(node_def.params, ctx)

        attempts = 1 + max(0, node_def.retry_count)
        last_error = ""
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    handler(ctx, params),
                    timeout=node_def.timeout,
                )
                ctx.outputs[node_def.id] = result
                nr.output = result
                nr.status = ExecStatus.SUCCESS
                nr.finished_at = time.time()
                nr.duration_ms = (nr.finished_at - nr.started_at) * 1000
                return nr

            except asyncio.TimeoutError:
                last_error = f"Timeout after {node_def.timeout}s"
                logger.warning(
                    f"Node {node_def.id} timeout (attempt {attempt + 1}/{attempts})"
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Node {node_def.id} error (attempt {attempt + 1}/{attempts}): {e}"
                )

            if attempt < attempts - 1:
                await asyncio.sleep(1 * (attempt + 1))

        nr.status = ExecStatus.FAILED
        nr.error = last_error
        nr.finished_at = time.time()
        nr.duration_ms = (nr.finished_at - nr.started_at) * 1000
        return nr

    # ── 事件触发 ─────────────────────────────────────────────────────────────────

    async def fire_event(self, event_name: str, data: Optional[Dict] = None):
        """触发事件，执行所有监听此事件的工作流"""
        wf_ids = self._event_listeners.get(event_name, [])
        for wf_id in wf_ids:
            wf = store.get_workflow(wf_id)
            if wf and wf.enabled:
                asyncio.create_task(
                    self._run_workflow(wf, "event", data)
                )

    def _load_event_listeners(self):
        """从数据库加载所有事件触发型工作流"""
        self._event_listeners.clear()
        for wf in store.list_workflows():
            if wf.enabled and wf.trigger.type == TriggerType.EVENT and wf.trigger.event:
                self._event_listeners.setdefault(wf.trigger.event, []).append(wf.id)

    def reload_listeners(self):
        self._load_event_listeners()
        self._restart_interval_tasks()

    # ── 调度器 ────────────────────────────────────────────────────────────────────

    async def _scheduler_loop(self):
        """主调度循环：每分钟检查 schedule 类型触发器"""
        logger.info("调度器已启动")
        last_check_minute = ""

        while self._running:
            try:
                now = datetime.now()
                current_minute = now.strftime("%H:%M")

                if current_minute != last_check_minute:
                    last_check_minute = current_minute
                    await self._check_schedules(now, current_minute)

                await asyncio.sleep(10)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"调度器错误: {e}")
                await asyncio.sleep(30)

        logger.info("调度器已停止")

    async def _check_schedules(self, now: datetime, current_minute: str):
        """检查所有定时工作流"""
        WEEKDAY_MAP = {
            0: "mon", 1: "tue", 2: "wed", 3: "thu",
            4: "fri", 5: "sat", 6: "sun",
        }
        today = WEEKDAY_MAP[now.weekday()]

        for wf in store.list_workflows():
            if not wf.enabled:
                continue
            t = wf.trigger
            if t.type != TriggerType.SCHEDULE:
                continue
            if t.time != current_minute:
                continue
            if t.days and today not in t.days:
                continue

            logger.info(f"⏰ 定时触发工作流: {wf.name}")
            asyncio.create_task(
                self._run_workflow(wf, "schedule", None)
            )

    def _restart_interval_tasks(self):
        """重启所有 interval 类型工作流的定时任务"""
        for tid, task in self._interval_tasks.items():
            task.cancel()
        self._interval_tasks.clear()

        for wf in store.list_workflows():
            if wf.enabled and wf.trigger.type == TriggerType.INTERVAL:
                if wf.trigger.seconds > 0:
                    self._interval_tasks[wf.id] = asyncio.create_task(
                        self._interval_runner(wf.id, wf.trigger.seconds)
                    )

    async def _interval_runner(self, workflow_id: str, interval: int):
        """循环执行 interval 类型工作流"""
        while self._running:
            try:
                await asyncio.sleep(interval)
                wf = store.get_workflow(workflow_id)
                if wf and wf.enabled:
                    await self._run_workflow(wf, "interval", None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Interval runner {workflow_id} error: {e}")
                await asyncio.sleep(60)

    # ── 取消执行 ─────────────────────────────────────────────────────────────────

    def cancel_execution(self, exec_id: str) -> bool:
        ex = self._active_executions.get(exec_id)
        if ex:
            ex.status = ExecStatus.CANCELLED
            return True
        return False

    # ── 状态查询 ─────────────────────────────────────────────────────────────────

    def get_active_executions(self) -> List[Dict]:
        return [ex.to_dict() for ex in self._active_executions.values()]

    def get_status(self) -> Dict:
        stats = store.get_stats()
        stats["running"] = self._running
        stats["active_executions"] = len(self._active_executions)
        stats["event_listeners"] = {
            k: len(v) for k, v in self._event_listeners.items()
        }
        return stats


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_engine: Optional[WorkflowEngine] = None


def get_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
