# -*- coding: utf-8 -*-
"""
Ollama 本地模型桥接器

职责：
  1. 自动检测 Ollama 是否运行 + 自动启用/停用
  2. 模型管理（列举/拉取/删除）
  3. 智能任务路由 — 轻量任务走本地、重量任务走云端
  4. 健康监控 + 性能基准测试

架构优化思考：
  不直接调用 Ollama Python SDK，而是复用现有 AIRouter 的 httpx 通道。
  Ollama 本身暴露 OpenAI-compatible 的 /v1 端点，
  所以只需确保 router 中 ollama provider 被正确启用即可。
  本模块提供的是"围绕 router 的增值层"。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import httpx
from loguru import logger


OLLAMA_BASE = "http://localhost:11434"
OLLAMA_V1 = f"{OLLAMA_BASE}/v1"


class TaskWeight(str, Enum):
    """任务权重分级"""
    LIGHT = "light"      # 意图分类、关键词提取、简单判断
    MEDIUM = "medium"    # 普通对话、评论生成、摘要
    HEAVY = "heavy"      # 长文生成、复杂推理、内容日历规划
    VISION = "vision"    # 图像理解


@dataclass
class OllamaModel:
    name: str
    size: str = ""
    parameter_size: str = ""
    quantization: str = ""
    modified_at: str = ""
    digest: str = ""


@dataclass
class OllamaHealth:
    available: bool = False
    version: str = ""
    models: List[OllamaModel] = field(default_factory=list)
    gpu_info: str = ""
    last_check: float = 0
    latency_ms: float = 0
    error: str = ""


class OllamaBridge:
    """
    Ollama 本地模型桥接器

    用法：
        bridge = OllamaBridge()
        await bridge.check_health()
        if bridge.is_available:
            bridge.auto_enable_in_router(router_config)
    """

    def __init__(self, base_url: str = OLLAMA_BASE):
        self._base = base_url
        self._v1 = f"{base_url}/v1"
        self._health = OllamaHealth()
        self._client = httpx.AsyncClient(timeout=2)  # 快速检测：Ollama 在本机，2s 足够
        self._benchmark_results: Dict[str, float] = {}

    @property
    def is_available(self) -> bool:
        return self._health.available

    @property
    def health(self) -> OllamaHealth:
        return self._health

    @property
    def models(self) -> List[OllamaModel]:
        return self._health.models

    async def check_health(self) -> OllamaHealth:
        """探测 Ollama 是否运行，获取版本和已安装模型列表"""
        start = time.time()
        try:
            resp = await self._client.get(f"{self._base}/api/version")
            if resp.status_code == 200:
                data = resp.json()
                self._health.available = True
                self._health.version = data.get("version", "unknown")
                self._health.latency_ms = (time.time() - start) * 1000
                self._health.error = ""
                await self._load_models()
            else:
                self._health.available = False
                self._health.error = f"HTTP {resp.status_code}"
        except Exception as e:
            self._health.available = False
            self._health.error = str(e)
            self._health.models = []

        self._health.last_check = time.time()
        return self._health

    async def _load_models(self):
        """加载已安装的模型列表"""
        try:
            resp = await self._client.get(f"{self._base}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                self._health.models = []
                for m in data.get("models", []):
                    details = m.get("details", {})
                    self._health.models.append(OllamaModel(
                        name=m.get("name", ""),
                        size=_format_size(m.get("size", 0)),
                        parameter_size=details.get("parameter_size", ""),
                        quantization=details.get("quantization_level", ""),
                        modified_at=m.get("modified_at", ""),
                        digest=m.get("digest", "")[:12],
                    ))
        except Exception as e:
            logger.debug(f"Ollama load models failed: {e}")

    async def pull_model(self, name: str, progress_cb: Callable = None) -> bool:
        """拉取模型（支持进度回调）"""
        try:
            async with self._client.stream(
                "POST", f"{self._base}/api/pull",
                json={"name": name}, timeout=None
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    import json
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if progress_cb:
                            total = data.get("total", 0)
                            completed = data.get("completed", 0)
                            pct = (completed / total * 100) if total else 0
                            progress_cb(status, pct)
                    except Exception:
                        pass

            await self._load_models()
            return True
        except Exception as e:
            logger.error(f"Ollama pull {name} failed: {e}")
            return False

    async def delete_model(self, name: str) -> bool:
        """删除模型"""
        try:
            resp = await self._client.delete(
                f"{self._base}/api/delete",
                json={"name": name}
            )
            if resp.status_code == 200:
                await self._load_models()
                return True
            return False
        except Exception as e:
            logger.error(f"Ollama delete {name} failed: {e}")
            return False

    async def benchmark(self, model: str = "") -> Dict:
        """快速基准测试：测量首 token 延迟和吞吐量"""
        if not self._health.available:
            return {"error": "Ollama not available"}

        model = model or self._pick_default_model()
        if not model:
            return {"error": "No model available"}

        test_prompt = "请用一句话介绍你自己。"
        try:
            start = time.time()
            first_token_time = 0
            total_tokens = 0

            async with self._client.stream(
                "POST", f"{self._base}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": test_prompt}],
                    "stream": True,
                    "max_tokens": 100,
                },
                timeout=30
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    import json
                    try:
                        chunk = json.loads(payload)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if delta.get("content"):
                            if first_token_time == 0:
                                first_token_time = time.time() - start
                            total_tokens += 1
                    except Exception:
                        pass

            elapsed = time.time() - start
            result = {
                "model": model,
                "first_token_ms": round(first_token_time * 1000),
                "total_ms": round(elapsed * 1000),
                "tokens": total_tokens,
                "tokens_per_second": round(total_tokens / elapsed, 1) if elapsed > 0 else 0,
            }
            self._benchmark_results[model] = result["tokens_per_second"]
            return result
        except Exception as e:
            return {"error": str(e), "model": model}

    def auto_enable_in_router(self, router_config) -> bool:
        """
        自动在路由器中启用/停用 Ollama provider。
        如果 Ollama 可用且有模型，自动启用并设置 API key。
        """
        if not self._health.available or not self._health.models:
            router_config.set_provider_enabled("ollama", False)
            return False

        default_model = self._pick_default_model()
        router_config.set_provider_enabled("ollama", True)
        router_config.set_provider_key("ollama", "ollama")
        if default_model:
            router_config.set_provider_model("ollama", default_model)
        router_config.set_provider_url("ollama", self._v1)

        current_order = router_config.provider_order
        if "ollama" not in current_order:
            current_order.insert(0, "ollama")
            section = "providers"
            if not router_config._cfg.has_section(section):
                router_config._cfg.add_section(section)
            router_config._cfg[section]["order"] = ",".join(current_order)

        router_config.save()
        logger.info(f"Ollama 已自动启用 (model: {default_model})")
        return True

    def _pick_default_model(self) -> str:
        """选择最佳默认模型"""
        prefer = ["qwen2.5:7b", "qwen2.5:3b", "qwen2.5:1.5b",
                   "deepseek-r1:7b", "gemma3:4b", "llama3.2:3b", "phi4:14b"]
        model_names = {m.name for m in self._health.models}
        for p in prefer:
            if p in model_names:
                return p
        return self._health.models[0].name if self._health.models else ""

    def get_status(self) -> Dict:
        return {
            "available": self._health.available,
            "version": self._health.version,
            "models": [
                {"name": m.name, "size": m.size, "params": m.parameter_size,
                 "quant": m.quantization}
                for m in self._health.models
            ],
            "latency_ms": round(self._health.latency_ms, 1),
            "error": self._health.error,
            "benchmarks": self._benchmark_results,
        }

    async def close(self):
        await self._client.aclose()


# ── 智能任务路由器 ─────────────────────────────────────────────────────────────

class SmartTaskRouter:
    """
    智能任务路由：根据任务权重自动选择本地/云端模型。

    核心思想：
      - LIGHT 任务（意图分类等）→ 优先 Ollama（零成本、低延迟）
      - MEDIUM 任务（对话回复等）→ Ollama 可用时用 Ollama，否则云端
      - HEAVY 任务（长文生成等）→ 始终走云端（质量优先）
      - VISION 任务 → 始终走 Zhipu Vision

    使用：
        router = SmartTaskRouter(ai_backend)
        result = await router.route(messages, weight=TaskWeight.LIGHT)
    """

    def __init__(self, ai_backend=None, ollama_bridge: OllamaBridge = None):
        self._backend = ai_backend
        self._bridge = ollama_bridge
        self._ollama_client = None
        self._stats = {"local": 0, "cloud": 0, "vision": 0}

    async def route(
        self,
        messages: list,
        weight: TaskWeight = TaskWeight.MEDIUM,
        max_tokens: int = 600,
        temperature: float = 0.7,
    ) -> str:
        """根据权重路由到最佳模型"""

        if weight == TaskWeight.VISION:
            self._stats["vision"] += 1
            return await self._call_cloud(messages, max_tokens, temperature)

        if weight == TaskWeight.HEAVY:
            self._stats["cloud"] += 1
            return await self._call_cloud(messages, max_tokens, temperature)

        if self._bridge and self._bridge.is_available:
            if weight == TaskWeight.LIGHT:
                result = await self._call_local(messages, max_tokens=200, temperature=0.3)
                if result:
                    self._stats["local"] += 1
                    return result

            if weight == TaskWeight.MEDIUM:
                result = await self._call_local(messages, max_tokens, temperature)
                if result:
                    self._stats["local"] += 1
                    return result

        self._stats["cloud"] += 1
        return await self._call_cloud(messages, max_tokens, temperature)

    async def _call_local(self, messages: list, max_tokens: int, temperature: float) -> str:
        """调用 Ollama 本地模型"""
        if not self._bridge or not self._bridge.is_available:
            return ""

        model = self._bridge._pick_default_model()
        if not model:
            return ""

        try:
            if not self._ollama_client:
                self._ollama_client = httpx.AsyncClient(timeout=30)

            resp = await self._ollama_client.post(
                f"{self._bridge._v1}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": False,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            return ""
        except Exception as e:
            logger.debug(f"Ollama local call failed: {e}")
            return ""

    async def _call_cloud(self, messages: list, max_tokens: int, temperature: float) -> str:
        """走 AIBackend 的 chat_simple（通过 AI Router 路由到云端）"""
        if self._backend:
            try:
                return await self._backend.chat_simple(messages)
            except Exception as e:
                logger.warning(f"Cloud call failed: {e}")
                return ""
        return ""

    def get_stats(self) -> Dict:
        total = sum(self._stats.values())
        return {
            **self._stats,
            "total": total,
            "local_ratio": f"{self._stats['local']/total*100:.0f}%" if total else "0%",
        }


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1e9:
        return f"{size_bytes/1e9:.1f}GB"
    if size_bytes >= 1e6:
        return f"{size_bytes/1e6:.0f}MB"
    return f"{size_bytes/1e3:.0f}KB"
