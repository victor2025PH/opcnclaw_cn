# -*- coding: utf-8 -*-
"""A2A 协议测试

覆盖：
  - Agent Card 完整性
  - 任务生命周期（创建→执行→完成/失败）
  - 任务取消
  - 消息通信
  - 任务过滤查询
  - 技能注册与调度
  - Webhook 注册
  - 异常处理
"""

import asyncio
import time
import pytest

from src.server.a2a import (
    A2AServer, A2ATask, Artifact, A2AMessage,
    TaskState, get_agent_card,
)


@pytest.fixture
def server():
    """创建干净的 A2A 服务器（不注册内置技能）"""
    return A2AServer()


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run_async(coro):
    """运行异步函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAgentCard:
    """Agent Card 测试"""

    def test_card_structure(self):
        card = get_agent_card()
        assert card["name"] == "ShisanXiang"
        assert "description" in card
        assert card["protocol"] == "a2a/1.0"

    def test_card_has_skills(self):
        card = get_agent_card()
        assert len(card["skills"]) >= 5
        skill_ids = {s["id"] for s in card["skills"]}
        assert "desktop_control" in skill_ids
        assert "wechat_send" in skill_ids
        assert "screenshot" in skill_ids

    def test_card_has_capabilities(self):
        card = get_agent_card()
        caps = card["capabilities"]
        assert "pushNotifications" in caps
        assert "stateTransitionHistory" in caps

    def test_card_has_auth(self):
        card = get_agent_card()
        assert card["authentication"]["schemes"] == ["pin"]

    def test_skill_input_output_modes(self):
        card = get_agent_card()
        for skill in card["skills"]:
            assert "inputModes" in skill
            assert "outputModes" in skill
            assert len(skill["inputModes"]) > 0


class TestA2ATask:
    """任务数据模型测试"""

    def test_task_defaults(self):
        task = A2ATask(source_agent="test", intent="screenshot")
        assert task.state == TaskState.SUBMITTED
        assert task.priority == 5
        assert len(task.id) == 8

    def test_task_to_dict(self):
        task = A2ATask(source_agent="claude", intent="wechat_send", params={"contact": "test"})
        d = task.to_dict()
        assert d["source_agent"] == "claude"
        assert d["intent"] == "wechat_send"
        assert d["state"] == "submitted"
        assert d["params"]["contact"] == "test"

    def test_add_message(self):
        task = A2ATask(source_agent="test", intent="test")
        task.add_message("user", "请截屏")
        assert len(task.messages) == 1
        assert task.messages[0].content == "请截屏"

    def test_add_artifact(self):
        task = A2ATask(source_agent="test", intent="test")
        task.add_artifact("result", "text", "操作成功")
        assert len(task.artifacts) == 1
        assert task.artifacts[0].data == "操作成功"


class TestArtifact:
    """产出物测试"""

    def test_text_artifact(self):
        a = Artifact(name="output", type="text", data="hello")
        d = a.to_dict()
        assert d["data"] == "hello"

    def test_image_artifact_masked(self):
        """图片数据不应在 to_dict 中暴露原始数据"""
        a = Artifact(name="screenshot", type="image", data="base64longstring")
        d = a.to_dict()
        assert "base64longstring" not in str(d["data"])


class TestTaskLifecycle:
    """任务生命周期测试"""

    def test_create_task_unknown_skill(self, server):
        """创建任务但无处理器 → 失败"""
        task = run_async(server.create_task("agent-1", "unknown_skill"))
        assert task.state == TaskState.FAILED
        assert "unknown_skill" in task.error

    def test_create_task_with_handler(self, server):
        """创建任务有处理器 → 完成"""
        async def mock_handler(task):
            return {"result": "done"}

        server.register_skill("test_skill", mock_handler)
        task = run_async(server.create_task("agent-1", "test_skill"))
        assert task.state == TaskState.COMPLETED
        assert len(task.artifacts) > 0

    def test_handler_sync(self, server):
        """同步处理器也能工作"""
        def sync_handler(task):
            return {"sync": True}

        server.register_skill("sync_test", sync_handler)
        task = run_async(server.create_task("agent-1", "sync_test"))
        assert task.state == TaskState.COMPLETED

    def test_handler_exception(self, server):
        """处理器异常 → 任务失败"""
        async def bad_handler(task):
            raise ValueError("模拟错误")

        server.register_skill("bad_skill", bad_handler)
        task = run_async(server.create_task("agent-1", "bad_skill"))
        assert task.state == TaskState.FAILED
        assert "模拟错误" in task.error

    def test_task_messages_recorded(self, server):
        """任务应自动记录系统消息"""
        async def handler(task):
            return {}

        server.register_skill("msg_test", handler)
        task = run_async(server.create_task("agent-1", "msg_test"))
        # 至少有 "任务已创建" 和 "技能匹配" 和 "任务完成" 三条消息
        assert len(task.messages) >= 3


class TestTaskCancel:
    """任务取消测试"""

    def test_cancel_submitted(self, server):
        task = A2ATask(source_agent="test", intent="test")
        server._tasks[task.id] = task
        ok = server.cancel_task(task.id)
        assert ok is True
        assert task.state == TaskState.CANCELED

    def test_cancel_completed(self, server):
        """已完成的任务不能取消"""
        task = A2ATask(source_agent="test", intent="test")
        task.state = TaskState.COMPLETED
        server._tasks[task.id] = task
        ok = server.cancel_task(task.id)
        assert ok is False

    def test_cancel_nonexistent(self, server):
        ok = server.cancel_task("nonexistent")
        assert ok is False


class TestTaskQuery:
    """任务查询测试"""

    def test_get_task(self, server):
        task = A2ATask(source_agent="agent-1", intent="test")
        server._tasks[task.id] = task
        found = server.get_task(task.id)
        assert found is task

    def test_list_tasks(self, server):
        for i in range(5):
            t = A2ATask(source_agent=f"agent-{i % 2}", intent="test")
            server._tasks[t.id] = t

        all_tasks = server.list_tasks()
        assert len(all_tasks) == 5

    def test_filter_by_agent(self, server):
        for i in range(4):
            t = A2ATask(source_agent=f"agent-{i % 2}", intent="test")
            server._tasks[t.id] = t

        agent0 = server.list_tasks(source_agent="agent-0")
        assert len(agent0) == 2

    def test_filter_by_state(self, server):
        t1 = A2ATask(source_agent="test", intent="test")
        t2 = A2ATask(source_agent="test", intent="test")
        t2.state = TaskState.COMPLETED
        server._tasks[t1.id] = t1
        server._tasks[t2.id] = t2

        completed = server.list_tasks(state="completed")
        assert len(completed) == 1


class TestTaskMessage:
    """任务消息通信测试"""

    def test_send_message(self, server):
        task = A2ATask(source_agent="test", intent="test")
        server._tasks[task.id] = task
        ok = server.send_message(task.id, "user", "请确认操作")
        assert ok is True
        assert len(task.messages) == 1

    def test_message_resumes_input_required(self, server):
        """input-required 状态收到消息后恢复 working"""
        task = A2ATask(source_agent="test", intent="test")
        task.state = TaskState.INPUT_REQUIRED
        server._tasks[task.id] = task

        server.send_message(task.id, "user", "确认")
        assert task.state == TaskState.WORKING

    def test_message_nonexistent(self, server):
        ok = server.send_message("nonexistent", "user", "test")
        assert ok is False


class TestSkillRegistration:
    """技能注册测试"""

    def test_register_skill(self, server):
        server.register_skill("custom_skill", lambda t: {"ok": True})
        assert "custom_skill" in server._skill_handlers

    def test_overwrite_skill(self, server):
        server.register_skill("skill_a", lambda t: 1)
        server.register_skill("skill_a", lambda t: 2)
        assert server._skill_handlers["skill_a"](None) == 2


class TestWebhook:
    """Webhook 测试"""

    def test_register_webhook(self, server):
        server.register_webhook("agent-1", "http://example.com/webhook")
        assert server._webhooks["agent-1"] == "http://example.com/webhook"


class TestCleanup:
    """清理测试"""

    def test_cleanup_old_tasks(self, server):
        server.MAX_TASKS = 5
        for i in range(10):
            t = A2ATask(source_agent="test", intent="test")
            t.state = TaskState.COMPLETED
            t.completed_at = time.time() - 7200  # 2小时前
            server._tasks[t.id] = t

        server._cleanup_old_tasks()
        assert len(server._tasks) < 10


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_params(self, server):
        """空参数不应崩溃"""
        async def handler(task):
            return {}
        server.register_skill("empty", handler)
        task = run_async(server.create_task("test", "empty"))
        assert task.state == TaskState.COMPLETED

    def test_large_result(self, server):
        """大结果不应崩溃"""
        async def handler(task):
            return {"data": "x" * 10000}
        server.register_skill("large", handler)
        task = run_async(server.create_task("test", "large"))
        assert task.state == TaskState.COMPLETED
        assert len(task.artifacts) > 0

    def test_concurrent_tasks(self, server):
        """并发创建多个任务"""
        async def handler(task):
            return {"id": task.id}
        server.register_skill("concurrent", handler)

        async def create_many():
            tasks = await asyncio.gather(*[
                server.create_task(f"agent-{i}", "concurrent")
                for i in range(10)
            ])
            return tasks

        tasks = run_async(create_many())
        assert all(t.state == TaskState.COMPLETED for t in tasks)
        assert len(server._tasks) == 10
