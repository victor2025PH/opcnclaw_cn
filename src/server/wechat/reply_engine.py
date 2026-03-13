# -*- coding: utf-8 -*-
"""
智能回复引擎 v2.0

核心设计思路：
  1. 消息批处理 — 对方连发多条时，等发完再一起处理（不逐条回复）
  2. 单次 LLM 调用 — 意图分类 + 情感分析 + 回复生成一次完成（省延迟/成本）
  3. 升级决策 — AI 判断是否需要人工接管（敏感/复杂/高情绪）
  4. 回复长度校准 — 短消息回短，长消息回中等长度
  5. 对话摘要 — 历史超长时自动压缩，保持上下文不丢失
"""

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from loguru import logger


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    """LLM 分析结果"""
    intent: str = "chitchat"    # chitchat/question/request/complaint/greeting/sensitive/unknown
    emotion: str = "neutral"    # neutral/happy/sad/angry/anxious/urgent
    should_reply: bool = True
    escalate: bool = False
    escalate_reason: str = ""
    reply: str = ""
    confidence: float = 0.8

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "emotion": self.emotion,
            "should_reply": self.should_reply,
            "escalate": self.escalate,
            "escalate_reason": self.escalate_reason,
            "confidence": self.confidence,
        }


@dataclass
class EscalationItem:
    """需要人工处理的升级项"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    contact: str = ""
    messages: List[str] = field(default_factory=list)
    reason: str = ""
    intent: str = ""
    emotion: str = ""
    ai_draft: str = ""       # AI 草拟的回复（供人工参考）
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / handled / dismissed


@dataclass
class BatchedMessages:
    """一个联系人的待处理消息批"""
    contact: str
    sender: str
    messages: List[str] = field(default_factory=list)
    first_time: float = 0
    last_time: float = 0
    is_group: bool = False
    at_me: bool = False
    timer: Optional[threading.Timer] = field(default=None, repr=False)


# ── 回复长度校准规则 ──────────────────────────────────────────────────────────

def _calibrate_length(incoming_total_len: int, raw_reply: str) -> str:
    """
    根据对方消息长度校准回复长度，模拟真人习惯：
      对方 < 10 字 → 回复 ≤ 20 字
      对方 10~50 字 → 回复 ≤ 60 字
      对方 > 50 字 → 回复 ≤ 120 字
    """
    if incoming_total_len < 10:
        max_len = 20
    elif incoming_total_len < 50:
        max_len = 60
    else:
        max_len = 120

    if len(raw_reply) <= max_len:
        return raw_reply

    # 在 max_len 附近找断句点
    cutoff = raw_reply[:max_len + 10]
    for sep in ["。", "！", "？", "~", "，", "；", "\n"]:
        idx = cutoff.rfind(sep)
        if idx > max_len // 2:
            return cutoff[: idx + 1]

    return raw_reply[:max_len]


# ── 对话摘要生成 ──────────────────────────────────────────────────────────────

def build_context_messages(
    history: List[Dict],
    persona: str,
    contact: str,
    is_group: bool,
    max_recent: int = 8,
    max_total_chars: int = 3000,
) -> List[Dict]:
    """
    构建给 LLM 的消息列表，智能处理历史长度：
      - 最近 max_recent 条保持原样
      - 更早的消息压缩为一句话摘要
      - 总字符数不超过 max_total_chars
    """
    system_prompt = (
        f"{persona}\n\n"
        f"当前联系人：{contact}{'（群聊）' if is_group else '（私聊）'}\n"
        "规则：回复自然简短，符合微信聊天习惯。不要暴露你是AI。"
    )

    if len(history) <= max_recent:
        return [{"role": "system", "content": system_prompt}] + history

    old_part = history[:-max_recent]
    recent_part = history[-max_recent:]

    # 提取旧消息的关键内容作为摘要
    topics = []
    for msg in old_part[-6:]:
        text = msg.get("content", "")[:40]
        if text:
            role_label = "对方" if msg["role"] == "user" else "你"
            topics.append(f"{role_label}说：{text}")

    summary = "；".join(topics) if topics else "之前有过简短对话"

    messages = [{"role": "system", "content": system_prompt}]
    messages.append({
        "role": "system",
        "content": f"[之前的对话摘要（共{len(old_part)}条）：{summary}]",
    })
    messages.extend(recent_part)

    # 控制总长度
    total = sum(len(m.get("content", "")) for m in messages)
    while total > max_total_chars and len(messages) > 3:
        removed = messages.pop(2)
        total -= len(removed.get("content", ""))

    return messages


# ── 结构化分析 Prompt ─────────────────────────────────────────────────────────

ANALYSIS_PROMPT_TEMPLATE = """\
你同时扮演两个角色：
1) 消息分析师：判断消息的意图和情感
2) 回复者：按照人设生成回复

对方发来的新消息：
{incoming}

请用以下JSON格式回复（不要多余文字）：
{{
  "intent": "意图（chitchat/question/request/complaint/greeting/sensitive）",
  "emotion": "情感（neutral/happy/sad/angry/anxious/urgent）",
  "should_reply": true或false,
  "escalate": 是否需要转人工（true/false），以下情况应该转人工：对方很愤怒、涉及金钱转账、紧急求助、你无法回答的专业问题,
  "escalate_reason": "转人工原因（不转则空字符串）",
  "reply": "你的回复内容（自然简短，符合人设）",
  "confidence": 0到1的置信度
}}"""


# ── 智能回复引擎 ──────────────────────────────────────────────────────────────

class SmartReplyEngine:
    """
    智能回复引擎

    使用方式：
        engine = SmartReplyEngine(ai_fn=backend.chat_simple)
        engine.on_reply(send_callback)
        engine.on_escalation(escalation_callback)
        engine.queue_message(contact, sender, content, history, config)
    """

    def __init__(
        self,
        ai_fn: Callable[..., Coroutine],
        anti_risk=None,
        batch_timeout: float = 4.0,  # 消息批处理等待时间
    ):
        self._ai_fn = ai_fn            # async (messages: list) -> str
        self._anti_risk = anti_risk     # AntiRiskEngine 实例
        self._batch_timeout = batch_timeout
        self._batches: Dict[str, BatchedMessages] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 回调
        self._reply_callbacks: List[Callable] = []
        self._escalation_callbacks: List[Callable] = []

        # 升级队列
        self._escalations: Dict[str, EscalationItem] = {}

        # 统计
        self.stats = {
            "messages_received": 0,
            "batches_processed": 0,
            "replies_generated": 0,
            "escalations": 0,
            "skipped": 0,
        }

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def on_reply(self, callback: Callable):
        """注册回复回调: callback(contact, reply_text, analysis: AnalysisResult)"""
        self._reply_callbacks.append(callback)

    def on_escalation(self, callback: Callable):
        """注册升级回调: callback(item: EscalationItem)"""
        self._escalation_callbacks.append(callback)

    # ── 消息入口（带批处理）────────────────────────────────────────────────

    def queue_message(
        self,
        contact: str,
        sender: str,
        content: str,
        history: List[Dict],
        persona: str,
        is_group: bool = False,
        at_me: bool = False,
        daily_count: int = 0,
        daily_limit: int = 20,
    ):
        """
        将消息加入批处理队列。
        同一联系人的消息在 batch_timeout 内合并为一批。
        """
        self.stats["messages_received"] += 1
        now = time.time()

        with self._lock:
            if contact in self._batches:
                batch = self._batches[contact]
                batch.messages.append(content)
                batch.last_time = now
                if at_me:
                    batch.at_me = True
                # 重置计时器
                if batch.timer:
                    batch.timer.cancel()
            else:
                batch = BatchedMessages(
                    contact=contact,
                    sender=sender,
                    messages=[content],
                    first_time=now,
                    last_time=now,
                    is_group=is_group,
                    at_me=at_me,
                )
                self._batches[contact] = batch

            # 智能等待时间：短消息（可能还有后续）等久一点
            wait = self._calc_batch_wait(content)

            batch.timer = threading.Timer(
                wait,
                self._flush_batch,
                args=(contact, history, persona, daily_count, daily_limit),
            )
            batch.timer.daemon = True
            batch.timer.start()

    def _calc_batch_wait(self, last_content: str) -> float:
        """
        智能批处理等待时间：
          - 短消息（"嗯"、"好"）→ 等久一点（5s），可能还有后续
          - 长消息/问号结尾 → 等短一点（2.5s），可能已说完
        """
        text = last_content.strip()
        if len(text) <= 4:
            return min(self._batch_timeout + 1.5, 6.0)
        if text.endswith(("？", "?", "吗", "呢", "么")):
            return max(self._batch_timeout - 1.5, 2.0)
        return self._batch_timeout

    def _flush_batch(
        self,
        contact: str,
        history: List[Dict],
        persona: str,
        daily_count: int,
        daily_limit: int,
    ):
        """计时器到期，处理一个联系人的消息批"""
        with self._lock:
            batch = self._batches.pop(contact, None)
        if not batch or not batch.messages:
            return

        # 在事件循环中执行异步处理
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._process_batch(batch, history, persona, daily_count, daily_limit),
                self._loop,
            )
        else:
            # 降级：新建事件循环
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self._process_batch(batch, history, persona, daily_count, daily_limit)
                )
            finally:
                loop.close()

    # ── 批处理核心 ─────────────────────────────────────────────────────────

    async def _process_batch(
        self,
        batch: BatchedMessages,
        history: List[Dict],
        persona: str,
        daily_count: int,
        daily_limit: int,
    ):
        """处理一批消息：分析 → 决策 → 生成回复 → 分发"""
        self.stats["batches_processed"] += 1

        # 合并多条消息为一条
        if len(batch.messages) == 1:
            combined = batch.messages[0]
        else:
            combined = "\n".join(batch.messages)

        logger.info(
            f"[ReplyEngine] 处理批次: {batch.contact} "
            f"({len(batch.messages)}条消息, {len(combined)}字)"
        )

        try:
            # Step 1: 构建上下文
            context_msgs = build_context_messages(
                history=history,
                persona=persona,
                contact=batch.contact,
                is_group=batch.is_group,
            )

            # Step 2: 添加分析指令
            analysis_prompt = ANALYSIS_PROMPT_TEMPLATE.format(incoming=combined)
            context_msgs.append({"role": "user", "content": analysis_prompt})

            # Step 3: 单次 LLM 调用（分析 + 回复一起）
            raw_response = await self._ai_fn(context_msgs)
            analysis = self._parse_analysis(raw_response)

            # Step 4: 回复长度校准
            if analysis.reply:
                analysis.reply = _calibrate_length(len(combined), analysis.reply)

            # Step 5: 升级决策
            if analysis.escalate:
                self._handle_escalation(batch, analysis)
                return

            if not analysis.should_reply:
                self.stats["skipped"] += 1
                logger.debug(f"[ReplyEngine] AI 决定不回复 {batch.contact}")
                return

            # Step 6: 反风控延迟
            delay = 0.0
            if self._anti_risk:
                should_send, delay = self._anti_risk.evaluate(
                    batch.contact, combined, analysis.reply
                )
                if not should_send:
                    logger.debug(f"[ReplyEngine] 反风控拦截: {batch.contact}")
                    self.stats["skipped"] += 1
                    return

            if delay > 0:
                await asyncio.sleep(delay)

            # Step 7: 分发回复
            self.stats["replies_generated"] += 1
            for cb in self._reply_callbacks:
                try:
                    cb(batch.contact, analysis.reply, analysis)
                except Exception as e:
                    logger.error(f"Reply callback error: {e}")

            if self._anti_risk:
                self._anti_risk.record_sent(batch.contact)

        except Exception as e:
            logger.error(f"[ReplyEngine] process_batch error: {e}")

    # ── 分析结果解析 ───────────────────────────────────────────────────────

    def _parse_analysis(self, raw: str) -> AnalysisResult:
        """
        解析 LLM 返回的 JSON 分析结果。
        容错设计：JSON 解析失败时从纯文本提取回复。
        """
        result = AnalysisResult()

        if not raw:
            result.should_reply = False
            return result

        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                data = json.loads(json_match.group())
                result.intent = data.get("intent", "chitchat")
                result.emotion = data.get("emotion", "neutral")
                result.should_reply = data.get("should_reply", True)
                result.escalate = data.get("escalate", False)
                result.escalate_reason = data.get("escalate_reason", "")
                result.reply = data.get("reply", "")
                result.confidence = float(data.get("confidence", 0.8))
                return result
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # JSON 解析失败：把整段文本当回复
        cleaned = raw.strip()
        # 去除可能的 markdown 代码块标记
        cleaned = re.sub(r'^```json?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        # 去掉可能的字段前缀
        cleaned = re.sub(r'^(reply|回复)[：:]\s*', '', cleaned, flags=re.IGNORECASE)

        result.reply = cleaned[:200]
        result.confidence = 0.5  # 非结构化回复，置信度降低
        return result

    # ── 升级处理 ──────────────────────────────────────────────────────────

    def _handle_escalation(self, batch: BatchedMessages, analysis: AnalysisResult):
        """创建升级项并通知"""
        self.stats["escalations"] += 1

        item = EscalationItem(
            contact=batch.contact,
            messages=list(batch.messages),
            reason=analysis.escalate_reason or f"意图:{analysis.intent} 情感:{analysis.emotion}",
            intent=analysis.intent,
            emotion=analysis.emotion,
            ai_draft=analysis.reply,
        )

        self._escalations[item.id] = item
        logger.warning(
            f"[ReplyEngine] 🚨 升级: {batch.contact} — {item.reason}"
        )

        for cb in self._escalation_callbacks:
            try:
                cb(item)
            except Exception:
                pass

    def get_escalations(self, status: str = "pending") -> List[Dict]:
        """获取指定状态的升级列表"""
        return [
            {
                "id": item.id,
                "contact": item.contact,
                "messages": item.messages,
                "reason": item.reason,
                "intent": item.intent,
                "emotion": item.emotion,
                "ai_draft": item.ai_draft,
                "created_at": item.created_at,
                "status": item.status,
            }
            for item in self._escalations.values()
            if item.status == status
        ]

    def handle_escalation(self, eid: str, action: str, reply: str = "") -> bool:
        """
        处理升级项。
        action: 'send_draft' — 发送 AI 草稿
                'send_custom' — 发送自定义回复
                'dismiss' — 忽略
        """
        item = self._escalations.get(eid)
        if not item or item.status != "pending":
            return False

        if action == "dismiss":
            item.status = "dismissed"
            return True

        text = item.ai_draft if action == "send_draft" else reply
        if not text:
            return False

        item.status = "handled"
        for cb in self._reply_callbacks:
            try:
                cb(item.contact, text, AnalysisResult(intent=item.intent, emotion=item.emotion))
            except Exception:
                pass
        return True

    def get_stats(self) -> Dict:
        return {
            **self.stats,
            "pending_escalations": len([
                e for e in self._escalations.values() if e.status == "pending"
            ]),
            "active_batches": len(self._batches),
        }
