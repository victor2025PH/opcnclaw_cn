# -*- coding: utf-8 -*-
"""
用户画像引擎 — AI 自动从对话中学习用户信息

每次对话后，自动提取并积累：
  - 公司/品牌信息（名称、行业、规模）
  - 产品信息（产品名、卖点、定价）
  - 目标用户（年龄、职业、痛点）
  - 写作偏好（风格、常用词、禁忌词）
  - 工作习惯（常用时间、常用功能）

这些信息注入到所有 Agent 的 system prompt 中，
让 AI 越用越懂老板。

护城河：用了 3 个月后，所有 Agent 都了解你的业务，
换任何其他工具都要从零开始。

v2.0 优化：
  - 增加更多关键词模式（中英混合）
  - 写作风格自动检测（正式/口语/表情偏好）
  - 竞品自动提取
  - 团队规模提取
  - 画像变更事件通知
  - 交互计数始终递增（不论是否有新提取）
"""

from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional

from loguru import logger


# ── 用户画像数据结构 ──

DEFAULT_PROFILE = {
    "company": "",           # 公司/品牌名
    "industry": "",          # 行业
    "products": [],          # 产品列表 [{name, description, price}]
    "target_users": "",      # 目标用户描述
    "brand_tone": "",        # 品牌调性（如"专业但不严肃"）
    "writing_style": "",     # 写作风格偏好
    "forbidden_words": [],   # 禁忌词
    "common_terms": [],      # 常用术语
    "competitor_names": [],   # 竞品名称
    "budget_range": "",      # 常见预算范围
    "team_size": "",         # 团队规模
    "interaction_count": 0,  # 交互次数
    "last_updated": 0,
    "auto_style": "",        # 自动检测的写作风格
}


def get_user_profile() -> dict:
    """获取用户画像"""
    try:
        from .agent_memory import get_user_preference
        data = get_user_preference("user_profile", "")
        if data:
            profile = json.loads(data)
            # 合并默认值
            for k, v in DEFAULT_PROFILE.items():
                if k not in profile:
                    profile[k] = v
            return profile
    except Exception:
        pass
    return dict(DEFAULT_PROFILE)


def save_user_profile(profile: dict):
    """保存用户画像"""
    try:
        profile["last_updated"] = time.time()
        from .agent_memory import save_user_preference
        save_user_preference("user_profile", json.dumps(profile, ensure_ascii=False))
    except Exception:
        pass


def _extract_after(msg: str, original: str, pattern: str, max_len: int = 20) -> str:
    """从 pattern 后提取文本片段（到标点截止）"""
    idx = msg.index(pattern) + len(pattern)
    raw = original[idx:idx + max_len]
    # 在常见标点处截断
    for sep in ["，", ",", "。", ".", "！", "!", "？", "?", "；", ";", "\n", "、"]:
        if sep in raw:
            raw = raw[:raw.index(sep)]
    return raw.strip()


def _notify_profile_change(changes: List[str]):
    """通知前端画像变更（通过 EventBus）"""
    try:
        from .event_bus import get_bus
        bus = get_bus()
        bus.publish("profile_updated", {
            "changes": changes,
            "timestamp": time.time(),
        })
    except Exception:
        pass


def update_profile_from_conversation(user_message: str, ai_response: str):
    """从对话中自动提取用户信息并更新画像

    零 AI 调用，纯关键词+正则提取
    """
    profile = get_user_profile()
    changes = []

    msg = user_message.lower()
    original = user_message  # 保留原始大小写

    # ── 1. 提取公司/品牌名 ──
    company_patterns = [
        "我们公司叫", "我的公司是", "品牌名是", "品牌叫",
        "我们公司是", "公司名叫", "店铺叫", "店名是",
        "我开了一家", "我创办了",
    ]
    if not profile["company"]:
        for pattern in company_patterns:
            if pattern in msg:
                try:
                    name = _extract_after(msg, original, pattern, 20)
                    if name and 1 < len(name) <= 15:
                        profile["company"] = name
                        changes.append(f"公司: {name}")
                        break
                except ValueError:
                    pass

    # ── 2. 提取产品名 ──
    product_patterns = [
        "产品是", "产品叫", "我们做的是", "我在做", "我们卖",
        "主要产品是", "核心产品", "我们的产品", "在卖",
    ]
    for pattern in product_patterns:
        if pattern in msg:
            try:
                name = _extract_after(msg, original, pattern, 30)
                if name and 1 < len(name) <= 20:
                    if not any(p.get("name") == name for p in profile["products"]):
                        profile["products"].append({"name": name, "description": ""})
                        if len(profile["products"]) > 10:
                            profile["products"] = profile["products"][-10:]
                        changes.append(f"产品: {name}")
                    break
            except ValueError:
                pass

    # ── 3. 提取目标用户 ──
    target_patterns = [
        "面向", "目标用户是", "目标客户是", "客户群是",
        "主要客户是", "用户画像是", "服务对象是",
    ]
    if not profile["target_users"]:
        for pattern in target_patterns:
            if pattern in msg:
                try:
                    target = _extract_after(msg, original, pattern, 30)
                    if target and len(target) > 1:
                        profile["target_users"] = target
                        changes.append(f"目标用户: {target}")
                        break
                except ValueError:
                    pass

    # ── 4. 提取预算 ──
    budget_patterns = ["预算", "费用大概", "大概花", "月花", "年费"]
    if not profile["budget_range"]:
        for pattern in budget_patterns:
            if pattern in msg:
                try:
                    budget = _extract_after(msg, original, pattern, 20)
                    if budget:
                        profile["budget_range"] = budget
                        changes.append(f"预算: {budget}")
                        break
                except ValueError:
                    pass

    # ── 5. 提取行业（扩展列表）──
    industries = {
        "电商": "电商", "跨境": "跨境电商", "教育": "教育",
        "医疗": "医疗健康", "金融": "金融", "餐饮": "餐饮",
        "房产": "房地产", "科技": "科技", "农业": "农业",
        "旅游": "旅游", "物流": "物流", "制造": "制造",
        "美妆": "美妆", "服装": "服装", "母婴": "母婴",
        "宠物": "宠物", "汽车": "汽车", "游戏": "游戏",
        "直播": "直播电商", "社交": "社交", "saas": "SaaS",
        "b2b": "B2B", "外贸": "外贸", "家居": "家居",
        "食品": "食品", "健身": "健身", "律师": "法律服务",
        "会计": "财税服务", "培训": "培训", "咨询": "咨询",
    }
    if not profile["industry"]:
        for keyword, industry in industries.items():
            if keyword in msg:
                profile["industry"] = industry
                changes.append(f"行业: {industry}")
                break

    # ── 6. 提取团队规模 ──
    if not profile["team_size"]:
        team_match = re.search(r'(\d+)\s*[个人名].*?(团队|员工|人的)', msg)
        if not team_match:
            team_match = re.search(r'(团队|公司|我们).*?(\d+)\s*[个人]', msg)
        if team_match:
            profile["team_size"] = team_match.group(0)
            changes.append(f"团队: {team_match.group(0)}")

    # ── 7. 提取竞品 ──
    competitor_patterns = ["竞品是", "竞争对手是", "竞品有", "对手是", "竞品包括"]
    for pattern in competitor_patterns:
        if pattern in msg:
            try:
                raw = _extract_after(msg, original, pattern, 40)
                names = [n.strip() for n in re.split(r'[,，、和与]', raw) if n.strip()]
                for n in names:
                    if n and n not in profile["competitor_names"] and len(n) <= 15:
                        profile["competitor_names"].append(n)
                if profile["competitor_names"]:
                    profile["competitor_names"] = profile["competitor_names"][-10:]
                    changes.append(f"竞品: {', '.join(names)}")
                break
            except ValueError:
                pass

    # ── 8. 写作风格自动检测 ──
    _detect_writing_style(msg, original, profile)

    # ── 9. 常用术语自动提取 ──
    _extract_terms(msg, profile)

    # ── 更新交互计数（始终递增）──
    profile["interaction_count"] = profile.get("interaction_count", 0) + 1

    # 保存策略：有变更立即保存，否则每 3 次保存一次（风格累积+计数）
    if changes or profile["interaction_count"] % 3 == 0:
        save_user_profile(profile)
    if changes:
        _notify_profile_change(changes)
        logger.info(f"[UserProfile] 画像更新: {', '.join(changes)}")

    # ── AI 深度画像（每 20 次交互触发一次异步 AI 总结）──
    if profile["interaction_count"] % 20 == 0 and profile["interaction_count"] > 0:
        _trigger_deep_profile(user_message, ai_response, profile)


def _detect_writing_style(msg: str, original: str, profile: dict):
    """渐进式写作风格检测 — 累积多次对话的风格特征，越来越准"""
    # 只在消息足够长时分析（短消息不具代表性）
    if len(original) < 30:
        return

    # 初始化风格计数器
    if "_style_stats" not in profile:
        profile["_style_stats"] = {
            "emoji_count": 0, "formal_count": 0, "casual_count": 0,
            "long_sentence": 0, "short_sentence": 0, "samples": 0,
        }

    stats = profile["_style_stats"]
    stats["samples"] = stats.get("samples", 0) + 1

    # 检测是否使用表情
    emoji_count = len(re.findall(r'[\U0001F600-\U0001F9FF\u2600-\u26FF]', original))
    if emoji_count > 0:
        stats["emoji_count"] = stats.get("emoji_count", 0) + 1

    # 检测正式程度
    formal_words = ["您", "贵公司", "敬请", "恳请", "烦请", "谨此", "尊敬", "请问"]
    casual_words = ["哈哈", "嗯嗯", "咋", "啥", "整", "搞", "哦", "呢", "吧", "嘻嘻"]
    if any(w in original for w in formal_words):
        stats["formal_count"] = stats.get("formal_count", 0) + 1
    if any(w in original for w in casual_words):
        stats["casual_count"] = stats.get("casual_count", 0) + 1

    # 检测句子长度偏好
    sentences = re.split(r'[。！？\n，,]', original)
    sentences = [s for s in sentences if len(s.strip()) > 2]
    if sentences:
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        if avg_len > 25:
            stats["long_sentence"] = stats.get("long_sentence", 0) + 1
        elif avg_len < 8:
            stats["short_sentence"] = stats.get("short_sentence", 0) + 1

    # 每 5 个样本更新一次风格描述
    if stats["samples"] >= 5 and stats["samples"] % 5 == 0:
        traits = []
        total = stats["samples"]

        if stats.get("emoji_count", 0) > total * 0.3:
            traits.append("喜欢用表情")

        fc = stats.get("formal_count", 0)
        cc = stats.get("casual_count", 0)
        if fc > cc * 2:
            traits.append("偏正式")
        elif cc > fc * 2:
            traits.append("偏口语化")
        elif fc > 0 and cc > 0:
            traits.append("正式与口语混合")

        ls = stats.get("long_sentence", 0)
        ss = stats.get("short_sentence", 0)
        if ls > ss * 2:
            traits.append("长句偏好")
        elif ss > ls * 2:
            traits.append("简洁风格")

        if traits:
            profile["auto_style"] = "、".join(traits)


def _extract_terms(msg: str, profile: dict):
    """从对话中提取专业术语"""
    # 常见营销/商业术语
    known_terms = [
        "roi", "kpi", "kol", "koc", "gmv", "arpu", "ltv",
        "私域", "公域", "转化率", "复购率", "客单价", "获客成本",
        "种草", "拔草", "直播带货", "信息流", "seo", "sem",
        "用户增长", "裂变", "社群", "私域流量", "用户留存",
        "a/b测试", "数据中台", "用户旅程", "触达",
    ]
    existing = set(t.lower() for t in profile.get("common_terms", []))
    for term in known_terms:
        if term in msg and term not in existing:
            profile["common_terms"].append(term.upper() if len(term) <= 4 else term)
            existing.add(term)
    # 限制数量
    if len(profile["common_terms"]) > 20:
        profile["common_terms"] = profile["common_terms"][-20:]


def get_profile_context() -> str:
    """生成用户画像上下文（注入到 AI system prompt）"""
    profile = get_user_profile()

    parts = []

    if profile.get("company"):
        parts.append(f"老板的公司/品牌：{profile['company']}")
    if profile.get("industry"):
        parts.append(f"所在行业：{profile['industry']}")
    if profile.get("products"):
        names = ", ".join(p["name"] for p in profile["products"][:5])
        parts.append(f"主要产品：{names}")
    if profile.get("target_users"):
        parts.append(f"目标用户：{profile['target_users']}")
    if profile.get("brand_tone"):
        parts.append(f"品牌调性：{profile['brand_tone']}")
    if profile.get("writing_style"):
        parts.append(f"写作偏好：{profile['writing_style']}")
    elif profile.get("auto_style"):
        parts.append(f"写作风格（自动检测）：{profile['auto_style']}")
    if profile.get("budget_range"):
        parts.append(f"常见预算：{profile['budget_range']}")
    if profile.get("team_size"):
        parts.append(f"团队规模：{profile['team_size']}")
    if profile.get("forbidden_words"):
        parts.append(f"禁忌词（绝不使用）：{', '.join(profile['forbidden_words'][:10])}")
    if profile.get("common_terms"):
        parts.append(f"常用术语：{', '.join(profile['common_terms'][:10])}")
    if profile.get("competitor_names"):
        parts.append(f"竞品：{', '.join(profile['competitor_names'][:5])}")

    if not parts:
        return ""

    header = "\n\n## 关于老板（你需要了解的背景信息）\n"
    body = "\n".join(f"- {p}" for p in parts)
    footer = "\n\n> 重要：基于以上信息，你的建议和创作应该紧密贴合老板的业务场景。"
    return header + body + footer


# ── AI 深度画像（每 20 次交互，用 AI 总结对话中的业务信息）──

def _trigger_deep_profile(user_message: str, ai_response: str, profile: dict):
    """异步触发 AI 深度画像分析"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_deep_profile_async(user_message, ai_response, profile))
        else:
            # 非异步环境，跳过
            pass
    except RuntimeError:
        pass


async def _deep_profile_async(user_message: str, ai_response: str, profile: dict):
    """用 AI 分析最近对话，提取深层业务信息"""
    try:
        # 获取最近 20 条对话历史
        from . import memory as _memory
        history = _memory.get_history("default", limit=20)
        if len(history) < 6:
            return  # 对话太少，不值得 AI 分析

        # 构建对话摘要
        conversation_text = ""
        for msg in history[-20:]:
            role = "用户" if msg["role"] == "user" else "AI"
            content = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
            conversation_text += f"{role}: {content[:200]}\n"

        if len(conversation_text) < 100:
            return

        # 构建当前画像摘要
        current = json.dumps({k: v for k, v in profile.items()
                             if k not in ("interaction_count", "last_updated", "auto_style")
                             and v}, ensure_ascii=False)

        prompt = f"""分析以下对话，提取用户的业务信息。只返回 JSON，不要其他文字。

当前已知画像：
{current}

最近对话：
{conversation_text[:3000]}

请提取对话中新发现的信息，只返回有新发现的字段（已知信息不重复）：
{{
  "company": "公司名（如有新发现）",
  "industry": "行业",
  "target_users": "目标用户描述",
  "brand_tone": "品牌调性",
  "writing_style": "写作风格偏好",
  "budget_range": "预算范围",
  "team_size": "团队规模",
  "new_products": ["新发现的产品名"],
  "new_terms": ["新发现的专业术语"],
  "new_competitors": ["新发现的竞品"]
}}

规则：
- 只返回有新发现的字段，没有就返回空 {{}}
- 不要臆造，必须从对话中有明确依据
- JSON 格式，不要 markdown 代码块"""

        messages = [{"role": "user", "content": prompt}]

        # 调用 AI（复用全局路由器）
        try:
            from src.server.main import backend as _b
            if not _b:
                return
            result = await _b.chat_simple(messages)
        except Exception:
            return

        # 解析 AI 返回的 JSON
        result = result.strip()
        # 去除可能的 markdown 代码块
        if result.startswith("```"):
            result = re.sub(r'^```\w*\n?', '', result)
            result = re.sub(r'\n?```$', '', result)

        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                return

        # 合并新发现到画像
        changes = []
        for field in ("company", "industry", "target_users", "brand_tone",
                       "writing_style", "budget_range", "team_size"):
            val = data.get(field, "")
            if val and not profile.get(field):
                profile[field] = val
                changes.append(f"{field}: {val}")

        # 合并新产品
        for name in data.get("new_products", []):
            if name and not any(p.get("name") == name for p in profile["products"]):
                profile["products"].append({"name": name, "description": ""})
                changes.append(f"产品: {name}")

        # 合并新术语
        existing_terms = set(t.lower() for t in profile.get("common_terms", []))
        for term in data.get("new_terms", []):
            if term and term.lower() not in existing_terms:
                profile["common_terms"].append(term)
                changes.append(f"术语: {term}")

        # 合并新竞品
        for name in data.get("new_competitors", []):
            if name and name not in profile.get("competitor_names", []):
                profile["competitor_names"].append(name)
                changes.append(f"竞品: {name}")

        if changes:
            save_user_profile(profile)
            _notify_profile_change([f"[AI深度分析] {c}" for c in changes])
            logger.info(f"[UserProfile] AI 深度画像更新: {', '.join(changes)}")

    except Exception as e:
        logger.debug(f"[UserProfile] AI 深度分析失败: {e}")
