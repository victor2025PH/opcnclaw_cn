"""
飞书机器人桥接

支持：
1. 自定义机器人 Webhook（最简单，只需一个URL，5分钟配置完）
2. 群消息推送：文本/富文本/卡片

配置方式：
  在飞书群里添加「自定义机器人」→ 复制 Webhook URL → 填入设置

接收消息（进阶）：
  需要飞书开放平台应用，需要企业管理员权限，留在后续版本实现
"""
import hashlib
import hmac
import json
import time
from typing import Optional

import httpx
from loguru import logger

from .manager import BaseBridge


class FeishuBridge(BaseBridge):
    """
    飞书自定义机器人

    文档：https://open.feishu.cn/document/client-docs/bot-5/add-custom-bot
    """

    def __init__(
        self,
        webhook_url: str,
        secret: str = "",           # 可选安全签名
        at_all: bool = False,       # 是否 @所有人
    ):
        self.webhook_url = webhook_url
        self.secret = secret
        self.at_all = at_all

    def _sign(self) -> tuple[str, str]:
        """生成飞书签名（如果配置了密钥）"""
        ts = str(int(time.time()))
        if not self.secret:
            return ts, ""
        string_to_sign = f"{ts}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        import base64
        sign = base64.b64encode(hmac_code).decode("utf-8")
        return ts, sign

    async def send_text(self, text: str, title: str = "") -> bool:
        """发送纯文本消息"""
        ts, sign = self._sign()
        payload = {
            "msg_type": "text",
            "content": {"text": f"[OpenClaw]\n{text}"},
        }
        if sign:
            payload["timestamp"] = ts
            payload["sign"] = sign
        if self.at_all:
            payload["content"]["text"] += "\n<at user_id=\"all\">所有人</at>"
        return await self._post(payload)

    async def send_card(self, title: str, content: str, color: str = "blue") -> bool:
        """发送卡片消息（更美观）"""
        ts, sign = self._sign()
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"🦞 {title}"},
                    "template": color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": content},
                    },
                    {
                        "tag": "note",
                        "elements": [{"tag": "plain_text", "content": f"OpenClaw AI 助手 · {time.strftime('%H:%M')}"}],
                    },
                ],
            },
        }
        if sign:
            payload["timestamp"] = ts
            payload["sign"] = sign
        return await self._post(payload)

    async def send_ai_response(self, user_msg: str, ai_response: str) -> bool:
        """发送 AI 对话卡片"""
        content = (
            f"**用户：** {user_msg}\n\n"
            f"**AI 回复：** {ai_response}"
        )
        return await self.send_card("AI 语音助手回复", content, color="blue")

    async def _post(self, payload: dict) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                data = r.json()
                if data.get("code", 0) == 0 or data.get("StatusCode") == 0:
                    logger.debug("飞书消息发送成功")
                    return True
                else:
                    logger.warning(f"飞书发送失败: {data}")
                    return False
        except Exception as e:
            logger.warning(f"飞书发送异常: {e}")
            return False

    @staticmethod
    def test_webhook(url: str) -> str:
        """测试 Webhook 是否有效（同步版本）"""
        import asyncio
        bridge = FeishuBridge(url)
        async def _t():
            return await bridge.send_text("✅ OpenClaw 飞书机器人配置成功！这是一条测试消息。")
        try:
            result = asyncio.run(_t())
            return "连接成功！" if result else "发送失败，请检查 Webhook URL"
        except Exception as e:
            return f"连接失败: {e}"
