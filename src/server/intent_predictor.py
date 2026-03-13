# -*- coding: utf-8 -*-
"""
对话意图预测器

问题：用户连续讨论某个领域时，AI 只是被动回答。
     如果能预判下一个可能的需求，主动建议，体验更智能。

方案对比：
  方案A: 每轮都调 LLM 预测 → 延迟翻倍，成本高
  方案B: 基于历史模式的马尔可夫链 → 零延迟，零成本
  选择B，LLM 只在需要生成建议文案时才调用。

架构：
  1. 意图分类器：将用户消息映射到意图类别（20+ 类）
  2. 转移矩阵：统计意图 A 之后出现意图 B 的概率
  3. 预测器：基于当前意图 + 转移矩阵，返回 top-3 可能的下一意图
  4. 建议生成：将预测的意图转化为自然语言的主动建议

意图分类用正则规则（不用 LLM），确保零延迟。
"""

from __future__ import annotations

import re
import time
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

try:
    import jieba
    jieba.setLogLevel(20)
    _JIEBA = True
except ImportError:
    _JIEBA = False


# ── 意图定义 ─────────────────────────────────────────────────────────────────

INTENT_PATTERNS: Dict[str, List[str]] = {
    "weather":      [r"天气|温度|下雨|下雪|气温|穿什么|冷不冷|热不热"],
    "time":         [r"几点|时间|日期|今天周几|星期几|几号"],
    "news":         [r"新闻|热搜|头条|发生了什么|最新消息"],
    "food":         [r"吃什么|餐厅|美食|饿了|午饭|晚饭|早餐|外卖|好吃"],
    "travel":       [r"旅游|机票|酒店|去哪玩|景点|攻略|出行"],
    "shopping":     [r"买|淘宝|京东|价格|便宜|优惠|打折|推荐.*产品"],
    "wechat_send":  [r"发消息|发微信|告诉.{1,4}说|转告"],
    "wechat_moment":[r"朋友圈|发圈|动态|分享"],
    "wechat_read":  [r"看看消息|未读|谁.*发.*消息|收件箱"],
    "music":        [r"音乐|歌|播放|听.*曲"],
    "reminder":     [r"提醒|闹钟|定时|别忘了|记得"],
    "schedule":     [r"日程|会议|安排|行程|日历"],
    "calculate":    [r"算|计算|多少钱|加|减|乘|除|百分比|\d+.*[+\-*/]"],
    "translate":    [r"翻译|英文|中文|怎么说"],
    "knowledge":    [r"是什么|为什么|怎么回事|解释|介绍|科普"],
    "health":       [r"健康|运动|跑步|减肥|睡眠|锻炼|身体"],
    "emotion":      [r"心情|开心|难过|烦|累|压力|焦虑|无聊|郁闷"],
    "joke":         [r"笑话|段子|搞笑|逗我|开心一下"],
    "coding":       [r"代码|编程|bug|python|javascript|程序"],
    "workflow":     [r"工作流|自动化|定时任务|批量"],
    "greeting":     [r"^(你好|嗨|hi|hello|早|晚安|morning)"],
}

_compiled_patterns: Dict[str, re.Pattern] = {
    intent: re.compile("|".join(patterns), re.IGNORECASE)
    for intent, patterns in INTENT_PATTERNS.items()
}

# 内置转移概率先验（常见意图链）
_PRIOR_TRANSITIONS = {
    "weather": {"travel": 0.2, "food": 0.15, "schedule": 0.1},
    "food": {"travel": 0.1, "shopping": 0.1, "health": 0.1},
    "travel": {"weather": 0.2, "shopping": 0.15, "food": 0.1},
    "wechat_send": {"wechat_moment": 0.15, "wechat_read": 0.1},
    "wechat_moment": {"wechat_send": 0.1, "wechat_read": 0.1},
    "shopping": {"calculate": 0.2, "food": 0.1},
    "schedule": {"reminder": 0.3, "weather": 0.1},
    "reminder": {"schedule": 0.2, "time": 0.15},
    "emotion": {"joke": 0.25, "music": 0.2, "health": 0.1},
    "joke": {"emotion": 0.1, "music": 0.1},
    "health": {"food": 0.15, "schedule": 0.1},
    "greeting": {"weather": 0.15, "time": 0.1, "news": 0.1},
}

# 意图 → 主动建议文案
INTENT_SUGGESTIONS: Dict[str, str] = {
    "weather":      "要不要我帮你查一下天气？",
    "food":         "要不要推荐附近的美食？",
    "travel":       "需要我帮你查查旅行攻略吗？",
    "shopping":     "要不要我帮你比较一下价格？",
    "reminder":     "需要我帮你设个提醒吗？",
    "schedule":     "要不要看看今天的日程安排？",
    "calculate":    "需要我帮你算一下吗？",
    "translate":    "要我帮你翻译吗？",
    "joke":         "要不要我讲个笑话逗你开心？",
    "music":        "要不要我推荐一些音乐？",
    "wechat_moment":"要不要看看朋友圈有什么新动态？",
    "wechat_read":  "要不要我帮你看看有什么未读消息？",
    "health":       "要不要制定一个运动计划？",
    "news":         "要不要我帮你看看今天的热点？",
}


# ── 意图分类 ─────────────────────────────────────────────────────────────────

def classify_intent(text: str) -> str:
    """
    将用户消息分类到意图类别。

    纯正则匹配，零延迟。返回空字符串表示无法分类。
    """
    if not text or len(text) < 2:
        return ""
    for intent, pattern in _compiled_patterns.items():
        if pattern.search(text):
            return intent
    return ""


# ── 转移矩阵 ─────────────────────────────────────────────────────────────────

class TransitionMatrix:
    """
    意图转移概率矩阵。

    记录 intent_A → intent_B 出现的次数。
    结合先验知识 + 实际观测数据做贝叶斯更新。
    """

    def __init__(self):
        self._counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._totals: Dict[str, int] = defaultdict(int)
        # 加载先验
        for src, targets in _PRIOR_TRANSITIONS.items():
            for dst, prob in targets.items():
                # 先验转换为伪计数（权重 10）
                count = max(1, int(prob * 10))
                self._counts[src][dst] += count
                self._totals[src] += count

    def record(self, from_intent: str, to_intent: str):
        """记录一次转移"""
        if from_intent and to_intent and from_intent != to_intent:
            self._counts[from_intent][to_intent] += 1
            self._totals[from_intent] += 1

    def predict(self, current_intent: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """
        预测下一个最可能的意图。

        返回: [(intent, probability), ...]
        """
        if not current_intent or current_intent not in self._counts:
            return []

        total = self._totals[current_intent]
        if total == 0:
            return []

        probs = [
            (intent, count / total)
            for intent, count in self._counts[current_intent].items()
        ]
        probs.sort(key=lambda x: x[1], reverse=True)
        return probs[:top_k]


# ── 意图预测器 ───────────────────────────────────────────────────────────────

class IntentPredictor:
    """
    对话意图预测器

    用法：
        predictor = IntentPredictor()
        suggestion = predictor.process("今天天气怎么样？")
        # → "要不要推荐附近的美食？" (weather 之后常问 food)
    """

    def __init__(self, min_confidence: float = 0.15):
        self._matrix = TransitionMatrix()
        self._last_intent: str = ""
        self._intent_history: List[str] = []
        self._min_confidence = min_confidence
        self._suggestion_cooldown: Dict[str, float] = {}

    def process(self, user_message: str) -> Optional[str]:
        """
        处理用户消息，返回主动建议（或 None）。

        流程：
          1. 分类当前意图
          2. 记录转移（上次意图 → 当前意图）
          3. 预测下一意图
          4. 如果置信度足够高，返回建议
        """
        intent = classify_intent(user_message)
        if not intent:
            return None

        # 记录转移
        if self._last_intent:
            self._matrix.record(self._last_intent, intent)
        self._last_intent = intent
        self._intent_history.append(intent)
        if len(self._intent_history) > 100:
            self._intent_history = self._intent_history[-100:]

        # 预测
        predictions = self._matrix.predict(intent, top_k=3)
        if not predictions:
            return None

        top_intent, confidence = predictions[0]

        # 置信度过滤
        if confidence < self._min_confidence:
            return None

        # 冷却期：同一建议 10 分钟内不重复
        now = time.time()
        if top_intent in self._suggestion_cooldown:
            if now - self._suggestion_cooldown[top_intent] < 600:
                if len(predictions) > 1:
                    top_intent, confidence = predictions[1]
                    if confidence < self._min_confidence:
                        return None
                else:
                    return None

        suggestion = INTENT_SUGGESTIONS.get(top_intent)
        if suggestion:
            self._suggestion_cooldown[top_intent] = now
            return suggestion

        return None

    def get_status(self) -> Dict:
        """获取预测器状态"""
        predictions = self._matrix.predict(self._last_intent) if self._last_intent else []
        return {
            "last_intent": self._last_intent,
            "history_length": len(self._intent_history),
            "predictions": [
                {"intent": i, "confidence": round(c, 3)}
                for i, c in predictions
            ],
            "recent_intents": self._intent_history[-10:],
        }


# session_id → IntentPredictor
_predictors: Dict[str, IntentPredictor] = {}


def get_predictor(session_id: str = "default") -> IntentPredictor:
    if session_id not in _predictors:
        _predictors[session_id] = IntentPredictor()
    return _predictors[session_id]
