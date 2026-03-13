# -*- coding: utf-8 -*-
"""
工作流节点注册表 & 实现

所有节点函数签名:  async def node_xxx(ctx: ExecContext, params: dict) -> Any
  - ctx 提供 AI后端、TTS引擎、上游节点输出、变量池
  - params 中 {{key}} 会在执行前被上下文插值替换
  - 返回值自动存入 ctx.outputs[node_id]

注册：用 @register("node_type") 装饰即可
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from loguru import logger

# ── 节点注册表 ──────────────────────────────────────────────────────────────────

NODE_REGISTRY: Dict[str, Callable] = {}


def register(node_type: str):
    """装饰器：将 async 函数注册为节点类型"""
    def decorator(fn):
        NODE_REGISTRY[node_type] = fn
        return fn
    return decorator


# ── 执行上下文 ──────────────────────────────────────────────────────────────────

@dataclass
class ExecContext:
    """工作流执行期间的共享上下文"""
    workflow_id: str = ""
    workflow_name: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    ai_backend: Any = None        # AIBackend instance
    tts_engine: Any = None        # ChatterboxTTS instance
    wechat_adapter: Any = None    # WeChatAdapter instance
    wechat_engine: Any = None     # WeChatAutoReply instance
    desktop: Any = None           # DesktopStreamer instance
    event_data: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def get(self, key: str, default=None):
        """从上下文获取值，支持点号路径：node_id.key"""
        if "." in key:
            parts = key.split(".", 1)
            node_out = self.outputs.get(parts[0])
            if isinstance(node_out, dict):
                return node_out.get(parts[1], default)
            if node_out is not None and parts[1] == "output":
                return node_out
            return default
        if key in self.variables:
            return self.variables[key]
        if key in self.outputs:
            return self.outputs[key]
        return default


def interpolate(text: str, ctx: ExecContext) -> str:
    """将 {{expr}} 替换为上下文中的值"""
    if not isinstance(text, str):
        return text

    def _replace(m):
        expr = m.group(1).strip()
        val = ctx.get(expr, "")
        return str(val) if val is not None else ""

    return re.sub(r"\{\{(.+?)\}\}", _replace, text)


def interpolate_params(params: dict, ctx: ExecContext) -> dict:
    """递归插值 params 字典中的所有字符串值"""
    result = {}
    for k, v in params.items():
        if isinstance(v, str):
            result[k] = interpolate(v, ctx)
        elif isinstance(v, dict):
            result[k] = interpolate_params(v, ctx)
        elif isinstance(v, list):
            result[k] = [
                interpolate(item, ctx) if isinstance(item, str) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# ── LLM 节点 ────────────────────────────────────────────────────────────────────

@register("llm_generate")
async def node_llm_generate(ctx: ExecContext, params: dict) -> Any:
    """调用 LLM 生成文本"""
    prompt = params.get("prompt", "")
    system = params.get("system", "你是一个有用的AI助手，回答简洁明了。")
    max_tokens = int(params.get("max_tokens", 500))

    if not ctx.ai_backend:
        return {"output": "[错误] AI 后端未初始化", "error": True}

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        result = await ctx.ai_backend.chat_simple(messages)
        return {"output": result.strip()}
    except Exception as e:
        logger.error(f"llm_generate error: {e}")
        return {"output": f"[LLM错误] {e}", "error": True}


@register("llm_classify")
async def node_llm_classify(ctx: ExecContext, params: dict) -> Any:
    """用 LLM 对文本进行分类"""
    text = params.get("text", "")
    categories = params.get("categories", [])
    cat_str = "、".join(categories) if categories else "正面、负面、中性"

    prompt = f"请将以下文本分类为其中一个类别：{cat_str}\n\n文本：{text}\n\n只返回类别名称，不要解释。"
    messages = [{"role": "user", "content": prompt}]

    if not ctx.ai_backend:
        return {"category": "unknown", "error": True}

    try:
        result = await ctx.ai_backend.chat_simple(messages)
        return {"category": result.strip(), "output": result.strip()}
    except Exception as e:
        return {"category": "unknown", "error": str(e)}


# ── 模板节点 ─────────────────────────────────────────────────────────────────────

@register("template")
async def node_template(ctx: ExecContext, params: dict) -> Any:
    """字符串模板拼接，已在执行前完成 {{}} 插值"""
    template = params.get("template", "")
    return {"output": template}


# ── TTS 节点 ─────────────────────────────────────────────────────────────────────

@register("tts_speak")
async def node_tts_speak(ctx: ExecContext, params: dict) -> Any:
    """通过 TTS 引擎朗读文本"""
    text = params.get("text", "")
    if not text:
        return {"output": "空文本，跳过朗读"}

    if ctx.tts_engine:
        try:
            audio = await asyncio.get_event_loop().run_in_executor(
                None, ctx.tts_engine.synthesize, text
            )
            return {"output": f"已朗读 {len(text)} 字", "audio_len": len(audio) if audio else 0}
        except Exception as e:
            logger.warning(f"TTS speak failed: {e}")
            return {"output": f"朗读失败: {e}", "error": True}
    return {"output": "TTS 引擎未就绪", "error": True}


# ── 微信节点 ─────────────────────────────────────────────────────────────────────

@register("wechat_send")
async def node_wechat_send(ctx: ExecContext, params: dict) -> Any:
    """发送微信消息"""
    contact = params.get("contact", "")
    message = params.get("message", "")
    if not contact or not message:
        return {"output": "缺少联系人或消息内容", "error": True}

    adapter = ctx.wechat_adapter
    if adapter:
        try:
            ok = await asyncio.get_event_loop().run_in_executor(
                None, adapter.send_message, contact, message
            )
            return {"output": f"已发送给 {contact}", "success": ok}
        except Exception as e:
            return {"output": f"发送失败: {e}", "error": True}
    return {"output": "微信适配器未就绪", "error": True}


@register("wechat_read")
async def node_wechat_read(ctx: ExecContext, params: dict) -> Any:
    """读取微信新消息"""
    contact = params.get("contact", "")

    adapter = ctx.wechat_adapter
    if adapter:
        try:
            messages = await asyncio.get_event_loop().run_in_executor(
                None, adapter.get_new_messages
            )
            if contact:
                messages = [m for m in messages if m.contact == contact]
            msg_list = [
                {"sender": m.sender, "content": m.content, "contact": m.contact,
                 "time": m.raw_time_str}
                for m in messages
            ]
            return {
                "output": f"读取到 {len(msg_list)} 条消息",
                "messages": msg_list,
                "count": len(msg_list),
            }
        except Exception as e:
            return {"output": f"读取失败: {e}", "messages": [], "error": True}
    return {"output": "微信适配器未就绪", "messages": [], "error": True}


@register("wechat_autoreply")
async def node_wechat_autoreply(ctx: ExecContext, params: dict) -> Any:
    """控制微信自动回复（启动/停止/切换智能模式）"""
    action = params.get("action", "status")  # start / stop / status / toggle_smart
    engine = ctx.wechat_engine

    if not engine:
        return {"output": "自动回复引擎未就绪", "error": True}

    if action == "start":
        engine.start()
        return {"output": "自动回复已启动"}
    elif action == "stop":
        engine.stop()
        return {"output": "自动回复已停止"}
    elif action == "toggle_smart":
        cfg = engine.config
        cfg.smart_mode = not getattr(cfg, "smart_mode", False)
        return {"output": f"智能模式 {'开启' if cfg.smart_mode else '关闭'}"}
    else:
        stats = engine.get_stats()
        return {"output": "自动回复状态", "stats": stats}


# ── 系统节点 ─────────────────────────────────────────────────────────────────────

@register("delay")
async def node_delay(ctx: ExecContext, params: dict) -> Any:
    """等待指定秒数"""
    seconds = float(params.get("seconds", 1))
    seconds = min(seconds, 3600)
    await asyncio.sleep(seconds)
    return {"output": f"等待了 {seconds} 秒"}


@register("condition")
async def node_condition(ctx: ExecContext, params: dict) -> Any:
    """
    条件分支：根据 expr 决定走 then_branch 还是 else_branch。
    expr 支持简单表达式，如 "{{count}} > 0"
    """
    expr = params.get("expr", "true")
    then_val = params.get("then", "true")
    else_val = params.get("else", "false")

    try:
        result = bool(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        result = bool(expr and expr.lower() not in ("false", "0", "", "none"))

    branch = then_val if result else else_val
    return {"output": branch, "condition": result, "branch": "then" if result else "else"}


@register("system_info")
async def node_system_info(ctx: ExecContext, params: dict) -> Any:
    """获取系统信息"""
    info_type = params.get("type", "datetime")  # datetime / date / time / weekday
    now = datetime.now()

    WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    info = {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": WEEKDAY_CN[now.weekday()],
        "timestamp": time.time(),
    }

    if info_type == "all":
        return {"output": json.dumps(info, ensure_ascii=False), **info}
    val = info.get(info_type, info["datetime"])
    return {"output": val, **info}


@register("http_request")
async def node_http_request(ctx: ExecContext, params: dict) -> Any:
    """发起 HTTP 请求"""
    import httpx

    url = params.get("url", "")
    method = params.get("method", "GET").upper()
    headers = params.get("headers", {})
    body = params.get("body", None)
    timeout = float(params.get("timeout", 15))

    if not url:
        return {"output": "缺少 URL", "error": True}

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            if method == "POST":
                resp = await client.post(url, json=body, headers=headers)
            elif method == "PUT":
                resp = await client.put(url, json=body, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            else:
                resp = await client.get(url, headers=headers)

            try:
                data = resp.json()
            except Exception:
                data = resp.text

            return {
                "output": resp.text[:500],
                "status_code": resp.status_code,
                "data": data,
            }
    except Exception as e:
        return {"output": f"请求失败: {e}", "error": True}


@register("notify")
async def node_notify(ctx: ExecContext, params: dict) -> Any:
    """发送通知（Windows toast / 日志 / 微信自发消息）"""
    message = params.get("message", "")
    channel = params.get("channel", "log")  # log / toast / wechat

    if channel == "toast":
        try:
            from ctypes import windll
            windll.user32.MessageBoxW(0, message, "OpenClaw 工作流通知", 0x40)
            return {"output": "已弹出通知"}
        except Exception:
            logger.info(f"[通知] {message}")
            return {"output": f"[通知] {message}"}
    elif channel == "wechat":
        contact = params.get("contact", "文件传输助手")
        if ctx.wechat_adapter:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, ctx.wechat_adapter.send_message, contact, message
                )
                return {"output": f"已通知 {contact}"}
            except Exception as e:
                return {"output": f"通知失败: {e}", "error": True}
    logger.info(f"[工作流通知] {message}")
    return {"output": message}


# ── 数据节点 ─────────────────────────────────────────────────────────────────────

@register("file_read")
async def node_file_read(ctx: ExecContext, params: dict) -> Any:
    """读取文件内容"""
    path = params.get("path", "")
    encoding = params.get("encoding", "utf-8")
    max_chars = int(params.get("max_chars", 10000))

    if not path:
        return {"output": "缺少文件路径", "error": True}

    try:
        with open(path, "r", encoding=encoding, errors="replace") as f:
            content = f.read(max_chars)
        return {"output": content, "length": len(content)}
    except Exception as e:
        return {"output": f"读取失败: {e}", "error": True}


@register("file_write")
async def node_file_write(ctx: ExecContext, params: dict) -> Any:
    """写入文件"""
    path = params.get("path", "")
    content = params.get("content", "")
    mode = params.get("mode", "w")  # w / a

    if not path:
        return {"output": "缺少文件路径", "error": True}

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return {"output": f"已写入 {len(content)} 字到 {path}"}
    except Exception as e:
        return {"output": f"写入失败: {e}", "error": True}


@register("skill_execute")
async def node_skill_execute(ctx: ExecContext, params: dict) -> Any:
    """执行桌面技能"""
    skill_id = params.get("skill_id", "")
    if not skill_id:
        return {"output": "缺少 skill_id", "error": True}

    try:
        from ..desktop_skills import get_skill
        skill = get_skill(skill_id)
        if not skill:
            return {"output": f"技能 {skill_id} 不存在", "error": True}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, skill.execute, ctx.desktop)
        return {"output": str(result), "result": result}
    except Exception as e:
        return {"output": f"技能执行失败: {e}", "error": True}


@register("python_eval")
async def node_python_eval(ctx: ExecContext, params: dict) -> Any:
    """
    安全的 Python 表达式求值。
    仅允许数学运算和字符串操作，不可导入或调用危险函数。
    """
    expression = params.get("expression", "")
    if not expression:
        return {"output": "", "error": True}

    safe_globals = {"__builtins__": {}}
    safe_locals = {
        "len": len, "str": str, "int": int, "float": float,
        "max": max, "min": min, "sum": sum, "abs": abs,
        "round": round, "sorted": sorted,
    }
    safe_locals.update(ctx.variables)

    try:
        result = eval(expression, safe_globals, safe_locals)
        return {"output": str(result), "value": result}
    except Exception as e:
        return {"output": f"表达式错误: {e}", "error": True}


@register("loop")
async def node_loop(ctx: ExecContext, params: dict) -> Any:
    """
    循环节点 — 对列表数据循环执行子节点。
    参数：
      items_key: 上下文中列表数据的 key（如 "wechat_read.messages"）
      item_var:  每次迭代注入到变量池的名称（默认 "item"）
      sub_nodes: 每次迭代要执行的节点定义列表
    """
    items_key = params.get("items_key", "")
    items = ctx.get(items_key, [])
    if not isinstance(items, list):
        items = [items] if items else []

    item_var = params.get("item_var", "item")
    results = []

    for i, item in enumerate(items):
        ctx.variables[item_var] = item
        ctx.variables["loop_index"] = i
        results.append({"index": i, "item": str(item)[:200]})

    return {"output": f"循环 {len(items)} 次", "count": len(items), "results": results}


@register("parallel")
async def node_parallel(ctx: ExecContext, params: dict) -> Any:
    """
    并行节点 — 同时执行多个子节点（简化版：记录需要并行的节点ID列表）。
    实际并行执行逻辑在 engine.py 中处理。
    """
    node_ids = params.get("node_ids", [])
    return {"output": f"并行执行 {len(node_ids)} 个节点", "node_ids": node_ids}


# ── 朋友圈节点 ────────────────────────────────────────────────────────────────────

@register("wechat_browse_moments")
async def node_wechat_browse_moments(ctx: ExecContext, params: dict) -> Any:
    """浏览朋友圈并用 AI 分析每条动态"""
    max_posts = int(params.get("max_posts", 5))
    auto_interact = params.get("auto_interact", False)

    try:
        from ..wechat.moments_reader import MomentsReader
        from ..wechat.moments_ai import MomentsAIEngine
        from ..wechat.moments_actor import MomentsActor
        from ..wechat.moments_guard import MomentsGuard

        reader = MomentsReader(
            ai_backend=ctx.ai_backend,
            wxauto_reader=getattr(ctx.wechat_adapter, "_wxauto_reader", None)
                          if ctx.wechat_adapter else None,
        )
        page = await reader.browse(max_posts)

        if not page.posts:
            return {"output": "未读取到朋友圈动态", "posts": [], "count": 0}

        results = []
        ai_engine = MomentsAIEngine(
            ai_call=ctx.ai_backend.chat_simple if ctx.ai_backend else None,
        )

        for post in page.posts:
            analysis = await ai_engine.analyze_post(post)
            entry = {
                "author": post.author,
                "text": post.text[:200],
                "image_desc": post.image_desc[:200],
                "summary": analysis.content_summary,
                "mood": analysis.mood,
                "should_like": analysis.should_like,
                "should_comment": analysis.should_comment,
                "comment": analysis.comment_text,
            }
            results.append(entry)

            if auto_interact and (analysis.should_like or analysis.should_comment):
                actor = MomentsActor(
                    wxauto_reader=getattr(ctx.wechat_adapter, "_wxauto_reader", None),
                    guard=MomentsGuard(),
                )
                if analysis.should_like:
                    await actor.like_post(post)
                if analysis.should_comment and analysis.comment_text:
                    await actor.comment_post(post, analysis.comment_text)

        summary = f"浏览了 {len(results)} 条动态"
        return {"output": summary, "posts": results, "count": len(results)}

    except Exception as e:
        logger.error(f"朋友圈浏览节点错误: {e}")
        return {"output": f"错误: {e}", "posts": [], "error": True}


@register("wechat_publish_moment")
async def node_wechat_publish_moment(ctx: ExecContext, params: dict) -> Any:
    """发布朋友圈"""
    text = params.get("text", "")
    media_files = params.get("media_files", [])
    privacy = params.get("privacy", "all")
    generate = params.get("generate", False)
    topic = params.get("topic", "")

    if generate and ctx.ai_backend:
        from ..wechat.moments_ai import MomentsAIEngine
        ai_engine = MomentsAIEngine(ai_call=ctx.ai_backend.chat_simple)
        drafts = await ai_engine.generate_moment_text(
            topic=topic or text,
            style=params.get("style", "日常"),
            mood=params.get("mood", "平常"),
        )
        if drafts:
            text = drafts[0]["text"]

    if not text:
        return {"output": "缺少文案内容", "error": True}

    try:
        from ..wechat.moments_actor import MomentsActor
        from ..wechat.moments_guard import MomentsGuard

        actor = MomentsActor(
            wxauto_reader=getattr(ctx.wechat_adapter, "_wxauto_reader", None)
                          if ctx.wechat_adapter else None,
            guard=MomentsGuard(),
        )
        ok = await actor.publish_moment(text, media_files, privacy)
        return {"output": f"发圈{'成功' if ok else '失败'}: {text[:50]}", "success": ok, "text": text}

    except Exception as e:
        return {"output": f"发圈错误: {e}", "error": True}


@register("wechat_like_moment")
async def node_wechat_like_moment(ctx: ExecContext, params: dict) -> Any:
    """对指定动态点赞（通常配合 browse_moments 使用）"""
    author = params.get("author", "")
    post_text = params.get("post_text", "")

    if not author:
        return {"output": "缺少作者信息", "error": True}

    from ..wechat.moments_reader import MomentPost
    from ..wechat.moments_actor import MomentsActor
    from ..wechat.moments_guard import MomentsGuard

    post = MomentPost(author=author, text=post_text)
    actor = MomentsActor(
        wxauto_reader=getattr(ctx.wechat_adapter, "_wxauto_reader", None)
                      if ctx.wechat_adapter else None,
        guard=MomentsGuard(),
    )
    ok = await actor.like_post(post)
    return {"output": f"点赞 {author} {'成功' if ok else '失败'}", "success": ok}


@register("wechat_comment_moment")
async def node_wechat_comment_moment(ctx: ExecContext, params: dict) -> Any:
    """对指定动态发表评论"""
    author = params.get("author", "")
    comment = params.get("comment", "")
    post_text = params.get("post_text", "")
    ai_generate = params.get("ai_generate", False)

    if not author:
        return {"output": "缺少作者信息", "error": True}

    from ..wechat.moments_reader import MomentPost
    from ..wechat.moments_ai import MomentsAIEngine
    from ..wechat.moments_actor import MomentsActor
    from ..wechat.moments_guard import MomentsGuard

    post = MomentPost(author=author, text=post_text)

    if ai_generate and ctx.ai_backend and not comment:
        ai_engine = MomentsAIEngine(ai_call=ctx.ai_backend.chat_simple)
        analysis = await ai_engine.analyze_post(post)
        comment = analysis.comment_text

    if not comment:
        return {"output": "无评论内容", "error": True}

    actor = MomentsActor(
        wxauto_reader=getattr(ctx.wechat_adapter, "_wxauto_reader", None)
                      if ctx.wechat_adapter else None,
        guard=MomentsGuard(),
    )
    ok = await actor.comment_post(post, comment)
    return {"output": f"评论 {author} {'成功' if ok else '失败'}: {comment[:30]}", "success": ok}


def get_available_nodes() -> List[Dict[str, str]]:
    """返回所有已注册节点类型的列表"""
    NODE_INFO = {
        "llm_generate": {"label": "LLM 生成", "icon": "🤖", "category": "AI"},
        "llm_classify": {"label": "LLM 分类", "icon": "🏷️", "category": "AI"},
        "template": {"label": "文本模板", "icon": "📝", "category": "数据"},
        "tts_speak": {"label": "语音朗读", "icon": "🔊", "category": "输出"},
        "wechat_send": {"label": "微信发送", "icon": "💬", "category": "微信"},
        "wechat_read": {"label": "微信读取", "icon": "📩", "category": "微信"},
        "wechat_autoreply": {"label": "自动回复控制", "icon": "🤖", "category": "微信"},
        "delay": {"label": "延时等待", "icon": "⏱️", "category": "控制"},
        "condition": {"label": "条件分支", "icon": "🔀", "category": "控制"},
        "system_info": {"label": "系统信息", "icon": "ℹ️", "category": "系统"},
        "http_request": {"label": "HTTP 请求", "icon": "🌐", "category": "数据"},
        "notify": {"label": "发送通知", "icon": "🔔", "category": "输出"},
        "file_read": {"label": "读取文件", "icon": "📄", "category": "数据"},
        "file_write": {"label": "写入文件", "icon": "💾", "category": "数据"},
        "skill_execute": {"label": "执行技能", "icon": "🎯", "category": "系统"},
        "python_eval": {"label": "表达式计算", "icon": "🔢", "category": "数据"},
        "loop": {"label": "循环", "icon": "🔄", "category": "控制"},
        "parallel": {"label": "并行执行", "icon": "⚡", "category": "控制"},
        "wechat_browse_moments": {"label": "浏览朋友圈", "icon": "👀", "category": "朋友圈"},
        "wechat_publish_moment": {"label": "发朋友圈", "icon": "📢", "category": "朋友圈"},
        "wechat_like_moment": {"label": "点赞朋友圈", "icon": "👍", "category": "朋友圈"},
        "wechat_comment_moment": {"label": "评论朋友圈", "icon": "💭", "category": "朋友圈"},
    }

    result = []
    for ntype in NODE_REGISTRY:
        info = NODE_INFO.get(ntype, {"label": ntype, "icon": "⚙️", "category": "其他"})
        result.append({"type": ntype, **info})
    return result
