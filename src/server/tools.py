"""
Function Calling tools for the AI assistant.

Implements ReAct-style tool use via simple text parsing (no native function-call API needed).
Tools: get_current_time, get_weather, calculate
"""

import json
import math
import os
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
            "name": "web_search",
            "description": "搜索互联网获取最新信息。当用户要求搜索、查找、采集新闻/资料时调用。比打开浏览器更快更准。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如'OpenClaw最新新闻'、'AI行业动态2026'"},
                    "count": {"type": "integer", "description": "返回结果数量，默认5"}
                },
                "required": ["query"],
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
    # ── 桌面操作工具（A2A 集成）──────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "desktop_screenshot",
            "description": "截取当前屏幕并用 OCR 识别文字。当用户说'看看屏幕'、'截个图'、'屏幕上写了什么'时调用。",
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
            "name": "desktop_click",
            "description": "点击屏幕上的指定文字或位置。当用户说'点击xx按钮'、'打开xx'时调用。先截图识别，再精确点击。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "要点击的文字内容（会先 OCR 定位再点击）"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_type",
            "description": "在当前焦点位置输入文字。当用户说'输入xx'、'打字xx'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文字内容"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_hotkey",
            "description": "执行键盘快捷键。当用户说'复制'、'粘贴'、'撤销'、'全选'、'切换窗口'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "string",
                        "description": "快捷键组合，如 'ctrl+c'、'ctrl+v'、'alt+tab'、'ctrl+z'、'ctrl+a'",
                    },
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "打开应用程序。当用户说'打开微信'、'打开浏览器'、'打开记事本'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名称：微信/浏览器/记事本/文件管理器/命令行/计算器"},
                },
                "required": ["app_name"],
            },
        },
    },
    # ── IoT 工具 ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "iot_control",
            "description": "控制智能家居设备。当用户说'关灯'、'开空调'、'调高温度'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名称，如'客厅灯'、'卧室空调'"},
                    "action": {"type": "string", "description": "操作：on/off/toggle/set_temperature/set_brightness"},
                    "value": {"type": "object", "description": "参数，如 {\"brightness\": 128} 或 {\"temperature\": 26}"},
                },
                "required": ["device_name", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_wechat_messages",
            "description": "读取微信聊天记录。当用户说'看看张三发了什么'、'微信有新消息吗'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {"type": "string", "description": "联系人昵称（留空则读取当前会话）"},
                    "count": {"type": "integer", "description": "读取条数，默认10"},
                },
                "required": [],
            },
        },
    },
    # ── Agent 团队工具（核心！让 AI 能调度团队干活）──────────
    {
        "type": "function",
        "function": {
            "name": "deploy_team",
            "description": "部署 AI 团队来完成复杂任务。当用户说'帮我做方案'、'写一个计划'、'分析市场'、'做竞品调研'、'上架产品'等需要多人协作的任务时，必须调用此工具。不要自己回答，交给团队去做。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "任务描述（用户的原始需求）"},
                    "template": {
                        "type": "string",
                        "description": "团队模板：startup(创业5人)/software(研发10人)/content_factory(内容8人)/marketing(营销10人)/ecommerce(电商15人)/service_center(客服7人)/business(商务6人)/consulting(咨询7人)/all_hands(全员52人)。根据任务类型选择最合适的。",
                    },
                },
                "required": ["task", "template"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_morning_brief",
            "description": "团队早会。当用户说'团队早会'、'汇报工作'、'今天的进度'、'团队状态'时调用。各 Agent 逐一汇报最新工作成果。",
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
            "name": "confirm_team",
            "description": "用户确认后开始执行团队任务。当用户说'开始'、'出发'、'执行'、'好的开始吧'时调用。必须在 deploy_team 之后、用户明确确认后才能调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {"type": "string", "description": "deploy_team 返回的 team_id"},
                    "task": {"type": "string", "description": "最终确认的任务描述（可能经过用户修改）"},
                },
                "required": ["team_id", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_team_result",
            "description": "查询 AI 团队的执行结果。当之前已部署团队且用户问'做完了吗'、'结果呢'、'方案出来了吗'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {"type": "string", "description": "团队ID（deploy_team 返回的）"},
                },
                "required": ["team_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_last_project",
            "description": (
                "继续上次的项目/方案。当用户说'继续上次'、'接着做'、'上次的方案'、'继续之前的'时调用。"
                "自动加载最近的项目成果，让团队在此基础上续做。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "用户补充的新要求（如'把文案部分重写'、'加上预算表'）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_history",
            "description": (
                "查看历史项目列表。当用户问'之前做过什么'、'有哪些项目'、'历史方案'时调用。"
            ),
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


async def web_search(query: str, count: int = 5) -> Dict[str, Any]:
    """搜索互联网，返回搜索结果摘要"""
    try:
        # 用 DuckDuckGo HTML 搜索（免费，无需 API Key）
        url = f"https://html.duckduckgo.com/html/?q={query}"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return {"error": f"搜索失败: HTTP {r.status_code}"}
            # 简单提取结果
            results = []
            for match in re.finditer(r'class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>.*?class="result__snippet"[^>]*>(.*?)</span>', r.text, re.DOTALL):
                href, title, snippet = match.groups()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                if title.strip():
                    results.append({"title": title.strip(), "snippet": snippet[:200], "url": href})
                    if len(results) >= count:
                        break
            if not results:
                # 降级：提取所有链接文本
                for match in re.finditer(r'class="result__a"[^>]*>([^<]*)</a>', r.text):
                    results.append({"title": match.group(1).strip(), "snippet": "", "url": ""})
                    if len(results) >= count:
                        break
            return {"query": query, "results": results, "count": len(results)}
    except Exception as e:
        return {"error": f"搜索失败: {e}"}


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


# ── 桌面操作工具实现 ─────────────────────────────────────────

async def desktop_screenshot() -> Dict[str, Any]:
    """截屏 + OCR 识别文字"""
    try:
        from .routers.desktop import desktop
        if not desktop:
            return {"error": "桌面控制不可用"}
        items = desktop.ocr_screen(force=True)
        text = " | ".join(i["text"] for i in items[:50])
        sw, sh = desktop.screen_size()
        return {
            "text": text[:2000],
            "elements_count": len(items),
            "screen_size": f"{sw}x{sh}",
        }
    except Exception as e:
        return {"error": f"截屏失败: {e}"}


async def desktop_click(target: str) -> Dict[str, Any]:
    """OCR 定位目标文字并点击"""
    try:
        from .routers.desktop import desktop
        if not desktop:
            return {"error": "桌面控制不可用"}

        # 先检查人机协作状态
        from .cowork_bus import get_bus
        if not get_bus().can_operate_desktop():
            return {"error": "用户正在操作电脑，AI 暂停桌面操作"}

        found = desktop.find_text(target)
        if found:
            desktop.mouse_click(found["x"], found["y"])
            return {"clicked": True, "target": target, "position": f"({found['x']}, {found['y']})"}
        return {"clicked": False, "error": f"未找到 '{target}'，请确认屏幕上有该文字"}
    except Exception as e:
        return {"error": f"点击失败: {e}"}


async def desktop_type(text: str) -> Dict[str, Any]:
    """在当前焦点输入文字"""
    try:
        import asyncio
        await asyncio.sleep(0.5)  # 等前一步操作生效
        from .routers.desktop import desktop
        if not desktop:
            return {"error": "桌面控制不可用"}
        from .cowork_bus import get_bus
        if not get_bus().can_operate_desktop():
            return {"error": "用户正在操作电脑，AI 暂停桌面操作"}

        # 中文走剪贴板，英文直接打字
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
        if has_cjk:
            desktop.type_chinese(text)
        else:
            desktop.type_text(text)
        await asyncio.sleep(0.3)
        return {"typed": True, "text": text[:50], "hint": "文字已输入，如果需要确认请调用 desktop_hotkey(keys='enter')"}
    except Exception as e:
        return {"error": f"输入失败: {e}"}


async def desktop_hotkey(keys: str) -> Dict[str, Any]:
    """执行键盘快捷键"""
    try:
        import asyncio
        await asyncio.sleep(0.3)  # 等前一步操作生效
        from .routers.desktop import desktop
        if not desktop:
            return {"error": "桌面控制不可用"}
        key_list = [k.strip() for k in keys.split("+")]
        desktop.hotkey(key_list)
        await asyncio.sleep(0.5)  # 等快捷键生效
        return {"executed": True, "keys": keys}
    except Exception as e:
        return {"error": f"快捷键执行失败: {e}"}


async def open_application(app_name: str) -> Dict[str, Any]:
    """打开应用程序"""
    # 检测 Chrome 是否安装
    import shutil
    _has_chrome = bool(shutil.which("chrome") or shutil.which("google-chrome")
                       or os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                       or os.path.exists(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"))
    # 用 --profile-directory=Default 跳过 Chrome 用户选择页
    _default_browser = 'chrome --profile-directory="Default"' if _has_chrome else "msedge"

    APP_MAP = {
        "微信": "WeChat",
        "浏览器": _default_browser,
        "chrome": "chrome",
        "谷歌": "chrome",
        "edge": "msedge",
        "记事本": "notepad",
        "文件管理器": "explorer",
        "命令行": "cmd",
        "终端": "wt",
        "计算器": "calc",
        "vscode": "code",
        "word": "winword",
        "excel": "excel",
        "ppt": "powerpnt",
        "powerpoint": "powerpnt",
        "网页": _default_browser,
    }

    # 如果 app_name 是 URL 或网站名，直接用浏览器打开
    _is_url = any(x in app_name.lower() for x in ["youtube", "google", "baidu", "taobao", "bilibili",
                  ".com", ".cn", ".org", "http", "www"])
    try:
        import subprocess
        if _is_url:
            url = app_name if app_name.startswith("http") else f"https://www.{app_name.lower().strip()}.com"
            # 常见网站映射
            url_map = {"youtube": "https://www.youtube.com", "谷歌": "https://www.google.com",
                       "百度": "https://www.baidu.com", "淘宝": "https://www.taobao.com",
                       "bilibili": "https://www.bilibili.com", "b站": "https://www.bilibili.com"}
            url = url_map.get(app_name.lower(), url)
            subprocess.Popen(f'start "" "{url}"', shell=True)
            import asyncio; await asyncio.sleep(2)  # 等浏览器加载
            return {"opened": True, "app": app_name, "url": url}

        cmd = APP_MAP.get(app_name.lower(), APP_MAP.get(app_name, app_name))
        subprocess.Popen(f'start "" "{cmd}"', shell=True)
        import asyncio; await asyncio.sleep(1.5)  # 等窗口出现
        return {"opened": True, "app": app_name, "command": cmd}
    except Exception as e:
        return {"error": f"打开 {app_name} 失败: {e}"}


async def read_wechat_messages(contact: str = "", count: int = 10) -> Dict[str, Any]:
    """读取微信聊天记录"""
    try:
        from .wechat_monitor import WeChatMonitor
        monitor = WeChatMonitor()
        if contact:
            ok = monitor.click_session(contact)
            if not ok:
                return {"error": f"未找到联系人: {contact}"}

        contact_name, messages = monitor.get_current_chat_messages(last_n=count)
        return {
            "contact": contact_name or contact,
            "messages": [
                {"sender": m.get("sender", ""), "content": m.get("content", "")[:100],
                 "time": m.get("time_str", ""), "type": m.get("msg_type", "text")}
                for m in messages[-count:]
            ],
            "count": len(messages),
        }
    except Exception as e:
        return {"error": f"读取消息失败: {e}"}


async def deploy_team(task: str, template: str = "startup") -> Dict[str, Any]:
    """组建 AI 团队（不立即执行，先让每个 Agent 自我介绍，等用户确认）"""
    try:
        from .agent_team import create_team
        from .agent_templates import get_template, AGENT_ROLES
        from .agent_skills import get_skills_for_role

        # 智能选模板（结合用户画像推荐）
        tpl = get_template(template)
        if not tpl:
            task_lower = task.lower()

            # 先尝试用户画像行业推荐
            _profile_industry = ""
            try:
                from .user_profile_ai import get_user_profile
                _up = get_user_profile()
                _profile_industry = (_up.get("industry", "") or "").lower()
            except Exception:
                pass

            if any(w in task_lower for w in ["代码", "开发", "程序", "bug", "api"]):
                template = "software"
            elif any(w in task_lower for w in ["营销", "推广", "广告", "品牌"]):
                template = "marketing"
            elif any(w in task_lower for w in ["电商", "上架", "产品", "店铺"]) or "电商" in _profile_industry:
                template = "ecommerce"
            elif any(w in task_lower for w in ["内容", "文案", "视频", "文章"]):
                template = "content_factory"
            elif any(w in task_lower for w in ["客服", "回复", "售后"]):
                template = "service_center"
            elif any(w in task_lower for w in ["咨询", "顾问", "调研"]) or "咨询" in _profile_industry:
                template = "consulting"
            else:
                # 根据行业默认推荐
                if _profile_industry in ("电商", "跨境电商", "直播电商"):
                    template = "ecommerce"
                elif _profile_industry in ("saas", "科技", "b2b"):
                    template = "software"
                else:
                    template = "startup"
            tpl = get_template(template)

        # ── 检测可用 AI 平台 ──
        import os
        available_platforms = []
        platform_checks = [
            ("zhipu_flash", "ZHIPU_API_KEY", "智谱GLM-4-Flash(免费)"),
            ("deepseek", "DEEPSEEK_API_KEY", "DeepSeek(送500万token)"),
            ("baidu_speed", "BAIDU_API_KEY", "百度文心(免费)"),
            ("siliconflow_free", "SILICONFLOW_API_KEY", "硅基流动(免费)"),
            ("tongyi", "TONGYI_API_KEY", "通义千问"),
            ("openai", "OPENAI_API_KEY", "OpenAI"),
        ]
        missing_platforms = []
        for pid, env_key, name in platform_checks:
            if os.environ.get(env_key):
                available_platforms.append((pid, name))
            else:
                missing_platforms.append(name)

        if not available_platforms:
            return {
                "error": "没有可用的 AI 平台！请在设置中配置至少一个 API Key。",
                "hint": "推荐：智谱GLM-4-Flash（永久免费）→ 设置 → AI配置",
            }

        # ── 检测路由模式，提醒切换 ──
        route_mode_hint = ""
        try:
            from src.router.config import RouterConfig
            cfg = RouterConfig()
            if cfg.routing_mode == "cost_saving":
                route_mode_hint = "\n\n⚠️ 当前为「省钱模式」，团队工作建议切换为「质量优先」模式（设置 → AI配置 → 路由模式）以获得更好的方案质量。"
        except Exception:
            pass

        # ── 智能分配 Agent 到可用平台（轮询分散）──
        platform_cycle = available_platforms * 10  # 足够多
        for i, (aid, agent) in enumerate(list(AGENT_ROLES.items())):
            if aid in [r for r in (tpl["roles"] if tpl else [])]:
                assigned = platform_cycle[i % len(platform_cycle)]
                AGENT_ROLES[aid].preferred_model = assigned[0]

        # 创建团队（但不执行）
        async def _ai_call(messages, model=""):
            try:
                from .main import backend as _b
                if _b and _b._router:
                    result = ""
                    async for chunk, _ in _b._router.chat_stream(
                        messages, max_tokens=600, temperature=0.7
                    ):
                        if chunk not in ("__SWITCH__", "__TOOL_CALLS__"):
                            result += chunk
                    return result
                elif _b:
                    return await _b.chat_simple(messages)
                return "AI 未就绪"
            except Exception as e:
                return f"AI 错误: {e}"

        team = create_team(template, _ai_call)

        # 生成每个 Agent 的自我介绍（关键！一个一个出场）
        introductions = []
        for i, (aid, agent) in enumerate(team.agents.items()):
            role = agent.role
            skills = get_skills_for_role(aid)
            skill_names = "、".join(s["name"] for s in skills[:4]) if skills else "综合分析"

            intro = {
                "order": i + 1,
                "id": aid,
                "name": role.name,
                "avatar": role.avatar,
                "greeting": f"老板好！我是{role.name}，",
                "description": role.description,
                "skills": skill_names,
                "full_intro": f"{role.avatar} **{role.name}**：老板好！我是{role.name}，负责{role.description}。我的专长是：{skill_names}。请放心交给我！",
            }
            introductions.append(intro)

        return {
            "team_id": team.team_id,
            "template": template,
            "team_name": tpl["name"] if tpl else template,
            "agent_count": len(team.agents),
            "status": "awaiting_confirmation",
            "introductions": introductions,
            "available_platforms": [p[1] for p in available_platforms],
            "missing_platforms_hint": f"💡 提示：配置更多 AI 平台可提升团队工作质量。当前未配置：{', '.join(missing_platforms[:3])}" if missing_platforms else "",
            "route_mode_hint": route_mode_hint,
            "message": (
                "请按以下步骤展示给用户：\n"
                "1. 先说'我为你组建了XX团队，来认识一下你的团队成员：'\n"
                "2. 把每个成员的 full_intro 逐一展示（一个一个，像报到一样）\n"
                "3. 如果有 missing_platforms_hint，展示给用户\n"
                "4. 如果有 route_mode_hint，展示给用户\n"
                "5. 告诉用户：'所有产出将保存到项目文件夹，完成后可一键下载'\n"
                "6. 最后问'团队已就位，是否开始执行？'\n"
                "7. 用户确认后调用 confirm_team，team_id 是：" + team.team_id
            ),
        }
    except Exception as e:
        return {"error": f"团队部署失败: {e}"}


async def confirm_team(team_id: str, task: str) -> Dict[str, Any]:
    """用户确认后，真正开始执行团队任务"""
    try:
        from .agent_team import get_team
        team = get_team(team_id)
        if not team:
            return {"error": "团队不存在，请重新组建"}

        # 用用户画像丰富任务描述（让所有 Agent 了解业务背景）
        enriched_task = task
        try:
            from .user_profile_ai import get_user_profile
            up = get_user_profile()
            context_parts = []
            if up.get("company"):
                context_parts.append(f"公司：{up['company']}")
            if up.get("industry"):
                context_parts.append(f"行业：{up['industry']}")
            if up.get("products"):
                context_parts.append(f"产品：{', '.join(p['name'] for p in up['products'][:3])}")
            if up.get("target_users"):
                context_parts.append(f"目标用户：{up['target_users']}")
            if up.get("brand_tone"):
                context_parts.append(f"品牌调性：{up['brand_tone']}")
            if context_parts:
                enriched_task = task + "\n\n【业务背景】" + "；".join(context_parts)
        except Exception:
            pass

        import asyncio
        asyncio.create_task(team.execute(enriched_task))

        return {
            "team_id": team_id,
            "status": "executing",
            "agent_count": len(team.agents),
            "message": f"收到！{len(team.agents)} 人团队已出发！我会实时汇报进度。",
        }
    except Exception as e:
        return {"error": f"启动失败: {e}"}


async def check_team_result(team_id: str) -> Dict[str, Any]:
    """查询团队执行结果"""
    try:
        from .agent_team import get_team
        team = get_team(team_id)
        if not team:
            return {"error": "团队不存在"}

        status = team.status
        if status == "done":
            # 获取项目文件列表
            project_files = []
            if hasattr(team, '_project') and team._project:
                project_files = team._project.list_files()
            return {
                "status": "done",
                "result": team.final_result,
                "tasks_completed": sum(1 for t in team.tasks if t.status == "done"),
                "total_tasks": len(team.tasks),
                "project_files": project_files,
                "project_id": team._project.project_id if hasattr(team, '_project') and team._project else "",
                "download_url": f"/api/projects/{team._project.project_id}/download" if hasattr(team, '_project') and team._project else "",
                "message": "所有产出文件已保存，可以通过项目文件夹查看或一键下载ZIP",
            }
        elif status == "error":
            return {"status": "error", "message": "团队执行出错"}
        else:
            done = sum(1 for t in team.tasks if t.status == "done")
            return {
                "status": status,
                "progress": f"{done}/{len(team.tasks)} 任务完成",
                "message": "团队正在工作中，请稍后再查询",
            }
    except Exception as e:
        return {"error": str(e)}


async def team_morning_brief() -> Dict[str, Any]:
    """团队早会——各 Agent 汇报最新状态"""
    try:
        from .agent_team import list_teams
        teams = list_teams()

        # 找最近完成的团队
        done_teams = [t for t in teams if t.get("status") == "done"]
        if not done_teams:
            return {
                "message": "目前没有团队任务记录。你可以说'帮我写个营销方案'来创建第一个团队任务。",
                "has_teams": False,
            }

        latest = done_teams[0]
        agents = latest.get("agents", {})

        # 生成各 Agent 汇报
        reports = []
        for aid, a in agents.items():
            task = None
            for t in latest.get("tasks", []):
                if t.get("agent_id") == aid:
                    task = t
                    break
            result_preview = task["result"][:100] if task and task.get("result") else "暂无成果"
            reports.append({
                "avatar": a.get("avatar", "🤖"),
                "name": a.get("name", aid),
                "report": f"老板好！{result_preview}",
            })

        # 构建汇报文本
        brief_text = "# 团队早会\n\n"
        for r in reports[:10]:
            brief_text += f"**{r['avatar']} {r['name']}**：{r['report']}\n\n"

        # TTS 播报文本（用于语音输出）
        tts_text = f"团队早会开始。"
        for r in reports[:5]:
            tts_text += f"{r['name']}说：{r['report'][:50]}。"
        tts_text += "以上是今日团队汇报。"

        return {
            "message": "请用自然语言把每个 Agent 的汇报逐一展示给用户（用上面的内容），像真人开会一样。每个人说完后换行。",
            "team_name": latest.get("name", ""),
            "reports": reports,
            "brief_text": brief_text,
            "tts_text": tts_text,
            "has_teams": True,
        }
    except Exception as e:
        return {"error": str(e)}


async def resume_last_project(instruction: str = "") -> Dict[str, Any]:
    """继续上次的项目"""
    try:
        from .project_workspace import list_projects, get_project

        projects = list_projects()
        if not projects:
            return {
                "message": "暂无历史项目。你可以说'帮我写个营销方案'来创建第一个项目。",
                "has_project": False,
            }

        # 取最近的项目
        latest = projects[0]
        project_id = latest["project_id"]
        p = get_project(project_id)

        # 读取 README（上次的成果摘要）
        summary = ""
        if p:
            readme_content = p.get_file("README.md")
            if readme_content:
                summary = readme_content[:1000]

        # 构建上下文
        task_desc = latest.get("task", "")
        team_name = latest.get("team_name", "")
        files = latest.get("artifacts", [])
        file_names = [f.get("filename", "") for f in files] if isinstance(files, list) else []

        resume_context = f"""上次的项目：{latest.get('name', '')}
任务：{task_desc}
团队：{team_name}（{latest.get('agent_count', 0)}人）
产出文件：{', '.join(file_names[:5])}

上次的成果摘要：
{summary[:800]}
"""
        if instruction:
            resume_context += f"\n用户新要求：{instruction}"

        # 注入用户画像
        profile_hint = ""
        try:
            from .user_profile_ai import get_user_profile
            up = get_user_profile()
            if up.get("company"):
                profile_hint = f"（{up['company']}，{up.get('industry', '')}）"
        except Exception:
            pass

        return {
            "has_project": True,
            "project_id": project_id,
            "project_name": latest.get("name", ""),
            "original_task": task_desc,
            "team_name": team_name,
            "file_count": len(file_names),
            "resume_context": resume_context,
            "share_url": f"/report/{project_id}",
            "message": (
                f"找到上次的项目「{latest.get('name', '')}{profile_hint}」\n\n"
                "请把上次的成果摘要展示给用户，然后问：\n"
                f"1. 如果用户有新要求（instruction={instruction!r}），调用 deploy_team 带上原始任务+新要求\n"
                "2. 如果用户只是想看，展示成果和分享链接\n"
                "3. confirm_team 时把 resume_context 作为任务的一部分传入"
            ),
        }
    except Exception as e:
        return {"error": str(e)}


async def get_project_history() -> Dict[str, Any]:
    """查看历史项目列表"""
    try:
        from .project_workspace import list_projects
        projects = list_projects()

        if not projects:
            return {
                "message": "暂无历史项目。说'帮我写个营销方案'来创建第一个！",
                "projects": [],
            }

        items = []
        for p in projects[:10]:
            items.append({
                "name": p.get("name", ""),
                "task": p.get("task", "")[:60],
                "team": p.get("team_name", ""),
                "agents": p.get("agent_count", 0),
                "files": len(p.get("artifacts", [])),
                "share_url": f"/report/{p['project_id']}",
                "created": p.get("created_at", 0),
            })

        # 构建展示文本
        text = f"共 {len(projects)} 个历史项目：\n\n"
        for i, item in enumerate(items, 1):
            text += f"{i}. **{item['name']}** — {item['task']}\n"
            text += f"   团队：{item['team']}（{item['agents']}人），{item['files']}个文件\n\n"

        return {
            "message": "请把项目列表用自然语言展示给用户，每个项目附上分享链接。用户可以说'继续第X个'来恢复项目。",
            "projects": items,
            "display_text": text,
        }
    except Exception as e:
        return {"error": str(e)}


async def _iot_control_tool(device_name: str, action: str, value: dict = None) -> Dict[str, Any]:
    """IoT 设备控制（工具接口）"""
    try:
        from .iot_bridge import get_iot_bridge
        bridge = get_iot_bridge()
        if not bridge.is_configured:
            return {"error": "智能家居未配置，请在设置中配置 HomeAssistant"}
        dev = bridge.get_device_by_name(device_name)
        if not dev:
            return {"error": f"未找到设备: {device_name}"}
        result = await bridge.control(dev.id, action, value)
        return result
    except Exception as e:
        return {"error": str(e)}


async def call_tool(name: str, args: Dict[str, Any]) -> str:
    """Dispatch a tool call and return a JSON string result."""
    try:
        if name == "get_current_time":
            result = get_current_time(**args)
        elif name == "web_search":
            result = await web_search(**args)
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
        # ── 桌面操作工具 ──
        elif name == "desktop_screenshot":
            result = await desktop_screenshot()
        elif name == "desktop_click":
            result = await desktop_click(**args)
        elif name == "desktop_type":
            result = await desktop_type(**args)
        elif name == "desktop_hotkey":
            result = await desktop_hotkey(**args)
        elif name == "open_application":
            result = await open_application(**args)
        elif name == "read_wechat_messages":
            result = await read_wechat_messages(**args)
        elif name == "iot_control":
            result = await _iot_control_tool(**args)
        elif name == "team_morning_brief":
            result = await team_morning_brief()
        elif name == "deploy_team":
            result = await deploy_team(**args)
        elif name == "confirm_team":
            result = await confirm_team(**args)
        elif name == "check_team_result":
            result = await check_team_result(**args)
        elif name == "resume_last_project":
            result = await resume_last_project(**args)
        elif name == "get_project_history":
            result = await get_project_history()
        else:
            result = {"error": f"未知工具: {name}"}
    except Exception as e:
        result = {"error": str(e)}
    return json.dumps(result, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# System prompt injection
# ─────────────────────────────────────────────────────────────

TOOLS_SYSTEM_ADDENDUM = """
你是十三香小龙虾 AI 工作队的智能助手。你不只是聊天，你能真正干活。

⚡ 你的核心能力（用户让你做事时，立即行动）：

🖥️ **操控电脑**（你有 4 个底层工具，可以自由组合完成任何操作）

  工具列表：
  - desktop_hotkey(keys) — 按快捷键。如 "win+r"打开运行框, "ctrl+c"复制, "alt+f4"关闭, "enter"回车
  - desktop_type(text) — 打字输入。在当前光标位置输入任何文字或网址
  - desktop_click(x, y) — 点击屏幕坐标
  - desktop_screenshot() — 截屏+OCR，返回屏幕上所有文字和坐标（不确定时先看一眼）
  - open_application(app_name) — 快捷打开软件/网站（记事本/微信/chrome/word/excel/youtube/百度等）

  操作思路：你可以像人一样操作电脑，自由组合这些工具。
  示例：
  - 打开网页：desktop_hotkey(keys="win+r") → desktop_type(text="https://youtube.com") → desktop_hotkey(keys="enter")
  - 打开软件：open_application(app_name="记事本") 或 desktop_hotkey(keys="win+r") → desktop_type(text="notepad") → desktop_hotkey(keys="enter")
  - 搜索内容：打开浏览器后 → desktop_hotkey(keys="ctrl+l") → desktop_type(text="搜索内容") → desktop_hotkey(keys="enter")
  - 复制粘贴：desktop_hotkey(keys="ctrl+a") → desktop_hotkey(keys="ctrl+c")
  - 不确定时：先 desktop_screenshot() 看看屏幕上有什么，再决定操作

👥 **52人AI团队**（大型任务自动分工协作）
  当用户要求做方案/报告/策划时：
  1. 简单问1-2个关键信息（产品是什么？目标用户？）
  2. 调用 deploy_team 组建团队
  3. 介绍团队成员
  4. 用户确认后 confirm_team 执行

📱 **微信操作**
  发消息: send_wechat(contact, message)
  发朋友圈: publish_moment(text)
  读消息: read_wechat_messages(contact)

🔧 **实用工具**
  搜索互联网: web_search(query) — 搜索新闻、资料、信息，比打开浏览器更快
  时间: get_current_time()
  天气: get_weather(city)
  计算: calculate(expression)

📂 **项目管理**
  继续上次: resume_last_project(instruction)
  历史项目: get_project_history()

⚠️ 重要原则：
1. 用户让你做事时，**立即用工具行动**，不要只说"好的我来帮你"
2. 能用工具完成的就用工具，不要只给文字建议
3. 操控电脑时，用 desktop_hotkey + desktop_type 组合完成，像人一样操作
4. 可以连续调用多个工具（如先按快捷键，再打字，再按回车）
5. 大型任务（方案/报告）用 deploy_team，简单操作直接用桌面工具
6. 回答简洁，重在行动

调用格式：
[TOOL_CALL] {"name": "工具名", "args": {...}} [/TOOL_CALL]

🏢 团队模板：startup(5人)/marketing(10人)/ecommerce(15人)/software(10人)/content_factory(8人)/service_center(7人)/consulting(7人)/all_hands(52人)
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
