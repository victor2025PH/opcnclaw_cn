"""
MCP Desktop Tools — Wrap desktop control capabilities as MCP-compatible tools.

This module registers desktop control actions as MCP tools that can be
discovered and invoked by any MCP client (including AI Agents).

Tool categories:
  - Mouse control: click, double_click, right_click, scroll, move_to
  - Keyboard control: type_text, hotkey, key_press
  - Screen capture: screenshot, ocr_screen, ocr_region
  - Window management: list_windows, focus_window, close_window
  - System: clipboard_get, clipboard_set, open_app

Each tool follows the MCP tool schema format (JSON Schema for inputs).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from loguru import logger


# ── MCP Tool Definitions ──

DESKTOP_MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "desktop_click",
        "description": "在指定屏幕坐标点击鼠标。不传坐标则点击当前位置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "屏幕X坐标（像素）"},
                "y": {"type": "integer", "description": "屏幕Y坐标（像素）"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            },
        },
    },
    {
        "name": "desktop_double_click",
        "description": "在指定位置双击鼠标。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "屏幕X坐标"},
                "y": {"type": "integer", "description": "屏幕Y坐标"},
            },
        },
    },
    {
        "name": "desktop_type",
        "description": "在当前焦点位置输入文本。支持中英文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
                "use_clipboard": {"type": "boolean", "description": "使用剪贴板粘贴（中文必须）", "default": True},
            },
            "required": ["text"],
        },
    },
    {
        "name": "desktop_hotkey",
        "description": "执行键盘快捷键组合，如 ctrl+c, alt+tab, win+d 等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按键列表，如 ['ctrl', 'c'] 或 ['alt', 'tab']",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "desktop_key",
        "description": "按下单个按键，如 enter, escape, tab, space, F5 等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "desktop_scroll",
        "description": "在指定位置或当前位置滚动鼠标。正数向上，负数向下。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dy": {"type": "integer", "description": "滚动量（正=上，负=下）", "default": -3},
                "x": {"type": "integer", "description": "滚动位置X（可选）"},
                "y": {"type": "integer", "description": "滚动位置Y（可选）"},
            },
        },
    },
    {
        "name": "desktop_move_to",
        "description": "将鼠标移动到指定屏幕坐标。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标X坐标"},
                "y": {"type": "integer", "description": "目标Y坐标"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "desktop_screenshot",
        "description": "截取当前屏幕截图并返回 base64 编码的图像。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "properties": {
                        "left": {"type": "integer"},
                        "top": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "description": "截图区域（可选，默认全屏）",
                },
            },
        },
    },
    {
        "name": "desktop_ocr",
        "description": "对当前屏幕进行OCR文字识别，返回屏幕上的所有可见文字及其位置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "properties": {
                        "left": {"type": "integer"},
                        "top": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "description": "识别区域（可选，默认全屏）",
                },
            },
        },
    },
    {
        "name": "desktop_find_and_click",
        "description": "在屏幕上查找指定文本并点击其位置。使用OCR定位。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要查找的屏幕文本"},
                "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
                "occurrence": {"type": "integer", "description": "第N个匹配（从1开始）", "default": 1},
            },
            "required": ["text"],
        },
    },
    {
        "name": "desktop_list_windows",
        "description": "列出当前所有可见窗口及其标题、位置、大小。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "desktop_focus_window",
        "description": "将指定标题的窗口置于前台。支持部分匹配。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "窗口标题（支持部分匹配）"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "desktop_clipboard",
        "description": "获取或设置系统剪贴板内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set"], "description": "获取或设置"},
                "text": {"type": "string", "description": "要设置的文本（仅 action=set 时需要）"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "desktop_open_app",
        "description": "通过名称或路径打开应用程序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "应用名称（如 '微信', 'notepad', 'chrome'）"},
                "path": {"type": "string", "description": "可执行文件的完整路径（可选）"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "desktop_wait",
        "description": "等待指定毫秒数。用于操作之间需要延迟的场景。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ms": {"type": "integer", "description": "等待时间（毫秒）", "default": 1000},
            },
        },
    },
]


def get_mcp_desktop_tools() -> List[Dict[str, Any]]:
    """Return all desktop MCP tool definitions."""
    return DESKTOP_MCP_TOOLS


async def execute_mcp_desktop_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    desktop_streamer=None,
) -> Dict[str, Any]:
    """
    Execute a desktop MCP tool and return the result.

    Parameters:
        tool_name: The MCP tool name (e.g., "desktop_click")
        arguments: Tool arguments from the MCP call
        desktop_streamer: The DesktopStreamer instance

    Returns:
        MCP tool result dict with 'content' field.
    """
    if desktop_streamer is None:
        return _error("Desktop streamer not available")

    try:
        return await _dispatch_tool(tool_name, arguments, desktop_streamer)
    except Exception as e:
        logger.error(f"MCP desktop tool error: {tool_name}: {e}")
        return _error(str(e))


async def _dispatch_tool(
    name: str, args: Dict[str, Any], ds
) -> Dict[str, Any]:
    """Dispatch to the appropriate desktop streamer method."""

    if name == "desktop_click":
        x, y = args.get("x"), args.get("y")
        button = args.get("button", "left")
        if x is not None and y is not None:
            ds.mouse_click(x, y, button=button)
        else:
            import pyautogui
            pyautogui.click(button=button)
        return _ok(f"Clicked ({x}, {y}) with {button} button")

    elif name == "desktop_double_click":
        x, y = args.get("x"), args.get("y")
        if x is not None and y is not None:
            ds.mouse_click(x, y, double=True)
        else:
            import pyautogui
            pyautogui.doubleClick()
        return _ok(f"Double-clicked ({x}, {y})")

    elif name == "desktop_type":
        text = args["text"]
        use_clipboard = args.get("use_clipboard", True)
        if use_clipboard:
            import pyperclip, pyautogui
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        else:
            import pyautogui
            pyautogui.typewrite(text, interval=0.02)
        return _ok(f"Typed {len(text)} characters")

    elif name == "desktop_hotkey":
        keys = args["keys"]
        import pyautogui
        pyautogui.hotkey(*keys)
        return _ok(f"Hotkey: {'+'.join(keys)}")

    elif name == "desktop_key":
        key = args["key"]
        import pyautogui
        pyautogui.press(key)
        return _ok(f"Key pressed: {key}")

    elif name == "desktop_scroll":
        dy = args.get("dy", -3)
        x, y = args.get("x"), args.get("y")
        import pyautogui
        if x is not None and y is not None:
            pyautogui.scroll(dy, x=x, y=y)
        else:
            pyautogui.scroll(dy)
        return _ok(f"Scrolled {dy}")

    elif name == "desktop_move_to":
        import pyautogui
        pyautogui.moveTo(args["x"], args["y"], duration=0.2)
        return _ok(f"Moved to ({args['x']}, {args['y']})")

    elif name == "desktop_screenshot":
        region = args.get("region")
        img_b64 = ds.capture_screen_base64(region=region)
        return {
            "content": [{"type": "image", "data": img_b64, "mimeType": "image/png"}],
            "isError": False,
        }

    elif name == "desktop_ocr":
        region = args.get("region")
        results = ds.ocr_screen(region=region)
        return _ok_data(results)

    elif name == "desktop_find_and_click":
        text = args["text"]
        button = args.get("button", "left")
        occurrence = args.get("occurrence", 1)
        pos = ds.find_text(text, occurrence=occurrence)
        if pos:
            ds.mouse_click(pos[0], pos[1], button=button)
            return _ok(f"Found '{text}' at ({pos[0]}, {pos[1]}) and clicked")
        return _error(f"Text '{text}' not found on screen")

    elif name == "desktop_list_windows":
        windows = ds.get_windows()
        return _ok_data(windows)

    elif name == "desktop_focus_window":
        title = args["title"]
        ok = ds.focus_window(title)
        return _ok(f"Focused window: {title}") if ok else _error(f"Window '{title}' not found")

    elif name == "desktop_clipboard":
        action = args["action"]
        if action == "get":
            import pyperclip
            content = pyperclip.paste()
            return _ok(content)
        elif action == "set":
            import pyperclip
            pyperclip.copy(args.get("text", ""))
            return _ok("Clipboard set")
        return _error(f"Unknown clipboard action: {action}")

    elif name == "desktop_open_app":
        name_or_path = args.get("path") or args["name"]
        import subprocess
        subprocess.Popen(name_or_path, shell=True)
        return _ok(f"Opened: {args['name']}")

    elif name == "desktop_wait":
        import asyncio
        ms = args.get("ms", 1000)
        await asyncio.sleep(ms / 1000)
        return _ok(f"Waited {ms}ms")

    return _error(f"Unknown tool: {name}")


def _ok(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": False}

def _ok_data(data: Any) -> Dict[str, Any]:
    import json
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False}

def _error(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Error: {text}"}], "isError": True}
