# -*- coding: utf-8 -*-
"""
工作流模板商店

功能：
  1. 内置模板库：提供常用自动化场景的一键安装
  2. 导入/导出：将工作流序列化为 JSON 分享文件
  3. 模板评分：简单的使用次数统计

设计决策：
  模板和工作流共用相同的 Workflow 模型。
  模板是特殊标记的工作流（category='template'），
  "安装"一个模板就是复制一份到用户的 workflows 中。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from .models import NodeDef, NodeType, Trigger, TriggerType, Workflow
from . import store


# ── 内置模板 ─────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    {
        "id": "tpl_morning_brief",
        "name": "晨间简报",
        "description": "每天早上 8:00 自动播报天气、待办和激励语",
        "category": "daily",
        "tags": ["定时", "天气", "TTS"],
        "trigger": {"type": "schedule", "schedule_time": "08:00"},
        "nodes": [
            {"id": "n1", "type": "system_info", "params": {"info_type": "datetime"}},
            {"id": "n2", "type": "http_request", "params": {"url": "https://api.open-meteo.com/v1/forecast?latitude=39.9&longitude=116.4&current_weather=true"}},
            {"id": "n3", "type": "llm_generate", "params": {"prompt": "根据天气信息 {{n2.output}} 和日期 {{n1.output}}，生成一段活力满满的晨间问候（50字内）"}},
            {"id": "n4", "type": "tts_speak", "params": {"text": "{{n3.output}}"}},
        ],
    },
    {
        "id": "tpl_auto_reply_vip",
        "name": "VIP 客户自动回复",
        "description": "VIP 标签客户来消息时自动触发 AI 高质量回复",
        "category": "wechat",
        "tags": ["微信", "自动回复", "客户"],
        "trigger": {"type": "event", "event_name": "wechat_message"},
        "nodes": [
            {"id": "n1", "type": "condition", "params": {"expression": "'VIP' in context.get('tags','')"}},
            {"id": "n2", "type": "llm_generate", "params": {"prompt": "你是专业的客户顾问。客户 {{contact}} 说: {{message}}。请给出专业且友好的回复。"}},
            {"id": "n3", "type": "wechat_send", "params": {"contact": "{{contact}}", "message": "{{n2.output}}"}},
        ],
    },
    {
        "id": "tpl_moments_auto",
        "name": "朋友圈定时互动",
        "description": "每天下午浏览朋友圈并自动点赞/评论",
        "category": "moments",
        "tags": ["朋友圈", "自动化", "定时"],
        "trigger": {"type": "schedule", "schedule_time": "14:00"},
        "nodes": [
            {"id": "n1", "type": "wechat_read", "params": {"target": "moments", "count": 10}},
            {"id": "n2", "type": "llm_generate", "params": {"prompt": "分析以下朋友圈动态，选择适合点赞和评论的：{{n1.output}}"}},
        ],
    },
    {
        "id": "tpl_daily_report",
        "name": "日报自动生成",
        "description": "每天 18:00 汇总今日消息和操作，生成工作日报",
        "category": "daily",
        "tags": ["定时", "报告", "自动化"],
        "trigger": {"type": "schedule", "schedule_time": "18:00"},
        "nodes": [
            {"id": "n1", "type": "system_info", "params": {"info_type": "datetime"}},
            {"id": "n2", "type": "llm_generate", "params": {"prompt": "今天是 {{n1.output}}，请生成一份简洁的日报模板，包含：今日完成、遇到问题、明日计划三个部分。"}},
            {"id": "n3", "type": "tts_speak", "params": {"text": "日报已生成：{{n2.output}}"}},
        ],
    },
    {
        "id": "tpl_keyword_alert",
        "name": "关键词消息预警",
        "description": "当消息中出现指定关键词时，立即 TTS 提醒",
        "category": "wechat",
        "tags": ["微信", "预警", "关键词"],
        "trigger": {"type": "event", "event_name": "wechat_message"},
        "nodes": [
            {"id": "n1", "type": "condition", "params": {"expression": "any(kw in context.get('message','') for kw in ['紧急','urgent','ASAP','马上'])"}},
            {"id": "n2", "type": "tts_speak", "params": {"text": "注意！收到来自 {{contact}} 的紧急消息：{{message}}"}},
        ],
    },
    {
        "id": "tpl_broadcast_holiday",
        "name": "节日祝福群发",
        "description": "一键向所有好友发送 AI 个性化节日祝福",
        "category": "wechat",
        "tags": ["微信", "群发", "节日"],
        "trigger": {"type": "manual"},
        "nodes": [
            {"id": "n1", "type": "llm_generate", "params": {"prompt": "生成一段温暖的节日祝福，适合发给好友（30字内）"}},
            {"id": "n2", "type": "wechat_send", "params": {"contact": "{{broadcast_list}}", "message": "{{n1.output}}"}},
        ],
    },
    {
        "id": "tpl_health_check",
        "name": "账号健康巡检",
        "description": "每小时检查所有账号连接状态，异常时 TTS 报警",
        "category": "system",
        "tags": ["系统", "监控", "定时"],
        "trigger": {"type": "interval", "interval_seconds": 3600},
        "nodes": [
            {"id": "n1", "type": "http_request", "params": {"url": "http://localhost:8766/api/health/overview"}},
            {"id": "n2", "type": "condition", "params": {"expression": "context.get('n1',{}).get('danger_count',0) > 0"}},
            {"id": "n3", "type": "tts_speak", "params": {"text": "警告：有账号健康状态异常，请检查管理面板。"}},
        ],
    },
    {
        "id": "tpl_focus_mode",
        "name": "专注模式",
        "description": "启动后暂停微信自动回复 2 小时，之后自动恢复",
        "category": "daily",
        "tags": ["专注", "定时", "微信"],
        "trigger": {"type": "manual"},
        "nodes": [
            {"id": "n1", "type": "http_request", "params": {"url": "http://localhost:8766/api/wechat/config", "method": "POST", "body": {"enabled": False}}},
            {"id": "n2", "type": "tts_speak", "params": {"text": "专注模式已开启，微信自动回复已暂停。2小时后自动恢复。"}},
            {"id": "n3", "type": "delay", "params": {"seconds": 7200}},
            {"id": "n4", "type": "http_request", "params": {"url": "http://localhost:8766/api/wechat/config", "method": "POST", "body": {"enabled": True}}},
            {"id": "n5", "type": "tts_speak", "params": {"text": "专注模式已结束，微信自动回复已恢复。"}},
        ],
    },
]


# ── 模板操作 ─────────────────────────────────────────────────────────────────

def list_templates(category: str = "") -> List[Dict]:
    """列出所有可用模板"""
    templates = BUILTIN_TEMPLATES
    if category:
        templates = [t for t in templates if t.get("category") == category]
    return templates


def get_template(template_id: str) -> Optional[Dict]:
    """获取模板详情"""
    for t in BUILTIN_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def install_template(template_id: str, custom_name: str = "") -> Optional[str]:
    """
    安装模板 → 创建工作流实例。

    返回新创建的工作流 ID。
    """
    tpl = get_template(template_id)
    if not tpl:
        return None

    wf_id = f"wf_{str(uuid.uuid4())[:8]}"
    trigger_data = tpl.get("trigger", {})
    trigger = Trigger(
        type=TriggerType(trigger_data.get("type", "manual")),
        time=trigger_data.get("schedule_time", trigger_data.get("time", "")),
        seconds=trigger_data.get("interval_seconds", trigger_data.get("seconds", 0)),
        event=trigger_data.get("event_name", trigger_data.get("event", "")),
    )

    nodes = []
    for nd in tpl.get("nodes", []):
        nodes.append(NodeDef(
            id=nd["id"],
            type=nd["type"],
            params=nd.get("params", {}),
        ))

    wf = Workflow(
        id=wf_id,
        name=custom_name or tpl["name"],
        description=tpl.get("description", ""),
        trigger=trigger,
        nodes=nodes,
        enabled=False,
        category=tpl.get("category", "custom"),
        tags=tpl.get("tags", []),
        created_at=time.time(),
    )

    store.save_workflow(wf)
    logger.info(f"[TemplateStore] 安装模板 {tpl['name']} → {wf_id}")
    return wf_id


def export_workflow(wf_id: str) -> Optional[Dict]:
    """导出工作流为可分享的 JSON"""
    wf = store.get_workflow(wf_id)
    if not wf:
        return None
    data = wf.to_dict()
    data["_export_version"] = "1.0"
    data["_exported_at"] = time.time()
    # 清除实例相关字段
    data.pop("created_at", None)
    data.pop("updated_at", None)
    return data


def import_workflow(data: Dict, custom_name: str = "") -> Optional[str]:
    """从 JSON 导入工作流"""
    try:
        if custom_name:
            data["name"] = custom_name
        # 生成新 ID 避免冲突
        data["id"] = f"wf_{str(uuid.uuid4())[:8]}"
        data["created_at"] = time.time()
        data["enabled"] = False
        wf = Workflow.from_dict(data)
        store.save_workflow(wf)
        logger.info(f"[TemplateStore] 导入工作流: {wf.name} → {wf.id}")
        return wf.id
    except Exception as e:
        logger.warning(f"[TemplateStore] 导入失败: {e}")
        return None


def get_template_categories() -> List[Dict]:
    """获取模板分类"""
    cats = {}
    for t in BUILTIN_TEMPLATES:
        cat = t.get("category", "other")
        if cat not in cats:
            cats[cat] = {"category": cat, "count": 0}
        cats[cat]["count"] += 1

    CATEGORY_LABELS = {
        "daily": "日常",
        "wechat": "微信",
        "moments": "朋友圈",
        "system": "系统",
    }
    for c in cats.values():
        c["label"] = CATEGORY_LABELS.get(c["category"], c["category"])

    return sorted(cats.values(), key=lambda c: c["count"], reverse=True)
