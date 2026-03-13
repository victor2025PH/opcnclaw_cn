"""
企业微信机器人桥接

配置方式：
  群管理 → 添加机器人 → 复制 Webhook URL → 填入设置

文档：https://developer.work.weixin.qq.com/document/path/91770
"""
import json
import time
from typing import Optional

import httpx
from loguru import logger

from .manager import BaseBridge


class WeComBridge(BaseBridge):
    """企业微信群机器人"""

    def __init__(self, webhook_url: str, at_all: bool = False):
        self.webhook_url = webhook_url
        self.at_all = at_all

    async def send_text(self, text: str, title: str = "") -> bool:
        """发送文本消息"""
        content = f"[OpenClaw AI]\n{text}"
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": ["@all"] if self.at_all else [],
            },
        }
        return await self._post(payload)

    async def send_markdown(self, content: str, title: str = "") -> bool:
        """发送 Markdown 消息（企业微信支持有限的Markdown）"""
        md = f"# 🦞 {title}\n\n{content}" if title else content
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": md},
        }
        return await self._post(payload)

    async def send_ai_response(self, user_msg: str, ai_response: str) -> bool:
        """发送 AI 对话（Markdown卡片）"""
        md = (
            f"> **用户说：** {user_msg}\n\n"
            f"**AI 回复：**\n{ai_response}\n\n"
            f"<font color=\"comment\">by OpenClaw · {time.strftime('%H:%M')}</font>"
        )
        return await self.send_markdown(md, title="AI 语音助手")

    async def _post(self, payload: dict) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                data = r.json()
                if data.get("errcode", -1) == 0:
                    logger.debug("企业微信消息发送成功")
                    return True
                else:
                    logger.warning(f"企业微信发送失败: {data}")
                    return False
        except Exception as e:
            logger.warning(f"企业微信发送异常: {e}")
            return False

    @staticmethod
    def test_webhook(url: str) -> str:
        import asyncio
        bridge = WeComBridge(url)
        async def _t():
            return await bridge.send_text("✅ OpenClaw 企业微信机器人配置成功！这是一条测试消息。")
        try:
            result = asyncio.run(_t())
            return "连接成功！" if result else "发送失败，请检查 Webhook URL"
        except Exception as e:
            return f"连接失败: {e}"
