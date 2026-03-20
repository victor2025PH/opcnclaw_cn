# -*- coding: utf-8 -*-
"""
国际化 (i18n) 支持

轻量级键值对翻译系统，支持中英文切换。

设计决策：
  方案A: gettext (.po/.mo 文件) → 标准但重，需要编译工具
  方案B: JSON 翻译文件 → 需要文件 IO，增加部署复杂度
  方案C: Python 字典内嵌 → 零依赖、零文件、即改即用、选这个

  当前只需中英双语，字典方案最轻量。
  未来扩展到 3+ 语言时可迁移到 JSON 文件方案。
"""

from __future__ import annotations

from typing import Dict, Optional

# 当前语言（全局状态）
_current_lang: str = "zh"


# ── 翻译字典 ─────────────────────────────────────────────────────────────────

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # ── 通用 ──
    "app_name": {"zh": "十三香小龙虾 语音助手", "en": "十三香小龙虾 Assistant"},
    "loading": {"zh": "加载中...", "en": "Loading..."},
    "save": {"zh": "保存", "en": "Save"},
    "cancel": {"zh": "取消", "en": "Cancel"},
    "delete": {"zh": "删除", "en": "Delete"},
    "enable": {"zh": "启用", "en": "Enable"},
    "disable": {"zh": "禁用", "en": "Disable"},
    "refresh": {"zh": "刷新", "en": "Refresh"},
    "search": {"zh": "搜索", "en": "Search"},
    "confirm": {"zh": "确认", "en": "Confirm"},
    "ok": {"zh": "确定", "en": "OK"},
    "error": {"zh": "错误", "en": "Error"},
    "success": {"zh": "成功", "en": "Success"},
    "no_data": {"zh": "暂无数据", "en": "No data"},

    # ── Admin 导航 ──
    "nav_dashboard": {"zh": "仪表盘", "en": "Dashboard"},
    "nav_wechat": {"zh": "微信管理", "en": "WeChat"},
    "nav_workflows": {"zh": "工作流", "en": "Workflows"},
    "nav_moments": {"zh": "朋友圈", "en": "Moments"},
    "nav_contacts": {"zh": "联系人", "en": "Contacts"},
    "nav_broadcast": {"zh": "群发消息", "en": "Broadcast"},
    "nav_accounts": {"zh": "多账号", "en": "Accounts"},
    "nav_inbox": {"zh": "统一收件箱", "en": "Unified Inbox"},
    "nav_knowledge": {"zh": "知识库", "en": "Knowledge Base"},
    "nav_daily_report": {"zh": "智能日报", "en": "Daily Report"},
    "nav_bigscreen": {"zh": "数据大屏", "en": "Big Screen"},
    "nav_sentiment": {"zh": "情感分析", "en": "Sentiment"},
    "nav_groups": {"zh": "群聊管理", "en": "Groups"},
    "nav_editor": {"zh": "流程编辑", "en": "Workflow Editor"},
    "nav_plugins": {"zh": "插件市场", "en": "Plugins"},
    "nav_templates": {"zh": "模板商店", "en": "Template Store"},
    "nav_monitor": {"zh": "性能监控", "en": "Monitor"},
    "nav_settings": {"zh": "设置", "en": "Settings"},
    "nav_search": {"zh": "搜索记录", "en": "Search History"},
    "nav_health": {"zh": "系统自检", "en": "Health Check"},
    "nav_audit": {"zh": "审计日志", "en": "Audit Log"},

    # ── 日报 ──
    "report_score": {"zh": "综合评分", "en": "Score"},
    "report_messages_received": {"zh": "收到消息", "en": "Messages Received"},
    "report_messages_sent": {"zh": "发送消息", "en": "Messages Sent"},
    "report_accounts_online": {"zh": "在线账号", "en": "Online Accounts"},
    "report_workflow_runs": {"zh": "工作流执行", "en": "Workflow Runs"},
    "report_ai_insight": {"zh": "AI 洞察", "en": "AI Insight"},
    "report_generate": {"zh": "生成日报", "en": "Generate Report"},

    # ── 情感分析 ──
    "sentiment_positive": {"zh": "正面", "en": "Positive"},
    "sentiment_neutral": {"zh": "中性", "en": "Neutral"},
    "sentiment_negative": {"zh": "负面", "en": "Negative"},
    "sentiment_mood": {"zh": "今日情绪", "en": "Today's Mood"},
    "sentiment_trend": {"zh": "情感趋势", "en": "Sentiment Trend"},

    # ── 插件 ──
    "plugin_running": {"zh": "运行中", "en": "Running"},
    "plugin_disabled": {"zh": "已禁用", "en": "Disabled"},
    "plugin_error": {"zh": "错误", "en": "Error"},

    # ── 健康检查 ──
    "health_healthy": {"zh": "系统正常", "en": "Healthy"},
    "health_degraded": {"zh": "部分异常", "en": "Degraded"},
    "health_unhealthy": {"zh": "系统异常", "en": "Unhealthy"},
    "health_run_check": {"zh": "执行检查", "en": "Run Check"},

    # ── 审计 ──
    "audit_action": {"zh": "操作", "en": "Action"},
    "audit_user": {"zh": "操作者", "en": "User"},
    "audit_time": {"zh": "时间", "en": "Time"},
    "audit_detail": {"zh": "详情", "en": "Detail"},
}


# ── API ──────────────────────────────────────────────────────────────────────

def t(key: str, lang: str = "") -> str:
    """翻译函数。返回指定语言的文本，找不到则返回 key 本身。"""
    lang = lang or _current_lang
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang, entry.get("zh", key))


def set_language(lang: str):
    """设置全局语言"""
    global _current_lang
    if lang in ("zh", "en"):
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def get_all_translations(lang: str = "") -> Dict[str, str]:
    """获取指定语言的全部翻译（前端一次性加载用）"""
    lang = lang or _current_lang
    return {key: entry.get(lang, entry.get("zh", key)) for key, entry in TRANSLATIONS.items()}


def get_supported_languages() -> list:
    return [
        {"code": "zh", "name": "中文", "native": "中文"},
        {"code": "en", "name": "English", "native": "English"},
    ]
