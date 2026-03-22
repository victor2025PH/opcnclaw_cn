# -*- coding: utf-8 -*-
"""
智能建议引擎 — AI 观察用户行为，主动提供帮助

原理：
  1. 定期检测前台窗口标题和应用
  2. 根据场景匹配建议规则
  3. 通过 EventBus 推送建议（桌宠弹通知）

场景示例：
  - 用户在写 Word 文档 → "要我帮你润色一下吗？"
  - 用户在看 Excel 表格 → "要我帮你分析数据吗？"
  - 用户在浏览器看竞品 → "要我做竞品分析吗？"
  - 用户长时间没操作 → "休息一下吧，我帮你总结今天的工作"
"""

from __future__ import annotations

import re
import threading
import time
from typing import Dict, List, Optional

from loguru import logger


# ── 场景规则 ──────────────────────────────────────────────────

SUGGEST_RULES = [
    {
        "id": "writing",
        "window_keywords": ["Word", "文档", "WPS", "Notepad", "记事本", "Typora", "Obsidian"],
        "icon": "✍️",
        "message": "检测到你在写文档，要我帮你润色一下吗？",
        "action": "帮我润色正在编辑的文档",
        "cooldown": 600,  # 10 分钟内不重复
    },
    {
        "id": "spreadsheet",
        "window_keywords": ["Excel", "表格", "Sheet", "WPS 表格"],
        "icon": "📊",
        "message": "在看表格？要我帮你分析数据吗？",
        "action": "帮我分析屏幕上的数据表格",
        "cooldown": 600,
    },
    {
        "id": "coding",
        "window_keywords": ["Visual Studio", "VS Code", "PyCharm", "IntelliJ", "Cursor", "代码"],
        "icon": "💻",
        "message": "在写代码？遇到问题我可以帮忙！",
        "action": "帮我看看屏幕上的代码有什么问题",
        "cooldown": 900,
    },
    {
        "id": "browsing",
        "window_keywords": ["Chrome", "Edge", "Firefox", "浏览器"],
        "icon": "🌐",
        "message": "在浏览网页？要我帮你总结页面内容吗？",
        "action": "帮我总结屏幕上的网页内容",
        "cooldown": 900,
    },
    {
        "id": "email",
        "window_keywords": ["Outlook", "邮件", "Mail", "Gmail", "QQ邮箱"],
        "icon": "📧",
        "message": "在处理邮件？要我帮你写回复吗？",
        "action": "帮我写一封邮件回复",
        "cooldown": 600,
    },
    {
        "id": "meeting",
        "window_keywords": ["Zoom", "腾讯会议", "Teams", "飞书", "钉钉"],
        "icon": "🎤",
        "message": "在开会？需要我帮你做会议纪要吗？",
        "action": "帮我记录当前会议的要点",
        "cooldown": 1800,
    },
    {
        "id": "design",
        "window_keywords": ["Figma", "Photoshop", "PS", "Illustrator", "Sketch", "Canva"],
        "icon": "🎨",
        "message": "在做设计？要我帮你生成配色方案吗？",
        "action": "帮我生成一个配色方案",
        "cooldown": 900,
    },
    {
        "id": "idle",
        "window_keywords": [],  # 特殊：检测空闲时间
        "icon": "☕",
        "message": "休息一下吧！要我帮你总结今天做了什么？",
        "action": "帮我总结今天的工作成果",
        "cooldown": 3600,
        "idle_threshold": 300,  # 5 分钟无操作
    },
]


class SmartSuggestEngine:
    """智能建议引擎"""

    CHECK_INTERVAL = 30.0  # 每 30 秒检测一次

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_suggest: Dict[str, float] = {}  # rule_id → 上次建议时间
        self._enabled = True

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SmartSuggest")
        self._thread.start()
        logger.info("[SmartSuggest] 智能建议引擎启动")

    def stop(self):
        self._running = False

    def _loop(self):
        time.sleep(30)  # 启动后等 30 秒再开始检测
        while self._running:
            try:
                if self._enabled:
                    self._check()
            except Exception as e:
                logger.debug(f"[SmartSuggest] check error: {e}")
            time.sleep(self.CHECK_INTERVAL)

    def _check(self):
        """检测当前场景并推送建议"""
        import sys
        if sys.platform != "win32":
            return

        # 获取前台窗口标题
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            window_title = buf.value
        except Exception:
            return

        if not window_title:
            return

        now = time.time()

        # 检测空闲
        try:
            from .human_detector import get_human_state
            state = get_human_state()
            if state.idle_ms > 300000:  # 5 分钟无操作
                idle_rule = next((r for r in SUGGEST_RULES if r["id"] == "idle"), None)
                if idle_rule:
                    last = self._last_suggest.get("idle", 0)
                    if now - last > idle_rule["cooldown"]:
                        self._push_suggest(idle_rule)
                        self._last_suggest["idle"] = now
                        return
        except Exception:
            pass

        # 匹配窗口标题
        for rule in SUGGEST_RULES:
            if rule["id"] == "idle":
                continue
            for keyword in rule["window_keywords"]:
                if keyword.lower() in window_title.lower():
                    last = self._last_suggest.get(rule["id"], 0)
                    if now - last > rule["cooldown"]:
                        self._push_suggest(rule)
                        self._last_suggest[rule["id"]] = now
                        return

    def _push_suggest(self, rule: dict):
        """推送建议到 EventBus"""
        try:
            from .event_bus import publish
            publish("smart_suggest", {
                "id": rule["id"],
                "icon": rule["icon"],
                "message": rule["message"],
                "action": rule["action"],
            })
            logger.info(f"[SmartSuggest] 推送建议: {rule['icon']} {rule['message']}")
        except Exception:
            pass


# ── 全局单例 ──

_engine: Optional[SmartSuggestEngine] = None

def get_suggest_engine() -> SmartSuggestEngine:
    global _engine
    if _engine is None:
        _engine = SmartSuggestEngine()
        _engine.start()
    return _engine
