"""
技能意图匹配器

优化思路：
- 三层匹配：关键词精确 → jieba 分词TF-IDF → AI语义兜底
- 置信度阈值控制（低于阈值走普通 AI 对话）
- 参数提取（从用户句子中抽取数字/城市/食材等）
"""

import re
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .registry import Skill, SkillRegistry, get_registry

# 置信度阈值：高于此值直接执行，低于此值走 AI 对话
HIGH_CONFIDENCE = 0.75
LOW_CONFIDENCE = 0.30


class MatchResult:
    def __init__(self, skill: Skill, confidence: float, params: dict):
        self.skill = skill
        self.confidence = confidence
        self.params = params

    def __repr__(self):
        return f"<Match {self.skill.id} conf={self.confidence:.2f} params={self.params}>"


class SkillMatcher:
    """意图匹配器"""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        self.registry = registry or get_registry()
        self.registry.load_all()
        self._jieba_ready = False
        self._init_jieba()

    def _init_jieba(self):
        """初始化 jieba，预加载技能触发词"""
        try:
            import jieba
            import jieba.analyse
            # 把所有触发词加入 jieba 词典
            for skill in self.registry.all_skills():
                for word in skill.trigger_words:
                    if len(word) >= 2:
                        jieba.add_word(word)
            self._jieba = jieba
            self._jieba_ready = True
        except ImportError:
            logger.warning("jieba 未安装，技能匹配降级到关键词模式")

    def match(self, text: str) -> Optional[MatchResult]:
        """
        主匹配方法：返回最佳匹配技能，或 None（走普通 AI 对话）
        """
        text = text.strip()
        if not text:
            return None

        # 第1层：精确关键词匹配（速度最快）
        result = self._keyword_match(text)
        if result and result.confidence >= HIGH_CONFIDENCE:
            logger.debug(f"关键词匹配: {result}")
            return result

        # 第2层：jieba 分词匹配（准确率更高）
        if self._jieba_ready:
            result2 = self._jieba_match(text)
            if result2 and result2.confidence >= HIGH_CONFIDENCE:
                logger.debug(f"jieba匹配: {result2}")
                return result2
            # 取两层中较好的
            if result2 and (not result or result2.confidence > result.confidence):
                result = result2

        if result and result.confidence >= LOW_CONFIDENCE:
            return result
        return None

    def _keyword_match(self, text: str) -> Optional[MatchResult]:
        """
        关键词精确匹配

        置信度公式（优化后）：
        - 短词(<=2字)命中 → +0.30
        - 中词(3-4字)命中 → +0.55
        - 长词(5+字)命中  → +0.80
        累加后 cap 到 0.99。
        """
        best_skill = None
        best_score = 0.0

        for skill in self.registry.all_skills():
            score = 0.0
            for word in skill.trigger_words:
                if word in text:
                    n = len(word)
                    if n >= 5:
                        score += 0.80
                    elif n >= 3:
                        score += 0.55
                    else:
                        score += 0.30
            if score > best_score:
                best_score = score
                best_skill = skill

        if not best_skill or best_score == 0:
            return None

        confidence = min(0.99, best_score)
        params = self._extract_params(text, best_skill)
        return MatchResult(best_skill, confidence, params)

    def _jieba_match(self, text: str) -> Optional[MatchResult]:
        """jieba 分词后计算覆盖率"""
        words = set(self._jieba.cut(text))
        best_skill = None
        best_score = 0.0

        for skill in self.registry.all_skills():
            trigger_set = set()
            for tw in skill.trigger_words:
                trigger_set.update(self._jieba.cut(tw))
            if not trigger_set:
                continue
            overlap = words & trigger_set
            if not overlap:
                continue
            score = len(overlap) / len(trigger_set)
            if score > best_score:
                best_score = score
                best_skill = skill

        if not best_skill:
            return None

        params = self._extract_params(text, best_skill)
        return MatchResult(best_skill, best_score, params)

    def _extract_params(self, text: str, skill: Skill) -> dict:
        """从用户文本中提取技能所需参数（按顺序消耗数字）"""
        params = {}
        # 预提取所有数字（按出现顺序）
        all_numbers = re.findall(r'\d+(?:\.\d+)?(?:万|亿)?', text)
        num_idx = 0  # 数字消耗指针

        for param in skill.params:
            name = param["name"]
            ptype = param.get("type", "string")
            default = param.get("default")

            if ptype == "number":
                if num_idx < len(all_numbers):
                    raw = all_numbers[num_idx]
                    num_idx += 1
                    if '亿' in raw:
                        val = float(raw.replace('亿', '')) * 100000000
                    elif '万' in raw:
                        val = float(raw.replace('万', '')) * 10000
                    else:
                        val = float(raw)
                    params[name] = val
                elif default is not None:
                    params[name] = default
            elif ptype == "city":
                # 简单城市提取
                city = self._extract_city(text)
                if city:
                    params[name] = city
                elif default is not None:
                    params[name] = default
            elif ptype == "string":
                if name == "expression":
                    # 计算器表达式：直接用用户原文，让 calc 函数处理中文
                    params[name] = text
                elif name in ("text", "id_number"):
                    # 文本处理类：用原文
                    params[name] = text
                elif default is not None:
                    params[name] = default
            else:
                if default is not None:
                    params[name] = default

        return params

    def _extract_city(self, text: str) -> Optional[str]:
        """从文本中提取城市名（简单版）"""
        # 常见城市列表（可扩展）
        CITIES = [
            "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "重庆",
            "西安", "南京", "天津", "苏州", "青岛", "大连", "厦门", "宁波",
            "长沙", "郑州", "沈阳", "哈尔滨", "济南", "福州", "合肥", "昆明",
            "南宁", "太原", "南昌", "贵阳", "石家庄", "乌鲁木齐", "银川",
            "兰州", "西宁", "拉萨", "呼和浩特", "长春", "海口", "三亚",
        ]
        for city in CITIES:
            if city in text:
                return city
        return None
