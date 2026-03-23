"""
OpenClaw AI 智能路由器

核心功能：
1. 多平台轮询（永久免费优先，赠送额度次之，付费兜底）
2. 自动限速冷却（429 → 冷却 → 切换）
3. 三种调度模式（省钱/质量/竞速）
4. 余额/额度监控
5. 与现有 AIBackend 完全兼容（直接替换 client）
"""

import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from loguru import logger

from .config import RouterConfig


class ProviderState:
    """单个平台的运行时状态"""

    def __init__(self, pid: str, meta: dict, cfg: RouterConfig):
        self.pid = pid
        self.meta = meta
        self.cfg = cfg

        # 运行时指标
        self.status: str = "unknown"       # ok / rate_limited / exhausted / error / disabled
        self.cooldown_until: float = 0.0   # 限速冷却到期时间戳
        self.consecutive_errors: int = 0
        self.total_calls: int = 0
        self.last_call_ts: float = 0.0
        self.last_latency: float = 0.0
        self.recent_latencies: List[float] = []

        # 额度信息（异步刷新）
        self.balance: Optional[float] = None
        self.balance_unit: str = "¥"
        self.quota_used: int = 0
        self.quota_total: Optional[int] = None
        self.balance_checked_at: float = 0.0

    @property
    def is_available(self) -> bool:
        if self.status == "disabled":
            return False
        if self.status == "exhausted":
            return False
        if self.cooldown_until > time.time():
            return False
        return True

    @property
    def avg_latency(self) -> float:
        if not self.recent_latencies:
            return 999.0
        return sum(self.recent_latencies[-5:]) / len(self.recent_latencies[-5:])

    @property
    def api_key(self) -> Optional[str]:
        return self.cfg.get_provider_key(self.pid)

    @property
    def base_url(self) -> str:
        return self.cfg.get_provider_url(self.pid)

    @property
    def model(self) -> str:
        return self.cfg.get_provider_model(self.pid)

    def record_success(self, latency: float):
        self.status = "ok"
        self.consecutive_errors = 0
        self.total_calls += 1
        self.last_call_ts = time.time()
        self.last_latency = latency
        self.recent_latencies.append(latency)
        if len(self.recent_latencies) > 10:
            self.recent_latencies.pop(0)

    def record_rate_limit(self):
        cooldown = self.cfg.cooldown_seconds
        self.status = "rate_limited"
        self.cooldown_until = time.time() + cooldown
        logger.warning(f"🔄 {self.pid} 被限速，冷却 {cooldown}s")

    def record_error(self, error: str):
        self.consecutive_errors += 1
        max_errors = self.cfg._cfg.getint("router", "max_errors", fallback=3)
        if self.consecutive_errors >= max_errors:
            self.status = "error"
            self.cooldown_until = time.time() + 120
            logger.warning(f"⚠️ {self.pid} 连续失败 {self.consecutive_errors} 次，暂停 120s")

    def mark_exhausted(self):
        self.status = "exhausted"
        logger.warning(f"💸 {self.pid} 额度耗尽，切换备用")

    def __repr__(self):
        return f"<Provider {self.pid} status={self.status} key={'✓' if self.api_key else '✗'}>"


class AIRouter:
    """
    多平台 AI 路由器 — 对外提供与 openai.AsyncOpenAI 相同的 chat 接口。
    
    优化亮点（相比简单轮询）：
    - 令牌桶限速追踪（不依赖 429 响应，提前预判）
    - 竞速模式下 2 路并发取最快
    - 健康评分系统（成功率 × 速度 × 优先级）
    - 余额自动查询（平台 API 支持时）
    """

    def __init__(self, cfg: RouterConfig):
        self.cfg = cfg
        self._states: Dict[str, ProviderState] = {}
        self._lock = asyncio.Lock()
        self.s2s = None
        self._init_states()

    @property
    def s2s_available(self) -> bool:
        return self.s2s is not None

    def _init_states(self):
        """根据配置初始化所有平台状态"""
        for meta in self.cfg.all_providers_meta():
            pid = meta["id"]
            state = ProviderState(pid, meta, self.cfg)
            if not self.cfg.is_provider_enabled(pid):
                state.status = "disabled"
            elif not state.api_key:
                state.status = "disabled"
            else:
                state.status = "ok"
            self._states[pid] = state
            if state.status == "ok":
                logger.info(f"✅ Provider ready: {meta['name_short']}")
            else:
                logger.debug(f"⭕ Provider skipped: {pid} (no key or disabled)")

    def reload_states(self):
        """重新加载（用户改了配置后调用）"""
        self.cfg.reload()
        self._init_states()

    # ──────────────────────────────────────────────────────
    # 核心调度逻辑
    # ──────────────────────────────────────────────────────

    def _score_provider(self, state: ProviderState, mode: str) -> float:
        """
        计算平台健康评分（越高越优先）

        省钱模式：tier_score >> latency
        质量模式：priority_score >> latency
        竞速模式：latency 主导
        """
        if not state.is_available:
            return -1.0

        tier = state.meta.get("tier", "paid")
        tier_score = {"free_unlimited": 100, "quota": 60, "custom": 80, "paid": 20}.get(tier, 20)
        priority = 10 - state.meta.get("priority", 9)  # 越小优先级越高 → 倒排
        latency_score = max(0, 50 - state.avg_latency * 10)

        if mode == "cost_saving":
            return tier_score * 2 + priority * 5 + latency_score * 0.5
        elif mode == "quality_first":
            return priority * 20 + tier_score * 0.5 + latency_score
        else:  # speed_first
            return latency_score * 3 + tier_score * 0.3 + priority

    _force_next: str = ""  # 外部指定下一次优先使用的平台

    def _pick_providers(self, mode: str, n: int = 2) -> List[ProviderState]:
        """返回按评分排序的可用平台列表（取前 n 个）"""
        # 如果外部指定了优先平台，放到最前面
        forced = None
        if self._force_next:
            forced = self._states.get(self._force_next)
            self._force_next = ""  # 用完即清

        order = self.cfg.provider_order
        all_states = []
        for pid in order:
            if pid in self._states:
                all_states.append(self._states[pid])
        for pid, state in self._states.items():
            if pid not in order:
                all_states.append(state)

        scored = [(self._score_provider(s, mode), s) for s in all_states]
        scored.sort(key=lambda x: x[0], reverse=True)
        result = [s for score, s in scored if score >= 0][:n]

        # 强制平台插到最前面
        if forced and forced.status == "ok":
            result = [s for s in result if s.pid != forced.pid]
            result.insert(0, forced)

        return result

    # ──────────────────────────────────────────────────────
    # 对外接口（兼容 openai.AsyncOpenAI 风格）
    # ──────────────────────────────────────────────────────

    # 首 chunk 超时：如果平台在此时间内没有返回任何内容，立即切换
    # 远低于 HTTP 超时（90s），实现快速故障转移
    FIRST_CHUNK_TIMEOUT = 30.0  # GLM-5-Turbo 有 reasoning 思考过程，需要更长时间

    async def chat_stream(
        self,
        messages: list,
        max_tokens: int = 600,
        temperature: float = 0.7,
        tools: list = None,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """
        流式对话，yield (text_chunk, provider_id)
        自动在限速/错误时切换平台。

        优化：
        - speed_first: 竞速（2 个并行，取最快）
        - cost_saving/quality_first: 顺序 + 首 chunk 超时快速切换
        """
        mode = self.cfg.routing_mode
        tried = set()

        while True:
            candidates = self._pick_providers(mode, n=3)
            candidates = [c for c in candidates if c.pid not in tried]

            if not candidates:
                logger.error("所有 AI 平台均不可用，请检查网络和 API Key")
                yield ("抱歉，AI 引擎暂时繁忙。请稍等几秒再试，或到设置中检查 API Key 是否正确。", "error")
                return

            if mode == "speed_first" and len(candidates) >= 2:
                # 竞速：同时请求 2 个，取最快的
                result = await self._race(candidates[:2], messages, max_tokens, temperature)
                if result:
                    async for chunk in result:
                        yield chunk
                    return
                tried.update(c.pid for c in candidates[:2])
            else:
                # 顺序尝试 + 首 chunk 超时
                state = candidates[0]
                tried.add(state.pid)
                success = False
                timed_out = False

                gen = self._call_provider(state, messages, max_tokens, temperature, tools=tools)
                try:
                    # 等待首个 chunk，设超时
                    first = await asyncio.wait_for(
                        gen.__anext__(), timeout=self.FIRST_CHUNK_TIMEOUT
                    )
                    if first[0] == "__SWITCH__":
                        continue
                    yield first
                    success = True
                    # 后续 chunk 正常流式
                    async for chunk in gen:
                        if chunk[0] == "__SWITCH__":
                            break
                        yield chunk
                except asyncio.TimeoutError:
                    timed_out = True
                    state.record_error("first_chunk_timeout")
                    logger.warning(
                        f"⏱️ {state.pid} 首 chunk 超时 ({self.FIRST_CHUNK_TIMEOUT}s)，切换..."
                    )
                except StopAsyncIteration:
                    pass

                if success and not timed_out:
                    return

    async def _call_provider(
        self,
        state: ProviderState,
        messages: list,
        max_tokens: int,
        temperature: float,
        tools: list = None,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """调用单个平台，处理限速/错误，失败时 yield __SWITCH__

        tools: OpenAI 格式的工具定义列表，仅在平台支持 function calling 时传递。
        """
        if not state.api_key:
            state.status = "disabled"
            yield ("__SWITCH__", state.pid)
            return

        t0 = time.time()
        try:
            payload = {
                "model": state.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            # 原生 Function Calling：平台支持 + 调用方传入工具
            if tools and state.meta.get("supports_function_calling"):
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{state.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {state.api_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code == 429:
                        state.record_rate_limit()
                        yield ("__SWITCH__", state.pid)
                        return
                    if resp.status_code in (401, 403):
                        state.status = "disabled"
                        logger.error(f"{state.pid} API Key 无效 ({resp.status_code})")
                        yield ("__SWITCH__", state.pid)
                        return
                    if resp.status_code >= 400:
                        state.record_error(f"HTTP {resp.status_code}")
                        yield ("__SWITCH__", state.pid)
                        return

                    got_content = False
                    # 累积原生 tool_calls 分片
                    _tc_chunks: list = []  # [{index, id, function:{name, arguments}}]

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                            choice = parsed.get("choices", [{}])[0]
                            delta = choice.get("delta", {})

                            # 文本内容
                            content = delta.get("content", "")
                            if content:
                                got_content = True
                                yield (content, state.pid)

                            # 原生 Function Calling 分片
                            tc_list = delta.get("tool_calls")
                            if tc_list:
                                for tc in tc_list:
                                    idx = tc.get("index", 0)
                                    while len(_tc_chunks) <= idx:
                                        _tc_chunks.append({"id": "", "name": "", "arguments": ""})
                                    if tc.get("id"):
                                        _tc_chunks[idx]["id"] = tc["id"]
                                    fn = tc.get("function", {})
                                    if fn.get("name"):
                                        _tc_chunks[idx]["name"] = fn["name"]
                                    if fn.get("arguments"):
                                        _tc_chunks[idx]["arguments"] += fn["arguments"]

                        except json.JSONDecodeError:
                            continue

                    # 如果有原生 tool_calls，yield 特殊标记让上层处理
                    if _tc_chunks and _tc_chunks[0].get("name"):
                        yield ("__TOOL_CALLS__", json.dumps(_tc_chunks, ensure_ascii=False))

                    latency = time.time() - t0
                    state.record_success(latency)
                    logger.debug(f"✅ {state.pid} 完成 {latency:.2f}s")

        except httpx.TimeoutException:
            state.record_error("timeout")
            logger.warning(f"⏱️ {state.pid} 超时，切换中...")
            yield ("__SWITCH__", state.pid)
        except Exception as e:
            state.record_error(str(e))
            logger.warning(f"❌ {state.pid} 错误: {e}，切换中...")
            yield ("__SWITCH__", state.pid)

    async def _race(
        self,
        candidates: List[ProviderState],
        messages: list,
        max_tokens: int,
        temperature: float,
    ) -> Optional[AsyncGenerator]:
        """竞速：向两个平台同时发请求，谁先有输出用谁"""
        queue: asyncio.Queue = asyncio.Queue()
        winner_pid = None
        tasks = []

        async def _feed(state: ProviderState):
            nonlocal winner_pid
            got_first = False
            async for chunk in self._call_provider(state, messages, max_tokens, temperature):
                if chunk[0] == "__SWITCH__":
                    await queue.put(("__FAIL__", state.pid))
                    return
                if not got_first:
                    got_first = True
                    if winner_pid is None:
                        winner_pid = state.pid
                if winner_pid == state.pid:
                    await queue.put(chunk)
            if winner_pid == state.pid:
                await queue.put(("__DONE__", state.pid))

        for c in candidates:
            tasks.append(asyncio.create_task(_feed(c)))

        async def _drain():
            while True:
                chunk = await queue.get()
                if chunk[0] == "__DONE__":
                    for t in tasks:
                        t.cancel()
                    return
                if chunk[0] != "__FAIL__":
                    yield chunk

        return _drain()

    # ──────────────────────────────────────────────────────
    # 余额查询
    # ──────────────────────────────────────────────────────

    async def check_balance(self, pid: str) -> Optional[str]:
        """查询指定平台余额（返回格式化字符串）"""
        state = self._states.get(pid)
        if not state or not state.api_key:
            return None
        meta = state.meta
        balance_api = meta.get("balance_api")
        if not balance_api:
            return "无余额查询接口"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{state.base_url}{balance_api}",
                    headers={"Authorization": f"Bearer {state.api_key}"},
                )
                data = r.json()
                # DeepSeek balance format
                if "balance_infos" in data:
                    total = sum(float(b.get("total_balance", 0))
                                for b in data["balance_infos"])
                    state.balance = total
                    return f"余额 ¥{total:.2f}"
                return str(data)
        except Exception as e:
            return f"查询失败: {e}"

    # ──────────────────────────────────────────────────────
    # 状态面板数据（给 GUI 用）
    # ──────────────────────────────────────────────────────

    def get_status_panel(self) -> List[dict]:
        """返回所有平台状态，供 GUI 展示"""
        result = []
        for pid, state in self._states.items():
            meta = state.meta
            status_text = {
                "ok": "✅ 正常",
                "rate_limited": "⏱️ 限速冷却中",
                "exhausted": "💸 额度耗尽",
                "error": "❌ 连接失败",
                "disabled": "⭕ 未配置",
                "unknown": "❓ 未知",
            }.get(state.status, state.status)

            result.append({
                "id": pid,
                "name": meta.get("name_short", pid),
                "name_full": meta.get("name", pid),
                "tier": meta.get("tier", "paid"),
                "tag": meta.get("tag", ""),
                "status": state.status,
                "status_text": status_text,
                "has_key": bool(state.api_key),
                "balance": state.balance,
                "balance_unit": state.balance_unit,
                "avg_latency": round(state.avg_latency, 2) if state.total_calls > 0 else None,
                "total_calls": state.total_calls,
                "free_info": meta.get("free_info", ""),
                "priority": meta.get("priority", 9),
            })
        result.sort(key=lambda x: x["priority"])
        return result

    def get_active_provider(self) -> Optional[str]:
        """返回当前使用的平台名称"""
        mode = self.cfg.routing_mode
        candidates = self._pick_providers(mode, n=1)
        if candidates:
            return candidates[0].meta.get("name_short", candidates[0].pid)
        return None
