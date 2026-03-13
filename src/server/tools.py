"""
Function Calling tools for the AI assistant.

Implements ReAct-style tool use via simple text parsing (no native function-call API needed).
Tools: get_current_time, get_weather, calculate
"""

import json
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger


# ─────────────────────────────────────────────────────────────
# Tool definitions (OpenAI function-calling schema)
# ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Get the current date and time. Call this when the user asks what time it is, "
                "today's date, day of week, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone name, e.g. 'Asia/Shanghai'. Defaults to local.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Get current weather for a city. Use this when the user asks about the weather."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name in English, e.g. 'Beijing', 'Shanghai', 'London'.",
                    }
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression. Use this for arithmetic, "
                "unit conversion, or any calculation the user requests."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A Python-style math expression, e.g. '2 ** 10', 'sqrt(144)', '(3+4)*2'.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    # ── WeChat 工具 ──────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "send_wechat",
            "description": "发送微信消息给指定联系人。当用户说'帮我给xx发消息'、'告诉xx...'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {"type": "string", "description": "联系人昵称或备注名"},
                    "message": {"type": "string", "description": "要发送的消息内容"},
                },
                "required": ["contact", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_moment",
            "description": "发布朋友圈。当用户说'帮我发朋友圈'、'发一条关于xx的朋友圈'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "朋友圈文案。如果用户没给具体文案，留空让AI生成。"},
                    "topic": {"type": "string", "description": "主题关键词，用于AI生成文案"},
                    "style": {"type": "string", "description": "风格：日常/文艺/幽默/简洁，默认日常"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_moments",
            "description": "浏览朋友圈动态。当用户说'看看朋友圈'、'朋友圈有什么新动态'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "浏览条数，默认5"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wechat_stats",
            "description": "获取微信和朋友圈统计信息。当用户问'朋友圈数据'、'互动情况'时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_media",
            "description": "搜索素材库中的配图。当用户说'找张xx的图'、'有没有xx的素材'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "搜索关键词"},
                    "count": {"type": "integer", "description": "返回数量，默认3"},
                },
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast_message",
            "description": "群发微信消息（准备阶段）。返回目标人数预览，需用户确认后才调用 confirm_broadcast 执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "要群发的消息内容"},
                    "relationship": {"type": "string", "description": "筛选关系类型：friend/colleague/family/all"},
                    "min_intimacy": {"type": "number", "description": "最低亲密度（0-100），默认30"},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_broadcast",
            "description": "确认执行群发（用户说'确认'、'发吧'、'好的'后调用）。必须先调用 broadcast_message 预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "personalize": {"type": "boolean", "description": "是否用AI为每人个性化消息，默认false"},
                },
                "required": [],
            },
        },
    },
    # ── 多账号工具 ──────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "account_send",
            "description": (
                "用指定的微信账号发消息。当用户说'用2号发'、'帮我用小号给xx发消息'时调用。"
                "account 参数支持序号（'1号'→ default）或账号ID。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "账号标识：'1号'/'2号'/'小号' 或 账号ID"},
                    "contact": {"type": "string", "description": "联系人昵称"},
                    "message": {"type": "string", "description": "消息内容"},
                },
                "required": ["account", "contact", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "列出所有已连接的微信账号。当用户问'有几个号'、'哪些账号在线'时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "account_inbox",
            "description": "查看指定账号的未读消息。当用户说'2号有什么消息'、'看看小号的消息'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "账号标识：'1号'/'2号'/'小号' 或 账号ID"},
                },
                "required": ["account"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notification_digest",
            "description": "获取所有账号的消息摘要。当用户说'有什么新消息'、'消息汇总'时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ─────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────

def get_current_time(timezone: str = "") -> Dict[str, Any]:
    """Return the current local date and time."""
    now = datetime.now()
    weekdays_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_zh = weekdays_zh[now.weekday()]
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y年%m月%d日"),
        "time": now.strftime("%H:%M"),
        "weekday": weekday_zh,
        "timestamp": int(now.timestamp()),
    }


async def get_weather(city: str) -> Dict[str, Any]:
    """
    Fetch weather using the free Open-Meteo + Geocoding API.
    No API key required.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Geocode city → lat/lon
            geo_r = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            )
            geo_r.raise_for_status()
            geo_data = geo_r.json()

            if not geo_data.get("results"):
                return {"error": f"找不到城市: {city}"}

            loc = geo_data["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            city_name = loc.get("name", city)
            country = loc.get("country", "")

            # 2. Fetch current weather
            weather_r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": [
                        "temperature_2m",
                        "apparent_temperature",
                        "relative_humidity_2m",
                        "weather_code",
                        "wind_speed_10m",
                        "precipitation",
                    ],
                    "wind_speed_unit": "kmh",
                    "timezone": "auto",
                },
            )
            weather_r.raise_for_status()
            weather_data = weather_r.json()
            current = weather_data.get("current", {})

            return {
                "city": city_name,
                "country": country,
                "temperature": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "precipitation_mm": current.get("precipitation"),
                "condition": _wmo_code_to_zh(current.get("weather_code", 0)),
            }
    except httpx.TimeoutException:
        return {"error": "天气服务超时，请稍后再试"}
    except Exception as e:
        logger.warning(f"Weather API error: {e}")
        return {"error": f"获取天气失败: {e}"}


def calculate(expression: str) -> Dict[str, Any]:
    """Safely evaluate a mathematical expression."""
    # Whitelist characters and functions
    safe_expr = expression.strip()
    # Allow: digits, operators, parentheses, spaces, dots, and safe function names
    allowed = re.compile(r'^[\d\s\+\-\*/\(\)\.\^%,a-zA-Z_]+$')
    if not allowed.match(safe_expr):
        return {"error": f"不支持的表达式: {expression}"}

    # Map common math functions to Python
    safe_expr = safe_expr.replace("^", "**")
    safe_names = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "log": math.log, "log10": math.log10,
        "log2": math.log2, "abs": abs, "round": round,
        "floor": math.floor, "ceil": math.ceil,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(safe_expr, {"__builtins__": {}}, safe_names)  # noqa: S307
        return {"expression": expression, "result": result}
    except ZeroDivisionError:
        return {"error": "除以零"}
    except Exception as e:
        return {"error": f"计算错误: {e}"}


# ─────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────

async def send_wechat(contact: str, message: str) -> Dict[str, Any]:
    """发送微信消息"""
    try:
        from .wechat.wxauto_reader import WxAutoReader
        import asyncio
        reader = WxAutoReader()
        if reader._wx:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: reader._wx.SendMsg(message, contact))
            return {"success": True, "contact": contact, "message": message[:50]}
        return {"error": "微信未连接，请确认微信PC端已登录"}
    except ImportError:
        return {"error": "wxauto 未安装，请运行 pip install wxauto"}
    except Exception as e:
        return {"error": f"发送失败: {str(e)}"}


async def publish_moment(text: str = "", topic: str = "", style: str = "日常") -> Dict[str, Any]:
    """发布朋友圈"""
    try:
        if not text and topic:
            from .wechat.moments_ai import MomentsAIEngine
            engine = MomentsAIEngine()
            drafts = await engine.generate_moment_text(topic=topic, style=style)
            if drafts:
                text = drafts[0].get("text", "")
        if not text:
            return {"error": "未提供文案且无法生成，请指定内容或主题"}

        from .wechat.moments_actor import MomentsActor
        from .wechat.moments_guard import MomentsGuard
        from .wechat.moments_reader import MomentPost
        actor = MomentsActor(guard=MomentsGuard())
        success = await actor.publish_moment(text=text)
        if success:
            from .wechat.moments_analytics import record_publish
            record_publish(text)
            return {"success": True, "text": text[:100], "status": "已提交发布"}
        return {"error": "发布失败，可能被风控拦截或微信未连接"}
    except Exception as e:
        return {"error": f"发布失败: {str(e)}"}


async def browse_moments(count: int = 5) -> Dict[str, Any]:
    """浏览朋友圈"""
    try:
        from .wechat.moments_reader import MomentsReader
        reader = MomentsReader()
        page = await reader.browse(max_posts=count)
        if page and page.posts:
            summaries = []
            for p in page.posts[:count]:
                summaries.append(f"{p.author}: {p.text[:60]}")
            return {
                "success": True,
                "count": len(page.posts),
                "posts": summaries,
            }
        return {"info": "暂无新朋友圈动态"}
    except Exception as e:
        return {"error": f"浏览失败: {str(e)}"}


async def get_wechat_stats() -> Dict[str, Any]:
    """获取微信和朋友圈统计"""
    result = {}
    try:
        from .wechat.moments_guard import MomentsGuard
        guard = MomentsGuard()
        result["moments_guard"] = guard.get_stats()
    except Exception:
        pass
    try:
        from .wechat.moments_analytics import get_overview
        result["analytics"] = get_overview(7)
    except Exception:
        pass
    try:
        from .wechat.contact_profile import get_stats
        result["contacts"] = get_stats()
    except Exception:
        pass
    return result if result else {"info": "暂无统计数据"}


async def search_media(keywords: str, count: int = 3) -> Dict[str, Any]:
    """搜索素材库配图"""
    try:
        from .wechat.media_library import match_images
        images = match_images(keywords, count=count)
        if images:
            return {
                "success": True,
                "count": len(images),
                "images": [
                    {"filename": m["filename"], "tags": m.get("tags", [])[:5],
                     "category": m.get("category", "")}
                    for m in images
                ],
            }
        return {"info": "素材库中未找到匹配图片"}
    except Exception as e:
        return {"error": f"搜索失败: {str(e)}"}


async def broadcast_message(
    message: str,
    relationship: str = "all",
    min_intimacy: float = 30,
) -> Dict[str, Any]:
    """群发微信消息 — 第一次调用返回预览，用户确认后调用 confirm_broadcast 执行"""
    try:
        from .wechat.broadcast import filter_audience
        audience = filter_audience(
            min_intimacy=min_intimacy,
            relationship="" if relationship == "all" else relationship,
        )
        if not audience:
            return {"error": "未找到符合条件的联系人，请先添加联系人画像"}

        targets = [a["name"] for a in audience]

        # 缓存到全局以便 confirm_broadcast 使用
        _broadcast_pending["targets"] = targets
        _broadcast_pending["message"] = message
        _broadcast_pending["personalize"] = False

        return {
            "preview": True,
            "message": message[:80],
            "target_count": len(targets),
            "targets_sample": targets[:8],
            "info": f"已准备好向 {len(targets)} 人发送。请询问用户是否确认发送。如果确认，调用 confirm_broadcast。",
        }
    except Exception as e:
        return {"error": f"群发准备失败: {str(e)}"}


_broadcast_pending: Dict[str, Any] = {}


async def confirm_broadcast(personalize: bool = False) -> Dict[str, Any]:
    """确认并执行群发（用户语音确认后调用）"""
    if not _broadcast_pending.get("targets"):
        return {"error": "没有待发送的群发任务，请先调用 broadcast_message 准备"}

    targets = _broadcast_pending["targets"]
    message = _broadcast_pending["message"]
    _broadcast_pending.clear()

    try:
        from .wechat.broadcast import BroadcastCampaign, BroadcastEngine

        campaign = BroadcastCampaign(
            name="语音群发",
            message=message,
            targets=targets,
            personalize=personalize,
        )

        sent_count = 0

        async def send_fn(contact: str, msg: str) -> bool:
            try:
                from .wechat.wxauto_reader import WxAutoReader
                import asyncio as _aio
                reader = WxAutoReader()
                if reader._wx:
                    loop = _aio.get_event_loop()
                    await loop.run_in_executor(
                        None, lambda: reader._wx.SendMsg(msg, contact)
                    )
                    return True
            except Exception:
                pass
            return False

        engine = BroadcastEngine(send_fn=send_fn)
        result = await engine.execute_campaign(campaign)
        return {
            "success": True,
            "sent": result.get("sent", 0),
            "failed": result.get("failed", 0),
            "total": len(targets),
        }
    except Exception as e:
        return {"error": f"群发执行失败: {str(e)}"}


def _resolve_account(label: str) -> str:
    """
    将用户口语化的账号标识解析为 account_id。

    支持: "1号"→第1个, "2号"→第2个, "小号"/"大号"→模糊匹配, 或直接使用 ID
    """
    label = label.strip()
    # 序号匹配
    import re as _re
    m = _re.match(r"(\d+)\s*号", label)
    if m:
        idx = int(m.group(1)) - 1
        try:
            from .wechat.account_manager import list_accounts
            accts = list_accounts()
            if 0 <= idx < len(accts):
                return accts[idx].id
        except Exception:
            pass
        return label

    # 特殊昵称
    ALIAS_MAP = {"小号": 1, "大号": 0, "主号": 0, "副号": 1}
    if label in ALIAS_MAP:
        try:
            from .wechat.account_manager import list_accounts
            accts = list_accounts()
            idx = ALIAS_MAP[label]
            if idx < len(accts):
                return accts[idx].id
        except Exception:
            pass

    return label


async def account_send(account: str, contact: str, message: str) -> Dict[str, Any]:
    """用指定账号发送微信消息"""
    acct_id = _resolve_account(account)
    try:
        from .wechat.account_manager import get_wx
        import asyncio as _aio
        wx = get_wx(acct_id)
        if not wx:
            return {"error": f"账号 {acct_id} 未连接，请先在管理面板绑定"}
        loop = _aio.get_event_loop()
        await loop.run_in_executor(None, lambda: wx.SendMsg(message, contact))
        return {"success": True, "account": acct_id, "contact": contact, "message": message[:50]}
    except Exception as e:
        return {"error": f"发送失败: {str(e)}"}


async def list_accounts_tool() -> Dict[str, Any]:
    """列出所有已连接的微信账号"""
    try:
        from .wechat.account_manager import list_accounts as _la, get_wx
        accts = _la()
        result = []
        for i, a in enumerate(accts):
            connected = get_wx(a.id) is not None
            result.append({
                "index": i + 1,
                "id": a.id,
                "name": a.name or a.wx_name or a.id,
                "connected": connected,
                "status": a.status,
            })
        return {"accounts": result, "total": len(result), "connected": sum(1 for a in result if a["connected"])}
    except Exception as e:
        return {"error": f"获取账号列表失败: {str(e)}"}


async def account_inbox(account: str) -> Dict[str, Any]:
    """查看指定账号的未读消息"""
    acct_id = _resolve_account(account)
    try:
        from .wechat.unified_inbox import query_inbox, get_inbox_stats
        stats = get_inbox_stats(acct_id)
        msgs = query_inbox(account_id=acct_id, unread_only=True, limit=10)
        return {
            "account": acct_id,
            "unread": stats.get("unread", 0),
            "messages": [
                {"from": m["contact"], "content": m["content"][:60], "time": m.get("timestamp", 0)}
                for m in msgs
            ],
        }
    except Exception as e:
        return {"error": f"获取收件箱失败: {str(e)}"}


async def get_notification_digest() -> Dict[str, Any]:
    """获取所有账号的消息摘要"""
    try:
        from .notification_aggregator import get_aggregator
        agg = get_aggregator()
        digest = agg.get_digest(limit=10)
        summary = agg.get_unread_summary()
        return {
            "total_messages": summary.get("total_messages", 0),
            "high_priority": summary.get("high_priority", 0),
            "groups": [
                {"contact": g["contact"], "account": g["account_id"],
                 "count": g["count"], "priority": g["priority"], "brief": g["brief"]}
                for g in digest[:8]
            ],
        }
    except Exception as e:
        return {"error": f"获取消息摘要失败: {str(e)}"}


async def call_tool(name: str, args: Dict[str, Any]) -> str:
    """Dispatch a tool call and return a JSON string result."""
    try:
        if name == "get_current_time":
            result = get_current_time(**args)
        elif name == "get_weather":
            result = await get_weather(**args)
        elif name == "calculate":
            result = calculate(**args)
        elif name == "send_wechat":
            result = await send_wechat(**args)
        elif name == "publish_moment":
            result = await publish_moment(**args)
        elif name == "browse_moments":
            result = await browse_moments(**args)
        elif name == "get_wechat_stats":
            result = await get_wechat_stats()
        elif name == "search_media":
            result = await search_media(**args)
        elif name == "broadcast_message":
            result = await broadcast_message(**args)
        elif name == "confirm_broadcast":
            result = await confirm_broadcast(**args)
        elif name == "account_send":
            result = await account_send(**args)
        elif name == "list_accounts":
            result = await list_accounts_tool()
        elif name == "account_inbox":
            result = await account_inbox(**args)
        elif name == "get_notification_digest":
            result = await get_notification_digest()
        else:
            result = {"error": f"未知工具: {name}"}
    except Exception as e:
        result = {"error": str(e)}
    return json.dumps(result, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# System prompt injection
# ─────────────────────────────────────────────────────────────

TOOLS_SYSTEM_ADDENDUM = """
你可以使用以下工具来执行操作：

基础工具：
1. **get_current_time** — 获取当前时间日期
2. **get_weather(city)** — 获取城市天气（city 用英文如 "Beijing"）
3. **calculate(expression)** — 数学计算

微信工具：
4. **send_wechat(contact, message)** — 给指定联系人发微信消息
5. **publish_moment(text, topic, style)** — 发朋友圈
6. **browse_moments(count)** — 浏览朋友圈最新动态
7. **get_wechat_stats** — 获取微信互动统计
8. **search_media(keywords, count)** — 搜索素材库配图
9. **broadcast_message(message, relationship, min_intimacy)** — 群发预览
10. **confirm_broadcast(personalize)** — 确认群发

多账号工具：
11. **account_send(account, contact, message)** — 用指定账号发消息（account 支持 "1号"/"2号"/"小号" 或 ID）
12. **list_accounts** — 列出所有已连接的微信账号
13. **account_inbox(account)** — 查看指定账号的未读消息
14. **get_notification_digest** — 获取所有账号的消息摘要

调用格式（不要加额外文字）：
[TOOL_CALL] {"name": "工具名", "args": {...}} [/TOOL_CALL]

多步任务链（最多 5 步）：
- "用2号给张三发消息" → account_send(account="2号", ...)
- "看看有什么新消息" → get_notification_digest
- "发一条美食朋友圈配图" → search_media → publish_moment

规则：
- 用自然语言告知用户结果，不要显示 JSON。
- 群发消息前必须先告知目标人数并获得确认。
- 用户说"用X号"时，用 account_send 而不是 send_wechat。
""".strip()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _wmo_code_to_zh(code: int) -> str:
    """Convert WMO weather code to Chinese description."""
    mapping = {
        0: "晴天", 1: "大致晴朗", 2: "局部多云", 3: "阴天",
        45: "雾", 48: "冻雾",
        51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        80: "小阵雨", 81: "中阵雨", 82: "强阵雨",
        85: "小阵雪", 86: "大阵雪",
        95: "雷暴", 96: "雷暴带冰雹", 99: "强雷暴带冰雹",
    }
    return mapping.get(code, f"天气代码 {code}")


def parse_tool_calls(text: str) -> List[Dict]:
    """Extract all [TOOL_CALL]...[/TOOL_CALL] blocks from model output."""
    pattern = r'\[TOOL_CALL\]\s*(.*?)\s*\[/TOOL_CALL\]'
    matches = re.findall(pattern, text, re.DOTALL)
    calls = []
    for m in matches:
        try:
            obj = json.loads(m.strip())
            calls.append({"name": obj["name"], "args": obj.get("args", {})})
        except Exception:
            pass
    return calls
