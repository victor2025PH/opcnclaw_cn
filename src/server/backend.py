"""
AI Backend module - connects to OpenAI, OpenClaw gateway, or custom backends.
v2.0: 集成 AI 路由器（多平台轮询）+ 技能引擎（技能优先执行）
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, List, Dict, AsyncGenerator

from loguru import logger

# 确保项目根目录在路径中（供独立运行时使用）
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Optional persistent memory (SQLite). Imported lazily to avoid circular deps.
try:
    from . import memory as _memory
    _MEMORY_ENABLED = True
except ImportError:
    _memory = None  # type: ignore
    _MEMORY_ENABLED = False

# Tool calling support
try:
    from .tools import call_tool, parse_tool_calls, TOOLS_SYSTEM_ADDENDUM
    _TOOLS_ENABLED = True
except ImportError:
    _TOOLS_ENABLED = False
    TOOLS_SYSTEM_ADDENDUM = ""
    def parse_tool_calls(text): return []
    async def call_tool(name, args): return "{}"

# Long-term memory (conversation compression + retrieval)
try:
    from .long_memory import build_memory_context, compress_old_messages
    _LONG_MEMORY_ENABLED = True
except ImportError:
    _LONG_MEMORY_ENABLED = False
    def build_memory_context(s, m, **kw): return ""
    async def compress_old_messages(s, **kw): return 0

# Topic tracking (conversation context continuity)
try:
    from .topic_tracker import get_tracker as _get_topic_tracker
    _TOPIC_TRACKING_ENABLED = True
except ImportError:
    _TOPIC_TRACKING_ENABLED = False
    def _get_topic_tracker(s): return None

# Intent prediction (proactive suggestions)
try:
    from .intent_predictor import get_predictor as _get_intent_predictor
    _INTENT_PREDICTION_ENABLED = True
except ImportError:
    _INTENT_PREDICTION_ENABLED = False
    def _get_intent_predictor(s): return None

# Knowledge base RAG (private document retrieval)
try:
    from .knowledge_base import build_rag_context
    _RAG_ENABLED = True
except ImportError:
    _RAG_ENABLED = False
    def build_rag_context(q, **kw): return ""

# Adaptive conversation style
try:
    from .adaptive_style import get_style_prompt
    _ADAPTIVE_STYLE_ENABLED = True
except ImportError:
    _ADAPTIVE_STYLE_ENABLED = False
    def get_style_prompt(**kw): return ""

# Context compressor (sliding window compression)
try:
    from .context_compressor import get_compressor
    _COMPRESSOR_ENABLED = True
except ImportError:
    _COMPRESSOR_ENABLED = False

# AI 路由器（可选，启用多平台轮询）
try:
    from src.router.config import RouterConfig
    from src.router.router import AIRouter
    _router_cfg = RouterConfig()
    _GLOBAL_ROUTER = AIRouter(_router_cfg)
    _ROUTER_ENABLED = True
    logger.info("✅ AI 路由器已加载")
except Exception as _re:
    _GLOBAL_ROUTER = None
    _ROUTER_ENABLED = False
    _router_cfg = None
    logger.debug(f"AI 路由器未加载（使用直接连接模式）: {_re}")

# 技能引擎（可选）
try:
    from skills._engine.executor import get_executor as _get_skill_executor
    _SKILLS_ENABLED = True
    logger.info("✅ 技能引擎已加载")
except Exception as _se:
    _get_skill_executor = None
    _SKILLS_ENABLED = False
    logger.debug(f"技能引擎未加载: {_se}")


class AIBackend:
    """AI backend for processing user messages."""
    
    def __init__(
        self,
        backend_type: str = "openai",
        url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        vision_api_key: Optional[str] = None,
        vision_model: str = "glm-4v-flash",
        vision_url: str = "https://open.bigmodel.cn/api/paas/v4",
        session_id: str = "default",
        enable_tools: bool = True,
    ):
        self.backend_type = backend_type
        self.url = url
        self.model = model
        self.api_key = api_key
        self.enable_tools = enable_tools and _TOOLS_ENABLED
        self.system_prompt = system_prompt or (
            "你是 OpenClaw 智能语音助手，回答要简洁口语化，1-2句话为主，"
            "除非用户明确要求详细说明。不使用 Markdown 格式，直接说话。"
        )
        # In-memory cache (populated from DB on first use)
        self._history_cache: Optional[List[Dict]] = None
        self.session_id = session_id
        self._client = None
        # 智谱视觉模型 — 仅在 image_b64 存在时使用
        self._vision_client = None
        self._vision_model = vision_model
        # AI 路由器 — 多平台轮询（优先使用）
        self._router: Optional["AIRouter"] = _GLOBAL_ROUTER if _ROUTER_ENABLED else None
        # 技能引擎 — 意图识别 + 工具执行
        self._skill_executor = _get_skill_executor() if _SKILLS_ENABLED else None
        self._setup_client()
        if vision_api_key:
            self._setup_vision_client(vision_api_key, vision_url)

    # ── Session / history helpers ──────────────────────────
    @property
    def conversation_history(self) -> List[Dict]:
        """Lazy-load history from SQLite on first access."""
        if self._history_cache is None:
            if _MEMORY_ENABLED:
                self._history_cache = _memory.get_history(self.session_id, limit=40)
            else:
                self._history_cache = []
        return self._history_cache

    @conversation_history.setter
    def conversation_history(self, value: List[Dict]):
        self._history_cache = value

    def _persist(self, role: str, content):
        """Write a single message to SQLite (best-effort)."""
        if _MEMORY_ENABLED:
            try:
                _memory.add_message(self.session_id, role, content)
            except Exception as e:
                logger.warning(f"Memory persist failed: {e}")
    
    def _setup_vision_client(self, api_key: str, url: str):
        """Set up the Zhipu vision client (OpenAI-compatible)."""
        try:
            from openai import AsyncOpenAI
            self._vision_client = AsyncOpenAI(
                api_key=api_key,
                base_url=url,
            )
            logger.info(f"✅ 智谱视觉客户端就绪 (model: {self._vision_model})")
        except ImportError:
            logger.error("openai package not installed, vision client unavailable")

    def _setup_client(self):
        """Set up the API client."""
        if self.backend_type == "openai":
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.url if self.url != "https://api.openai.com/v1" else None,
                )
                logger.info(f"✅ OpenAI client ready (model: {self.model})")
            except ImportError:
                logger.error("openai package not installed")
        elif self.backend_type == "openclaw":
            # OpenClaw gateway uses OpenAI-compatible API
            logger.info("OpenClaw gateway backend")
        else:
            logger.warning(f"Unknown backend type: {self.backend_type}")
    
    async def chat_simple(self, messages: list) -> str:
        """
        Non-streaming completion from a pre-built messages list.
        Used by wechat auto-reply engine (messages already include system prompt + history).
        """
        if self._router:
            try:
                full = ""
                async for chunk_text, provider_id in self._router.chat_stream(
                    messages, max_tokens=600, temperature=0.7
                ):
                    if chunk_text != "__SWITCH__":
                        full += chunk_text
                if full:
                    return full
            except Exception as e:
                logger.debug(f"chat_simple router fallback: {e}")

        if self._client:
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=600,
                    temperature=0.7,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"chat_simple error: {e}")
                return ""

        return ""

    async def chat(self, user_message: str) -> str:
        """
        Send a message and get a response.
        
        Args:
            user_message: The user's transcribed speech
            
        Returns:
            AI response text
        """
        if self.backend_type == "openai" and self._client:
            return await self._chat_openai(user_message)
        else:
            # Fallback echo response
            return f"I heard you say: {user_message}"
    
    async def chat_stream(self, user_message: str, image_b64: str = None) -> AsyncGenerator[str, None]:
        """
        Stream a response, yielding chunks as they arrive.
        Optionally includes a camera frame for multimodal vision.
        """
        if self.backend_type == "openai" and self._client:
            async for chunk in self._chat_openai_stream(user_message, image_b64=image_b64):
                yield chunk
        else:
            yield f"I heard you say: {user_message}"
    
    async def _chat_openai(self, user_message: str) -> str:
        """Chat via OpenAI API."""
        self.conversation_history.append({"role": "user", "content": user_message})
        self._persist("user", user_message)

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.conversation_history[-10:])

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=500,
                temperature=0.7,
            )
            assistant_message = response.choices[0].message.content
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            self._persist("assistant", assistant_message)
            return assistant_message
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return "Sorry, I had trouble processing that. Could you try again?"
    
    async def _chat_openai_stream(self, user_message: str, image_b64: str = None) -> AsyncGenerator[str, None]:
        """
        流式对话 v2.0

        执行流程：
        1. 有图像 → 智谱 GLM-4V（视觉专用）
        2. 无图像 → 技能引擎匹配（高置信度直接执行，注入结果给 AI 自然语言化）
        3. AI 回复 → 优先走路由器（多平台轮询），降级到直接 openai 客户端
        """
        # ── 1. 视觉路径 ──────────────────────────────────────────────
        if image_b64 and self._vision_client:
            async for chunk in self._chat_zhipu_vision_stream(user_message, image_b64):
                yield chunk
            return

        # ── 纯文字路径 ──────────────────────────────────────────────
        if image_b64:
            user_content = [
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                    "detail": "low",
                }},
            ]
        else:
            user_content = user_message

        self.conversation_history.append({"role": "user", "content": user_content})
        self._persist("user", user_content)

        system = self.system_prompt

        # 注入上一轮的意图预测建议
        if hasattr(self, '_pending_suggestion') and self._pending_suggestion:
            system += f"\n\n[提示] 根据对话模式预测，用户可能接下来想要：{self._pending_suggestion}。如果合适，你可以在回答末尾自然地提出这个建议。"
            self._pending_suggestion = None

        skill_context = None

        # ── 2. 技能引擎（无图像时优先匹配）──────────────────────────
        if not image_b64 and self._skill_executor:
            try:
                skill_result = await self._skill_executor.process(user_message)
                if skill_result:
                    skill_name, skill_context = skill_result
                    logger.info(f"🧩 技能命中: {skill_name}")
                    # 技能结果注入系统提示，AI 负责自然语言化
                    system = system + "\n\n" + skill_context
            except Exception as e:
                logger.debug(f"技能引擎处理失败: {e}")

        if not skill_context:
            if self.enable_tools:
                system = system + "\n\n" + TOOLS_SYSTEM_ADDENDUM
        if image_b64:
            system += "\n\n用户发送了摄像头画面。请结合图像内容来回答问题，说明你看到了什么。"

        # 长期记忆注入：检索与当前消息相关的历史摘要
        if _LONG_MEMORY_ENABLED and not image_b64:
            mem_ctx = build_memory_context(self.session_id, user_message)
            if mem_ctx:
                system = system + "\n\n" + mem_ctx

        # 话题跟踪：检测指代词/延续信号，注入当前话题上下文
        if _TOPIC_TRACKING_ENABLED and not image_b64:
            tracker = _get_topic_tracker(self.session_id)
            if tracker:
                topic_ctx = tracker.process_message("user", user_message)
                if topic_ctx:
                    system = system + "\n" + topic_ctx

        # 知识库 RAG：检索私有文档中的相关内容
        if _RAG_ENABLED and not image_b64:
            rag_ctx = build_rag_context(user_message, top_k=2)
            if rag_ctx:
                system = system + "\n\n" + rag_ctx

        # 自适应风格：根据时间+联系人+场景动态调整
        if _ADAPTIVE_STYLE_ENABLED and not image_b64:
            style = get_style_prompt(message=user_message)
            if style:
                system = system + "\n\n" + style

        messages = [{"role": "system", "content": system}]

        # 智能上下文压缩：替代硬截断 [-10:]
        if _COMPRESSOR_ENABLED and not image_b64 and len(self.conversation_history) > 10:
            try:
                import asyncio
                compressor = get_compressor()
                compressed = await compressor.compress(
                    self.conversation_history,
                    ai_call=self.chat_simple if hasattr(self, 'chat_simple') else None,
                )
                for msg in compressed:
                    if isinstance(msg.get("content"), list):
                        text = " ".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
                        messages.append({"role": msg["role"], "content": text})
                    else:
                        messages.append(msg)
            except Exception:
                for msg in self.conversation_history[-10:]:
                    if isinstance(msg.get("content"), list):
                        text = " ".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
                        messages.append({"role": msg["role"], "content": text})
                    else:
                        messages.append(msg)
        else:
            for msg in self.conversation_history[-10:]:
                if isinstance(msg.get("content"), list):
                    text = " ".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
                    messages.append({"role": msg["role"], "content": text})
                else:
                    messages.append(msg)

        if image_b64 and messages[-1]["role"] == "user":
            messages[-1]["content"] = user_content

        full_response = ""

        # ── 3a. 优先走路由器（多平台轮询）──────────────────────────
        router_ok = False
        if self._router:
            try:
                last_provider = None
                async for chunk_text, provider_id in self._router.chat_stream(
                    messages, max_tokens=600, temperature=0.7
                ):
                    if chunk_text == "__SWITCH__":
                        continue
                    full_response += chunk_text
                    yield chunk_text
                    last_provider = provider_id
                if last_provider:
                    logger.debug(f"路由器使用平台: {last_provider}")
                router_ok = True
            except Exception as e:
                logger.warning(f"路由器失败，降级到直连: {e}")

        # ── 3b. 降级：直接连接（路由器失败时）──────────────────────
        if not router_ok:
            if not self._client:
                yield "AI 客户端未配置，请在设置中填写 API Key。"
                return
            try:
                stream = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=600,
                    temperature=0.7,
                    stream=True,
                )
                async for chunk in stream:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_response += text
                        yield text
            except Exception as e:
                logger.error(f"OpenAI streaming error: {e}")
                yield "抱歉，处理时出现问题，请稍后再试。"
                return

        # ── 3c. Agent Loop — 多步工具调用（最多 5 轮）──────────────
        if self.enable_tools and not skill_context:
            agent_msgs = list(messages)
            for _loop in range(5):
                tool_calls = parse_tool_calls(full_response)
                if not tool_calls:
                    break

                # 执行本轮所有工具调用，收集结果
                results_text = ""
                for tc in tool_calls:
                    logger.info(f"🔧 Tool[{_loop+1}]: {tc['name']}({tc['args']})")
                    tool_result = await call_tool(tc["name"], tc["args"])
                    results_text += f"工具 {tc['name']} 返回：{tool_result}\n"

                # 去掉工具调用标记，仅保留自然语言部分
                clean_resp = re.sub(r'\[TOOL_CALL\].*?\[/TOOL_CALL\]', '', full_response, flags=re.DOTALL).strip()
                agent_msgs.append({"role": "assistant", "content": clean_resp or "(调用工具中)"})
                is_last = _loop >= 4
                # 截断过长的工具结果，防止超出上下文窗口
                if len(results_text) > 2000:
                    results_text = results_text[:2000] + "\n...(结果已截断)"
                hint = "请用自然语言回答用户。" if is_last else "根据结果决定是否需要继续调用工具完成任务，或直接用自然语言回答用户。"
                agent_msgs.append({"role": "user", "content": f"{results_text}\n{hint}"})

                followup_text = ""
                if self._router:
                    try:
                        async for chunk_text, _ in self._router.chat_stream(
                            agent_msgs, max_tokens=500, temperature=0.7
                        ):
                            if chunk_text != "__SWITCH__":
                                followup_text += chunk_text
                                yield chunk_text
                    except Exception:
                        pass
                if not followup_text and self._client:
                    try:
                        followup = await self._client.chat.completions.create(
                            model=self.model, messages=agent_msgs,
                            max_tokens=500, temperature=0.7, stream=True,
                        )
                        async for fc in followup:
                            if fc.choices[0].delta.content:
                                t = fc.choices[0].delta.content
                                followup_text += t
                                yield t
                    except Exception:
                        pass

                if followup_text:
                    full_response = followup_text
                else:
                    break

        self.conversation_history.append({"role": "assistant", "content": full_response})
        self._persist("assistant", full_response)

        # 记录 AI 回复到话题跟踪器
        if _TOPIC_TRACKING_ENABLED:
            try:
                tracker = _get_topic_tracker(self.session_id)
                if tracker:
                    tracker.process_message("assistant", full_response)
            except Exception:
                pass

        # 意图预测：记录当前意图，生成主动建议（缓存到下一轮注入）
        if _INTENT_PREDICTION_ENABLED:
            try:
                predictor = _get_intent_predictor(self.session_id)
                if predictor:
                    suggestion = predictor.process(user_message)
                    if suggestion:
                        self._pending_suggestion = suggestion
            except Exception:
                pass

        # 后台触发记忆压缩（每 50 条消息检查一次，不阻塞响应）
        if _LONG_MEMORY_ENABLED and len(self.conversation_history) % 50 == 0:
            asyncio.create_task(self._compress_memory())

    async def _compress_memory(self):
        """后台压缩旧消息为长期记忆摘要"""
        try:
            ai_call = self.chat_simple if hasattr(self, 'chat_simple') else None
            count = await compress_old_messages(self.session_id, ai_call=ai_call)
            if count:
                logger.info(f"[LongMemory] 压缩了 {count} 个记忆片段")
        except Exception as e:
            logger.debug(f"[LongMemory] 压缩失败: {e}")

    async def _chat_zhipu_vision_stream(self, user_message: str, image_b64: str) -> AsyncGenerator[str, None]:
        """使用智谱 GLM-4V 处理带图像的请求，结果同步写入主对话历史。"""
        user_content = [
            {"type": "text", "text": user_message},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
            }},
        ]
        # 只把纯文字历史传给视觉模型（不传旧图，节省 token）
        history_text = []
        for msg in self.conversation_history[-6:]:
            if isinstance(msg["content"], list):
                text = " ".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
                history_text.append({"role": msg["role"], "content": text})
            else:
                history_text.append(msg)

        messages = [
            {"role": "system", "content": (
                "你是一个智能视觉语音助手。用户发来了摄像头截图，"
                "请结合图像内容简洁地回答，语气自然口语化，不用 Markdown 格式。"
            )},
            *history_text,
            {"role": "user", "content": user_content},
        ]

        # 记录到主历史（文字版，供后续轮次参考）
        self.conversation_history.append({"role": "user", "content": user_content})
        self._persist("user", user_content)

        full_response = ""
        try:
            stream = await self._vision_client.chat.completions.create(
                model=self._vision_model,
                messages=messages,
                max_tokens=500,
                temperature=0.7,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    text = delta.content
                    full_response += text
                    yield text
            self.conversation_history.append({"role": "assistant", "content": full_response})
            self._persist("assistant", full_response)
            logger.info(f"🖼️ 智谱视觉回复完成 ({len(full_response)} chars)")
        except Exception as e:
            logger.error(f"智谱视觉 API 错误: {e}")
            yield "抱歉，图像分析时出现问题，请稍后再试。"
    
    def clear_history(self):
        """Clear conversation history (both in-memory and SQLite)."""
        self._history_cache = []
        if _MEMORY_ENABLED:
            try:
                _memory.clear_history(self.session_id)
            except Exception as e:
                logger.warning(f"Memory clear failed: {e}")
