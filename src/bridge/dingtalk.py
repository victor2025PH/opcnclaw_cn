"""
钉钉机器人桥接

配置方式：
  群设置 → 智能群助手 → 添加机器人 → 自定义 → 复制 Webhook URL
  
注意：钉钉机器人需要配置「安全设置」，推荐选「自定义关键词」（填"OpenClaw"）

文档：https://open.dingtalk.com/document/robots/custom-robot-access
"""
import hashlib
import hmac
import base64
import time
import urllib.parse
from typing import Optional

import httpx
from loguru import logger

from .manager import BaseBridge


class DingTalkBridge(BaseBridge):
    """钉钉自定义机器人"""

    def __init__(
        self,
        webhook_url: str,
        secret: str = "",       # 加签模式的密钥
        at_all: bool = False,
    ):
        self.webhook_url = webhook_url
        self.secret = secret
        self.at_all = at_all

    def _get_signed_url(self) -> str:
        """钉钉签名模式"""
        if not self.secret:
            return self.webhook_url
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"{self.webhook_url}&timestamp={ts}&sign={sign}"

    async def send_text(self, text: str, title: str = "") -> bool:
        """发送文本消息"""
        payload = {
            "msgtype": "text",
            "text": {"content": f"[OpenClaw]\n{text}"},
            "at": {"isAtAll": self.at_all},
        }
        return await self._post(payload)

    async def send_markdown(self, content: str, title: str = "") -> bool:
        """发送 Markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title or "OpenClaw AI",
                "text": content,
            },
            "at": {"isAtAll": self.at_all},
        }
        return await self._post(payload)

    async def send_ai_response(self, user_msg: str, ai_response: str) -> bool:
        md = (
            f"## 🦞 OpenClaw AI 语音助手\n\n"
            f"**用户：** {user_msg}\n\n"
            f"**AI：** {ai_response}\n\n"
            f"> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return await self.send_markdown(md, title="AI 回复")

    async def _post(self, payload: dict) -> bool:
        url = self._get_signed_url()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"},
                )
                data = r.json()
                if data.get("errcode", -1) == 0:
                    logger.debug("钉钉消息发送成功")
                    return True
                else:
                    logger.warning(f"钉钉发送失败: {data}")
                    return False
        except Exception as e:
            logger.warning(f"钉钉发送异常: {e}")
            return False

    @staticmethod
    def test_webhook(url: str, secret: str = "") -> str:
        import asyncio
        bridge = DingTalkBridge(url, secret)
        async def _t():
            return await bridge.send_text("✅ OpenClaw 钉钉机器人配置成功！这是一条测试消息。关键词：OpenClaw")
        try:
            result = asyncio.run(_t())
            return "连接成功！" if result else "发送失败，检查URL和安全设置"
        except Exception as e:
            return f"连接失败: {e}"
