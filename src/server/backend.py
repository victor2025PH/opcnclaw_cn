"""
AI Backend module - connects to OpenAI, OpenClaw gateway, or custom backends.
v2.0: 集成 AI 路由器（多平台轮询）+ 技能引擎（技能优先执行）
"""

import asyncio
import json
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
    from .tools import call_tool, parse_tool_calls, TOOLS_SYSTEM_ADDENDUM, TOOL_SCHEMAS
    _TOOLS_ENABLED = True
except ImportError:
    _TOOLS_ENABLED = False
    TOOLS_SYSTEM_ADDENDUM = ""
    def parse_tool_calls(text): return []
    async def call_tool(name, args): return "{}"

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
        """Lazy-load history from SQLite on first access, auto-compress if too long."""
        if self._history_cache is None:
            if _MEMORY_ENABLED:
                self._history_cache = _memory.get_history(self.session_id, limit=40)
            else:
                self._history_cache = []
            # 自动压缩过长历史
            try:
                from .memory_compressor import should_compress, compress_history
                if should_compress(self._history_cache):
                    self._history_cache = compress_history(self._history_cache)
            except Exception:
                pass
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
        if role == "user" and self.session_id.startswith("profile:"):
            try:
                from .profiles import learn_interests
                pid = self.session_id.split(":", 1)[1]
                learn_interests(pid, content)
            except Exception:
                pass
    
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
                    api_key=self.api_key or "placeholder",
                    base_url=self.url if self.url != "https://api.openai.com/v1" else None,
                )
                if not self.api_key:
                    logger.warning("OpenAI client created without API key (router mode or unconfigured)")
                else:
                    logger.info(f"✅ OpenAI client ready (model: {self.model})")
            except Exception as e:
                logger.warning(f"OpenAI client setup skipped: {e}")
        elif self.backend_type == "openclaw":
            logger.info("OpenClaw gateway backend")
        else:
            logger.warning(f"Unknown backend type: {self.backend_type}")
    
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
        # 注入用户画像（让 AI 越用越懂老板，限 600 字）
        try:
            from .user_profile_ai import get_profile_context
            profile_ctx = get_profile_context()
            if profile_ctx:
                system = system + profile_ctx[:600]
        except Exception:
            pass
        # 注入质量守卫（防止空洞回复，限 200 字）
        try:
            from .quality_guard import get_quality_prompt_boost
            quality_boost = get_quality_prompt_boost(user_message)
            if quality_boost:
                system = system + "\n\n" + quality_boost[:200]
        except Exception:
            pass
        skill_context = None

        _SKILL_ICONS = {
            "time": "⏰", "calculator": "🔢", "unit_conversion": "📐",
            "date_calc": "📅", "timer": "⏱️", "weather": "🌤️",
            "iot": "🏠", "tool": "🔧",
        }
        _skill_meta = None

        # ── 2a. 离线技能（零延迟本地处理）────────────────────────────
        if not image_b64:
            try:
                from .offline_skills import process as offline_process
                offline_result = offline_process(user_message)
                if offline_result:
                    skill_name, skill_context = offline_result
                    logger.info(f"⚡ 离线技能命中: {skill_name}")
                    system = system + "\n\n[离线技能结果] " + skill_context
                    _skill_meta = {"name": skill_name, "icon": _SKILL_ICONS.get(skill_name, "⚡"), "source": "offline"}
            except Exception as e:
                logger.debug(f"离线技能处理失败: {e}")

        # ── 2b. IoT 意图预处理（仅智能家居，排除软件/桌面操作）─────
        _not_iot = any(w in user_message for w in [
            "记事本", "浏览器", "Excel", "Word", "PPT", "微信", "软件",
            "文件", "程序", "网站", "网页", "应用", "方案", "报告",
            "代码", "营销", "分析", "桌面", "截图", "窗口",
        ])
        if not image_b64 and not skill_context and not _not_iot:
            try:
                from .iot_intent import is_iot_intent, parse_intent, execute_iot
                if is_iot_intent(user_message):
                    intent = parse_intent(user_message)
                    if intent:
                        iot_result = await execute_iot(intent)
                        skill_context = iot_result
                        logger.info(f"🏠 IoT 意图命中: {intent['action']} → {intent.get('entity_id', intent['entity_hint'])}")
                        system = system + "\n\n" + iot_result
                        _skill_meta = {"name": intent["action"], "icon": "🏠", "source": "iot"}
            except Exception as e:
                logger.debug(f"IoT 意图处理失败: {e}")

        # ── 2c. 技能引擎（无图像且无前置匹配时）─────────────────────
        if not image_b64 and not skill_context and self._skill_executor:
            try:
                skill_result = await self._skill_executor.process(user_message)
                if skill_result:
                    skill_name, skill_context = skill_result
                    logger.info(f"🧩 技能命中: {skill_name}")
                    system = system + "\n\n" + skill_context
                    _skill_meta = {"name": skill_name, "icon": "🧩", "source": "skill"}
            except Exception as e:
                logger.debug(f"技能引擎处理失败: {e}")

        if _skill_meta:
            yield "__SKILL__" + json.dumps(_skill_meta, ensure_ascii=False)

        if not skill_context:
            # 仅在无技能匹配时注入工具调用提示
            if self.enable_tools:
                system = system + "\n\n" + TOOLS_SYSTEM_ADDENDUM
        if image_b64:
            system += "\n\n用户发送了摄像头画面。请结合图像内容来回答问题，说明你看到了什么。"

        messages = [{"role": "system", "content": system}]
        for msg in self.conversation_history[-10:]:
            if isinstance(msg["content"], list):
                text = " ".join(p.get("text", "") for p in msg["content"] if p.get("type") == "text")
                messages.append({"role": msg["role"], "content": text})
            else:
                messages.append(msg)
        if image_b64 and messages[-1]["role"] == "user":
            messages[-1]["content"] = user_content

        full_response = ""

        # ── 3a. 优先走路由器（多平台轮询）──────────────────────────
        if self._router:
            try:
                # 原生 FC：传递工具定义（平台不支持时路由器会忽略）
                _tools = TOOL_SCHEMAS if (self.enable_tools and not skill_context) else None

                last_provider = None
                native_tool_calls = None
                async for chunk_text, provider_id in self._router.chat_stream(
                    messages, max_tokens=1200, temperature=0.7, tools=_tools,
                ):
                    if chunk_text == "__SWITCH__":
                        continue
                    if chunk_text == "__TOOL_CALLS__":
                        # 原生 Function Calling 结果
                        native_tool_calls = json.loads(provider_id)
                        continue
                    full_response += chunk_text
                    yield chunk_text
                    last_provider = provider_id

                # 处理原生 tool_calls（比 ReAct 更准确）
                if native_tool_calls:
                    for tc in native_tool_calls:
                        tc_name = tc.get("name", "")
                        try:
                            tc_args = json.loads(tc.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            tc_args = {}
                        logger.info(f"🔧 原生FC: {tc_name}({tc_args})")
                        tool_result = await call_tool(tc_name, tc_args)
                        # 将工具结果发回模型生成自然语言回答
                        followup_msgs = messages + [
                            {"role": "assistant", "content": None,
                             "tool_calls": [{"id": tc.get("id", "call_1"), "type": "function",
                                           "function": {"name": tc_name, "arguments": json.dumps(tc_args, ensure_ascii=False)}}]},
                            {"role": "tool", "tool_call_id": tc.get("id", "call_1"), "content": tool_result},
                        ]
                        async for chunk_text2, _ in self._router.chat_stream(
                            followup_msgs, max_tokens=400, temperature=0.7
                        ):
                            if chunk_text2 in ("__SWITCH__", "__TOOL_CALLS__"):
                                continue
                            full_response += chunk_text2
                            yield chunk_text2

                if last_provider:
                    logger.debug(f"路由器使用平台: {last_provider}")

                # ── ReAct 降级：原生 FC 未触发时，解析文本中的 [TOOL_CALL] ──
                if not native_tool_calls and self.enable_tools and not skill_context:
                    text_tool_calls = parse_tool_calls(full_response)
                    if text_tool_calls:
                        for tc in text_tool_calls:
                            logger.info(f"🔧 ReAct Tool: {tc['name']}({tc['args']})")
                            tool_result = await call_tool(tc["name"], tc["args"])
                            followup_msgs = messages + [
                                {"role": "assistant", "content": full_response},
                                {"role": "user", "content": f"工具 {tc['name']} 返回结果：{tool_result}\n请用自然语言把结果告诉用户。"},
                            ]
                            async for chunk_text2, _ in self._router.chat_stream(
                                followup_msgs, max_tokens=600, temperature=0.7
                            ):
                                if chunk_text2 in ("__SWITCH__", "__TOOL_CALLS__"):
                                    continue
                                full_response += chunk_text2
                                yield chunk_text2

                # 质量检测：空洞回复自动补救（仅路由器可用时，最多 1 次）
                if self._router and full_response and len(full_response) < 150:
                    try:
                        from .quality_guard import check_response_quality
                        qr = check_response_quality(user_message, full_response)
                        if qr["quality"] == "hollow" and qr.get("suggestion"):
                            logger.warning(f"[QualityGuard] 空洞回复, score={qr['score']}, 自动补救")
                            retry_msgs = messages + [
                                {"role": "assistant", "content": full_response},
                                {"role": "user", "content": qr["suggestion"]},
                            ]
                            yield "\n\n"
                            async for chunk2, _ in self._router.chat_stream(
                                retry_msgs, max_tokens=600, temperature=0.7,
                                tools=TOOL_SCHEMAS if self.enable_tools else None,
                            ):
                                if chunk2 in ("__SWITCH__", "__TOOL_CALLS__"):
                                    continue
                                full_response += chunk2
                                yield chunk2
                    except Exception as e:
                        logger.debug(f"[QualityGuard] 跳过: {e}")

                self.conversation_history.append({"role": "assistant", "content": full_response})
                self._persist("assistant", full_response)
                # 从对话中学习用户画像
                try:
                    from .user_profile_ai import update_profile_from_conversation
                    update_profile_from_conversation(user_message, full_response)
                except Exception:
                    pass
                return
            except Exception as e:
                logger.warning(f"路由器失败，降级到直连: {e}")

        # ── 3b. 降级：直接连接（原有逻辑）──────────────────────────
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

            # ── 工具调用拦截（无技能命中时）──────────────────────
            if self.enable_tools and not skill_context:
                tool_calls = parse_tool_calls(full_response)
                if tool_calls:
                    for tc in tool_calls:
                        logger.info(f"🔧 Tool call: {tc['name']}({tc['args']})")
                        tool_result = await call_tool(tc["name"], tc["args"])
                        followup_msgs = messages + [
                            {"role": "assistant", "content": full_response},
                            {"role": "user", "content": f"工具 {tc['name']} 返回结果：{tool_result}\n请用自然语言回答用户。"},
                        ]
                        followup = await self._client.chat.completions.create(
                            model=self.model, messages=followup_msgs,
                            max_tokens=400, temperature=0.7, stream=True,
                        )
                        followup_text = ""
                        async for fc in followup:
                            if fc.choices[0].delta.content:
                                t = fc.choices[0].delta.content
                                followup_text += t
                                yield t
                        full_response = followup_text

            self.conversation_history.append({"role": "assistant", "content": full_response})
            self._persist("assistant", full_response)
            # 从对话中学习用户画像
            try:
                from .user_profile_ai import update_profile_from_conversation
                update_profile_from_conversation(user_message, full_response)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}")
            yield "抱歉，处理时出现问题，请稍后再试。"

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
    
    async def chat_simple(self, messages: list) -> str:
        """简单对话接口（非流式），用于内部工具调用（记忆压缩、日报等）"""
        if self._router:
            try:
                result = ""
                async for chunk, _ in self._router.chat_stream(messages, max_tokens=400):
                    if chunk != "__SWITCH__":
                        result += chunk
                return result
            except Exception:
                pass
        if self._client:
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model, messages=messages,
                    max_tokens=400, temperature=0.7,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                return f"AI 调用失败: {e}"
        return ""

    def clear_history(self):
        """Clear conversation history (both in-memory and SQLite)."""
        self._history_cache = []
        if _MEMORY_ENABLED:
            try:
                _memory.clear_history(self.session_id)
            except Exception as e:
                logger.warning(f"Memory clear failed: {e}")
