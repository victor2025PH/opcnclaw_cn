# -*- coding: utf-8 -*-
"""
iLink 消息处理器 — 将微信消息接入 AI 工作队

收到微信消息 → AI 处理 → 回复
支持：
  - 普通聊天（直接调用 AI 路由器）
  - 团队任务（"帮我写营销方案" → 52 Agent 协作）
  - 用户画像学习（微信对话也积累护城河）
"""

from __future__ import annotations

import asyncio
from loguru import logger


async def handle_wechat_message(from_user: str, text: str, context_token: str):
    """处理微信收到的消息"""
    from .ilink_bot import get_ilink_bot
    bot = get_ilink_bot()

    # 检查是否是团队任务关键词
    team_keywords = ["帮我写", "帮我做", "帮我分析", "写一个", "做一个",
                     "营销方案", "竞品分析", "商业计划", "技术方案"]
    is_team_task = any(kw in text for kw in team_keywords)

    if is_team_task:
        await _handle_team_task(bot, from_user, text, context_token)
    else:
        await _handle_chat(bot, from_user, text, context_token)

    # 用户画像学习（微信对话也积累护城河）
    try:
        from .user_profile_ai import update_profile_from_conversation
        update_profile_from_conversation(text, "")
    except Exception:
        pass


async def _handle_chat(bot, from_user: str, text: str, context_token: str):
    """普通聊天 — 调用 AI 回复"""
    try:
        from src.server.main import backend as _backend
        if not _backend:
            await bot.send_text(from_user, "AI 未配置，请在设置中填写 API Key", context_token)
            return

        # 收集完整回复（微信不支持流式）
        full_response = ""
        async for chunk in _backend.chat_stream(text):
            if chunk and chunk not in ("__SWITCH__", "__TOOL_CALLS__"):
                if chunk.startswith("__SKILL__"):
                    continue
                full_response += chunk

        if not full_response:
            full_response = "抱歉，我暂时无法回复。"

        # 微信消息长度限制，截断
        if len(full_response) > 2000:
            full_response = full_response[:1950] + "\n\n(内容较长，已截断。在电脑端查看完整内容)"

        await bot.send_text(from_user, full_response, context_token)
        logger.info(f"[iLink] 回复: {full_response[:50]}...")

    except Exception as e:
        logger.error(f"[iLink] 聊天处理错误: {e}")
        await bot.send_text(from_user, f"处理出错了: {str(e)[:100]}", context_token)


async def _handle_team_task(bot, from_user: str, text: str, context_token: str):
    """团队任务 — 部署 Agent 团队执行"""
    try:
        # 先回复"收到，正在组建团队"
        await bot.send_text(from_user, f"收到！正在为你组建 AI 团队...\n\n任务：{text}", context_token)

        from .tools import deploy_team, confirm_team

        # 部署团队
        result = await deploy_team(task=text)
        if "error" in result:
            await bot.send_text(from_user, f"团队部署失败：{result['error']}", context_token)
            return

        team_id = result.get("team_id", "")
        team_name = result.get("team_name", "")
        agent_count = result.get("agent_count", 0)

        # 通知用户团队已组建
        intro_msg = f"✅ {team_name}（{agent_count}人）已就位！\n\n正在执行任务，完成后会自动通知你。"
        await bot.send_text(from_user, intro_msg, context_token)

        # 自动确认执行（微信场景不需要额外确认）
        exec_result = await confirm_team(team_id=team_id, task=text)
        if "error" in exec_result:
            await bot.send_text(from_user, f"执行失败：{exec_result['error']}", context_token)
            return

        # 后台等待完成并推送结果
        asyncio.create_task(_wait_and_notify(bot, from_user, team_id, context_token))

    except Exception as e:
        logger.error(f"[iLink] 团队任务错误: {e}")
        await bot.send_text(from_user, f"任务处理出错: {str(e)[:100]}", context_token)


async def _wait_and_notify(bot, from_user: str, team_id: str, context_token: str):
    """等待团队完成并推送结果到微信"""
    from .agent_team import get_team
    max_wait = 300  # 最多等 5 分钟
    interval = 10   # 每 10 秒检查一次

    for _ in range(max_wait // interval):
        await asyncio.sleep(interval)
        team = get_team(team_id)
        if not team:
            break
        if team.status == "done":
            # 发送结果摘要
            summary = team.final_result or "(无结果)"
            if len(summary) > 1800:
                summary = summary[:1750] + "\n\n... (完整报告请在电脑端查看)"

            # 添加分享链接
            project_id = ""
            if hasattr(team, '_project') and team._project:
                project_id = team._project.project_id

            result_msg = f"✅ 团队任务完成！\n\n{summary}"
            if project_id:
                result_msg += f"\n\n📄 完整报告：查看电脑端 /report/{project_id}"

            await bot.send_text(from_user, result_msg, context_token)
            logger.info(f"[iLink] 团队结果已推送: {team_id}")
            return

        if team.status == "error":
            await bot.send_text(from_user, "❌ 团队执行出错，请在电脑端查看详情", context_token)
            return

    # 超时
    await bot.send_text(from_user, "⏰ 任务执行超时（5分钟），请在电脑端查看进度", context_token)
