# -*- coding: utf-8 -*-
"""Admin infrastructure: events, health, i18n, audit, export, monitoring, ollama routes"""
from __future__ import annotations
import asyncio, json, os, time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from loguru import logger
from starlette.responses import StreamingResponse

router = APIRouter()


# ── SSE 实时推送 ───────────────────────────────────────────────────────────────

@router.get("/api/events/stream")
async def sse_stream(request: Request):
    """Server-Sent Events 端点 — Admin 面板实时更新"""
    from ..event_bus import get_bus

    async def event_generator():
        try:
            async for event in get_bus().subscribe():
                data = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: {event['type']}\ndata: {data}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/events/recent")
async def sse_recent(limit: int = 20, event_type: str = ""):
    """最近事件历史"""
    from ..event_bus import get_bus
    return {"ok": True, "events": get_bus().recent_events(limit, event_type)}


# ── 日报系统 API ─────────────────────────────────────────────────────────────

@router.post("/api/daily-report")
async def daily_report_generate():
    from ..daily_report import generate_and_cache
    from ..main import app
    backend = getattr(app.state, "ai_backend", None)
    ai_call = backend.chat_simple if backend else None
    report = await generate_and_cache(ai_call)
    return {"ok": True, **report.to_dict()}


@router.get("/api/daily-report")
async def daily_report_get():
    from ..daily_report import get_last_report, generate_and_cache
    from ..main import app
    report = get_last_report()
    if not report:
        backend = getattr(app.state, "ai_backend", None)
        ai_call = backend.chat_simple if backend else None
        report = await generate_and_cache(ai_call)
    return {"ok": True, **report.to_dict()}


@router.get("/api/daily-report/text")
async def daily_report_text():
    from ..daily_report import get_last_report
    report = get_last_report()
    if not report:
        return {"ok": False, "text": "暂无日报，请先生成"}
    return {"ok": True, "text": report.to_text()}


# ── 异常检测 API ─────────────────────────────────────────────────────────────

@router.get("/api/anomaly/status")
async def anomaly_status():
    from ..anomaly_detector import get_detector
    return {"ok": True, **get_detector().get_status()}


@router.get("/api/anomaly/alerts")
async def anomaly_alerts(limit: int = 20):
    from ..anomaly_detector import get_detector
    return {"ok": True, "alerts": get_detector().get_recent_alerts(limit)}


@router.post("/api/anomaly/reset/{account_id}")
async def anomaly_reset(account_id: str):
    from ..anomaly_detector import get_detector
    get_detector().reset_circuit_breaker(account_id)
    return {"ok": True}


@router.post("/api/anomaly/check")
async def anomaly_check_now():
    """手动触发异常检查"""
    from ..anomaly_detector import get_detector
    from ..wechat.account_health import get_health_monitor
    detector = get_detector()
    all_alerts = []
    for m in get_health_monitor().get_all_status():
        alerts = detector.check(
            m["account_id"],
            current_send=m["send_rate_per_hour"],
            current_error=m["error_rate_per_hour"],
        )
        all_alerts.extend(alerts)
    return {"ok": True, "alerts": [a.to_dict() for a in all_alerts]}


# ── 知识库 API ───────────────────────────────────────────────────────────────

@router.get("/api/knowledge")
async def knowledge_list():
    from ..knowledge_base import list_documents, get_stats
    return {"ok": True, "documents": list_documents(), **get_stats()}


@router.post("/api/knowledge/import")
async def knowledge_import(request: Request):
    data = await request.json()
    from ..knowledge_base import import_document
    doc_id = import_document(
        title=data.get("title", "未命名文档"),
        content=data.get("content", ""),
        source=data.get("source", ""),
        chunk_size=data.get("chunk_size", 500),
    )
    return {"ok": True, "doc_id": doc_id}


@router.post("/api/knowledge/search")
async def knowledge_search(request: Request):
    data = await request.json()
    from ..knowledge_base import search
    results = search(data.get("query", ""), top_k=data.get("top_k", 5))
    return {"ok": True, "results": results}


@router.delete("/api/knowledge/{doc_id}")
async def knowledge_delete(doc_id: str):
    from ..knowledge_base import delete_document
    delete_document(doc_id)
    return {"ok": True}


# ── 插件系统 API ─────────────────────────────────────────────────────────────

@router.get("/api/plugins")
async def plugins_list():
    from ..plugin_system import get_plugin_manager
    pm = get_plugin_manager()
    return {"ok": True, "plugins": pm.list_plugins(), **pm.get_stats()}


@router.post("/api/plugins/{plugin_id}/enable")
async def plugin_enable(plugin_id: str):
    from ..plugin_system import get_plugin_manager
    ok = get_plugin_manager().enable(plugin_id)
    try:
        from .. import audit_log
        audit_log.log("plugin_toggle", target=plugin_id, detail="enable")
    except Exception:
        pass
    return {"ok": ok}


@router.post("/api/plugins/{plugin_id}/disable")
async def plugin_disable(plugin_id: str):
    from ..plugin_system import get_plugin_manager
    ok = get_plugin_manager().disable(plugin_id)
    try:
        from .. import audit_log
        audit_log.log("plugin_toggle", target=plugin_id, detail="disable")
    except Exception:
        pass
    return {"ok": ok}


@router.get("/api/plugins/{plugin_id}")
async def plugin_detail(plugin_id: str):
    from ..plugin_system import get_plugin_manager
    info = get_plugin_manager().get_plugin(plugin_id)
    return {"ok": bool(info), **(info or {})}


# ── 上下文压缩 API ───────────────────────────────────────────────────────────

@router.get("/api/compressor/stats")
async def compressor_stats():
    from ..context_compressor import get_compressor
    return {"ok": True, **get_compressor().get_stats()}


# ── WebSocket 实时推送（双通道） ────────────────────────────────────────────

@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """WebSocket 事件推送 — 替代 SSE，支持客户端过滤"""
    from ..event_bus import get_bus
    await websocket.accept()

    client_id = id(websocket)
    bus = get_bus()
    queue = bus.register_ws(client_id)
    logger.info(f"WebSocket 事件客户端连接 #{client_id}")

    try:
        send_task = asyncio.create_task(_ws_event_sender(websocket, queue))
        recv_task = asyncio.create_task(_ws_event_receiver(websocket, bus, client_id))
        done, pending = await asyncio.wait(
            {send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS events error: {e}")
    finally:
        bus.unregister_ws(client_id)
        logger.info(f"WebSocket 事件客户端断开 #{client_id}")


async def _ws_event_sender(websocket: WebSocket, queue: asyncio.Queue):
    while True:
        event = await queue.get()
        await websocket.send_json(event)


async def _ws_event_receiver(websocket: WebSocket, bus, client_id: int):
    """接收客户端指令：subscribe/unsubscribe 事件类型过滤"""
    while True:
        try:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            cmd = msg.get("cmd", "")
            if cmd == "subscribe":
                types = set(msg.get("types", []))
                bus.update_ws_filters(client_id, types if types else None)
            elif cmd == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
        except (WebSocketDisconnect, Exception):
            break


# ── 对话记忆搜索 API ──────────────────────────────────────────────────────────

@router.get("/api/memory/search")
async def memory_search(
    q: str = "", session: str = "", role: str = "",
    start: str = "", end: str = "", limit: int = 50, offset: int = 0,
):
    from ..memory_search import search
    return {"ok": True, **search(q, session, role, start, end, limit, offset)}


@router.get("/api/memory/sessions")
async def memory_sessions():
    from ..memory_search import get_sessions
    return {"ok": True, "sessions": get_sessions()}


@router.get("/api/memory/stats")
async def memory_stats():
    from ..memory_search import get_stats
    return {"ok": True, **get_stats()}


# ── 系统健康检查 API ──────────────────────────────────────────────────────────

@router.get("/api/health")
async def health_check():
    from ..health_check import get_health_checker
    checker = get_health_checker()
    results = await checker.run_all()
    return {"ok": True, **checker.get_summary()}


@router.post("/api/health/recheck")
async def health_recheck():
    from ..health_check import get_health_checker
    checker = get_health_checker()
    await checker.run_all(force=True)
    return {"ok": True, **checker.get_summary()}


# ── 国际化 API ────────────────────────────────────────────────────────────────

@router.get("/api/i18n/translations")
async def i18n_translations(lang: str = ""):
    from ..i18n import get_all_translations, get_language
    return {"ok": True, "lang": lang or get_language(), "translations": get_all_translations(lang)}


@router.post("/api/i18n/language")
async def i18n_set_language(request: Request):
    data = await request.json()
    from ..i18n import set_language, get_language
    set_language(data.get("lang", "zh"))
    return {"ok": True, "lang": get_language()}


@router.get("/api/i18n/languages")
async def i18n_languages():
    from ..i18n import get_supported_languages
    return {"ok": True, "languages": get_supported_languages()}


# ── 审计日志 API ──────────────────────────────────────────────────────────────

@router.get("/api/audit/logs")
async def audit_logs(
    action: str = "", actor: str = "", severity: str = "",
    limit: int = 50, offset: int = 0,
):
    from .. import audit_log
    return {"ok": True, **audit_log.query(action, actor, severity, limit=limit, offset=offset)}


@router.get("/api/audit/stats")
async def audit_stats():
    from .. import audit_log
    return {"ok": True, **audit_log.get_stats()}


# ── 速率限制 API ──────────────────────────────────────────────────────────────

@router.get("/api/ratelimit/stats")
async def ratelimit_stats():
    from ..rate_limiter import get_limiter
    return {"ok": True, **get_limiter().get_stats()}


# ── 事件总线统计 API ──────────────────────────────────────────────────────────

@router.get("/api/events/stats")
async def events_stats():
    from ..event_bus import get_bus
    bus = get_bus()
    return {"ok": True, "subscribers": bus.subscriber_count, "ws_clients": bus.ws_count, **bus.get_persist_stats()}


# ── 大屏数据 API ─────────────────────────────────────────────────────────────

@router.get("/api/dashboard/realtime")
async def dashboard_realtime():
    """大屏实时数据聚合端点"""
    result = {}
    try:
        from ..wechat.unified_inbox import get_inbox_stats
        result["inbox"] = get_inbox_stats()
    except Exception:
        result["inbox"] = {}
    try:
        from ..wechat.account_health import get_health_monitor
        result["health"] = get_health_monitor().get_overview()
        result["accounts"] = get_health_monitor().get_all_status()
    except Exception:
        result["health"] = {}
    try:
        from ..workflow.store import get_stats as wf_stats
        result["workflows"] = wf_stats()
    except Exception:
        result["workflows"] = {}
    try:
        from ..notification_aggregator import get_aggregator
        result["notifications"] = get_aggregator().get_unread_summary()
    except Exception:
        result["notifications"] = {}
    try:
        from ..anomaly_detector import get_detector
        result["anomaly"] = {
            "breakers": get_detector()._circuit_breakers,
            "recent_alerts": len(get_detector()._alerts),
        }
    except Exception:
        result["anomaly"] = {}
    try:
        from ..knowledge_base import get_stats as kb_stats
        result["knowledge"] = kb_stats()
    except Exception:
        result["knowledge"] = {}
    return {"ok": True, **result}


# ── 数据导出 API ──────────────────────────────────────────────────────────────

@router.get("/api/export/analytics")
async def export_analytics(days: int = 30):
    from ..data_export import export_analytics_csv
    content = export_analytics_csv(days)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=analytics_{days}d.csv"},
    )


@router.get("/api/export/contacts")
async def export_contacts():
    from ..data_export import export_contacts_csv
    content = export_contacts_csv()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@router.get("/api/export/workflows")
async def export_workflows():
    from ..data_export import export_workflows_json
    content = export_workflows_json()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=workflows.json"},
    )


@router.get("/api/export/conversations")
async def export_conversations(session: str = "default"):
    from ..data_export import export_conversations_json
    content = export_conversations_json(session)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=conversations_{session}.json"},
    )


@router.get("/api/export/messages")
async def export_messages(
    source: str = "memory", session: str = "", contact: str = "",
    account_id: str = "", start: str = "", end: str = "",
    fmt: str = "csv", sentiment: bool = False,
):
    """导出消息报表：CSV / HTML / JSON"""
    from ..message_export import export_conversations as do_export
    result = do_export(source, session, contact, account_id, start, end, fmt, sentiment)
    return Response(
        content=result["content"],
        media_type=result["mime"],
        headers={"Content-Disposition": f"attachment; filename={result['filename']}"},
    )


@router.get("/api/export/rules")
async def export_rules():
    from ..data_export import export_rules_json
    content = export_rules_json()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=msg_rules.json"},
    )


@router.get("/api/export/report")
async def export_report(days: int = 30):
    from ..data_export import export_full_report_json
    content = export_full_report_json(days)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=full_report.json"},
    )


# ── 长期记忆 API ──────────────────────────────────────────────────────────────

@router.get("/api/memory/long/stats")
async def long_memory_stats(session: str = "default"):
    try:
        from ..long_memory import get_memory_stats
        return {"ok": True, **get_memory_stats(session)}
    except ImportError:
        return {"ok": False, "error": "long_memory module not available"}


@router.post("/api/memory/compress")
async def memory_compress(request: Request):
    """手动触发记忆压缩"""
    data = await request.json()
    session = data.get("session", "default")
    try:
        from ..long_memory import compress_old_messages
        from ..main import app
        backend = getattr(app.state, "ai_backend", None)
        ai_call = backend.chat_simple if backend else None
        count = await compress_old_messages(session, ai_call=ai_call)
        return {"ok": True, "compressed": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/memory/long/search")
async def long_memory_search(q: str, session: str = "default"):
    """检索相关记忆"""
    try:
        from ..long_memory import retrieve_relevant
        segments = retrieve_relevant(session, q, top_k=5)
        return {"ok": True, "results": [
            {"summary": s.summary, "keywords": s.keywords, "relevance": round(s.relevance, 3)}
            for s in segments
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 系统监控 API ──────────────────────────────────────────────────────────────

@router.get("/api/router/status")
async def router_status():
    """AI Router 状态"""
    try:
        from ..main import app
        backend = getattr(app.state, "ai_backend", None)
        ai_router = getattr(backend, "_router", None) if backend else None
        if not ai_router:
            return {"ok": True, "providers": [], "note": "Router not loaded, using direct backend"}
        providers = ai_router.get_status_panel()
        active = ai_router.get_active_provider()
        return {"ok": True, "providers": providers, "active_provider": active}
    except Exception as e:
        return {"ok": False, "providers": [], "error": str(e)}


@router.get("/api/system/stats")
async def system_stats():
    """系统资源统计"""
    import time as _time
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_mb = round(process.memory_info().rss / 1024 / 1024, 1)
        cpu_pct = process.cpu_percent(interval=0)
        return {
            "ok": True,
            "memory_mb": mem_mb,
            "cpu_percent": cpu_pct,
            "threads": process.num_threads(),
            "uptime_seconds": round(_time.time() - process.create_time()),
        }
    except ImportError:
        return {"ok": True, "memory_mb": "N/A", "cpu_percent": 0, "threads": 0, "uptime_seconds": 0}


# ── Ollama API ─────────────────────────────────────────────────────────────────

@router.get("/api/ollama/status")
async def ollama_status():
    """Ollama 状态"""
    from ..main import app
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        return {"available": False, "error": "bridge not initialized"}
    return {"ok": True, **bridge.get_status()}


@router.post("/api/ollama/check")
async def ollama_check():
    """重新检测 Ollama"""
    from ..main import app
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        from ..ollama_bridge import OllamaBridge
        bridge = OllamaBridge()
        app.state.ollama_bridge = bridge
    health = await bridge.check_health()
    if health.available:
        try:
            from src.router.config import RouterConfig
            bridge.auto_enable_in_router(RouterConfig())
        except Exception:
            pass
    return {"ok": True, **bridge.get_status()}


@router.post("/api/ollama/pull")
async def ollama_pull(request: Request):
    """拉取模型"""
    data = await request.json()
    model = data.get("model", "qwen2.5:7b")
    from ..main import app
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge or not bridge.is_available:
        return {"ok": False, "error": "Ollama not available"}
    success = await bridge.pull_model(model)
    return {"ok": success}


@router.post("/api/ollama/benchmark")
async def ollama_benchmark(request: Request):
    """基准测试"""
    data = await request.json() if request.headers.get("content-type") else {}
    from ..main import app
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge or not bridge.is_available:
        return {"ok": False, "error": "Ollama not available"}
    result = await bridge.benchmark(data.get("model", ""))
    return {"ok": True, **result}


@router.delete("/api/ollama/models/{name}")
async def ollama_delete_model(name: str):
    """删除模型"""
    from ..main import app
    bridge = getattr(app.state, "ollama_bridge", None)
    if not bridge:
        return {"ok": False}
    success = await bridge.delete_model(name)
    return {"ok": success}


# ── Profile / Multi-member System ─────────────────────────────────────────────

@router.get("/api/profiles")
async def profiles_list(environment: Optional[str] = None):
    from ..profiles import list_profiles
    return {"ok": True, "profiles": list_profiles(environment)}


@router.get("/api/profiles/active")
async def profiles_active():
    from ..profiles import get_active_profile
    p = get_active_profile()
    return {"ok": True, "profile": p}


@router.get("/api/profiles/stats")
async def profiles_stats():
    """Return message count and last active time for each profile."""
    from ..profiles import list_profiles, get_session_id
    from .. import memory
    profiles = list_profiles()
    stats = {}
    for p in profiles:
        session = get_session_id(p["id"])
        try:
            conn = memory._get_conn()
            row = conn.execute(
                "SELECT COUNT(*) as cnt, MAX(ts) as last_ts FROM messages WHERE session = ?",
                (session,)
            ).fetchone()
            stats[p["id"]] = {
                "message_count": row[0] if row else 0,
                "last_active": row[1] if row and row[1] else None,
            }
        except Exception:
            stats[p["id"]] = {"message_count": 0, "last_active": None}
    return {"ok": True, "stats": stats}


@router.get("/api/profiles/{profile_id}/export")
async def profiles_export(profile_id: str, fmt: str = "json"):
    """Export a profile's conversation history as JSON or TXT."""
    from ..profiles import get_profile, get_session_id
    from .. import memory
    import time as _time

    p = get_profile(profile_id)
    if not p:
        return {"ok": False, "error": "Profile not found"}

    session = get_session_id(profile_id)
    msgs = memory.get_history_raw(session, limit=10000)

    if fmt == "txt":
        lines = [f"# {p['name']} 的对话记录", f"# 导出时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for m in msgs:
            ts = m.get("timestamp", "")
            role = "用户" if m["role"] == "user" else "AI"
            lines.append(f"[{ts}] {role}: {m['content']}")
        content = "\n".join(lines)
        media = "text/plain"
        ext = "txt"
    else:
        content = json.dumps({
            "profile": p,
            "session": session,
            "exported_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "message_count": len(msgs),
            "messages": msgs,
        }, ensure_ascii=False, indent=2)
        media = "application/json"
        ext = "json"

    from urllib.parse import quote
    safe_name = p["name"].replace(" ", "_")
    encoded = quote(f"{safe_name}_chat.{ext}")
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.get("/api/profiles/presets")
async def profiles_presets(environment: Optional[str] = None):
    from ..profiles import get_presets
    return {"ok": True, "presets": get_presets(environment)}


@router.post("/api/profiles")
async def profiles_create(request: Request):
    from ..profiles import create_profile, create_from_preset
    data = await request.json()

    preset_name = data.get("preset")
    env = data.get("environment", "family")
    if preset_name:
        p = create_from_preset(preset_name, env)
        if p:
            return {"ok": True, "profile": p}
        return {"ok": False, "error": "Preset not found"}

    p = create_profile(
        name=data.get("name", "新成员"),
        avatar=data.get("avatar", "👤"),
        environment=env,
        system_prompt=data.get("system_prompt", ""),
        voice_id=data.get("voice_id", "zh-CN-XiaoxiaoNeural"),
        clone_voice_path=data.get("clone_voice_path", ""),
        wake_word=data.get("wake_word", ""),
        age_group=data.get("age_group", "adult"),
        preferences=data.get("preferences"),
    )
    return {"ok": True, "profile": p}


@router.put("/api/profiles/{profile_id}")
async def profiles_update(profile_id: str, request: Request):
    from ..profiles import update_profile
    data = await request.json()
    p = update_profile(profile_id, **data)
    if p:
        return {"ok": True, "profile": p}
    return {"ok": False, "error": "Profile not found"}


@router.delete("/api/profiles/{profile_id}")
async def profiles_delete(profile_id: str):
    from ..profiles import delete_profile
    ok = delete_profile(profile_id)
    return {"ok": ok}


@router.post("/api/profiles/reorder")
async def profiles_reorder(request: Request):
    """Update sort_order for all profiles."""
    from ..profiles import update_profile
    data = await request.json()
    order = data.get("order", [])
    for i, pid in enumerate(order):
        update_profile(pid, sort_order=i)
    return {"ok": True}


@router.post("/api/profiles/{profile_id}/activate")
async def profiles_activate(profile_id: str):
    """Activate a profile and reconfigure the AI backend accordingly."""
    from ..profiles import activate_profile, get_session_id
    p = activate_profile(profile_id)
    if not p:
        return {"ok": False, "error": "Profile not found"}

    try:
        from ..main import backend, tts
        if backend:
            session = get_session_id(profile_id)
            backend.session_id = session
            if p.get("system_prompt"):
                backend.system_prompt = p["system_prompt"]
            backend._history_cache = None
            logger.info(f"Backend switched to session={session}")

        if tts:
            voice = p.get("voice_id")
            if voice:
                tts._edge_voice = voice
            clone_path = p.get("clone_voice_path")
            if clone_path:
                tts.set_clone_voice(clone_path)
            else:
                tts._clone_audio_path = None
    except Exception as e:
        logger.warning(f"Profile activation side-effects failed: {e}")

    return {"ok": True, "profile": p, "session_id": get_session_id(profile_id)}
