# -*- coding: utf-8 -*-
"""
AI 操作日志 — 记录所有桌面操作，支持撤销

每次 AI 执行桌面操作（click/type/hotkey/scroll）时：
1. 记录操作前截图缩略图
2. 记录操作参数
3. 记录操作后截图
4. 标记是否可逆

撤销：执行 Ctrl+Z 或反向操作
"""

from __future__ import annotations

import base64
import hashlib
import io
import time
import threading
from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger


@dataclass
class ActionEntry:
    """单条操作记录"""
    id: str = ""
    action: str = ""              # click / type / hotkey / scroll / key
    params: dict = field(default_factory=dict)
    description: str = ""         # 人类可读描述
    before_thumb: str = ""        # base64 缩略图（操作前）
    after_thumb: str = ""         # base64 缩略图（操作后）
    timestamp: float = 0.0
    reversible: bool = True
    undone: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "desc": self.description,
            "params": self.params,
            "ts": round(self.timestamp, 1),
            "reversible": self.reversible,
            "undone": self.undone,
            "has_before": bool(self.before_thumb),
            "has_after": bool(self.after_thumb),
        }


class ActionJournal:
    """操作日志管理器"""

    MAX_ENTRIES = 100              # 最多保留 100 条
    THUMB_SIZE = (320, 180)        # 缩略图尺寸
    THUMB_QUALITY = 40             # JPEG 质量

    def __init__(self):
        self._entries: List[ActionEntry] = []
        self._lock = threading.Lock()

    def record(self, action: str, params: dict, description: str = "",
               reversible: bool = True) -> ActionEntry:
        """记录一条操作（操作前调用）"""
        entry = ActionEntry(
            id=hashlib.md5(f"{time.time()}{action}".encode()).hexdigest()[:12],
            action=action,
            params=params,
            description=description or self._auto_describe(action, params),
            timestamp=time.time(),
            reversible=reversible,
        )

        # 操作前截图
        entry.before_thumb = self._take_thumbnail()

        with self._lock:
            self._entries.append(entry)
            # 超过上限时删除最旧的
            while len(self._entries) > self.MAX_ENTRIES:
                self._entries.pop(0)

        return entry

    def record_after(self, entry_id: str):
        """操作完成后截图（操作后调用）"""
        with self._lock:
            for e in reversed(self._entries):
                if e.id == entry_id:
                    e.after_thumb = self._take_thumbnail()
                    break

    def get_recent(self, limit: int = 20) -> List[dict]:
        """获取最近操作"""
        with self._lock:
            return [e.to_dict() for e in self._entries[-limit:]]

    def undo_last(self) -> Optional[dict]:
        """撤销最后一条可逆操作"""
        with self._lock:
            for e in reversed(self._entries):
                if e.reversible and not e.undone:
                    e.undone = True
                    self._execute_undo(e)
                    return e.to_dict()
        return None

    def get_entry_thumbnails(self, entry_id: str) -> dict:
        """获取指定操作的前后截图"""
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return {
                        "before": e.before_thumb,
                        "after": e.after_thumb,
                    }
        return {"before": "", "after": ""}

    def _execute_undo(self, entry: ActionEntry):
        """执行撤销"""
        try:
            import pyautogui
            action = entry.action

            if action == "type":
                # 文字输入 → 全选删除
                count = len(entry.params.get("text", ""))
                for _ in range(count):
                    pyautogui.press("backspace")
                logger.info(f"[Journal] 撤销输入: {count} 字符")

            elif action == "hotkey":
                # 热键 → Ctrl+Z
                pyautogui.hotkey("ctrl", "z")
                logger.info(f"[Journal] 撤销热键: Ctrl+Z")

            elif action in ("click", "double_click", "scroll"):
                # 点击/滚动 → Ctrl+Z（通用撤销）
                pyautogui.hotkey("ctrl", "z")
                logger.info(f"[Journal] 撤销{action}: Ctrl+Z")

            else:
                pyautogui.hotkey("ctrl", "z")
                logger.info(f"[Journal] 通用撤销: Ctrl+Z")

        except Exception as e:
            logger.warning(f"[Journal] 撤销失败: {e}")

    def _take_thumbnail(self) -> str:
        """截取屏幕缩略图（base64 JPEG）"""
        try:
            import pyautogui
            from PIL import Image

            img = pyautogui.screenshot()
            img = img.resize(self.THUMB_SIZE, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.THUMB_QUALITY)
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            return ""

    @staticmethod
    def _auto_describe(action: str, params: dict) -> str:
        """自动生成操作描述"""
        if action == "click":
            x, y = params.get("x", "?"), params.get("y", "?")
            return f"点击 ({x}, {y})"
        elif action == "type":
            text = params.get("text", "")[:20]
            return f"输入 \"{text}{'...' if len(params.get('text', '')) > 20 else ''}\""
        elif action == "hotkey":
            keys = params.get("keys", [])
            return f"快捷键 {'+'.join(keys)}"
        elif action == "scroll":
            dy = params.get("dy", 0)
            return f"滚动 {'↓' if dy > 0 else '↑'} {abs(dy)}"
        elif action == "key":
            return f"按键 {params.get('key', '?')}"
        return f"{action}"


# ── 全局单例 ──

_journal: Optional[ActionJournal] = None


def get_journal() -> ActionJournal:
    global _journal
    if _journal is None:
        _journal = ActionJournal()
    return _journal
