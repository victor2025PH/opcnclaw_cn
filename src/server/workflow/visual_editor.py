# -*- coding: utf-8 -*-
"""
工作流可视化编辑器后端

提供：
  1. 工作流 JSON ↔ 可视化表单数据的双向转换
  2. Cron 表达式 → 自然语言描述
  3. 工作流模拟执行（dry-run）
  4. 节点参数校验

设计决策：
  前端用纯 HTML 表单 + CSS 步骤条（不引入 React Flow 等重框架），
  后端提供校验和转换，确保轻量可维护。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from .models import NodeType, TriggerType, Trigger, NodeDef, Workflow


# ── Trigger 可视化描述 ───────────────────────────────────────────────────────

DAY_CN = {"mon": "周一", "tue": "周二", "wed": "周三", "thu": "周四",
          "fri": "周五", "sat": "周六", "sun": "周日"}


def trigger_to_human(trigger: Dict) -> str:
    """将触发器配置转为自然语言"""
    t_type = trigger.get("type", "manual")

    if t_type == "manual":
        return "手动触发"

    if t_type == "schedule":
        time_str = trigger.get("time", "00:00")
        days = trigger.get("days", [])
        if days:
            day_str = "、".join(DAY_CN.get(d, d) for d in days)
            return f"每{day_str} {time_str} 执行"
        return f"每天 {time_str} 执行"

    if t_type == "interval":
        secs = trigger.get("seconds", 0)
        if secs >= 3600:
            return f"每 {secs // 3600} 小时执行一次"
        if secs >= 60:
            return f"每 {secs // 60} 分钟执行一次"
        return f"每 {secs} 秒执行一次"

    if t_type == "event":
        event = trigger.get("event", "")
        event_cn = {
            "wechat_message": "收到微信消息时",
            "voice_command": "收到语音指令时",
            "api_call": "API 调用时",
            "moments_update": "朋友圈更新时",
        }
        return event_cn.get(event, f"事件「{event}」触发时")

    return "未知触发方式"


# ── Node 描述 ────────────────────────────────────────────────────────────────

NODE_DESCRIPTIONS = {
    "llm_generate": {"icon": "🤖", "label": "AI 生成", "color": "#89b4fa"},
    "llm_classify": {"icon": "🏷️", "label": "AI 分类", "color": "#89b4fa"},
    "template": {"icon": "📝", "label": "模板填充", "color": "#a6e3a1"},
    "tts_speak": {"icon": "🔊", "label": "语音播报", "color": "#f9e2af"},
    "wechat_send": {"icon": "💬", "label": "微信发送", "color": "#a6e3a1"},
    "wechat_read": {"icon": "📨", "label": "微信读取", "color": "#a6e3a1"},
    "wechat_autoreply": {"icon": "🤖", "label": "自动回复", "color": "#a6e3a1"},
    "delay": {"icon": "⏱️", "label": "延时等待", "color": "#cdd6f4"},
    "condition": {"icon": "🔀", "label": "条件分支", "color": "#f9e2af"},
    "http_request": {"icon": "🌐", "label": "HTTP 请求", "color": "#cba6f7"},
    "notify": {"icon": "📢", "label": "通知推送", "color": "#f38ba8"},
    "system_info": {"icon": "ℹ️", "label": "系统信息", "color": "#cdd6f4"},
    "file_read": {"icon": "📄", "label": "读取文件", "color": "#cdd6f4"},
    "file_write": {"icon": "💾", "label": "写入文件", "color": "#cdd6f4"},
    "skill_execute": {"icon": "🧩", "label": "执行技能", "color": "#cba6f7"},
    "python_eval": {"icon": "🐍", "label": "Python 脚本", "color": "#f9e2af"},
    "loop": {"icon": "🔁", "label": "循环", "color": "#f9e2af"},
    "parallel": {"icon": "⚡", "label": "并行执行", "color": "#f9e2af"},
}


def node_type_info() -> List[Dict]:
    """返回所有可用节点类型的描述"""
    result = []
    for nt in NodeType:
        desc = NODE_DESCRIPTIONS.get(nt.value, {})
        result.append({
            "type": nt.value,
            "icon": desc.get("icon", "📦"),
            "label": desc.get("label", nt.value),
            "color": desc.get("color", "#cdd6f4"),
        })
    return result


# ── 工作流 → 可视化数据 ─────────────────────────────────────────────────────

def workflow_to_visual(wf: Dict) -> Dict:
    """将工作流 JSON 转为前端渲染需要的可视化数据"""
    trigger = wf.get("trigger", {})
    nodes = wf.get("nodes", [])

    visual_nodes = []
    for i, n in enumerate(nodes):
        n_type = n.get("type", "template")
        desc = NODE_DESCRIPTIONS.get(n_type, {})
        visual_nodes.append({
            "index": i,
            "id": n.get("id", f"node_{i}"),
            "type": n_type,
            "icon": desc.get("icon", "📦"),
            "label": desc.get("label", n_type),
            "color": desc.get("color", "#cdd6f4"),
            "params": n.get("params", {}),
            "name": n.get("name", ""),
        })

    return {
        "id": wf.get("id", ""),
        "name": wf.get("name", ""),
        "trigger": trigger,
        "trigger_human": trigger_to_human(trigger),
        "nodes": visual_nodes,
        "node_count": len(visual_nodes),
        "enabled": wf.get("enabled", True),
    }


# ── 节点参数校验 ─────────────────────────────────────────────────────────────

REQUIRED_PARAMS = {
    "wechat_send": ["contact", "message"],
    "http_request": ["url"],
    "delay": ["seconds"],
    "tts_speak": ["text"],
    "llm_generate": ["prompt"],
    "condition": ["expression"],
    "template": ["template"],
    "file_read": ["path"],
    "file_write": ["path", "content"],
    "loop": ["count"],
}


def validate_workflow(wf_data: Dict) -> List[str]:
    """校验工作流数据，返回错误列表"""
    errors = []

    # 触发器校验
    trigger = wf_data.get("trigger", {})
    t_type = trigger.get("type", "manual")
    if t_type == "schedule" and not trigger.get("time"):
        errors.append("定时触发器缺少执行时间")
    if t_type == "interval" and not trigger.get("seconds"):
        errors.append("间隔触发器缺少间隔秒数")
    if t_type == "event" and not trigger.get("event"):
        errors.append("事件触发器缺少事件名称")

    # 节点校验
    nodes = wf_data.get("nodes", [])
    if not nodes:
        errors.append("工作流至少需要一个节点")

    for i, node in enumerate(nodes):
        n_type = node.get("type", "")
        if n_type not in [nt.value for nt in NodeType]:
            errors.append(f"节点 {i+1}: 未知类型 '{n_type}'")
            continue

        required = REQUIRED_PARAMS.get(n_type, [])
        params = node.get("params", {})
        for p in required:
            if not params.get(p):
                n_name = node.get("name") or NODE_DESCRIPTIONS.get(n_type, {}).get("label", n_type)
                errors.append(f"节点「{n_name}」缺少参数: {p}")

    return errors


# ── Dry-run 模拟 ─────────────────────────────────────────────────────────────

def dry_run(wf_data: Dict) -> List[Dict]:
    """模拟执行工作流，返回每步的预期行为"""
    steps = []
    context = {}

    nodes = wf_data.get("nodes", [])
    for i, node in enumerate(nodes):
        n_type = node.get("type", "")
        params = node.get("params", {})
        desc = NODE_DESCRIPTIONS.get(n_type, {})

        step = {
            "step": i + 1,
            "type": n_type,
            "icon": desc.get("icon", "📦"),
            "label": desc.get("label", n_type),
            "action": "",
            "output_key": node.get("id", f"node_{i}"),
        }

        if n_type == "llm_generate":
            step["action"] = f"AI 生成文本（提示词: {params.get('prompt', '')[:30]}...）"
        elif n_type == "wechat_send":
            step["action"] = f"发送微信消息给 {params.get('contact', '?')}"
        elif n_type == "tts_speak":
            step["action"] = f"语音播报: {params.get('text', '')[:30]}..."
        elif n_type == "delay":
            step["action"] = f"等待 {params.get('seconds', 0)} 秒"
        elif n_type == "http_request":
            step["action"] = f"{params.get('method', 'GET')} {params.get('url', '')[:40]}"
        elif n_type == "condition":
            step["action"] = f"条件判断: {params.get('expression', '')[:40]}"
        elif n_type == "template":
            step["action"] = f"模板填充"
        else:
            step["action"] = f"执行 {desc.get('label', n_type)}"

        steps.append(step)

    return steps
