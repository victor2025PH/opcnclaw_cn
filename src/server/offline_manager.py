# -*- coding: utf-8 -*-
"""
离线模式管理器 — 网络断开时自动切换到本地 AI

策略：
  - 每 30s 心跳检测外网连通性（不请求需鉴权的 AI /models，避免无 Token 时固定 401 污染日志）
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
    # 仅用「无需 Bearer 即可 2xx/3xx」的地址测公网；勿对智谱/DeepSeek 的 /models 发无鉴权请求（会 401，与 Key 是否正常无关）
    PING_URLS = [
        "https://www.baidu.com",
        "https://www.qq.com",
        "https://www.microsoft.com",
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
        """检测本机是否能访问公网（HTTPS）。不调用智谱/DeepSeek API，以免无 Key 时误报 401。"""
        for url in self.PING_URLS:
            try:
                with httpx.Client(
                    timeout=self.PING_TIMEOUT,
                    follow_redirects=True,
                ) as client:
                    r = client.head(url)
                    if r.status_code < 500:
                        return True
                    # 部分站点对 HEAD 返回 405/404，再试 GET
                    if r.status_code in (404, 405):
                        r = client.get(url)
                        if r.status_code < 500:
                            return True
            except Exception:
                continue
        return False

    def _check_ollama(self) -> bool:
        """检测本地 Ollama 是否可用"""
        import os
        if os.environ.get("OPENCLAW_OLLAMA_ENABLED", "false").lower() not in (
            "1", "true", "yes", "on",
        ):
            self._ollama_available = False
            self._local_model = ""
            return False
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

        # 与路由器集成：断网时强制切到 Ollama
        try:
            from src.server.main import backend
            if backend and backend._router:
                if new == NetworkMode.LOCAL and self._local_model:
                    # 强制路由器下次使用 Ollama
                    if "ollama" in backend._router._states:
                        backend._router._force_next = "ollama"
                        logger.info(f"[Offline] 路由器已切换到 Ollama: {self._local_model}")
                elif new == NetworkMode.ONLINE:
                    # 恢复正常路由
                    backend._router._force_next = ""
                    logger.info("[Offline] 路由器恢复正常云端调度")
        except Exception as e:
            logger.debug(f"[Offline] Router integration: {e}")

    def get_tts_provider(self) -> str:
        """根据网络状态返回推荐的 TTS 引擎

        降级链：配置的 TTS → Edge TTS → pyttsx3 → disabled
        """
        import os
        if self.is_online:
            return os.environ.get("TTS_PROVIDER", "edge_tts")
        # 离线时 Edge TTS 不可用（需要网络），降级到 pyttsx3
        try:
            import pyttsx3
            return "pyttsx3"
        except ImportError:
            logger.warning("[Offline] pyttsx3 未安装，离线 TTS 不可用")
            return "disabled"

    def should_force_ollama(self) -> bool:
        """路由器辅助：当前是否应该强制 Ollama"""
        return self._mode == NetworkMode.LOCAL and self._ollama_available


# ── 全局单例 ──────────────────────────────────────────────────

_manager: Optional[OfflineManager] = None


def get_offline_manager() -> OfflineManager:
    global _manager
    if _manager is None:
        _manager = OfflineManager()
        _manager.start()
    return _manager
