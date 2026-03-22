# -*- coding: utf-8 -*-
"""
Agent 团队引擎 — 一键部署多 Agent 协作

核心设计：
  - Agent: 单个 AI 角色（名称+模型+系统提示+工具权限）
  - Team: Agent 集合 + 消息总线 + 任务调度
  - 执行流程: CEO 接收需求 → 拆解子任务 → 分层并行（DAG）→ 波次结束后「请教」补全 → 汇总

与现有系统集成：
  - AI 路由器: 每个 Agent 可绑定不同平台
  - A2A 协议: Agent 间通信复用 EventBus
  - Function Calling: 21 个工具按权限分配
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    depends_on: List[str] = field(default_factory=list)  # 依赖的成员 agent_id（同轮并行 DAG）
    allow_runtime_consult: bool = False  # CEO 拆解为 true 时，波次结束后可做「请教」补全
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        partial = getattr(self, 'partial_result', '')
        return {
            "id": self.id, "agent_id": self.agent_id,
            "description": self.description, "status": self.status,
            "result": self.result[:200] if self.result else "",
            "partial_result": partial[:300] if partial else "",
            "depends_on": self.depends_on,
            "allow_runtime_consult": self.allow_runtime_consult,
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

            # 调用 AI（流式收集，前端可通过 status API 实时看到）
            task.partial_result = ""
            try:
                from src.server.main import backend as _b
                if _b and _b._router:
                    result = ""
                    async for chunk, _ in _b._router.chat_stream(messages, max_tokens=600):
                        if chunk not in ("__SWITCH__", "__TOOL_CALLS__"):
                            result += chunk
                            task.partial_result = result  # 实时更新
                else:
                    result = await ai_call(messages, model=self.role.preferred_model)
            except Exception:
                result = await ai_call(messages, model=self.role.preferred_model)

            task.status = "done"
            task.result = result
            task.finished_at = time.time()
            self.status = AgentStatus.DONE
            self._history.append({"task": task.description, "result": result[:500]})

            logger.info(f"[Agent:{self.role.name}] 完成: {task.description[:30]}")

            # 保存记忆（越用越聪明）
            try:
                from .agent_memory import save_agent_memory
                save_agent_memory(self.role.id, self.role.name, task.description, result)
            except Exception:
                pass

            # 根据角色类型执行实际操作
            await self._post_execute(task, result)

            return result

        except Exception as e:
            # 容错：失败时给默认回答，不阻塞团队
            task.status = "done"  # 标记为 done 而不是 error，避免阻塞
            task.result = f"（{self.role.name}因网络问题暂时无法完成，建议由其他成员补充此部分内容）"
            task.finished_at = time.time()
            self.status = AgentStatus.DONE
            logger.warning(f"[Agent:{self.role.name}] 降级完成: {e}")
            return task.result

    async def _post_execute(self, task: SubTask, result: str):
        """根据角色执行额外操作（真干活）"""
        try:
            role_id = self.role.id

            # 运营/社群：尝试发朋友圈
            if role_id in ("marketer", "community") and "发朋友圈" in task.description:
                try:
                    from .tools import call_tool
                    import json
                    # 提取文案（取结果前 100 字）
                    text = result[:100].replace("#", "").replace("*", "").strip()
                    if text and len(text) > 10:
                        r = await call_tool("publish_moment", {"text": text[:200]})
                        logger.info(f"[Agent:{self.role.name}] 自动发朋友圈: {text[:30]}")
                except Exception as e:
                    logger.debug(f"[Agent:{self.role.name}] 发朋友圈跳过: {e}")

            # 程序员/前端：如果结果包含代码块，提取保存为代码文件
            if role_id in ("coder", "backend", "frontend") and "```" in result:
                try:
                    import re
                    # 提取代码块
                    blocks = re.findall(r'```(\w*)\n(.*?)```', result, re.DOTALL)
                    for lang, code in blocks[:3]:
                        ext = {"python": "py", "javascript": "js", "html": "html",
                               "css": "css", "sql": "sql", "json": "json",
                               "bash": "sh", "typescript": "ts"}.get(lang, "txt")
                        # 通知外部保存（如果有项目空间）
                        task._code_files = getattr(task, '_code_files', [])
                        task._code_files.append({"lang": lang or "txt", "ext": ext, "code": code.strip()})
                except Exception:
                    pass

            # 数据分析：如果结果包含表格数据，标记为 CSV
            if role_id in ("data_analyst", "analyst", "finance") and "|" in result:
                task._has_table = True

        except Exception as e:
            logger.debug(f"[Agent:{self.role.name}] post_execute: {e}")

    # prompt 注入总长度上限（约 2000 token ≈ 3000 中文字符）
    _MAX_CONTEXT_CHARS = 3000

    def _build_prompt(self, task: SubTask, context: dict) -> str:
        """构建 Agent 执行 prompt（带智能截断）

        注入优先级（高→低）：
        1. 任务描述（必须）
        2. 用户画像（核心护城河）
        3. 反馈提醒（避免重复错误）
        4. 历史记忆（上下文连续性）
        5. 专长进化（锦上添花）
        6. 项目知识库（参考）
        7. 项目背景 + 历史工作
        """
        parts = [f"## 你的任务\n{task.description}"]
        used_chars = len(parts[0])

        # 按优先级依次注入，超出上限时截断
        injections = []

        # P1: 用户画像
        try:
            from .user_profile_ai import get_profile_context
            ctx = get_profile_context()
            if ctx:
                injections.append(("画像", ctx, 600))  # name, content, max_chars
        except Exception:
            pass

        # P2: 反馈提醒（避免重复错误最重要）
        try:
            from .quality_guard import get_feedback_reminder
            ctx = get_feedback_reminder(self.role.id)
            if ctx:
                injections.append(("反馈", ctx, 400))
        except Exception:
            pass

        # P3: 历史记忆
        try:
            from .agent_memory import get_agent_context
            ctx = get_agent_context(self.role.id)
            if ctx:
                injections.append(("记忆", ctx, 500))
        except Exception:
            pass

        # P4: 专长进化
        try:
            from .agent_evolution import get_agent_expertise
            ctx = get_agent_expertise(self.role.id)
            if ctx:
                injections.append(("进化", ctx, 300))
        except Exception:
            pass

        # P5: 项目知识库
        try:
            from .project_knowledge import get_knowledge_context
            ctx = get_knowledge_context(task.description)
            if ctx:
                injections.append(("知识库", ctx, 400))
        except Exception:
            pass

        # 按优先级注入，控制总长度
        for name, content, max_chars in injections:
            trimmed = content[:max_chars]
            if used_chars + len(trimmed) > self._MAX_CONTEXT_CHARS:
                remaining = self._MAX_CONTEXT_CHARS - used_chars
                if remaining > 100:  # 至少 100 字才值得注入
                    parts.append(trimmed[:remaining])
                    used_chars += remaining
                break  # 后续低优先级内容不再注入
            parts.append(trimmed)
            used_chars += len(trimmed)

        # 协作上下文（团队成员的成果）— 单独渲染，不占用护城河注入空间
        if context:
            collab_parts = []
            other_parts = []
            for k, v in context.items():
                if k.startswith("[") and k.endswith("]"):
                    # 协作数据（成员成果/共享板）
                    collab_parts.append(f"\n### {k}\n{v}")
                else:
                    other_parts.append(f"- {k}: {str(v)[:150]}")

            if collab_parts:
                collab_text = "\n## 团队协作（其他成员的工作成果，请参考并配合）" + "".join(collab_parts)
                # 协作上下文有独立配额（最多 1500 字）
                parts.append(collab_text[:1500])
            if other_parts and used_chars < self._MAX_CONTEXT_CHARS - 100:
                parts.append("\n## 项目背景\n" + "\n".join(other_parts[:5]))

        if self._history and used_chars < self._MAX_CONTEXT_CHARS - 100:
            recent = self._history[-2:]
            parts.append("\n## 你之前的工作")
            for h in recent:
                parts.append(f"- {h['task']}: {h['result'][:80]}")

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
        """执行团队任务（完整流程）— 每个 Agent 产出保存为文件"""
        self.status = "planning"
        self.context["user_request"] = user_request
        self._add_message("user", "ceo", "task", user_request)

        if not self._ai_call:
            self.status = "error"
            return "AI 调用未配置"

        # 创建项目工作空间
        try:
            from .project_workspace import create_project
            self._project = create_project(
                name=user_request[:20],
                team_name=self.name,
                task=user_request,
                agent_count=len(self.agents),
            )
            logger.info(f"[Team:{self.name}] 项目空间: {self._project.dir}")
        except Exception as e:
            logger.warning(f"[Team] 创建项目空间失败: {e}")
            self._project = None

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

            # 保存汇总到项目空间 + 生成精美 HTML 报告
            if hasattr(self, '_project') and self._project:
                try:
                    self._project.save_summary(summary)
                    # 生成精美 HTML 报告（可直接分享给客户）
                    self._generate_html_report(summary, user_request)
                except Exception:
                    pass

            # 持久化结果到 SQLite
            try:
                from . import db as _db
                conn = _db.get_conn("main")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS team_history (
                        team_id TEXT PRIMARY KEY, name TEXT, task TEXT,
                        agent_count INTEGER, result TEXT,
                        created_at REAL, finished_at REAL
                    )
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO team_history VALUES (?,?,?,?,?,?,?)",
                    (self.team_id, self.name, user_request[:500],
                     len(self.agents), summary[:5000] if summary else "",
                     self.created_at, time.time()),
                )
                conn.commit()
            except Exception:
                pass

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

        # 注入用户画像让 CEO 了解老板业务
        _profile_section = ""
        try:
            from .user_profile_ai import get_profile_context
            _profile_section = get_profile_context()
        except Exception:
            pass

        plan_prompt = f"""你是团队 CEO。用户需求如下：

{request}
{_profile_section}

你的团队成员：
{agent_list}

请将需求拆解为子任务（DAG 依赖图），每个子任务分配给一个成员。
输出 JSON 数组格式（不要多余文字）：
[
  {{"agent": "成员ID", "task": "具体任务描述", "depends_on": [], "consult_runtime": false}},
  {{"agent": "成员ID", "task": "具体任务描述", "depends_on": ["data_analyst"], "consult_runtime": true}},
  ...
]

规则：
- depends_on 为空 = 第一批执行（无依赖）
- depends_on 含某个 agent = 等该成员**本轮产出**完成后，下游才开始（硬依赖）
- 无依赖的任务会并行执行
- **consult_runtime**（可选）：设为 true 时，该成员在并行波次结束后，若初稿仍缺其他同事的数据/结论，系统可自动代为「请教」对应成员并整合（适合 CMO 需数据分析师补数等场景）
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
            import re
            match = re.search(r'\[.*\]', plan_text, re.DOTALL)
            if match:
                items = json.loads(match.group())
                # 构建 agent_id 大小写映射
                id_map = {}
                for aid in self.agents:
                    id_map[aid] = aid
                    id_map[aid.lower()] = aid
                    id_map[aid.upper()] = aid
                    # 也匹配中文名
                    id_map[self.agents[aid].role.name] = aid

                for item in items[:min(len(self.agents), 10)]:
                    raw_id = item.get("agent", "")
                    agent_id = id_map.get(raw_id) or id_map.get(raw_id.lower()) or id_map.get(raw_id.strip())
                    if agent_id and agent_id in self.agents:
                        deps = item.get("depends_on", [])
                        if isinstance(deps, str):
                            deps = [deps] if deps else []
                        task = SubTask(
                            agent_id=agent_id,
                            description=item.get("task", ""),
                            depends_on=deps,
                            allow_runtime_consult=bool(item.get("consult_runtime", False)),
                        )
                        self.tasks.append(task)
                        self._add_message("ceo", agent_id, "task", item.get("task", ""))
        except Exception as e:
            logger.warning(f"[Team] CEO 任务拆解解析失败: {e}")

        # 降级：如果拆解出的任务太少，给每个未分配的 Agent 分配通用任务
        if len(self.tasks) < 2:
            logger.info(f"[Team:{self.name}] 拆解不足({len(self.tasks)}个)，自动为每人分配任务")
            assigned = {t.agent_id for t in self.tasks}
            for aid, agent in self.agents.items():
                if aid != "ceo" and aid not in assigned:
                    task = SubTask(
                        agent_id=aid,
                        description=f"根据你的专长（{agent.role.description}），为以下需求提供你的专业意见：{request}",
                    )
                    self.tasks.append(task)
                    self._add_message("ceo", aid, "task", task.description[:50])

        logger.info(f"[Team:{self.name}] 拆解为 {len(self.tasks)} 个子任务")
        return plan_text

    @staticmethod
    def _extract_json_object(text: str) -> Optional[dict]:
        """从模型输出中取出第一个完整 JSON 对象（支持嵌套花括号）"""
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        return None
        return None

    def _persist_task_artifact(self, agent: Agent, task: SubTask) -> None:
        """子任务完成后写入项目空间（请教修订后会再次调用以覆盖）"""
        if not hasattr(self, "_project") or not self._project or not task.result:
            return
        try:
            self._project.save_artifact(
                agent_name=agent.role.name,
                agent_avatar=agent.role.avatar,
                filename=task.description[:30],
                content=task.result,
                file_type="md",
            )
            for cf in getattr(task, "_code_files", []):
                self._project.save_artifact(
                    agent_name=agent.role.name,
                    agent_avatar=agent.role.avatar,
                    filename=f"代码_{cf['lang']}",
                    content=cf["code"],
                    file_type=cf["ext"],
                )
        except Exception:
            pass

    def _enriched_context_for_task(self, task: SubTask) -> Dict[str, Any]:
        """构建单个子任务的协作上下文（依赖成员成果 + 共享成果板）"""
        enriched_ctx = dict(self.context)

        for dep_id in task.depends_on:
            dep_task = next((t for t in self.tasks if t.agent_id == dep_id), None)
            if dep_task and dep_task.result:
                dep_agent = self.agents.get(dep_id)
                dep_name = dep_agent.role.name if dep_agent else dep_id
                enriched_ctx[f"[{dep_name}的成果]"] = dep_task.result[:800]

        peer_summaries = []
        for t in self.tasks:
            if t.agent_id != task.agent_id and t.status == "done" and t.result:
                if t.agent_id not in task.depends_on:
                    peer = self.agents.get(t.agent_id)
                    name = peer.role.name if peer else t.agent_id
                    peer_summaries.append(f"- {name}：{t.result[:150]}")
        if peer_summaries:
            enriched_ctx["[其他成员已完成的工作]"] = "\n".join(peer_summaries[:5])
        return enriched_ctx

    def _should_attempt_runtime_consult(self, task: SubTask) -> bool:
        """是否值得做「请教」检测（避免每任务多一次 LLM）"""
        if getattr(task, "_consult_round", 0) >= 1:
            return False
        if task.allow_runtime_consult:
            return True
        r = task.result or ""
        if len(r) > 2800:
            return False
        hints = (
            "待补充", "数据不足", "需要具体", "需向", "请教", "分析师",
            "待确认", "缺少数据", "暂无数据", "需要数据", "待核实",
        )
        return any(h in r for h in hints) or len(r) < 180

    async def _detect_runtime_consult(self, agent: Agent, task: SubTask) -> Optional[Tuple[str, str]]:
        """返回 (被请教成员 agent_id, 追问内容) 或 None"""
        roster = "\n".join(
            f"- {aid}: {self.agents[aid].role.name}"
            for aid in sorted(self.agents.keys())
            if aid not in ("ceo", agent.role.id)
        )
        peer_results = []
        for t in self.tasks:
            if t.agent_id == agent.role.id or t is task or not t.result:
                continue
            a = self.agents.get(t.agent_id)
            nm = a.role.name if a else t.agent_id
            peer_results.append(f"- {nm}({t.agent_id}): {t.result[:400]}")
        peer_blob = "\n".join(peer_results[:8]) if peer_results else "(本团队本轮尚无其他成员产出)"

        prompt = f"""你是多 Agent 协作调度器。判断：这名成员的初稿是否还需要**向另一名同事单独追问**才能得到完整结论？

当前成员: {agent.role.name} (id={agent.role.id})
任务: {task.description[:600]}
初稿:
{(task.result or '')[:1400]}

团队中其他成员（可选请教对象，必选 id 或 none）:
{roster}

本轮已有成员产出摘要:
{peer_blob}

若初稿已充分，或仅缺的信息已在「已有产出」里（只需整合），输出严格 JSON:
{{"need": false}}

若必须向某人追问**新的事实/数据**（追问应简短明确），输出:
{{"need": true, "agent_id": "<成员id>", "question": "<向该成员的一句话追问>"}}

只输出 JSON，不要 markdown。"""
        messages = [{"role": "user", "content": prompt}]
        try:
            text = await asyncio.wait_for(self._ai_call(messages), timeout=25)
        except Exception:
            return None
        try:
            data = self._extract_json_object(text)
            if not data:
                return None
            if not data.get("need"):
                return None
            aid = (data.get("agent_id") or "").strip()
            q = (data.get("question") or "").strip()
            if not aid or aid not in self.agents or aid == agent.role.id or not q:
                return None
            return (aid, q[:1200])
        except Exception:
            return None

    async def _maybe_runtime_consult(self, agent: Agent, task: SubTask) -> None:
        """波次结束后：必要时向同伴请教并修订原成员产出（同一 Agent 实例串行，安全）"""
        consult = await self._detect_runtime_consult(agent, task)
        if not consult:
            return
        peer_id, question = consult
        peer = self.agents[peer_id]
        peer_name = peer.role.name

        peer_task = next(
            (
                t for t in self.tasks
                if t.agent_id == peer_id and t is not task and t.status == "done" and t.result
            ),
            None,
        )
        base_ctx = self._enriched_context_for_task(task)
        self._add_message(agent.role.id, peer_id, "question", question)

        if peer_task:
            payload = peer_task.result[:2200]
            self._add_message(peer_id, agent.role.id, "result", f"[已有产出摘要] {payload[:400]}…")
            merge = dict(base_ctx)
            merge[f"[{peer_name} 的可参考产出]"] = payload
            merge["[你的初稿]"] = (task.result or "")[:1800]
            merge["[整合说明]"] = (
                f"请结合「{peer_name}」的已有产出，修订你的结论；若仍有缺口，在文末用一句说明缺什么。"
            )
            task._consult_round = 1
            task.partial_result = ""
            task.status = "working"
            await agent.execute(task, merge, self._ai_call)
            self._persist_task_artifact(agent, task)
            return

        consult_task = SubTask(
            agent_id=peer_id,
            description=f"【同事请教】{agent.role.name} 需要你补充：{question}",
        )
        peer_ctx = dict(self.context)
        peer_ctx["[请教背景]"] = f"用户总需求摘要：{self.context.get('user_request', '')[:500]}"
        await peer.execute(consult_task, peer_ctx, self._ai_call)
        ans = consult_task.result or ""
        self._add_message(peer_id, agent.role.id, "answer", ans[:2000])

        merge = dict(base_ctx)
        merge[f"[{peer_name} 对请教的答复]"] = ans[:2200]
        merge["[整合说明]"] = (
            f"你已产出初稿。请根据「{peer_name}」的答复输出**修订后的最终版本**，突出新增信息。"
        )
        merge["[你的初稿]"] = (task.result or "")[:1800]
        task._consult_round = 1
        task.partial_result = ""
        task.status = "working"
        await agent.execute(task, merge, self._ai_call)
        self._persist_task_artifact(agent, task)

    async def _post_wave_runtime_consult(self, wave_tasks: List[SubTask]) -> None:
        """本波所有任务并行结束后执行，避免与同伴执行冲突"""
        for task in wave_tasks:
            if task.status != "done" or not task.result:
                continue
            agent = self.agents.get(task.agent_id)
            if not agent or agent.role.id == "ceo":
                continue
            if not self._should_attempt_runtime_consult(task):
                continue
            try:
                await self._maybe_runtime_consult(agent, task)
            except Exception as e:
                logger.debug(f"[Team] runtime consult 跳过: {e}")

    async def _execute_tasks(self):
        """DAG 分层并行执行：无依赖的先跑，依赖完成的再跑"""

        async def _run(task: SubTask):
            agent = self.agents.get(task.agent_id)
            if not agent:
                task.status = "error"
                task.result = f"Agent {task.agent_id} 不存在"
                return
            try:
                enriched_ctx = self._enriched_context_for_task(task)

                await asyncio.wait_for(
                    agent.execute(task, enriched_ctx, self._ai_call),
                    timeout=self.TASK_TIMEOUT,
                )
                self._persist_task_artifact(agent, task)
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

            # 运行时「请教」：本波全部结束后串行处理，避免与同伴执行冲突
            await self._post_wave_runtime_consult(ready)

            # CEO 中间审核（第一层完成后，为后续层补充协作指引）
            if wave == 0 and len(completed_agents) >= 2:
                try:
                    await self._ceo_mid_review(completed_agents)
                except Exception as e:
                    logger.debug(f"[Team] CEO 中间审核跳过: {e}")

    async def _ceo_mid_review(self, completed_agents: set):
        """CEO 中间审核 — 第一层完成后，为后续任务补充协作指引"""
        ceo = self.agents.get("ceo")
        if not ceo:
            return

        # 收集第一层结果摘要
        wave1_results = []
        for t in self.tasks:
            if t.agent_id in completed_agents and t.result:
                agent = self.agents.get(t.agent_id)
                name = agent.role.name if agent else t.agent_id
                wave1_results.append(f"- {name}: {t.result[:200]}")

        if not wave1_results:
            return

        # 找到待执行任务
        pending = [t for t in self.tasks if t.status == "pending"]
        if not pending:
            return

        pending_desc = "\n".join(f"- {self.agents.get(t.agent_id, t).role.name if self.agents.get(t.agent_id) else t.agent_id}: {t.description[:60]}" for t in pending[:5])

        review_prompt = f"""第一批成员已完成工作：
{chr(10).join(wave1_results[:5])}

接下来要执行的任务：
{pending_desc}

请用 1-2 句话给每个待执行成员一个协作建议（如"参考CMO的定位策略"、"数据要和财务的预算对齐"）。
只输出建议，每行一个，格式：成员ID: 建议"""

        messages = [
            {"role": "system", "content": "你是团队CEO，负责协调成员间的协作。简洁回答。"},
            {"role": "user", "content": review_prompt},
        ]

        try:
            review_text = await asyncio.wait_for(self._ai_call(messages), timeout=15)
            # 解析建议并注入到待执行任务的 context
            for line in review_text.strip().split("\n"):
                line = line.strip()
                if ":" in line or "：" in line:
                    sep = "：" if "：" in line else ":"
                    agent_hint, advice = line.split(sep, 1)
                    agent_hint = agent_hint.strip().lower()
                    for t in pending:
                        aid = t.agent_id.lower()
                        agent = self.agents.get(t.agent_id)
                        aname = agent.role.name if agent else ""
                        if aid in agent_hint or aname in agent_hint:
                            # 注入协作指引到任务描述
                            t.description = t.description + f"\n\n💡 CEO 协作指引：{advice.strip()}"
                            break

            self._add_message("ceo", "broadcast", "review", "已审核第一批成果，为后续任务补充协作指引")
            logger.info(f"[Team:{self.name}] CEO 中间审核完成，为 {len(pending)} 个待执行任务补充指引")
        except Exception as e:
            logger.debug(f"[Team] CEO mid-review failed: {e}")

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

    def _generate_html_report(self, summary: str, task: str):
        """生成精美 HTML 报告（可直接分享给客户）"""
        if not hasattr(self, '_project') or not self._project:
            return
        try:
            # 简单 Markdown → HTML
            import re
            html_body = summary
            html_body = re.sub(r'^### (.*$)', r'<h3>\1</h3>', html_body, flags=re.M)
            html_body = re.sub(r'^## (.*$)', r'<h2>\1</h2>', html_body, flags=re.M)
            html_body = re.sub(r'^# (.*$)', r'<h1>\1</h1>', html_body, flags=re.M)
            html_body = re.sub(r'^\- (.*$)', r'<li>\1</li>', html_body, flags=re.M)
            html_body = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_body)
            html_body = html_body.replace('\n\n', '</p><p>').replace('\n', '<br>')

            # 收集各 Agent 贡献
            agent_cards = ""
            for t in self.tasks:
                agent = self.agents.get(t.agent_id)
                if agent and t.result:
                    preview = t.result[:150].replace('<', '&lt;').replace('\n', ' ')
                    agent_cards += f"""
                    <div class="agent-card">
                        <div class="ac-head">{agent.role.avatar} {agent.role.name}</div>
                        <div class="ac-body">{preview}...</div>
                    </div>"""

            html = f"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{task[:30]} — 十三香小龙虾 AI 工作队</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#0b0d14;color:#eee;padding:0}}
.header{{background:linear-gradient(135deg,#6c63ff,#8b5cf6);padding:40px 20px;text-align:center}}
.header h1{{font-size:24px;margin-bottom:8px}}
.header p{{opacity:0.8;font-size:14px}}
.content{{max-width:800px;margin:0 auto;padding:20px}}
h1,h2,h3{{margin:20px 0 10px;color:#fff}}
p{{margin:8px 0;line-height:1.7;color:#ccc}}
li{{margin:4px 0;color:#ccc}}
strong{{color:#fff}}
.team-section{{margin-top:30px}}
.team-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:12px}}
.agent-card{{background:#1a1a2e;border:1px solid #333;border-radius:10px;padding:12px}}
.ac-head{{font-size:14px;font-weight:600;margin-bottom:6px}}
.ac-body{{font-size:12px;color:#aaa;line-height:1.5}}
.footer{{text-align:center;padding:30px;color:#666;font-size:12px}}
</style></head><body>
<div class="header">
<h1>{task[:50]}</h1>
<p>由 {self.name}（{len(self.agents)}人）完成 · 十三香小龙虾 AI 工作队</p>
</div>
<div class="content">
<p>{html_body}</p>
<div class="team-section">
<h2>👥 团队贡献</h2>
<div class="team-grid">{agent_cards}</div>
</div>
</div>
<div class="footer">由十三香小龙虾 AI 工作队自动生成 · shisanxiang.ai</div>
</body></html>"""

            self._project.save_artifact(
                agent_name="系统",
                agent_avatar="🌐",
                filename="报告_可分享",
                content=html,
                file_type="html",
            )
            logger.info(f"[Team:{self.name}] 生成 HTML 报告")
        except Exception as e:
            logger.debug(f"[Team] HTML 报告生成失败: {e}")

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
