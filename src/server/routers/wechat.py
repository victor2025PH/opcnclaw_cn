# -*- coding: utf-8 -*-
"""WeChat, Moments, Contacts, Inbox, Broadcast, Media, Analytics routes"""
from __future__ import annotations
import asyncio, json, sys, time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response
from loguru import logger
from starlette.responses import StreamingResponse

router = APIRouter()

# ── WeChat autoreply globals ──────────────────────────────────────────────────

_wechat_monitor = None
_wechat_engine = None
_wechat_adapter = None
try:
    if sys.platform == "win32":
        from ..wechat_autoreply import (
            init_wechat_autoreply, init_wechat_v2,
            get_monitor, get_engine, get_adapter,
        )
        _wechat_autoreply_available = True
    else:
        _wechat_autoreply_available = False
except ImportError:
    _wechat_autoreply_available = False

# ── Lazy helpers ──────────────────────────────────────────────────────────────

_chain_tracker = None
_content_calendar = None


def _get_app_state_backend():
    from ..main import app
    return getattr(app.state, "ai_backend", None)


def _get_backend():
    from ..main import backend
    return backend


def _get_desktop():
    try:
        from ..main import desktop
        if desktop is not None:
            return desktop
    except (ImportError, AttributeError):
        pass
    try:
        from .desktop import desktop
        return desktop
    except (ImportError, AttributeError):
        return None


_init_attempted = False

def _ensure_wechat_engine():
    """懒加载：首次调用时初始化 v2.0 三轨融合系统（只尝试一次）"""
    global _wechat_monitor, _wechat_engine, _wechat_adapter, _init_attempted
    if not _wechat_autoreply_available:
        return None, None
    if _wechat_engine is None and not _init_attempted:
        _init_attempted = True
        try:
            result = init_wechat_v2(
                ai_backend=_get_backend(),
                desktop=_get_desktop(),
            )
            if isinstance(result, tuple) and len(result) == 2:
                _wechat_adapter, _wechat_engine = result
                _wechat_monitor = get_monitor()
            else:
                _wechat_monitor, _wechat_engine = init_wechat_autoreply(
                    ai_backend=_get_backend(), desktop=_get_desktop(),
                )
            logger.info("✅ 微信自动回复引擎初始化完成")
        except Exception as e:
            logger.error(f"微信自动回复初始化失败: {e}")
            return None, None
    return _wechat_monitor, _wechat_engine


def _get_chain_tracker():
    global _chain_tracker
    if _chain_tracker is None:
        from ..wechat.moments_tracker import CommentChainTracker
        from ..main import app
        ai_call = None
        if hasattr(app.state, 'ai_backend') and app.state.ai_backend:
            ai_call = app.state.ai_backend.chat_simple
        _chain_tracker = CommentChainTracker(ai_call=ai_call)
    return _chain_tracker


def _get_content_calendar():
    global _content_calendar
    if _content_calendar is None:
        from ..wechat.moments_tracker import ContentCalendar
        from ..main import app
        ai_call = None
        if hasattr(app.state, 'ai_backend') and app.state.ai_backend:
            ai_call = app.state.ai_backend.chat_simple
        _content_calendar = ContentCalendar(ai_call=ai_call)
    return _content_calendar


# ── WeChat autoreply routes ───────────────────────────────────────────────────

@router.get("/api/wechat/status")
async def wechat_autoreply_status():
    """获取微信自动回复状态、统计、待审核列表（含三轨信息）"""
    if not _wechat_autoreply_available:
        return {"available": False, "reason": "仅支持 Windows 平台"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"available": False, "reason": "引擎初始化失败"}
    monitor = get_monitor()
    adapter = get_adapter() if _wechat_autoreply_available else None
    stats = engine.get_stats()
    stats["available"] = True
    stats["monitor_running"] = monitor.is_running if monitor else False
    stats["monitor_mode"] = monitor.get_mode() if monitor else "none"
    stats["monitor_stats"] = monitor.stats if monitor else {}
    # v2.0 三轨信息
    if adapter:
        adapter_status = adapter.get_status()
        stats["v2"] = {
            "active_track": adapter_status.get("active_track", "none"),
            "adapter_running": adapter_status.get("running", False),
            "tracks": adapter_status.get("tracks", {}),
            "anti_risk": adapter_status.get("anti_risk", {}),
        }
    return stats


@router.post("/api/wechat/toggle")
async def wechat_autoreply_toggle(request: Request):
    """
    开启 / 关闭自动回复总开关，或启动/停止监控器。
    Body: { "enabled": true/false }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    enabled = body.get("enabled", False)
    monitor, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎初始化失败"}), status_code=500)

    engine.update_config({"enabled": enabled})

    # v2.0 适配器
    adapter = get_adapter() if _wechat_autoreply_available else None
    if enabled:
        if adapter and not adapter.is_running:
            import threading
            threading.Thread(target=adapter.start, daemon=True).start()
            logger.info("v2.0 三轨适配器已启动")
        elif monitor and not monitor.is_running:
            monitor.start()
            logger.info("微信监控器已启动")
    else:
        if adapter and adapter.is_running:
            adapter.stop()
        if monitor and monitor.is_running:
            monitor.stop()
            logger.info("微信监控器已停止")

    return {"ok": True, "enabled": enabled}


@router.post("/api/wechat/config")
async def wechat_autoreply_config(request: Request):
    """
    更新全局配置。
    Body 字段（均可选）:
      manual_review, quiet_start, quiet_end,
      min_reply_delay, max_reply_delay,
      global_persona, keyword_blacklist
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    ok = engine.update_config(body)
    return {"ok": ok}


@router.post("/api/wechat/contacts")
async def wechat_add_contact(request: Request):
    """
    添加联系人到白名单。
    Body: { "name": "张三", "daily_limit": 20, "is_group": false, "persona": "" }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return Response(content=json.dumps({"error": "缺少 name"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    rule = engine.add_contact(
        name=name,
        daily_limit=body.get("daily_limit", 20),
        is_group=body.get("is_group", False),
        group_reply_only_at_me=body.get("group_reply_only_at_me", True),
        persona=body.get("persona", ""),
    )
    # v2.0: 自动加入 wxauto 后台监听
    adapter = get_adapter() if _wechat_autoreply_available else None
    if adapter:
        adapter.add_listen([name])
    return {"ok": True, "contact": name, "daily_limit": rule.daily_limit}


@router.delete("/api/wechat/contacts/{name}")
async def wechat_remove_contact(name: str):
    """从白名单移除联系人"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.remove_contact(name) if engine else False
    return {"ok": ok}


@router.patch("/api/wechat/contacts/{name}")
async def wechat_toggle_contact(name: str, request: Request):
    """启用 / 禁用某联系人的自动回复"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    body = await request.json()
    enabled = body.get("enabled", True)
    _, engine = _ensure_wechat_engine()
    ok = engine.toggle_contact(name, enabled) if engine else False
    return {"ok": ok}


@router.get("/api/wechat/reviews")
async def wechat_pending_reviews():
    """获取待人工审核的回复列表"""
    if not _wechat_autoreply_available:
        return {"reviews": []}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"reviews": []}
    return {"reviews": engine.get_pending_reviews()}


@router.post("/api/wechat/reviews/{reply_id}/approve")
async def wechat_approve_reply(reply_id: str):
    """批准一条待审核回复（发送）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.approve_reply(reply_id) if engine else False
    return {"ok": ok}


@router.post("/api/wechat/reviews/{reply_id}/reject")
async def wechat_reject_reply(reply_id: str):
    """拒绝一条待审核回复（不发送）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    ok = engine.reject_reply(reply_id) if engine else False
    return {"ok": ok}


@router.get("/api/wechat/escalations")
async def wechat_escalations():
    """获取待处理的升级列表（AI 判断需要人工介入的消息）"""
    if not _wechat_autoreply_available:
        return {"error": "不支持"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {"items": []}
    return {"items": engine.get_escalations()}


@router.post("/api/wechat/escalations/{eid}")
async def wechat_handle_escalation(eid: str, request: Request):
    """
    处理升级项。
    Body: { "action": "send_draft" | "send_custom" | "dismiss", "reply": "..." }
    """
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)
    body = await request.json()
    action = body.get("action", "dismiss")
    reply = body.get("reply", "")
    ok = engine.handle_escalation(eid, action, reply)
    return {"ok": ok}


@router.get("/api/wechat/smart-stats")
async def wechat_smart_stats():
    """获取智能回复引擎统计"""
    if not _wechat_autoreply_available:
        return {"error": "不支持"}
    _, engine = _ensure_wechat_engine()
    if not engine:
        return {}
    stats = engine.get_stats()
    return {
        "smart_mode": stats.get("smart_mode", False),
        "smart_engine": stats.get("smart_engine", {}),
    }


@router.get("/api/wechat/reviews/stream")
async def wechat_review_stream():
    """SSE 实时推送新的待审核回复（前端用于实时通知）"""
    if not _wechat_autoreply_available:
        return Response(content=json.dumps({"error": "不支持"}), status_code=400)
    _, engine = _ensure_wechat_engine()
    if not engine:
        return Response(content=json.dumps({"error": "引擎未初始化"}), status_code=500)

    queue: asyncio.Queue = asyncio.Queue()

    def on_review(pr):
        asyncio.run_coroutine_threadsafe(
            queue.put({
                "id": pr.id,
                "contact": pr.contact,
                "incoming": pr.incoming_msg,
                "reply": pr.ai_reply,
            }),
            asyncio.get_event_loop()
        )

    engine.on_review_needed(on_review)

    async def event_stream():
        yield "data: {\"type\": \"connected\"}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps({'type': 'review', **item}, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/wechat/monitor-stats")
async def wechat_monitor_stats():
    """获取监控器运行统计（含 v2.0 三轨信息）"""
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    monitor, engine = _ensure_wechat_engine()
    adapter = get_adapter() if _wechat_autoreply_available else None
    stats = {}
    if monitor:
        stats = {
            **monitor.stats,
            "is_running": monitor.is_running,
            "mode": monitor.get_mode(),
        }
    if adapter:
        adapter_st = adapter.get_status()
        stats["v2_active_track"] = adapter_st.get("active_track", "none")
        stats["v2_running"] = adapter_st.get("running", False)
        stats["v2_tracks"] = adapter_st.get("tracks", {})
        stats["v2_scans"] = adapter_st.get("stats", {}).get("scans", 0)
        stats["v2_messages"] = adapter_st.get("stats", {}).get("messages_detected", 0)
    return {"available": True, "stats": stats}


@router.post("/api/wechat/test-read")
async def wechat_test_read():
    """
    手动触发一次读取（不触发回复）。
    优先使用 v2.0 三轨适配器，降级到旧版 monitor.manual_scan。
    """
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    _ensure_wechat_engine()
    adapter = get_adapter() if _wechat_autoreply_available else None
    monitor = get_monitor() if _wechat_autoreply_available else None
    try:
        if adapter:
            result = await asyncio.get_event_loop().run_in_executor(
                None, adapter.manual_scan
            )
            return {"ok": True, "version": "v2", "result": result}
        elif monitor:
            result = await asyncio.get_event_loop().run_in_executor(
                None, monitor.manual_scan
            )
            return {"ok": True, "version": "v1", "result": result}
        else:
            return {"ok": False, "error": "无可用监控器"}
    except Exception as e:
        logger.error(f"wechat test-read error: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/api/wechat/uia-debug")
async def wechat_uia_debug(max_depth: int = 5):
    """
    导出微信窗口完整 UIA 控件树（诊断工具）。
    max_depth: 控件树最大深度（默认5，建议不超过7）
    """
    if not _wechat_autoreply_available:
        return {"error": "不支持", "available": False}
    monitor, _ = _ensure_wechat_engine()
    if not monitor:
        return {"error": "监控器未初始化"}
    try:
        depth = max(1, min(max_depth, 8))
        tree = await asyncio.get_event_loop().run_in_executor(
            None, lambda: monitor.dump_uia_tree(max_depth=depth)
        )
        return {"ok": True, "node_count": len(tree), "tree": tree}
    except Exception as e:
        logger.error(f"wechat uia-debug error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/wechat/activate")
async def wechat_activate():
    """自动查找并激活微信窗口（从最小化/托盘恢复到前台）"""
    if not _wechat_autoreply_available:
        return {"ok": False, "error": "微信模块不可用"}
    try:
        from ..wechat_monitor import UIAReader
        result = await asyncio.get_event_loop().run_in_executor(
            None, UIAReader.activate_wechat_window
        )
        return {"ok": result, "message": "微信窗口已激活" if result else "未找到微信窗口"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/wechat/send")
async def wechat_send_message(request: Request):
    """发送微信消息（测试用）"""
    if not _wechat_autoreply_available:
        return {"ok": False, "error": "微信模块不可用"}
    try:
        data = await request.json()
        contact = data.get("contact", "")
        text = data.get("text", "")
        if not text:
            return {"ok": False, "error": "text 不能为空"}

        adapter = get_adapter()
        if not adapter:
            return {"ok": False, "error": "adapter 未初始化"}

        ok = await asyncio.get_event_loop().run_in_executor(
            None, lambda: adapter.send_message(contact, text)
        )
        return {"ok": ok, "message": "已发送" if ok else "发送失败"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 朋友圈 API ─────────────────────────────────────────────────────────────────

@router.post("/api/moments/browse")
async def moments_browse(request: Request):
    """浏览朋友圈并用 AI 分析"""
    data = await request.json() if request.headers.get("content-type") else {}
    max_posts = data.get("max_posts", 5)

    try:
        from ..wechat.moments_reader import MomentsReader
        from ..wechat.moments_ai import MomentsAIEngine

        backend = _get_backend()

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        reader = MomentsReader(ai_backend=backend, wxauto_reader=wxauto_r)
        page = await reader.browse(max_posts)

        posts_data = []
        if page.posts and backend:
            ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
            for post in page.posts:
                analysis = await ai_engine.analyze_post(post)
                posts_data.append({
                    "author": post.author,
                    "text": post.text,
                    "image_desc": post.image_desc,
                    "time": post.time_str,
                    "analysis": analysis.to_dict(),
                })

        return {"ok": True, "posts": posts_data, "source": page.source}
    except Exception as e:
        logger.error(f"moments browse error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/moments/interact")
async def moments_interact(request: Request):
    """对一条朋友圈执行互动（点赞/评论）"""
    data = await request.json()
    action = data.get("action", "like")  # like / comment
    author = data.get("author", "")
    post_text = data.get("post_text", "")
    comment = data.get("comment", "")

    if not author:
        return {"error": "缺少 author"}

    try:
        from ..wechat.moments_reader import MomentPost
        from ..wechat.moments_actor import MomentsActor
        from ..wechat.moments_guard import MomentsGuard

        backend = _get_backend()

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        actor = MomentsActor(wxauto_reader=wxauto_r, guard=MomentsGuard())
        post = MomentPost(author=author, text=post_text)

        if action == "like":
            ok = await actor.like_post(post)
        elif action == "comment":
            if not comment and backend:
                from ..wechat.moments_ai import MomentsAIEngine
                ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
                analysis = await ai_engine.analyze_post(post)
                comment = analysis.comment_text
            ok = await actor.comment_post(post, comment) if comment else False
        else:
            return {"error": f"未知操作: {action}"}

        return {"ok": ok, "action": action, "author": author, "comment": comment}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/moments/publish")
async def moments_publish(request: Request):
    """发布朋友圈"""
    data = await request.json()
    text = data.get("text", "")
    media_files = data.get("media_files", [])
    privacy = data.get("privacy", "all")
    generate = data.get("generate", False)
    topic = data.get("topic", "")

    try:
        from ..wechat.moments_actor import MomentsActor
        from ..wechat.moments_guard import MomentsGuard

        backend = _get_backend()

        if generate and backend:
            from ..wechat.moments_ai import MomentsAIEngine
            ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
            drafts = await ai_engine.generate_moment_text(
                topic=topic or text, mood=data.get("mood", "平常"),
            )
            if drafts:
                text = drafts[0]["text"]

        if not text:
            return {"error": "缺少文案"}

        wxauto_r = None
        if _wechat_adapter and hasattr(_wechat_adapter, "_wxauto_reader"):
            wxauto_r = _wechat_adapter._wxauto_reader

        actor = MomentsActor(wxauto_reader=wxauto_r, guard=MomentsGuard())
        ok = await actor.publish_moment(text, media_files, privacy)
        return {"ok": ok, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/moments/generate-text")
async def moments_generate_text(request: Request):
    """AI 生成朋友圈文案（3个选项）"""
    data = await request.json()
    backend = _get_backend()
    if not backend:
        return {"error": "AI 后端未初始化"}

    try:
        from ..wechat.moments_ai import MomentsAIEngine
        ai_engine = MomentsAIEngine(ai_call=backend.chat_simple)
        drafts = await ai_engine.generate_moment_text(
            topic=data.get("topic", ""),
            style=data.get("style", "日常"),
            mood=data.get("mood", "平常"),
            scene=data.get("scene", ""),
            extra=data.get("extra", ""),
        )
        return {"ok": True, "drafts": drafts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/moments/stats")
async def moments_stats():
    """朋友圈互动统计"""
    try:
        from ..wechat.moments_guard import MomentsGuard
        from ..wechat.contact_profile import get_stats as profile_stats
        guard = MomentsGuard()
        chain_stats = {}
        try:
            chain_stats = _get_chain_tracker().get_chain_stats()
        except Exception:
            pass
        return {
            "ok": True,
            "guard": guard.get_stats(),
            "profiles": profile_stats(),
            "chain": chain_stats,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/moments/chain/stats")
async def chain_stats():
    """评论链跟进统计"""
    try:
        return {"ok": True, **_get_chain_tracker().get_chain_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/moments/chain/recent")
async def chain_recent():
    """最近评论链记录"""
    try:
        return {"ok": True, "chains": _get_chain_tracker().get_recent_chains()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/moments/calendar")
async def calendar_list(status: str = ""):
    """获取内容日历"""
    try:
        cal = _get_content_calendar()
        return {"ok": True, "entries": cal.get_entries(status)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/moments/calendar/generate")
async def calendar_generate(request: Request):
    """AI 生成 30 天内容日历"""
    try:
        data = await request.json()
        cal = _get_content_calendar()
        entries = await cal.generate_month_plan(
            user_profile=data.get("user_profile", ""),
            interests=data.get("interests", ""),
            style=data.get("style", "自然日常"),
            posts_per_week=data.get("posts_per_week", 3),
        )
        return {"ok": True, "entries": [e.to_dict() for e in entries]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/moments/calendar/{date}/{action}")
async def calendar_action(date: str, action: str):
    """日历条目操作：approve/skip"""
    try:
        cal = _get_content_calendar()
        if action == "approve":
            cal.approve_entry(date)
        elif action == "skip":
            cal.skip_entry(date)
        else:
            return {"ok": False, "error": f"未知操作: {action}"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/contacts/profiles")
async def contacts_profiles(min_intimacy: float = 0):
    """获取联系人社交画像列表"""
    try:
        from ..wechat.contact_profile import list_profiles
        profiles = list_profiles(min_intimacy)
        return {"ok": True, "profiles": [p.to_dict() for p in profiles]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/contacts/profiles/{name}")
async def update_contact_profile(name: str, request: Request):
    """更新联系人画像"""
    data = await request.json()
    try:
        from ..wechat.contact_profile import get_profile, save_profile
        profile = get_profile(name)
        if "relationship" in data:
            profile.relationship = data["relationship"]
        if "intimacy" in data:
            profile.intimacy = max(0, min(100, float(data["intimacy"])))
        if "comment_style" in data:
            profile.comment_style = data["comment_style"]
        if "interests" in data:
            profile.interests = data["interests"]
        if "notes" in data:
            profile.notes = data["notes"]
        save_profile(profile)
        return {"ok": True, "profile": profile.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 统一收件箱 API ────────────────────────────────────────────────────────────

@router.get("/api/inbox")
async def inbox_query(account_id: str = "", contact: str = "", unread: bool = False, limit: int = 50, offset: int = 0):
    from ..wechat.unified_inbox import query_inbox
    msgs = query_inbox(account_id, contact, unread_only=unread, limit=limit, offset=offset)
    return {"ok": True, "messages": msgs}


@router.get("/api/inbox/stats")
async def inbox_stats(account_id: str = ""):
    from ..wechat.unified_inbox import get_inbox_stats
    return {"ok": True, **get_inbox_stats(account_id)}


@router.get("/api/inbox/conversations")
async def inbox_conversations(account_id: str = "", limit: int = 30):
    from ..wechat.unified_inbox import get_conversations
    return {"ok": True, "conversations": get_conversations(account_id, limit)}


@router.post("/api/inbox/read")
async def inbox_mark_read(request: Request):
    data = await request.json()
    from ..wechat.unified_inbox import mark_read
    mark_read(
        msg_ids=data.get("msg_ids"),
        account_id=data.get("account_id", ""),
        contact=data.get("contact", ""),
    )
    return {"ok": True}


@router.post("/api/inbox/star/{msg_id}")
async def inbox_star(msg_id: int):
    from ..wechat.unified_inbox import toggle_star
    starred = toggle_star(msg_id)
    return {"ok": True, "starred": starred}


# ── 转发规则 API ──────────────────────────────────────────────────────────────

@router.get("/api/forward-rules")
async def forward_rules_list():
    from ..wechat.unified_inbox import list_forward_rules
    return {"ok": True, "rules": [r.to_dict() for r in list_forward_rules()]}


@router.post("/api/forward-rules")
async def forward_rules_save(request: Request):
    data = await request.json()
    from ..wechat.unified_inbox import ForwardRule, save_forward_rule
    rule = ForwardRule(
        id=data.get("id", ""),
        name=data.get("name", "新规则"),
        enabled=data.get("enabled", True),
        src_account=data.get("src_account", ""),
        src_contact=data.get("src_contact", ""),
        dst_account=data.get("dst_account", ""),
        dst_contact=data.get("dst_contact", ""),
        keyword_filter=data.get("keyword_filter", ""),
        transform=data.get("transform", "plain"),
    )
    save_forward_rule(rule)
    return {"ok": True, "id": rule.id}


@router.delete("/api/forward-rules/{rule_id}")
async def forward_rules_delete(rule_id: str):
    from ..wechat.unified_inbox import delete_forward_rule
    delete_forward_rule(rule_id)
    return {"ok": True}


# ── 朋友圈协作 API ───────────────────────────────────────────────────────────

@router.get("/api/moments-coop/status")
async def moments_coop_status():
    from ..wechat.moments_coordinator import get_coordinator
    return {"ok": True, **get_coordinator().get_status()}


@router.post("/api/moments-coop/browse")
async def moments_coop_browse(request: Request):
    data = await request.json()
    from ..wechat.moments_coordinator import get_coordinator
    coord = get_coordinator()
    tasks = await coord.schedule_browse(
        account_ids=data.get("account_ids", []),
        max_posts=data.get("max_posts", 5),
        auto_interact=data.get("auto_interact", True),
    )
    return {"ok": True, "tasks": len(tasks)}


@router.post("/api/moments-coop/publish")
async def moments_coop_publish(request: Request):
    data = await request.json()
    from ..wechat.moments_coordinator import get_coordinator
    coord = get_coordinator()
    tasks = await coord.schedule_coop_publish(
        account_ids=data.get("account_ids", []),
        topic=data.get("topic", ""),
        text=data.get("text", ""),
        stagger_minutes=data.get("stagger_minutes", 30),
    )
    return {"ok": True, "tasks": len(tasks)}


# ── 账号健康度 API ───────────────────────────────────────────────────────────

@router.get("/api/health/overview")
async def health_overview():
    from ..wechat.account_health import get_health_monitor
    return {"ok": True, **get_health_monitor().get_overview()}


@router.get("/api/health/accounts")
async def health_accounts():
    from ..wechat.account_health import get_health_monitor
    return {"ok": True, "accounts": get_health_monitor().get_all_status()}


@router.get("/api/health/{account_id}")
async def health_account(account_id: str):
    from ..wechat.account_health import get_health_monitor
    return {"ok": True, **get_health_monitor().get_status(account_id)}


@router.post("/api/health/check")
async def health_check():
    """手动触发心跳检查"""
    from ..wechat.account_health import get_health_monitor
    await get_health_monitor().check_all_heartbeats()
    return {"ok": True, "accounts": get_health_monitor().get_all_status()}


# ── 话题跟踪 API ─────────────────────────────────────────────────────────────

@router.get("/api/topics")
async def topics_status(session: str = "default"):
    from ..topic_tracker import get_tracker
    return {"ok": True, **get_tracker(session).get_status()}


# ── 通知聚合 API ─────────────────────────────────────────────────────────────

@router.get("/api/notifications/digest")
async def notif_digest(min_priority: int = 0, limit: int = 20):
    from ..notification_aggregator import get_aggregator
    return {"ok": True, "groups": get_aggregator().get_digest(min_priority, limit)}


@router.get("/api/notifications/summary")
async def notif_summary():
    from ..notification_aggregator import get_aggregator
    return {"ok": True, **get_aggregator().get_unread_summary()}


@router.post("/api/notifications/clear")
async def notif_clear(request: Request):
    data = await request.json()
    from ..notification_aggregator import get_aggregator
    get_aggregator().clear_group(data.get("account_id", ""), data.get("contact", ""))
    return {"ok": True}


@router.post("/api/notifications/summarize")
async def notif_ai_summarize():
    """用 AI 为高优先级分组生成摘要"""
    from ..notification_aggregator import get_aggregator
    agg = get_aggregator()
    backend = _get_backend()
    if backend:
        await agg.generate_summaries(ai_call=backend.chat_simple)
    return {"ok": True, "groups": agg.get_digest(limit=10)}


# ── 意图预测 API ─────────────────────────────────────────────────────────────

@router.get("/api/intent")
async def intent_status(session: str = "default"):
    from ..intent_predictor import get_predictor
    return {"ok": True, **get_predictor(session).get_status()}


# ── 联系人融合 API ───────────────────────────────────────────────────────────

@router.get("/api/contacts/discover-matches")
async def contacts_discover():
    from ..wechat.contact_fusion import auto_discover_matches
    return {"ok": True, "matches": auto_discover_matches()}


@router.post("/api/contacts/fuse")
async def contacts_fuse(request: Request):
    data = await request.json()
    from ..wechat.contact_fusion import create_fused_contact
    fc = create_fused_contact(
        display_name=data.get("display_name", ""),
        account_contacts=data.get("account_contacts", []),
        relationship=data.get("relationship", "normal"),
    )
    return {"ok": True, "id": fc.id}


@router.get("/api/contacts/fused")
async def contacts_fused_list():
    from ..wechat.contact_fusion import list_fused_contacts
    return {"ok": True, "contacts": [c.to_dict() for c in list_fused_contacts()]}


@router.get("/api/contacts/fused/{fused_id}")
async def contacts_fused_detail(fused_id: str):
    from ..wechat.contact_fusion import get_360_view
    return {"ok": True, **get_360_view(fused_id)}


@router.post("/api/contacts/fused/{fused_id}/merge")
async def contacts_fuse_merge(fused_id: str, request: Request):
    data = await request.json()
    from ..wechat.contact_fusion import merge_contacts
    ok = merge_contacts(fused_id, data.get("account_id", ""), data.get("name", ""))
    return {"ok": ok}


@router.delete("/api/contacts/fused/{fused_id}")
async def contacts_fuse_delete(fused_id: str):
    from ..wechat.contact_fusion import delete_fused_contact
    delete_fused_contact(fused_id)
    return {"ok": True}


# ── 情感分析 API ─────────────────────────────────────────────────────────────

@router.get("/api/sentiment/overview")
async def sentiment_overview():
    from ..sentiment_analyzer import get_overview
    return {"ok": True, **get_overview()}


@router.get("/api/sentiment/trend")
async def sentiment_trend(hours: int = 24, account_id: str = ""):
    from ..sentiment_analyzer import get_trend
    return {"ok": True, "trend": get_trend(hours, account_id)}


@router.get("/api/sentiment/contact/{contact}")
async def sentiment_contact(contact: str):
    from ..sentiment_analyzer import get_contact_sentiment
    return {"ok": True, **get_contact_sentiment(contact)}


# ── 群聊管理 API ─────────────────────────────────────────────────────────────

@router.get("/api/groups")
async def groups_list():
    from ..wechat.group_manager import get_group_manager
    return {"ok": True, "groups": get_group_manager().get_all_groups()}


@router.get("/api/groups/{group_name}")
async def group_stats(group_name: str):
    from ..wechat.group_manager import get_group_manager
    stats = get_group_manager().get_group_stats(group_name)
    return {"ok": True, **(stats or {})}


@router.get("/api/groups/{group_name}/important")
async def group_important(group_name: str, limit: int = 20):
    from ..wechat.group_manager import get_group_manager
    msgs = get_group_manager().get_important_messages(group_name, limit)
    return {"ok": True, "messages": msgs}


@router.post("/api/groups/{group_name}/summary")
async def group_summary(group_name: str):
    from ..wechat.group_manager import get_group_manager
    backend = _get_backend()
    ai_call = backend.chat_simple if backend else None
    summary = await get_group_manager().generate_summary(group_name, ai_call)
    return {"ok": True, "summary": summary}


# ── 多账号并行管理 API ────────────────────────────────────────────────────────

@router.get("/api/accounts")
async def accounts_list():
    from ..wechat.account_manager import list_accounts, ensure_default_account
    ensure_default_account()
    return {"ok": True, "accounts": [a.to_dict() for a in list_accounts()]}


@router.post("/api/accounts")
async def accounts_save(request: Request):
    data = await request.json()
    from ..wechat.account_manager import WeChatAccount, save_account
    acct = WeChatAccount(
        id=data.get("id", ""),
        name=data.get("name", "新账号"),
        wx_name=data.get("wx_name", ""),
        notes=data.get("notes", ""),
        autoreply_config=data.get("autoreply_config", {}),
        moments_config=data.get("moments_config", {}),
    )
    save_account(acct)
    return {"ok": True, "id": acct.id}


@router.get("/api/accounts/discover")
async def accounts_discover():
    """扫描当前系统中所有运行的微信窗口"""
    from ..wechat.account_manager import discover_instances
    instances = discover_instances()
    return {"ok": True, "instances": [
        {"hwnd": i.hwnd, "pid": i.pid, "title": i.title,
         "wx_name": i.wx_name, "bound_account_id": i.bound_account_id}
        for i in instances
    ]}


@router.post("/api/accounts/{acct_id}/bind")
async def accounts_bind(acct_id: str, request: Request):
    """将账号绑定到指定的微信窗口句柄"""
    data = await request.json()
    hwnd = data.get("hwnd", 0)
    if not hwnd:
        return {"ok": False, "error": "请指定窗口句柄 hwnd"}
    from ..wechat.account_manager import bind_account
    ok = bind_account(acct_id, hwnd)
    return {"ok": ok}


@router.post("/api/accounts/auto-bind")
async def accounts_auto_bind():
    """自动发现并绑定所有微信窗口"""
    from ..wechat.account_manager import auto_bind_all
    result = auto_bind_all()
    return {"ok": True, "bound": result}


@router.post("/api/accounts/{acct_id}/disconnect")
async def accounts_disconnect(acct_id: str):
    """断开账号的微信连接"""
    from ..wechat.account_manager import disconnect_account
    disconnect_account(acct_id)
    return {"ok": True}


@router.delete("/api/accounts/{acct_id}")
async def accounts_delete(acct_id: str):
    from ..wechat.account_manager import delete_account
    delete_account(acct_id)
    return {"ok": True}


@router.get("/api/accounts/connected")
async def accounts_connected():
    """返回所有已连接的账号"""
    from ..wechat.account_manager import get_all_connected
    return {"ok": True, "connected": get_all_connected()}


# ── 消息路由规则 API ──────────────────────────────────────────────────────────

@router.get("/api/msg-rules")
async def msg_rules_list():
    """列出所有消息路由规则"""
    from ..wechat.msg_router import list_rules
    rules = list_rules()
    return {"ok": True, "rules": [r.to_dict() for r in rules]}


@router.post("/api/msg-rules")
async def msg_rules_save(request: Request):
    """创建/更新消息路由规则"""
    data = await request.json()
    from ..wechat.msg_router import RoutingRule, save_rule
    rule = RoutingRule(
        id=data.get("id", ""),
        name=data.get("name", "新规则"),
        enabled=data.get("enabled", True),
        priority=data.get("priority", 50),
        match_type=data.get("match_type", "keyword"),
        match_pattern=data.get("match_pattern", ""),
        match_contacts=data.get("match_contacts", ""),
        action_type=data.get("action_type", "notify"),
        action_target=data.get("action_target", ""),
        action_params=data.get("action_params", {}),
        cooldown_seconds=data.get("cooldown_seconds", 60),
    )
    save_rule(rule)
    return {"ok": True, "id": rule.id}


@router.delete("/api/msg-rules/{rule_id}")
async def msg_rules_delete(rule_id: str):
    """删除消息路由规则"""
    from ..wechat.msg_router import delete_rule
    delete_rule(rule_id)
    return {"ok": True}


@router.get("/api/msg-rules/stats")
async def msg_rules_stats():
    """消息路由统计"""
    from ..wechat.msg_router import MessageRouter
    msg_router = MessageRouter()
    return {"ok": True, **msg_router.get_stats()}


@router.post("/api/msg-rules/suggest")
async def msg_rules_suggest():
    """AI 分析消息历史，建议新路由规则"""
    try:
        backend = _get_app_state_backend()
        ai_call = backend.chat_simple if backend else None
        if not ai_call:
            return {"ok": False, "error": "AI backend not available"}
        from ..wechat.msg_router import suggest_rules
        suggestions = await suggest_rules(ai_call)
        return {"ok": True, "suggestions": suggestions}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 素材库 API ─────────────────────────────────────────────────────────────────

@router.get("/api/media/list")
async def media_list(category: str = "", tag: str = "", limit: int = 50):
    """列出素材"""
    from ..wechat.media_library import list_media, get_stats, get_categories
    return {
        "ok": True,
        "media": list_media(category=category, tag=tag, limit=limit),
        "stats": get_stats(),
        "categories": get_categories(),
    }


@router.post("/api/media/import")
async def media_import(request: Request):
    """导入素材"""
    data = await request.json()
    path = data.get("path", "")
    category = data.get("category", "")
    from ..wechat.media_library import import_file, import_directory
    if Path(path).is_dir():
        results = import_directory(path, category)
    else:
        r = import_file(path, category)
        results = [r] if r else []
    return {"ok": True, "imported": len(results), "results": results}


@router.post("/api/media/match")
async def media_match(request: Request):
    """根据文案匹配配图"""
    data = await request.json()
    text = data.get("text", "")
    count = data.get("count", 3)
    from ..wechat.media_library import match_images
    images = match_images(text, count=count, category_hint=data.get("category", ""))
    return {"ok": True, "images": images}


@router.post("/api/media/analyze/{media_id}")
async def media_analyze(media_id: str):
    """AI 分析素材"""
    ai = _get_app_state_backend()
    if not ai:
        return {"ok": False, "error": "AI backend not available"}

    async def vision_call(b64, prompt):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]
        if hasattr(ai, '_vision_client') and ai._vision_client:
            resp = await ai._vision_client.chat.completions.create(
                model=ai._vision_model, messages=messages, max_tokens=300
            )
            return resp.choices[0].message.content
        return ""

    from ..wechat.media_library import analyze_media
    result = await analyze_media(media_id, vision_call)
    return {"ok": bool(result), "analysis": result}


@router.delete("/api/media/{media_id}")
async def media_delete(media_id: str):
    from ..wechat.media_library import delete_media
    return {"ok": delete_media(media_id)}


# ── 数据分析 API ───────────────────────────────────────────────────────────────

@router.get("/api/analytics/overview")
async def analytics_overview(days: int = 30):
    from ..wechat.moments_analytics import get_overview
    return {"ok": True, **get_overview(days)}


@router.get("/api/analytics/hourly")
async def analytics_hourly(days: int = 30):
    from ..wechat.moments_analytics import get_hourly_distribution
    return {"ok": True, "distribution": get_hourly_distribution(days)}


@router.get("/api/analytics/top-contacts")
async def analytics_top_contacts(days: int = 30, limit: int = 10):
    from ..wechat.moments_analytics import get_top_contacts
    return {"ok": True, "contacts": get_top_contacts(days, limit)}


@router.get("/api/analytics/content-performance")
async def analytics_content_perf(days: int = 30):
    from ..wechat.moments_analytics import get_content_performance
    return {"ok": True, "performance": get_content_performance(days)}


@router.get("/api/analytics/best-times")
async def analytics_best_times(days: int = 30):
    from ..wechat.moments_analytics import get_best_posting_times
    return {"ok": True, **get_best_posting_times(days)}


@router.get("/api/analytics/weekly-trend")
async def analytics_weekly_trend(weeks: int = 8):
    from ..wechat.moments_analytics import get_weekly_trend
    return {"ok": True, "trend": get_weekly_trend(weeks)}


@router.post("/api/analytics/strategy-report")
async def analytics_strategy_report(days: int = 30):
    ai = _get_app_state_backend()
    ai_call = ai.chat_simple if ai else None
    from ..wechat.moments_analytics import generate_strategy_report
    report = await generate_strategy_report(ai_call, days)
    return {"ok": True, "report": report}


# ── 群发 API ───────────────────────────────────────────────────────────────────

@router.get("/api/broadcast/templates")
async def broadcast_templates():
    from ..wechat.broadcast import list_templates, ensure_builtin_templates
    ensure_builtin_templates()
    return {"ok": True, "templates": list_templates()}


@router.post("/api/broadcast/templates")
async def broadcast_save_template(request: Request):
    data = await request.json()
    from ..wechat.broadcast import MessageTemplate, save_template
    tpl = MessageTemplate(
        name=data.get("name", ""),
        content=data.get("content", ""),
        variables=data.get("variables", []),
        category=data.get("category", ""),
    )
    save_template(tpl)
    return {"ok": True, "template": tpl.to_dict()}


@router.delete("/api/broadcast/templates/{tid}")
async def broadcast_delete_template(tid: str):
    from ..wechat.broadcast import delete_template
    return {"ok": delete_template(tid)}


@router.post("/api/broadcast/filter-audience")
async def broadcast_filter_audience(request: Request):
    data = await request.json()
    from ..wechat.broadcast import filter_audience
    audience = filter_audience(
        min_intimacy=data.get("min_intimacy", 0),
        max_intimacy=data.get("max_intimacy", 100),
        relationship=data.get("relationship", ""),
        interests=data.get("interests"),
        exclude=data.get("exclude"),
    )
    return {"ok": True, "audience": audience, "count": len(audience)}


@router.post("/api/broadcast/send")
async def broadcast_send(request: Request):
    data = await request.json()
    from ..wechat.broadcast import BroadcastCampaign, BroadcastEngine

    campaign = BroadcastCampaign(
        name=data.get("name", "群发任务"),
        message=data.get("message", ""),
        targets=data.get("targets", []),
        personalize=data.get("personalize", False),
    )

    ai = _get_app_state_backend()
    ai_call = ai.chat_simple if ai else None

    async def send_fn(contact: str, msg: str) -> bool:
        try:
            from ..wechat.wxauto_reader import WxAutoReader
            reader = WxAutoReader()
            if reader._wx:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: reader._wx.SendMsg(msg, contact)
                )
                return True
        except Exception as e:
            logger.warning(f"Broadcast send failed: {contact}: {e}")
        return False

    from ..event_bus import publish as pub_event

    def progress_cb(current, total, contact, sent, failed):
        pub_event("broadcast_progress", {
            "current": current, "total": total,
            "contact": contact, "sent": sent, "failed": failed,
        })

    engine = BroadcastEngine(send_fn=send_fn, ai_call=ai_call)
    result = await engine.execute_campaign(campaign, progress_cb=progress_cb)
    pub_event("broadcast_complete", result)
    try:
        from .. import audit_log
        audit_log.log("broadcast_send", target=campaign.name,
                      detail=f"targets={len(campaign.targets)}, sent={result.get('sent',0)}")
    except Exception:
        pass
    return {"ok": True, **result}


@router.get("/api/broadcast/campaigns")
async def broadcast_campaigns():
    from ..wechat.broadcast import BroadcastEngine
    engine = BroadcastEngine()
    return {"ok": True, "campaigns": engine.get_campaigns()}


@router.get("/api/broadcast/stats")
async def broadcast_stats():
    from ..wechat.broadcast import BroadcastEngine
    engine = BroadcastEngine()
    return {"ok": True, **engine.get_daily_stats()}
