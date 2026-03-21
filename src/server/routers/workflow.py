# -*- coding: utf-8 -*-
"""Workflow engine, templates, visual editor, calendar routes"""
from __future__ import annotations
import json, time, calendar as cal_mod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from loguru import logger

from ..auth import token_manager

router = APIRouter()

try:
    from ..workflow import get_engine as get_wf_engine, store as wf_store
    from ..workflow.nodes import get_available_nodes as wf_available_nodes
    _WORKFLOW_AVAILABLE = True
except ImportError:
    _WORKFLOW_AVAILABLE = False


# ── 工作流 API ──────────────────────────────────────────────────────────────────

@router.get("/admin")
@router.get("/admin/")
async def admin_page():
    """Serve the admin dashboard."""
    admin_path = Path(__file__).parent.parent.parent / "client" / "admin.html"
    if admin_path.exists():
        return FileResponse(str(admin_path))
    return Response(content="Admin page not found", status_code=404)


@router.get("/admin-manifest.json")
async def admin_manifest():
    p = Path(__file__).parent.parent.parent / "client" / "admin-manifest.json"
    return FileResponse(str(p), media_type="application/manifest+json") if p.exists() else Response("", 404)


@router.get("/admin-sw.js")
async def admin_sw():
    p = Path(__file__).parent.parent.parent / "client" / "admin-sw.js"
    return FileResponse(str(p), media_type="application/javascript") if p.exists() else Response("", 404)


@router.get("/api/workflow/status")
async def workflow_status():
    if not _WORKFLOW_AVAILABLE:
        return {"available": False}
    engine = get_wf_engine()
    return {"available": True, **engine.get_status()}


@router.get("/api/workflow/nodes")
async def workflow_node_types():
    if not _WORKFLOW_AVAILABLE:
        return {"nodes": []}
    return {"nodes": wf_available_nodes()}


@router.get("/api/workflow/list")
async def workflow_list(category: str = ""):
    if not _WORKFLOW_AVAILABLE:
        return {"workflows": []}
    wfs = wf_store.list_workflows(category=category or None)
    return {"workflows": [w.to_dict() for w in wfs]}


@router.get("/api/workflow/{wf_id}")
async def workflow_get(wf_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    wf = wf_store.get_workflow(wf_id)
    if not wf:
        return {"error": f"工作流 {wf_id} 不存在"}
    return {"workflow": wf.to_dict()}


@router.post("/api/workflow/save")
async def workflow_save(request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json()
    try:
        from ..workflow.models import Workflow
        wf = Workflow.from_dict(data)
        wf.updated_at = __import__("time").time()
        wf_store.save_workflow(wf)
        get_wf_engine().reload_listeners()
        return {"ok": True, "id": wf.id}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/workflow/{wf_id}")
async def workflow_delete(wf_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ok = wf_store.delete_workflow(wf_id)
    if ok:
        get_wf_engine().reload_listeners()
    return {"ok": ok}


@router.post("/api/workflow/{wf_id}/toggle")
async def workflow_toggle(wf_id: str, request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json()
    enabled = data.get("enabled", False)
    ok = wf_store.toggle_workflow(wf_id, enabled)
    if ok:
        get_wf_engine().reload_listeners()
    return {"ok": ok}


@router.post("/api/workflow/{wf_id}/execute")
async def workflow_execute(wf_id: str, request: Request):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    data = await request.json() if request.headers.get("content-type") else {}
    engine = get_wf_engine()

    from ..main import _wechat_adapter, _wechat_engine
    if engine.wechat_adapter is None and _wechat_adapter:
        engine.wechat_adapter = _wechat_adapter
    if engine.wechat_engine is None and _wechat_engine:
        engine.wechat_engine = _wechat_engine

    ex = await engine.execute(wf_id, trigger_type="manual", event_data=data)
    try:
        from .. import audit_log
        audit_log.log("workflow_run", target=wf_id, detail=f"status={ex.status.value}")
    except Exception:
        pass
    return {"ok": ex.status.value == "success", "execution": ex.to_dict()}


@router.get("/api/workflow/executions")
async def workflow_executions(
    workflow_id: str = "",
    limit: int = 50,
    offset: int = 0,
):
    if not _WORKFLOW_AVAILABLE:
        return {"executions": [], "total": 0}
    execs = wf_store.list_executions(
        workflow_id=workflow_id or None, limit=limit, offset=offset
    )
    total = wf_store.count_executions(workflow_id=workflow_id or None)
    return {
        "executions": [e.to_dict() for e in execs],
        "total": total,
    }


@router.get("/api/workflow/executions/{ex_id}")
async def workflow_execution_detail(ex_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ex = wf_store.get_execution(ex_id)
    if not ex:
        return {"error": "执行记录不存在"}
    return {"execution": ex.to_dict()}


@router.post("/api/workflow/executions/{ex_id}/cancel")
async def workflow_execution_cancel(ex_id: str):
    if not _WORKFLOW_AVAILABLE:
        return {"error": "工作流不可用"}
    ok = get_wf_engine().cancel_execution(ex_id)
    return {"ok": ok}


@router.get("/api/usage")
async def get_usage(api_key: str):
    """
    Get usage stats for an API key.
    
    curl "http://localhost:8765/api/usage?api_key=ocv_xxx"
    """
    key = token_manager.validate_key(api_key)
    if not key:
        return {"error": "Invalid API key"}
    
    return token_manager.get_usage(key)


# ── 工作流模板 API ───────────────────────────────────────────────────────────

@router.get("/api/templates")
async def templates_list(category: str = ""):
    from ..workflow.template_store import list_templates, get_template_categories
    return {"ok": True, "templates": list_templates(category), "categories": get_template_categories()}


@router.get("/api/templates/{tpl_id}")
async def templates_detail(tpl_id: str):
    from ..workflow.template_store import get_template
    tpl = get_template(tpl_id)
    return {"ok": True, "template": tpl} if tpl else {"ok": False, "error": "模板不存在"}


@router.post("/api/templates/{tpl_id}/install")
async def templates_install(tpl_id: str, request: Request):
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    from ..workflow.template_store import install_template
    wf_id = install_template(tpl_id, custom_name=data.get("name", ""))
    if wf_id:
        return {"ok": True, "workflow_id": wf_id}
    return {"ok": False, "error": "安装失败"}


@router.get("/api/workflows/{wf_id}/export")
async def workflow_export(wf_id: str):
    from ..workflow.template_store import export_workflow
    data = export_workflow(wf_id)
    if data:
        return {"ok": True, "workflow": data}
    return {"ok": False, "error": "工作流不存在"}


@router.post("/api/workflows/import")
async def workflow_import(request: Request):
    data = await request.json()
    from ..workflow.template_store import import_workflow
    wf_data = data.get("workflow", data)
    wf_id = import_workflow(wf_data, custom_name=data.get("name", ""))
    if wf_id:
        return {"ok": True, "workflow_id": wf_id}
    return {"ok": False, "error": "导入失败"}


# ── 工作流可视化编辑器 API ───────────────────────────────────────────────────

@router.get("/api/workflow-editor/node-types")
async def wf_editor_node_types():
    from ..workflow.visual_editor import node_type_info
    return {"ok": True, "types": node_type_info()}


@router.post("/api/workflow-editor/visualize")
async def wf_editor_visualize(request: Request):
    data = await request.json()
    from ..workflow.visual_editor import workflow_to_visual
    return {"ok": True, **workflow_to_visual(data)}


@router.post("/api/workflow-editor/validate")
async def wf_editor_validate(request: Request):
    data = await request.json()
    from ..workflow.visual_editor import validate_workflow
    errors = validate_workflow(data)
    return {"ok": len(errors) == 0, "errors": errors}


@router.post("/api/workflow-editor/dry-run")
async def wf_editor_dry_run(request: Request):
    data = await request.json()
    from ..workflow.visual_editor import dry_run
    steps = dry_run(data)
    return {"ok": True, "steps": steps}


# ── 统一日历 API ──────────────────────────────────────────────────────────────

@router.get("/api/calendar")
async def calendar_events(year: int = 0, month: int = 0):
    """
    聚合所有定时任务到统一日历视图。
    来源：工作流定时/周期触发、朋友圈内容日历、群发计划。
    """
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    _, days_in_month = cal_mod.monthrange(y, m)

    events = []

    # 1. 工作流定时任务
    try:
        from ..workflow.store import store
        from ..workflow.models import TriggerType
        all_wf = store.list_workflows()
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        for wf in all_wf:
            if not wf.enabled:
                continue
            t = wf.trigger
            if t.type == TriggerType.SCHEDULE and t.time:
                for d in range(1, days_in_month + 1):
                    dt = datetime(y, m, d)
                    weekday = day_names[dt.weekday()]
                    if t.days and weekday not in t.days:
                        continue
                    events.append({
                        "date": f"{y}-{m:02d}-{d:02d}",
                        "time": t.time,
                        "title": wf.name,
                        "icon": wf.icon or "🔄",
                        "type": "workflow",
                        "id": wf.id,
                    })
            elif t.type == TriggerType.INTERVAL and t.seconds > 0:
                events.append({
                    "date": f"{y}-{m:02d}-01",
                    "time": "",
                    "title": f"{wf.name} (每{t.seconds//60}分钟)",
                    "icon": wf.icon or "🔄",
                    "type": "interval",
                    "id": wf.id,
                })
    except Exception:
        pass

    # 2. 朋友圈内容日历
    try:
        from ..wechat.moments_tracker import ContentCalendar
        calendar = ContentCalendar()
        for entry in calendar.list_entries(y, m):
            events.append({
                "date": entry.get("date", ""),
                "time": entry.get("time", "12:00"),
                "title": entry.get("topic", "朋友圈发布"),
                "icon": "📢",
                "type": "moment",
                "id": entry.get("id", ""),
            })
    except Exception:
        pass

    # 3. 执行历史热力数据
    heatmap = {}
    try:
        from ..workflow.store import store as wf_store_inst
        execs = wf_store_inst.list_executions(limit=500)
        for ex in execs:
            if ex.started_at:
                from datetime import datetime as _dt
                d = _dt.fromtimestamp(ex.started_at)
                if d.year == y and d.month == m:
                    key = f"{y}-{m:02d}-{d.day:02d}"
                    heatmap[key] = heatmap.get(key, 0) + 1
    except Exception:
        pass

    return {"ok": True, "year": y, "month": m, "events": events, "heatmap": heatmap}


# ── RESTful 别名（供 Cursor 前端使用）─────────────────────────

@router.get("/api/workflows")
async def workflows_list_alias(category: str = ""):
    """别名：GET /api/workflows → /api/workflow/list"""
    return await workflow_list(category)


@router.post("/api/workflows")
async def workflows_create_alias(request: Request):
    """别名：POST /api/workflows → /api/workflow/save"""
    return await workflow_save(request)


@router.put("/api/workflows/{wf_id}")
async def workflows_update_alias(wf_id: str, request: Request):
    """别名：PUT /api/workflows/{id} → /api/workflow/save (含ID)"""
    return await workflow_save(request)


@router.post("/api/workflows/{wf_id}/run")
async def workflows_run_alias(wf_id: str, request: Request):
    """别名：POST /api/workflows/{id}/run → /api/workflow/{id}/execute"""
    return await workflow_execute(wf_id, request)


@router.get("/api/workflows/{wf_id}/history")
async def workflows_history_alias(wf_id: str, limit: int = 20):
    """工作流执行历史"""
    if not _WORKFLOW_AVAILABLE:
        return {"history": []}
    try:
        execs = wf_store.list_executions(workflow_id=wf_id, limit=limit)
        return {"history": [e.to_dict() for e in execs]}
    except Exception as e:
        return {"history": [], "error": str(e)}
