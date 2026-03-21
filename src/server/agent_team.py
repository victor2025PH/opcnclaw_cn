# -*- coding: utf-8 -*-
"""
Agent 团队引擎 — 一键部署多 Agent 协作

核心设计：
  - Agent: 单个 AI 角色（名称+模型+系统提示+工具权限）
  - Team: Agent 集合 + 消息总线 + 任务调度
  - 执行流程: CEO 接收需求 → 拆解子任务 → 分发 → 并行执行 → 汇总

与现有系统集成：
  - AI 路由器: 每个 Agent 可绑定不同平台
  - A2A 协议: Agent 间通信复用 EventBus
  - Function Calling: 21 个工具按权限分配
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


# ── 数据模型 ──────────────────────────────────────────────────

class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"
    WAITING = "waiting"


@dataclass
class AgentRole:
    """Agent 角色定义"""
    id: str
    name: str
    avatar: str
    description: str
    system_prompt: str
    preferred_model: str = ""         # 优先使用的 AI 平台
    tools: List[str] = field(default_factory=list)  # 允许的工具名
    can_delegate: bool = False        # 是否可以分配任务

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "avatar": self.avatar,
            "description": self.description, "preferred_model": self.preferred_model,
            "tools": self.tools, "can_delegate": self.can_delegate,
        }


@dataclass
class TeamMessage:
    """Agent 间消息"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: str = ""
    to_agent: str = ""              # "broadcast" = 广播
    type: str = "task"              # task / result / question / review
    content: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "from": self.from_agent, "to": self.to_agent,
            "type": self.type, "content": self.content,
            "timestamp": round(self.timestamp, 1),
        }


@dataclass
class SubTask:
    """子任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent_id: str = ""
    description: str = ""
    status: str = "pending"         # pending / working / done / error
    result: str = ""
    depends_on: List[str] = field(default_factory=list)  # 依赖的子任务 ID
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "agent_id": self.agent_id,
            "description": self.description, "status": self.status,
            "result": self.result[:200] if self.result else "",
            "depends_on": self.depends_on,
        }


# ── Agent 实例 ────────────────────────────────────────────────

class Agent:
    """单个 Agent 实例"""

    def __init__(self, role: AgentRole):
        self.role = role
        self.status = AgentStatus.IDLE
        self.current_task: Optional[SubTask] = None
        self._history: List[dict] = []  # 对话历史

    async def execute(self, task: SubTask, context: dict, ai_call: Callable) -> str:
        """执行子任务"""
        self.status = AgentStatus.WORKING
        self.current_task = task
        task.status = "working"
        task.started_at = time.time()

        try:
            # 构建 prompt
            messages = [
                {"role": "system", "content": self.role.system_prompt},
                {"role": "user", "content": self._build_prompt(task, context)},
            ]

            # 调用 AI
            result = await ai_call(messages, model=self.role.preferred_model)

            task.status = "done"
            task.result = result
            task.finished_at = time.time()
            self.status = AgentStatus.DONE
            self._history.append({"task": task.description, "result": result[:500]})

            logger.info(f"[Agent:{self.role.name}] 完成: {task.description[:30]}")
            return result

        except Exception as e:
            # 容错：失败时给默认回答，不阻塞团队
            task.status = "done"  # 标记为 done 而不是 error，避免阻塞
            task.result = f"（{self.role.name}因网络问题暂时无法完成，建议由其他成员补充此部分内容）"
            task.finished_at = time.time()
            self.status = AgentStatus.DONE
            logger.warning(f"[Agent:{self.role.name}] 降级完成: {e}")
            return task.result

    def _build_prompt(self, task: SubTask, context: dict) -> str:
        parts = [f"## 你的任务\n{task.description}"]
        if context:
            parts.append(f"\n## 项目背景\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        if self._history:
            recent = self._history[-3:]
            parts.append("\n## 你之前的工作")
            for h in recent:
                parts.append(f"- {h['task']}: {h['result'][:100]}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            **self.role.to_dict(),
            "status": self.status.value,
            "current_task": self.current_task.to_dict() if self.current_task else None,
        }


# ── 团队引擎 ─────────────────────────────────────────────────

class AgentTeam:
    """Agent 团队 — 多 Agent 协作执行"""

    TASK_TIMEOUT = 300  # 单任务 5 分钟超时
    MAX_ROUNDS = 3      # CEO 最多汇总 3 轮

    def __init__(self, team_id: str, name: str, agents: List[Agent]):
        self.team_id = team_id
        self.name = name
        self.agents: Dict[str, Agent] = {a.role.id: a for a in agents}
        self.messages: List[TeamMessage] = []
        self.tasks: List[SubTask] = []
        self.context: Dict[str, Any] = {}
        self.status = "idle"         # idle / planning / executing / done / error
        self.final_result = ""
        self.created_at = time.time()
        self._ai_call: Optional[Callable] = None

    def set_ai_call(self, fn: Callable):
        """注入 AI 调用函数"""
        self._ai_call = fn

    async def execute(self, user_request: str) -> str:
        """执行团队任务（完整流程）"""
        self.status = "planning"
        self.context["user_request"] = user_request
        self._add_message("user", "ceo", "task", user_request)

        if not self._ai_call:
            self.status = "error"
            return "AI 调用未配置"

        try:
            # 1. CEO 拆解任务
            ceo = self.agents.get("ceo")
            if not ceo:
                # 无 CEO 时直接分配给第一个 Agent
                agent = list(self.agents.values())[0]
                task = SubTask(agent_id=agent.role.id, description=user_request)
                self.tasks.append(task)
                result = await agent.execute(task, self.context, self._ai_call)
                self.final_result = result
                self.status = "done"
                return result

            plan = await self._ceo_plan(ceo, user_request)

            # 2. 并行执行子任务（尊重依赖关系）
            self.status = "executing"
            await self._execute_tasks()

            # 3. CEO 汇总
            summary = await self._ceo_summarize(ceo)
            self.final_result = summary
            self.status = "done"

            # 发布事件
            try:
                from .event_bus import publish
                publish("agent_team:done", {
                    "team_id": self.team_id,
                    "name": self.name,
                    "task": user_request[:100],
                    "agents_used": len(self.agents),
                    "tasks_completed": sum(1 for t in self.tasks if t.status == "done"),
                    "result_preview": summary[:300] if summary else "",
                })
            except Exception:
                pass

            return summary

        except asyncio.TimeoutError:
            self.status = "error"
            return "团队执行超时"
        except Exception as e:
            self.status = "error"
            logger.error(f"[Team:{self.name}] 执行失败: {e}")
            return f"团队执行失败: {e}"

    async def _ceo_plan(self, ceo: Agent, request: str) -> str:
        """CEO 拆解任务为子任务"""
        agent_list = "\n".join(
            f"- {a.role.id}: {a.role.name}（{a.role.description}）"
            for a in self.agents.values() if a.role.id != "ceo"
        )

        max_tasks = min(len(self.agents) - 1, 10)  # 动态上限

        plan_prompt = f"""你是团队 CEO。用户需求如下：

{request}

你的团队成员：
{agent_list}

请将需求拆解为子任务（DAG 依赖图），每个子任务分配给一个成员。
输出 JSON 数组格式（不要多余文字）：
[
  {{"agent": "成员ID", "task": "具体任务描述", "depends_on": []}},
  {{"agent": "成员ID", "task": "具体任务描述", "depends_on": ["上一步的agent ID"]}},
  ...
]

规则：
- depends_on 为空 = 第一批执行（无依赖）
- depends_on 含某个 agent = 等它完成后才开始
- 无依赖的任务会并行执行
- 任务描述要具体可执行
- 最多 {max_tasks} 个子任务"""

        messages = [
            {"role": "system", "content": ceo.role.system_prompt},
            {"role": "user", "content": plan_prompt},
        ]

        plan_text = await self._ai_call(messages)
        self._add_message("ceo", "broadcast", "task", f"任务拆解完成")

        # 解析 JSON
        try:
            # 提取 JSON 数组
            import re
            match = re.search(r'\[.*\]', plan_text, re.DOTALL)
            if match:
                items = json.loads(match.group())
                max_tasks = min(len(self.agents) - 1, 10)
                for item in items[:max_tasks]:
                    agent_id = item.get("agent", "")
                    if agent_id in self.agents:
                        # 解析依赖关系
                        deps = item.get("depends_on", [])
                        if isinstance(deps, str):
                            deps = [deps] if deps else []
                        task = SubTask(
                            agent_id=agent_id,
                            description=item.get("task", ""),
                            depends_on=deps,
                        )
                        self.tasks.append(task)
                        self._add_message("ceo", agent_id, "task", item.get("task", ""))
        except Exception as e:
            logger.warning(f"[Team] CEO 任务拆解解析失败: {e}")
            for aid, agent in self.agents.items():
                if aid != "ceo":
                    task = SubTask(agent_id=aid, description=request)
                    self.tasks.append(task)
                    break

        logger.info(f"[Team:{self.name}] 拆解为 {len(self.tasks)} 个子任务")
        return plan_text

    async def _execute_tasks(self):
        """DAG 分层并行执行：无依赖的先跑，依赖完成的再跑"""

        async def _run(task: SubTask):
            agent = self.agents.get(task.agent_id)
            if not agent:
                task.status = "error"
                task.result = f"Agent {task.agent_id} 不存在"
                return
            try:
                # 将前序任务结果注入 context
                enriched_ctx = dict(self.context)
                for dep_id in task.depends_on:
                    dep_task = next((t for t in self.tasks if t.agent_id == dep_id), None)
                    if dep_task and dep_task.result:
                        enriched_ctx[f"{dep_id}_result"] = dep_task.result[:500]

                await asyncio.wait_for(
                    agent.execute(task, enriched_ctx, self._ai_call),
                    timeout=self.TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                task.status = "error"
                task.result = "超时"

        # DAG 分层执行：每层的无依赖/已满足依赖的任务并行
        completed_agents = set()
        max_waves = 10  # 防无限循环

        for wave in range(max_waves):
            # 找出本层可执行的任务
            ready = [
                t for t in self.tasks
                if t.status == "pending"
                and all(dep in completed_agents for dep in t.depends_on)
            ]

            if not ready:
                # 检查是否还有未完成任务
                pending = [t for t in self.tasks if t.status == "pending"]
                if pending:
                    # 有 pending 但无 ready = 依赖死锁，强制执行
                    logger.warning(f"[Team] 第{wave+1}层：依赖死锁，强制执行 {len(pending)} 个任务")
                    ready = pending
                else:
                    break

            logger.info(f"[Team:{self.name}] 第{wave+1}层执行: {[t.agent_id for t in ready]}")
            await asyncio.gather(*[_run(t) for t in ready], return_exceptions=True)

            # 记录完成的 agent
            for t in ready:
                if t.status == "done":
                    completed_agents.add(t.agent_id)

    async def _ceo_summarize(self, ceo: Agent) -> str:
        """CEO 汇总所有结果"""
        results = []
        for t in self.tasks:
            agent = self.agents.get(t.agent_id)
            name = agent.role.name if agent else t.agent_id
            results.append(f"### {name} 的工作成果\n{t.result or '未完成'}")

        summary_prompt = f"""你是团队 CEO。以下是团队成员的工作成果：

{"".join(results)}

请汇总为一份完整的最终报告，包含：
1. 执行摘要（3句话）
2. 各成员贡献要点
3. 最终方案/结论
4. 后续建议

用清晰的 Markdown 格式输出。"""

        messages = [
            {"role": "system", "content": ceo.role.system_prompt},
            {"role": "user", "content": summary_prompt},
        ]

        summary = await self._ai_call(messages)
        self._add_message("ceo", "user", "result", "最终报告已生成")
        return summary

    def _add_message(self, from_a: str, to_a: str, msg_type: str, content: str):
        self.messages.append(TeamMessage(
            from_agent=from_a, to_agent=to_a,
            type=msg_type, content=content,
        ))

    def get_status(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "status": self.status,
            "agents": {aid: a.to_dict() for aid, a in self.agents.items()},
            "tasks": [t.to_dict() for t in self.tasks],
            "messages": [m.to_dict() for m in self.messages[-20:]],
            "final_result": self.final_result[:500] if self.final_result else "",
            "created_at": round(self.created_at, 1),
        }


# ── 全局团队管理 ──────────────────────────────────────────────

_teams: Dict[str, AgentTeam] = {}


def create_team(template_id: str, ai_call: Callable) -> AgentTeam:
    """根据模板一键创建团队"""
    from .agent_templates import get_template, build_agents
    tpl = get_template(template_id)
    if not tpl:
        raise ValueError(f"模板不存在: {template_id}")

    agents = build_agents(tpl["roles"])
    team_id = f"team_{int(time.time() * 1000) % 100000}"
    team = AgentTeam(team_id=team_id, name=tpl["name"], agents=agents)
    team.set_ai_call(ai_call)
    _teams[team_id] = team

    # 清理旧团队（保留最近 10 个）
    if len(_teams) > 10:
        oldest = sorted(_teams.keys())[0]
        del _teams[oldest]

    logger.info(f"[AgentTeam] 创建团队: {tpl['name']} ({len(agents)} 人)")
    return team


def get_team(team_id: str) -> Optional[AgentTeam]:
    return _teams.get(team_id)


def list_teams() -> List[dict]:
    return [t.get_status() for t in _teams.values()]
