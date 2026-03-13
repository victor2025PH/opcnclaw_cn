# -*- coding: utf-8 -*-
"""
对话上下文智能压缩

问题：对话超过 10 轮后，token 消耗急剧增长，可能超出模型窗口。
     现有的 long_memory.py 每 50 条消息才触发一次压缩，不够及时。

方案演进：
  V1: 简单截断最近 N 条 → 丢失上下文
  V2: 每 50 条 LLM 压缩 (long_memory.py) → 触发太晚，且压缩到独立数据库，不回写对话流
  V3 (本模块): 三层滑动窗口 + 在线压缩
    - 近期窗口（最近 6 条）：原文保留
    - 中期窗口（7-20 条）：实时压缩为 1 段摘要
    - 远期：交给 long_memory.py 处理

关键优化：
  - 压缩仅针对中期窗口，不阻塞响应
  - 无 LLM 时用纯提取式压缩（关键句筛选），有 LLM 时用生成式压缩
  - 压缩结果缓存，相同窗口不重复压缩
  - token 计算用字符数估算（中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1 token）
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple

from loguru import logger


def estimate_tokens(text: str) -> int:
    """粗估 token 数（不依赖 tiktoken）"""
    if not text:
        return 0
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_words = len(re.findall(r'[a-zA-Z]+', text))
    return int(cn_chars * 1.5 + en_words + len(text) * 0.1)


def estimate_messages_tokens(messages: List[Dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        total += estimate_tokens(str(c)) + 4  # role overhead
    return total


# ── 提取式压缩（零 LLM）────────────────────────────────────────────────────

def _extractive_compress(messages: List[Dict], max_sentences: int = 5) -> str:
    """
    从消息中提取关键句子，不调用 LLM。

    策略：
      1. 提取所有非寒暄句子
      2. 优先保留含实体（数字/专有名词）的句子
      3. 保留问句（用户意图）
    """
    sentences = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not content:
            continue

        prefix = "用户" if role == "user" else "AI"
        for s in re.split(r'[。！？\n.!?]', str(content)):
            s = s.strip()
            if len(s) < 4:
                continue
            sentences.append((prefix, s))

    if not sentences:
        return ""

    # 评分：问句+3，含数字+2，含名词+1，长度适中+1
    scored = []
    for prefix, s in sentences:
        score = 0
        if "?" in s or "？" in s or "吗" in s or "什么" in s:
            score += 3
        if re.search(r'\d+', s):
            score += 2
        if len(s) > 10:
            score += 1
        if prefix == "用户":
            score += 1  # 用户意图更重要
        scored.append((score, prefix, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_sentences]

    parts = [f"{prefix}说：{s}" for _, prefix, s in top]
    return "（历史摘要）" + "；".join(parts)


# ── 生成式压缩（LLM）──────────────────────────────────────────────────────

COMPRESS_PROMPT = (
    "将以下对话压缩为 1 段简洁摘要（50-80字），保留关键事实、数字、名称和用户意图。"
    "用第三人称（'用户'和'AI'）。只输出摘要。\n\n{conversation}"
)


async def _generative_compress(messages: List[Dict], ai_call) -> str:
    """用 LLM 压缩消息为摘要"""
    conv_lines = []
    for m in messages:
        role = "用户" if m.get("role") == "user" else "AI"
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        conv_lines.append(f"{role}: {str(content)[:200]}")

    conversation_text = "\n".join(conv_lines)
    prompt_messages = [
        {"role": "system", "content": "你是对话摘要压缩器，只输出摘要，不要其他格式。"},
        {"role": "user", "content": COMPRESS_PROMPT.format(conversation=conversation_text)},
    ]
    try:
        result = await ai_call(prompt_messages)
        if result and len(result.strip()) > 10:
            return f"（历史摘要）{result.strip()[:150]}"
    except Exception as e:
        logger.debug(f"[ContextCompressor] LLM compress failed: {e}")
    return ""


# ── 主压缩引擎 ──────────────────────────────────────────────────────────────

class ContextCompressor:
    """
    三层滑动窗口对话压缩器。

    用法：
        compressor = ContextCompressor()
        messages = compressor.compress(history, ai_call=backend.chat_simple)
        # messages 可直接传给 LLM
    """

    def __init__(
        self,
        recent_window: int = 6,
        mid_window: int = 14,
        max_total_tokens: int = 3000,
    ):
        self.recent_window = recent_window
        self.mid_window = mid_window
        self.max_total_tokens = max_total_tokens
        self._cache: Dict[str, str] = {}  # hash → summary

    def _cache_key(self, messages: List[Dict]) -> str:
        content = "|".join(str(m.get("content", ""))[:50] for m in messages)
        return hashlib.md5(content.encode()).hexdigest()[:12]

    async def compress(
        self,
        history: List[Dict],
        ai_call=None,
    ) -> List[Dict]:
        """
        压缩对话历史，返回可直接传给 LLM 的消息列表。

        不修改原始 history，返回新列表。
        """
        total = len(history)

        # 短对话不压缩
        if total <= self.recent_window:
            return list(history)

        # 分层
        recent = history[-self.recent_window:]
        mid_start = max(0, total - self.recent_window - self.mid_window)
        mid_end = total - self.recent_window
        mid = history[mid_start:mid_end]

        # 检查是否需要压缩
        recent_tokens = estimate_messages_tokens(recent)
        if recent_tokens < self.max_total_tokens and len(mid) <= 4:
            return list(history[-self.recent_window - len(mid):])

        # 压缩中期窗口
        summary = ""
        if mid:
            cache_key = self._cache_key(mid)
            if cache_key in self._cache:
                summary = self._cache[cache_key]
            else:
                # 优先用 LLM，回退到提取式
                if ai_call:
                    summary = await _generative_compress(mid, ai_call)
                if not summary:
                    summary = _extractive_compress(mid)
                if summary:
                    self._cache[cache_key] = summary
                    # LRU: 只保留最近 20 个缓存
                    if len(self._cache) > 20:
                        oldest = next(iter(self._cache))
                        del self._cache[oldest]

        result = []
        if summary:
            result.append({"role": "system", "content": summary})
        result.extend(recent)

        return result

    def get_stats(self) -> Dict:
        return {
            "cache_size": len(self._cache),
            "recent_window": self.recent_window,
            "mid_window": self.mid_window,
            "max_tokens": self.max_total_tokens,
        }


# 全局单例
_compressor: Optional[ContextCompressor] = None


def get_compressor() -> ContextCompressor:
    global _compressor
    if _compressor is None:
        _compressor = ContextCompressor()
    return _compressor
