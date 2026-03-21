# -*- coding: utf-8 -*-
"""
离线模式管理器 — 网络断开时自动切换到本地 AI

策略：
  - 每 30s 心跳检测网络连通性（ping AI 平台）
  - 有网 → 云端 AI（智谱/DeepSeek）
  - 断网 → 本地 Ollama（qwen2.5:7b）
  - 网络恢复 → 自动切回云端
  - TTS 降级：Edge TTS → pyttsx3

状态机：
  ONLINE → CHECKING → OFFLINE → CHECKING → ONLINE
"""

from __future__ import annotations

import asyncio
import threading
import time
from enum import Enum
from typing import Optional

import httpx
from loguru import logger


class NetworkMode(str, Enum):
    ONLINE = "online"           # 云端 AI 可用
    LOCAL = "local"             # 断网，使用本地 Ollama
    OFFLINE = "offline"         # 断网且无本地模型


class OfflineManager:
    """网络状态管理 + 自动切换"""

    CHECK_INTERVAL = 30.0       # 检测间隔（秒）
    PING_TIMEOUT = 5.0          # ping 超时
    PING_URLS = [
        "https://open.bigmodel.cn/api/paas/v4/models",  # 智谱
        "https://api.deepseek.com/v1/models",            # DeepSeek
        "https://www.baidu.com",                         # 通用
    ]

    def __init__(self):
        self._mode = NetworkMode.ONLINE
        self._last_check = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ollama_available = False
        self._local_model = ""
        self._listeners = []

    @property
    def mode(self) -> NetworkMode:
        return self._mode

    @property
    def is_online(self) -> bool:
        return self._mode == NetworkMode.ONLINE

    @property
    def local_model(self) -> str:
        return self._local_model

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, daemon=True, name="OfflineManager")
        self._thread.start()
        logger.info("[Offline] 网络检测已启动")

    def stop(self):
        self._running = False

    def on_mode_change(self, callback):
        """注册模式变化回调"""
        self._listeners.append(callback)

    def get_status(self) -> dict:
        return {
            "online": self.is_online,
            "mode": self._mode.value,
            "local_model": self._local_model,
            "ollama_available": self._ollama_available,
            "last_check": round(self._last_check, 1),
        }

    def _check_loop(self):
        # 首次立即检查
        self._do_check()
        while self._running:
            time.sleep(self.CHECK_INTERVAL)
            self._do_check()

    def _do_check(self):
        """检测网络 + Ollama 状态"""
        self._last_check = time.time()
        online = self._ping_network()
        ollama = self._check_ollama()

        old_mode = self._mode

        if online:
            self._mode = NetworkMode.ONLINE
        elif ollama:
            self._mode = NetworkMode.LOCAL
        else:
            self._mode = NetworkMode.OFFLINE

        if self._mode != old_mode:
            logger.info(f"[Offline] 模式切换: {old_mode.value} → {self._mode.value}")
            self._notify(old_mode, self._mode)

            # 通过 EventBus 发布
            try:
                from .event_bus import publish
                publish("network_mode_change", {
                    "old": old_mode.value,
                    "new": self._mode.value,
                    "local_model": self._local_model,
                })
            except Exception:
                pass

    def _ping_network(self) -> bool:
        """ping 任意一个 AI 平台检测网络"""
        for url in self.PING_URLS:
            try:
                with httpx.Client(timeout=self.PING_TIMEOUT) as client:
                    r = client.head(url)
                    if r.status_code < 500:
                        return True
            except Exception:
                continue
        return False

    def _check_ollama(self) -> bool:
        """检测本地 Ollama 是否可用"""
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get("http://localhost:11434/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    self._ollama_available = True
                    # 优先使用 qwen2.5
                    for m in models:
                        if "qwen" in m.lower():
                            self._local_model = m
                            return True
                    if models:
                        self._local_model = models[0]
                        return True
        except Exception:
            pass
        self._ollama_available = False
        self._local_model = ""
        return False

    def _notify(self, old: NetworkMode, new: NetworkMode):
        for cb in self._listeners:
            try:
                cb(old, new)
            except Exception:
                pass


# ── 全局单例 ──────────────────────────────────────────────────

_manager: Optional[OfflineManager] = None


def get_offline_manager() -> OfflineManager:
    global _manager
    if _manager is None:
        _manager = OfflineManager()
        _manager.start()
    return _manager
