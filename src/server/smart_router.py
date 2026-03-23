# -*- coding: utf-8 -*-
"""
智能任务路由 — 根据任务类型自动选择最优 AI 模型

任务分类：
  💬 chat      — 日常对话（选最快/最便宜的）
  🧠 reasoning — 深度推理/分析（选推理能力强的）
  ✍️ writing   — 文案/创作（选中文能力强的）
  💻 coding    — 代码编写（选代码模型）
  👁️ vision    — 图片理解（选支持视觉的）
  🎨 image     — 图片生成（选图片生成模型）
  📊 data      — 数据分析（选长上下文+推理的）

设计：
  - 每个 provider 有 capabilities 标签
  - 用户消息自动检测任务类型
  - 根据任务类型+已配置的平台 → 选最优
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

# 平台+模型能力标签
PROVIDER_CAPABILITIES = {
    "zhipu_flash":      {"chat": 90, "writing": 80, "vision": 85, "reasoning": 60, "coding": 50},
    "deepseek":         {"chat": 85, "reasoning": 95, "coding": 95, "writing": 80, "data": 90, "action": 95},
    "tongyi":           {"chat": 85, "writing": 90, "reasoning": 75, "data": 85, "vision": 70},
    "baidu_speed":      {"chat": 80, "writing": 75, "reasoning": 55, "coding": 40},
    "siliconflow_free": {"chat": 75, "writing": 70, "reasoning": 60, "coding": 55},
    "moonshot":         {"chat": 80, "writing": 85, "reasoning": 70, "data": 80},
    "openai":           {"chat": 95, "reasoning": 95, "coding": 95, "writing": 90, "vision": 95, "data": 90, "action": 95},
    "gemini_flash":     {"chat": 85, "reasoning": 85, "coding": 80, "vision": 90, "writing": 80},
    "groq":             {"chat": 85, "reasoning": 80, "coding": 75},
    "ollama":           {"chat": 70, "reasoning": 65, "coding": 60},
    "cloudflare_ai":    {"chat": 65, "reasoning": 55, "coding": 50},
}

# 任务→推荐的具体模型（最强优先）
TASK_MODEL_MAP = {
    "action":    {"deepseek": "deepseek-reasoner", "openai": "gpt-4o"},           # 执行操作→最强推理
    "reasoning": {"deepseek": "deepseek-reasoner", "openai": "gpt-4o"},           # 深度推理→R1
    "coding":    {"deepseek": "deepseek-reasoner", "openai": "gpt-4o"},           # 代码→R1
    "writing":   {"deepseek": "deepseek-chat", "tongyi": "qwen-plus"},            # 文案→V3
    "chat":      {"zhipu_flash": "glm-4-flash", "deepseek": "deepseek-chat"},     # 日常→快速
    "vision":    {"zhipu_flash": "glm-4v-flash", "openai": "gpt-4o"},             # 识图→视觉模型
    "data":      {"deepseek": "deepseek-reasoner", "tongyi": "qwen-long"},        # 数据→R1/长文本
}

# 任务类型检测关键词
TASK_KEYWORDS = {
    "action":    ["帮我打开", "帮我操作", "帮我点", "帮我输入", "打开软件", "关闭窗口", "操控", "执行", "运行", "启动", "安装"],
    "reasoning": ["分析", "推理", "为什么", "原因", "逻辑", "计算", "比较", "评估", "对比", "think", "reason", "analyze"],
    "coding":    ["代码", "编程", "函数", "bug", "api", "python", "javascript", "html", "css", "sql", "程序", "debug", "code"],
    "writing":   ["写", "文案", "文章", "营销", "方案", "报告", "策划", "广告", "标题", "slogan", "创作", "故事", "剧本"],
    "vision":    ["看这张图", "图片", "截图", "这是什么", "识别", "照片", "图中", "画面"],
    "image":     ["画", "生成图", "做图", "P图", "设计图", "海报", "logo", "配图"],
    "data":      ["数据", "表格", "统计", "excel", "csv", "报表", "图表", "趋势", "指标"],
}


def detect_task_type(message: str) -> str:
    """从用户消息检测任务类型"""
    msg = message.lower()
    scores = {}
    for task_type, keywords in TASK_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in msg)
        if score > 0:
            scores[task_type] = score
    if scores:
        return max(scores, key=scores.get)
    return "chat"  # 默认对话


def get_best_model(task_type: str, configured_providers: List[str]) -> Optional[Tuple[str, str]]:
    """根据任务类型选最优平台+模型

    Returns: (provider_id, model_name) or None
    """
    model_map = TASK_MODEL_MAP.get(task_type, {})

    # 先按任务专属推荐选
    for pid in configured_providers:
        if pid in model_map:
            return (pid, model_map[pid])

    # 降级：用平台默认模型
    best_pid = get_best_provider(task_type, configured_providers)
    if best_pid:
        return (best_pid, "")  # 空字符串表示用默认
    return None


def get_best_provider(task_type: str, configured_providers: List[str]) -> Optional[str]:
    """根据任务类型从已配置的平台中选最优"""
    if not configured_providers:
        return None

    candidates = []
    for pid in configured_providers:
        caps = PROVIDER_CAPABILITIES.get(pid, {})
        score = caps.get(task_type, caps.get("chat", 50))
        candidates.append((pid, score))

    candidates.sort(key=lambda x: x[1], reverse=True)
    best = candidates[0]
    logger.debug(f"[SmartRouter] 任务={task_type}, 选择={best[0]}(score={best[1]})")
    return best[0]


def get_routing_recommendation(configured_providers: List[str]) -> List[Dict]:
    """生成智能路由推荐方案（用于前端展示）"""
    task_labels = {
        "action": "⚡ 执行操作",
        "chat": "💬 日常对话",
        "reasoning": "🧠 深度推理",
        "writing": "✍️ 文案创作",
        "coding": "💻 代码编写",
        "vision": "👁️ 图片理解",
        "data": "📊 数据分析",
    }

    recommendations = []
    for task_type, label in task_labels.items():
        result = get_best_model(task_type, configured_providers)
        if result:
            pid, model = result
            caps = PROVIDER_CAPABILITIES.get(pid, {})
            score = caps.get(task_type, caps.get("chat", 50))
            recommendations.append({
                "task_type": task_type,
                "label": label,
                "provider": pid,
                "model": model,
                "score": score,
                "status": "ready" if score >= 70 else "limited",
            })
        else:
            recommendations.append({
                "task_type": task_type,
                "label": label,
                "provider": None,
                "model": "",
                "score": 0,
                "status": "unavailable",
            })
    return recommendations


def get_setup_guide() -> List[Dict]:
    """生成引导性设置建议"""
    return [
        {
            "step": 1,
            "title": "基础对话（必须）",
            "desc": "配置至少一个 AI 平台用于日常对话",
            "recommend": "智谱 GLM-4-Flash（永久免费、无限次数）",
            "provider": "zhipu_flash",
            "priority": "必须",
        },
        {
            "step": 2,
            "title": "深度推理 + 代码（推荐）",
            "desc": "需要分析、推理或写代码时自动切换",
            "recommend": "DeepSeek（注册送 500 万 token，推理和代码能力最强）",
            "provider": "deepseek",
            "priority": "推荐",
        },
        {
            "step": 3,
            "title": "文案创作（推荐）",
            "desc": "写营销方案、文章时使用中文能力更强的模型",
            "recommend": "通义千问（阿里云，中文能力优秀）",
            "provider": "tongyi",
            "priority": "推荐",
        },
        {
            "step": 4,
            "title": "图片理解（可选）",
            "desc": "发送图片让 AI 分析内容",
            "recommend": "智谱 GLM-4V（已含在步骤1中，免费）",
            "provider": "zhipu_flash",
            "priority": "已包含",
        },
        {
            "step": 5,
            "title": "备用通道（可选）",
            "desc": "主平台不可用时自动切换到备用",
            "recommend": "百度文心/硅基流动（都是免费的）",
            "provider": "baidu_speed",
            "priority": "可选",
        },
    ]
