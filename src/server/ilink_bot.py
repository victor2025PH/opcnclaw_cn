# -*- coding: utf-8 -*-
"""
微信 ClawBot (iLink) 官方接入

通过腾讯官方 iLink 协议，将微信消息接入十三香小龙虾 AI 工作队。
用户在微信聊天中发消息 → iLink 长轮询收取 → AI 处理 → 回复推送到微信。

协议参考：
  - 基础 URL: https://ilinkai.weixin.qq.com
  - 认证: Bearer bot_token
  - 收消息: POST /ilink/bot/getupdates (长轮询 35s)
  - 发消息: POST /ilink/bot/sendmessage
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
from pathlib import Path
from typing import Callable, Dict, Optional

import httpx
from loguru import logger

BASE_URL = "https://ilinkai.weixin.qq.com"
TOKEN_FILE = Path("data/ilink_token.json")


def _make_headers(bot_token: str = "") -> Dict[str, str]:
    """构建 iLink 请求头"""
    uin_b64 = base64.b64encode(str(random.getrandbits(32)).encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": uin_b64,
    }
    if bot_token:
        headers["Authorization"] = f"Bearer {bot_token}"
    return headers


class ILinkBot:
    """微信 ClawBot iLink 客户端"""

    def __init__(self):
        self._token: str = ""
        self._base_url: str = BASE_URL
        self._cursor: str = ""  # getupdates 游标
        self._running: bool = False
        self._poll_task: Optional[asyncio.Task] = None
        self._on_message: Optional[Callable] = None  # 消息回调
        self._client: Optional[httpx.AsyncClient] = None
        self._load_token()

    def _load_token(self):
        """从文件加载已保存的 token"""
        try:
            if TOKEN_FILE.exists():
                data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                self._token = data.get("bot_token", "")
                self._base_url = data.get("base_url", BASE_URL)
                self._cursor = data.get("cursor", "")
                if self._token:
                    logger.info(f"[iLink] 已加载 token: {self._token[:16]}...")
        except Exception as e:
            logger.debug(f"[iLink] 加载 token 失败: {e}")

    def _save_token(self):
        """保存 token 到文件"""
        try:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(json.dumps({
                "bot_token": self._token,
                "base_url": self._base_url,
                "cursor": self._cursor,
                "saved_at": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[iLink] 保存 token 失败: {e}")

    @property
    def is_connected(self) -> bool:
        return bool(self._token)

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 登录（获取 QR 码）──

    async def get_login_qrcode(self) -> Dict:
        """获取登录二维码"""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/ilink/bot/get_bot_qrcode",
                params={"bot_type": 3},
                headers=_make_headers(),
            )
            data = r.json()
            return {
                "qrcode_id": data.get("qrcode", ""),
                "qrcode_img": data.get("qrcode_img_content", ""),
            }

    async def check_qrcode_status(self, qrcode_id: str) -> Dict:
        """检查二维码扫描状态"""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/ilink/bot/get_qrcode_status",
                params={"qrcode": qrcode_id},
                headers=_make_headers(),
            )
            data = r.json()
            status = data.get("status", "")
            if status == "confirmed":
                self._token = data.get("bot_token", "")
                self._base_url = data.get("baseurl", BASE_URL) or BASE_URL
                self._save_token()
                logger.info(f"[iLink] 微信绑定成功！")
                return {"connected": True, "token": self._token[:16] + "..."}
            return {"connected": False, "status": status}

    # ── 消息收发 ──

    async def send_text(self, to_user_id: str, text: str, context_token: str):
        """发送文本消息"""
        if not self._token:
            return {"error": "未连接微信"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self._base_url}/ilink/bot/sendmessage",
                json={
                    "msg": {
                        "to_user_id": to_user_id,
                        "message_type": 2,
                        "message_state": 2,
                        "context_token": context_token,
                        "item_list": [
                            {"type": 1, "text_item": {"text": text}}
                        ],
                    }
                },
                headers=_make_headers(self._token),
            )
            return r.json()

    async def _poll_once(self) -> list:
        """单次长轮询收取消息"""
        try:
            if not self._client:
                self._client = httpx.AsyncClient(timeout=45)

            r = await self._client.post(
                f"{self._base_url}/ilink/bot/getupdates",
                json={
                    "get_updates_buf": self._cursor,
                    "base_info": {"channel_version": "1.0.2"},
                },
                headers=_make_headers(self._token),
            )
            data = r.json()

            # 更新游标
            new_cursor = data.get("get_updates_buf", "")
            if new_cursor:
                self._cursor = new_cursor
                self._save_token()

            # 提取用户消息
            messages = []
            for msg in data.get("msgs", []):
                if msg.get("message_type") != 1:  # 只处理用户消息
                    continue
                text = ""
                for item in msg.get("item_list", []):
                    if item.get("type") == 1:
                        text = item.get("text_item", {}).get("text", "")
                if text:
                    messages.append({
                        "from_user": msg.get("from_user_id", ""),
                        "text": text,
                        "context_token": msg.get("context_token", ""),
                        "timestamp": time.time(),
                    })
            return messages

        except httpx.ReadTimeout:
            return []  # 正常超时（35s 无消息）
        except Exception as e:
            logger.warning(f"[iLink] 轮询错误: {e}")
            await asyncio.sleep(3)
            return []

    # ── 消息处理循环 ──

    def set_message_handler(self, handler: Callable):
        """设置消息回调：async def handler(from_user, text, context_token)"""
        self._on_message = handler

    async def start_polling(self):
        """启动消息轮询"""
        if not self._token:
            logger.warning("[iLink] 未绑定微信，跳过轮询")
            return
        if self._running:
            return

        self._running = True
        logger.info("[iLink] 开始消息轮询...")

        while self._running:
            try:
                messages = await self._poll_once()
                for msg in messages:
                    logger.info(f"[iLink] 收到消息: {msg['text'][:50]}")
                    if self._on_message:
                        try:
                            await self._on_message(
                                msg["from_user"],
                                msg["text"],
                                msg["context_token"],
                            )
                        except Exception as e:
                            logger.error(f"[iLink] 消息处理错误: {e}")
                            # 发送错误提示给用户
                            await self.send_text(
                                msg["from_user"],
                                f"抱歉，处理出错了：{str(e)[:100]}",
                                msg["context_token"],
                            )
            except Exception as e:
                logger.error(f"[iLink] 轮询循环错误: {e}")
                await asyncio.sleep(5)

    def stop_polling(self):
        """停止轮询"""
        self._running = False
        if self._client:
            asyncio.create_task(self._client.aclose())
            self._client = None
        logger.info("[iLink] 轮询已停止")

    def disconnect(self):
        """断开连接"""
        self.stop_polling()
        self._token = ""
        self._cursor = ""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        logger.info("[iLink] 已断开微信连接")

    def get_status(self) -> Dict:
        """获取连接状态"""
        return {
            "connected": self.is_connected,
            "running": self.is_running,
            "token_preview": self._token[:16] + "..." if self._token else "",
        }


# ── 全局实例 ──

_bot: Optional[ILinkBot] = None


def get_ilink_bot() -> ILinkBot:
    global _bot
    if _bot is None:
        _bot = ILinkBot()
    return _bot
