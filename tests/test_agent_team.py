# -*- coding: utf-8 -*-
"""Agent 团队测试"""

import asyncio
import pytest

from src.server.agent_team import Agent, AgentTeam, AgentRole, SubTask, TeamMessage
from src.server.agent_templates import (
    AGENT_ROLES, TEAM_TEMPLATES, list_templates, list_roles,
    build_agents, get_template, get_role,
)


class TestAgentRole:
    def test_all_roles_defined(self):
        assert len(AGENT_ROLES) == 13

    def test_role_has_required_fields(self):
        for rid, role in AGENT_ROLES.items():
            assert role.id == rid
            assert role.name
            assert role.avatar
            assert role.system_prompt

    def test_ceo_can_delegate(self):
        assert AGENT_ROLES["ceo"].can_delegate is True

    def test_list_roles(self):
        roles = list_roles()
        assert len(roles) == 13
        assert all("id" in r for r in roles)


class TestTeamTemplates:
    def test_all_templates_defined(self):
        assert len(TEAM_TEMPLATES) == 7

    def test_template_roles_valid(self):
        for tid, tpl in TEAM_TEMPLATES.items():
            for rid in tpl["roles"]:
                assert rid in AGENT_ROLES, f"{tid}: 角色 {rid} 不存在"

    def test_all_hands_has_all(self):
        assert len(TEAM_TEMPLATES["all_hands"]["roles"]) == 13

    def test_list_templates(self):
        tpls = list_templates()
        assert len(tpls) == 7
        assert all("agent_count" in t for t in tpls)

    def test_get_template(self):
        t = get_template("startup")
        assert t is not None
        assert t["name"] == "创业团队"

    def test_get_nonexistent(self):
        assert get_template("nonexistent") is None


class TestBuildAgents:
    def test_build(self):
        agents = build_agents(["ceo", "writer", "coder"])
        assert len(agents) == 3
        assert agents[0].role.id == "ceo"

    def test_build_invalid(self):
        agents = build_agents(["ceo", "nonexistent"])
        assert len(agents) == 1  # 只有 ceo


class TestAgent:
    def test_agent_init(self):
        role = AGENT_ROLES["writer"]
        agent = Agent(role)
        assert agent.status.value == "idle"
        assert agent.current_task is None

    def test_agent_to_dict(self):
        agent = Agent(AGENT_ROLES["ceo"])
        d = agent.to_dict()
        assert d["id"] == "ceo"
        assert d["status"] == "idle"


class TestSubTask:
    def test_defaults(self):
        t = SubTask(agent_id="writer", description="写一篇文章")
        assert t.status == "pending"
        assert len(t.id) == 8

    def test_to_dict(self):
        t = SubTask(agent_id="coder", description="写代码")
        d = t.to_dict()
        assert d["agent_id"] == "coder"


class TestTeamMessage:
    def test_message(self):
        m = TeamMessage(from_agent="ceo", to_agent="writer", type="task", content="写文案")
        d = m.to_dict()
        assert d["from"] == "ceo"
        assert d["to"] == "writer"


class TestAgentTeam:
    def test_create_team(self):
        agents = build_agents(["ceo", "writer"])
        team = AgentTeam(team_id="test1", name="测试团队", agents=agents)
        assert team.status == "idle"
        assert len(team.agents) == 2

    def test_team_status(self):
        agents = build_agents(["ceo", "writer", "coder"])
        team = AgentTeam(team_id="test2", name="测试", agents=agents)
        s = team.get_status()
        assert s["team_id"] == "test2"
        assert len(s["agents"]) == 3

    def test_execute_without_ai(self):
        """无 AI 调用时应返回错误"""
        agents = build_agents(["writer"])
        team = AgentTeam(team_id="test3", name="测试", agents=agents)
        result = asyncio.get_event_loop().run_until_complete(team.execute("测试任务"))
        assert "未配置" in result

    def test_execute_with_mock_ai(self):
        """Mock AI 测试完整流程"""
        async def mock_ai(messages, model=""):
            content = messages[-1]["content"] if messages else ""
            if "拆解" in content or "子任务" in content:
                return '[{"agent": "writer", "task": "写一篇测试文章"}]'
            if "汇总" in content:
                return "# 最终报告\n所有任务完成。"
            return f"Mock 回复: {content[:50]}"

        agents = build_agents(["ceo", "writer"])
        team = AgentTeam(team_id="test4", name="测试", agents=agents)
        team.set_ai_call(mock_ai)

        result = asyncio.get_event_loop().run_until_complete(team.execute("写一篇产品介绍"))
        assert team.status == "done"
        assert len(team.final_result) > 0
        assert len(team.messages) > 0


class TestFileTransfer:
    def test_upload(self):
        from src.server.file_transfer import FileTransferManager
        mgr = FileTransferManager()
        record = mgr.upload("test.txt", b"hello world")
        assert record.filename == "test.txt"
        assert record.size == 11
        assert record.direction == "upload"

    def test_list(self):
        from src.server.file_transfer import FileTransferManager
        mgr = FileTransferManager()
        mgr.upload("a.txt", b"aaa")
        mgr.upload("b.txt", b"bbb")
        records = mgr.list_records()
        assert len(records) >= 2

    def test_delete(self):
        from src.server.file_transfer import FileTransferManager
        mgr = FileTransferManager()
        record = mgr.upload("del.txt", b"delete me")
        ok = mgr.delete(record.file_id)
        assert ok is True
