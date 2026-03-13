"""
Siri Shortcuts 桥接 — 通过 HTTP API 让 Siri 调用 OpenClaw。

原理：
  iOS/macOS 用户创建一个 Shortcut，内容为：
    1. 获取麦克风输入（或文本输入）
    2. 发送 HTTP POST 到 OpenClaw API
    3. 朗读返回的文字

配置步骤：
  1. OpenClaw 设置中开启 Siri 桥接（默认开启）
  2. 确保手机和电脑在同一局域网
  3. 在 iPhone 打开「快捷指令」→ 新建 → 添加以下操作
  4. 或直接下载预制的 .shortcut 文件导入

API 端点：
  POST /api/siri/chat
  Body: {"text": "用户说的话"} 或 {"audio": "base64编码音频"}
  Response: {"text": "AI回复", "audio_url": "..."}

  GET /api/siri/health
  Response: {"status": "ok", "version": "3.0.0"}
"""

import base64
import json
import time
from typing import Optional

from loguru import logger

from .manager import BaseBridge


class SiriBridge(BaseBridge):
    """
    Siri Shortcuts HTTP API bridge.

    Provides REST endpoints that Apple Shortcuts can call to interact
    with OpenClaw's AI assistant from any Apple device.
    """

    def __init__(
        self,
        api_token: str = "",
        enabled: bool = True,
    ):
        self.api_token = api_token
        self.enabled = enabled

    def verify_token(self, token: str) -> bool:
        if not self.api_token:
            return True
        return token == self.api_token

    async def send_text(self, text: str, title: str = "") -> bool:
        logger.debug(f"Siri bridge (outbound not applicable): {text[:50]}")
        return True

    @staticmethod
    def build_shortcut_config(host: str, port: int,
                              token: str = "") -> dict:
        """
        Generate the configuration that users need for their Shortcut.
        """
        base_url = f"http://{host}:{port}"
        return {
            "name": "OpenClaw AI 助手",
            "description": "通过 Siri 语音与 OpenClaw AI 对话",
            "api_url": f"{base_url}/api/siri/chat",
            "health_url": f"{base_url}/api/siri/health",
            "method": "POST",
            "headers": {
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            "body_template": {
                "text": "{{用户输入}}",
            },
            "setup_steps": [
                "1. 打开 iPhone「快捷指令」App",
                "2. 点击 + 新建快捷指令",
                "3. 添加操作「要求输入」→ 提示: 请说话",
                f"4. 添加操作「获取URL内容」→ URL: {base_url}/api/siri/chat",
                "5. 方法: POST, 请求体: JSON",
                '6. 键: text, 值: 「要求输入」的结果',
                "7. 添加操作「从字典中获取值」→ 键: text",
                "8. 添加操作「朗读文本」",
                "9. 完成！对 Siri 说「嘿 Siri，运行 OpenClaw」即可",
            ],
            "voice_steps": [
                "如需语音输入（更自然）：",
                "1. 将步骤3 替换为「录制音频」",
                "2. 添加「将音频编码为 Base64」",
                '3. 步骤6 改为键: audio, 值: Base64 结果',
            ],
        }

    @staticmethod
    def build_shortcut_url(host: str, port: int) -> str:
        """
        Build an Apple Shortcuts import URL.
        Users open this in Safari to auto-import the shortcut.
        """
        return (
            f"http://{host}:{port}/api/siri/shortcut.html"
        )
