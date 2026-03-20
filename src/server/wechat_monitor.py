# -*- coding: utf-8 -*-
"""
微信消息监控模块 — UIAutomation + OCR 双轨方案

架构：
  主轨（首选）: Windows UIAutomation API
    → 直接读取微信 UI 控件树中的文本元素
    → 无需截图，速度快，文字准确
    → 微信 PC 版通常允许 UIA 访问

  备用轨（降级）: OCR 截图分析
    → UIA 读不到内容时自动切换
    → 截取微信窗口区域 → 识别未读角标 → 识别消息文字

消息去重：
  用 (联系人, 消息内容, 时间戳hash) 作为消息指纹，
  60 秒内相同指纹只触发一次回调。
"""

import hashlib
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

# Windows 平台检查
IS_WINDOWS = sys.platform == "win32"

# ── UIAutomation 导入（仅 Windows）────────────────────────────────────────────
_uia_available = False
if IS_WINDOWS:
    try:
        import uiautomation as auto
        _uia_available = True
    except ImportError:
        logger.warning("uiautomation 未安装，将使用纯 OCR 模式")

# ── 微信 4.x 无障碍激活 ──────────────────────────────────────────
# 微信 4.1+ 只在检测到无障碍客户端时暴露完整 UIA 控件树。
# 注册 EVENT_OBJECT_FOCUS 钩子即可触发。
_accessibility_hook = None

def _ensure_accessibility_hook():
    """注册全局焦点事件钩子，触发微信暴露完整 UI 树"""
    global _accessibility_hook
    if _accessibility_hook or not IS_WINDOWS:
        return
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        WinEventProc = ctypes.WINFUNCTYPE(
            None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
            ctypes.wintypes.HWND, ctypes.c_long, ctypes.c_long,
            ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
        )
        _cb = WinEventProc(lambda *a: None)
        # 必须保持 _cb 引用，防止被 GC
        _ensure_accessibility_hook._cb_ref = _cb
        _accessibility_hook = user32.SetWinEventHook(
            0x8005, 0x8005,  # EVENT_OBJECT_FOCUS
            0, _cb, 0, 0,
            0x0002,  # WINEVENT_SKIPOWNPROCESS
        )
        if _accessibility_hook:
            logger.info("[Monitor] 无障碍钩子已注册 — 微信 4.x UI 树已激活")
        else:
            logger.warning("[Monitor] 无障碍钩子注册失败")
    except Exception as e:
        logger.debug(f"[Monitor] 无障碍钩子失败: {e}")

# 模块加载时自动注册
if IS_WINDOWS and _uia_available:
    _ensure_accessibility_hook()

# 微信窗口类名（兼容新旧版本）
WECHAT_CLASS = "WeChatMainWndForPC"       # 微信 3.x
WECHAT_CLASS_V4 = "mmui::MainWindow"      # 微信 4.x
WECHAT_CLASSES = [WECHAT_CLASS, WECHAT_CLASS_V4]
WECHAT_TITLE_KEYWORD = "微信"

# 扫描间隔（秒）
SCAN_INTERVAL_UIA = 1.5
SCAN_INTERVAL_OCR = 3.0

# 消息指纹过期时间（秒），防重复触发
FINGERPRINT_TTL = 60

# UIA 控件树最大深度（诊断用）
UIA_DUMP_MAX_DEPTH = 6


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class WeChatMessage:
    """一条微信消息"""
    contact: str          # 联系人 / 群名
    sender: str           # 发送人（群聊时与 contact 不同）
    content: str          # 消息内容
    is_group: bool = False
    at_me: bool = False   # 群聊时是否 @了我
    timestamp: float = field(default_factory=time.time)
    raw_time_str: str = ""
    msg_type: str = "text"  # text / image / voice / file / unknown

    def fingerprint(self) -> str:
        """消息唯一指纹（用于去重）"""
        key = f"{self.contact}|{self.sender}|{self.content[:80]}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def __repr__(self):
        flag = "[@我]" if self.at_me else ""
        return f"<WeChatMsg {self.contact}/{self.sender}{flag}: {self.content[:30]}>"


# ── UIAutomation 读取层 ───────────────────────────────────────────────────────

class UIAReader:
    """
    通过 Windows UIAutomation API 读取微信 UI 控件树。

    微信 PC 版 UI 结构（简化）：
      WeChatMainWndForPC
        ├── 左侧会话列表区  (ListControl 或 PaneControl)
        │     └── 会话项 (ListItemControl / CustomControl)
        │           ├── 联系人名 (TextControl)
        │           ├── 未读数角标 (TextControl, 内容如 "3")
        │           └── 最新消息预览 (TextControl)
        └── 右侧聊天区
              ├── 标题栏 (TitleBarControl / TextControl → 联系人名)
              └── 消息列表 (ListControl)
                    └── 消息气泡 (ListItemControl)
                          ├── 发送人名 (TextControl)
                          └── 消息内容 (TextControl / EditControl)
    """

    def __init__(self):
        self._wechat_ctrl = None
        self._last_find = 0.0

    def _get_wechat_window(self, force_refresh: bool = False):
        """获取微信主窗口控件，缓存 5 秒"""
        now = time.time()
        if not force_refresh and self._wechat_ctrl and (now - self._last_find) < 5.0:
            if self._wechat_ctrl.Exists(0):
                return self._wechat_ctrl

        if not _uia_available:
            return None
        # 兼容微信 3.x 和 4.x 窗口类名
        for cls in WECHAT_CLASSES:
            try:
                ctrl = auto.WindowControl(
                    ClassName=cls,
                    searchDepth=1,
                    timeout=1
                )
                if ctrl.Exists(0):
                    self._wechat_ctrl = ctrl
                    self._last_find = now
                    return ctrl
            except Exception as e:
                logger.debug(f"UIA find wechat window ({cls}): {e}")
        return None

    @staticmethod
    def activate_wechat_window() -> bool:
        """
        自动查找并激活微信窗口（从最小化/托盘恢复到前台）。
        返回是否成功。
        """
        if not _uia_available:
            return False
        import time as _time
        for cls in WECHAT_CLASSES:
            try:
                wnd = auto.WindowControl(ClassName=cls, searchDepth=1)
                if wnd.Exists(1, 0):
                    wnd.ShowWindow(9)  # SW_RESTORE
                    wnd.SetTopmost(True)
                    _time.sleep(0.3)
                    wnd.SetTopmost(False)
                    logger.info(f"[Monitor] 微信窗口已激活 ({cls})")
                    return True
            except Exception:
                continue
        logger.warning("[Monitor] 未找到微信窗口，无法激活")
        return False

    def send_message(self, text: str) -> bool:
        """
        在当前聊天窗口发送消息（微信 4.x 适配）。
        需要先打开目标聊天窗口。
        """
        win = self._get_wechat_window(force_refresh=True)
        if not win:
            return False
        try:
            import time as _t
            # 1. 找输入框 (mmui::ChatInputField 或 EditControl)
            input_ctrl = None
            for cls in ["mmui::ChatInputField", "mmui::XValidatorTextEdit"]:
                try:
                    c = win.Control(searchDepth=20, ClassName=cls)
                    if c.Exists(1, 0) and "搜索" not in (c.Name or ""):
                        input_ctrl = c
                        break
                except Exception:
                    pass
            if not input_ctrl:
                logger.warning("[UIA] 未找到输入框")
                return False

            # 2. 点击聚焦 + 清空 + 输入
            input_ctrl.Click()
            _t.sleep(0.2)
            input_ctrl.SendKeys("{Ctrl}a", waitTime=0.05)
            input_ctrl.SendKeys(text, waitTime=0.02)
            _t.sleep(0.3)

            # 3. 发送：优先点击发送按钮，回退到 Enter
            sent = False
            try:
                send_btn = win.Control(searchDepth=20, ClassName="mmui::XOutlineButton")
                if send_btn.Exists(1, 0):
                    send_btn.Click()
                    sent = True
            except Exception:
                pass
            if not sent:
                input_ctrl.SendKeys("{Enter}", waitTime=0.05)

            logger.info(f"[UIA] 消息已发送: {text[:30]}...")
            return True
        except Exception as e:
            logger.error(f"[UIA] 发送失败: {e}")
            return False

    def click_session(self, contact_name: str) -> bool:
        """
        点击左侧会话列表中的指定联系人（微信 4.x 适配）。
        """
        win = self._get_wechat_window(force_refresh=True)
        if not win:
            return False
        try:
            import time as _t
            # 找会话列表
            table = win.Control(searchDepth=20, ClassName="mmui::XTableView")
            if not table.Exists(2, 0):
                # 3.x 回退
                table = win.ListControl(searchDepth=6, timeout=1)
            if not table or not table.Exists(0):
                return False

            for item in table.GetChildren():
                name = (item.Name or "").split("\n")[0].strip()
                if name == contact_name:
                    item.Click()
                    _t.sleep(0.5)
                    logger.info(f"[UIA] 已切换到会话: {contact_name}")
                    return True

            # 搜索方式切换
            search = win.Control(searchDepth=20, ClassName="mmui::XValidatorTextEdit")
            if search.Exists(1, 0) and "搜索" in (search.Name or ""):
                search.Click()
                _t.sleep(0.2)
                search.SendKeys(contact_name, waitTime=0.02)
                _t.sleep(1.0)
                search.SendKeys("{Enter}", waitTime=0.1)
                _t.sleep(0.5)
                logger.info(f"[UIA] 搜索切换到: {contact_name}")
                return True

            return False
        except Exception as e:
            logger.error(f"[UIA] 切换会话失败: {e}")
            return False

    def get_unread_sessions(self) -> List[Dict]:
        """
        读取左侧会话列表，返回有未读消息的会话。
        每项格式：{contact, unread_count, preview, is_group}
        """
        win = self._get_wechat_window()
        if not win:
            return []

        results = []
        try:
            # 找左侧会话列表容器
            list_ctrl = None
            # 微信 4.x: mmui::XTableView (Name="会话")
            try:
                c = win.Control(searchDepth=20, ClassName="mmui::XTableView")
                if c.Exists(1, 0):
                    list_ctrl = c
            except Exception:
                pass
            # 3.x 回退
            if not list_ctrl:
                for find_fn in [
                    lambda: win.ListControl(searchDepth=6, timeout=1),
                    lambda: win.PaneControl(searchDepth=4, timeout=1),
                ]:
                    try:
                        c = find_fn()
                        if c.Exists(0):
                            list_ctrl = c
                            break
                    except Exception:
                        pass

            if not list_ctrl:
                return []

            # 遍历会话项
            items = list_ctrl.GetChildren()
            for item in items[:50]:
                try:
                    clsn = item.ClassName or ""

                    # 微信 4.x: mmui::ChatSessionCell 的 Name 包含完整信息
                    # 格式: "联系人名\n[N条] \n最后消息\n时间"
                    if "mmui::ChatSessionCell" in clsn:
                        raw = item.Name or ""
                        if not raw:
                            continue
                        lines = [l.strip() for l in raw.split('\n') if l.strip()]
                        contact = lines[0] if lines else ""
                        preview = ""
                        unread = 0
                        for line in lines:
                            m = re.search(r'\[(\d+)条?\]', line)
                            if m:
                                unread = int(m.group(1))
                            elif line != contact and not re.match(r'^\d{1,2}:\d{2}$|^\d{4}/', line):
                                preview = line
                        if contact:
                            results.append({
                                "contact": contact,
                                "unread_count": unread,
                                "preview": preview,
                                "is_group": _is_group_name(contact),
                            })
                        continue

                    # 3.x 回退
                    texts = _extract_texts(item, max_depth=4)
                    if not texts:
                        continue

                    contact = texts[0] if texts else ""
                    preview = texts[-1] if len(texts) > 1 else ""
                    unread = 0
                    for t in texts:
                        t = t.strip()
                        if t.isdigit():
                            unread = int(t)
                            break
                        m = re.search(r'\[(\d+)\]', t)
                        if m:
                            unread = int(m.group(1))
                            break

                    if unread > 0:
                        results.append({
                            "contact": contact,
                            "unread_count": unread,
                            "preview": preview,
                            "is_group": _is_group_name(contact),
                        })
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"UIA get_unread_sessions: {e}")

        return results

    def get_current_chat_messages(self, last_n: int = 10) -> Tuple[str, List[Dict]]:
        """
        读取当前打开的聊天窗口中最新的 last_n 条消息。
        返回 (contact_name, messages)
        每条消息格式：{sender, content, time_str, is_mine, msg_type}
        """
        win = self._get_wechat_window()
        if not win:
            return "", []

        contact = ""
        messages = []

        try:
            # ── 获取联系人名 ──────────────────────────────────────
            # 微信 4.x: ChatInputField.Name 就是当前聊天对象名
            try:
                input_field = win.Control(searchDepth=20, ClassName="mmui::ChatInputField")
                if input_field.Exists(1, 0):
                    contact = (input_field.Name or "").strip()
            except Exception:
                pass

            # 回退: 标题栏
            if not contact:
                title_texts = []
                try:
                    title_bar = win.TitleBarControl(searchDepth=4, timeout=1)
                    if title_bar.Exists(0):
                        title_texts = _extract_texts(title_bar, max_depth=3)
                except Exception:
                    pass
                if not title_texts:
                    try:
                        all_top = _extract_texts(win, max_depth=3)
                        title_texts = all_top[:3]
                    except Exception:
                        pass
                for t in title_texts:
                    t = t.strip()
                    if t and t not in ("微信", "WeChat", "MMUIRenderSubWindowHW", ""):
                        contact = t
                        break

            # ── 获取窗口边界（用于 is_mine 判断）────────────────────────────
            win_rect = None
            try:
                win_rect = win.BoundingRectangle
            except Exception:
                pass

            # ── 找消息列表控件 ───────────────────────────────────────────────
            msg_list = None

            # 方法1: 按 AutomationId 精确查找
            for aid in ("__chat_content_area__", "MessageList", "msgList"):
                try:
                    c = win.Control(AutomationId=aid, searchDepth=10, timeout=1)
                    if c.Exists(0):
                        msg_list = c
                        break
                except Exception:
                    pass

            # 方法2: 微信 4.x — 查找 mmui::RecyclerListView (Name="消息")
            if not msg_list:
                try:
                    c = win.Control(searchDepth=20, ClassName="mmui::RecyclerListView")
                    if c.Exists(1, 0):
                        msg_list = c
                        logger.debug("[UIA] 使用 mmui::RecyclerListView")
                except Exception:
                    pass

            # 方法3: 找最大的 ListControl（消息列表子项最多）
            if not msg_list:
                try:
                    all_lists: List = []

                    def _collect_lists(ctrl, depth=0):
                        if depth > 8:
                            return
                        try:
                            ct = ctrl.ControlTypeName
                            if ct in ("ListControl", "List"):
                                all_lists.append(ctrl)
                            for c in ctrl.GetChildren():
                                _collect_lists(c, depth + 1)
                        except Exception:
                            pass

                    _collect_lists(win)
                    if all_lists:
                        # 选子项最多的（排除会话列表那个，它在左侧）
                        def _list_score(c):
                            try:
                                children = c.GetChildren()
                                rect = c.BoundingRectangle
                                # 排除左侧面板（宽度占比 < 30%）
                                if win_rect and rect:
                                    win_w = win_rect.right - win_rect.left
                                    c_left = rect.left - win_rect.left
                                    if win_w > 0 and c_left / win_w < 0.30:
                                        return 0
                                return len(children)
                            except Exception:
                                return 0

                        msg_list = max(all_lists, key=_list_score)
                        if _list_score(msg_list) == 0:
                            msg_list = None
                except Exception:
                    pass

            if msg_list:
                items = msg_list.GetChildren()
                for item in items[-last_n:]:
                    try:
                        clsn = item.ClassName or ""

                        # 微信 4.x: mmui::ChatTextItemView 的 Name 直接是消息内容
                        if "mmui::Chat" in clsn:
                            item_name = item.Name or ""
                            if item_name:
                                msg_type = "text"
                                if "Image" in clsn or "图片" in item_name:
                                    msg_type = "image"
                                elif "Refer" in clsn:
                                    msg_type = "reference"
                                elif "Voice" in clsn:
                                    msg_type = "voice"
                                messages.append({
                                    "sender": "",
                                    "content": item_name,
                                    "time_str": "",
                                    "is_mine": False,
                                    "msg_type": msg_type,
                                })
                                continue

                        texts = _extract_texts(item, max_depth=5)
                        if not texts:
                            continue

                        content = ""
                        sender = ""
                        time_str = ""
                        msg_type = "text"

                        # 解析时间
                        remaining = []
                        for t in texts:
                            ts = t.strip()
                            if re.match(r'^\d{1,2}:\d{2}$', ts):
                                time_str = ts
                            elif re.match(r'^\d{4}-\d{2}-\d{2}', ts):
                                time_str = ts
                            elif re.match(r'^(今天|昨天|星期[一二三四五六日])\s*\d{1,2}:\d{2}$', ts):
                                time_str = ts
                            else:
                                remaining.append(t)

                        if remaining:
                            sender = remaining[0] if len(remaining) > 1 else ""
                            content = remaining[-1]

                        # 识别消息类型
                        if content in ("[图片]", "[图片消息]", "[Photo]"):
                            msg_type = "image"
                        elif content in ("[语音]", "[语音消息]", "[Voice]"):
                            msg_type = "voice"
                        elif content in ("[文件]", "[File]"):
                            msg_type = "file"
                        elif content in ("[视频]", "[Video]", "[小视频]"):
                            msg_type = "video"
                        elif content.startswith("[") and content.endswith("]"):
                            msg_type = "system"

                        # is_mine: 判断消息气泡是否在右侧
                        is_mine = _is_mine_by_rect(item, win_rect)

                        if content:
                            messages.append({
                                "sender": sender,
                                "content": content,
                                "time_str": time_str,
                                "is_mine": is_mine,
                                "msg_type": msg_type,
                            })
                    except Exception:
                        continue

        except Exception as e:
            logger.debug(f"UIA get_chat_messages: {e}")

        return contact, messages

    def click_session(self, contact: str) -> bool:
        """在左侧会话列表中点击指定联系人"""
        win = self._get_wechat_window(force_refresh=True)
        if not win:
            return False
        try:
            item = win.ListItemControl(
                SubName=contact,
                searchDepth=8,
                timeout=2
            )
            if item.Exists(0):
                item.Click()
                time.sleep(0.8)
                return True
        except Exception as e:
            logger.debug(f"UIA click_session({contact}): {e}")
        return False

    def dump_uia_tree(self, max_depth: int = UIA_DUMP_MAX_DEPTH) -> List[Dict]:
        """
        导出微信窗口 UIA 控件树（用于调试/诊断）。
        返回树形结构列表，每项：{name, type, automation_id, depth, rect, children_count}
        """
        win = self._get_wechat_window(force_refresh=True)
        if not win:
            return [{"error": f"未找到微信窗口（尝试: {', '.join(WECHAT_CLASSES)}）"}]

        result = []

        def _walk(ctrl, depth: int):
            if depth > max_depth:
                return
            try:
                name = (ctrl.Name or "").strip()[:60]
                ctrl_type = getattr(ctrl, "ControlTypeName", "?")
                auto_id = (getattr(ctrl, "AutomationId", "") or "").strip()[:40]
                class_name = (getattr(ctrl, "ClassName", "") or "").strip()[:40]
                rect = None
                try:
                    r = ctrl.BoundingRectangle
                    rect = {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom}
                except Exception:
                    pass
                children = []
                try:
                    children = ctrl.GetChildren()
                except Exception:
                    pass
                result.append({
                    "depth": depth,
                    "name": name,
                    "type": ctrl_type,
                    "automation_id": auto_id,
                    "class_name": class_name,
                    "rect": rect,
                    "children_count": len(children),
                })
                for child in children[:30]:  # 每层最多展开30个子项
                    _walk(child, depth + 1)
            except Exception:
                pass

        _walk(win, 0)
        return result

    def get_window_info(self) -> Dict:
        """获取微信窗口基本信息"""
        win = self._get_wechat_window()
        if not win:
            return {"found": False}
        try:
            rect = win.BoundingRectangle
            return {
                "found": True,
                "title": win.Name or "",
                "class_name": win.ClassName or "",
                "rect": {
                    "left": rect.left, "top": rect.top,
                    "right": rect.right, "bottom": rect.bottom,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                },
                "uia_available": _uia_available,
            }
        except Exception as e:
            return {"found": True, "error": str(e)}


# ── OCR 读取层（备用轨）─────────────────────────────────────────────────────

class OCRReader:
    """当 UIA 无法读取时，使用截图 + OCR 获取微信消息。"""

    def __init__(self, desktop):
        self._desktop = desktop  # src.server.desktop.DesktopStreamer 实例

    def get_unread_sessions(self) -> List[Dict]:
        """OCR 扫描微信左侧会话列表，识别红点/数字角标"""
        if not self._desktop:
            return []
        results = []
        try:
            items = self._desktop.ocr_screen()
            if not items:
                return []

            # 微信会话列表通常在屏幕左侧 0%-20% 水平区域
            left_items = [
                it for it in items
                if it.get("x", 1.0) < 0.22
            ]

            # 找纯数字文本（未读角标）
            for it in left_items:
                text = it.get("text", "").strip()
                if text.isdigit() and int(text) > 0:
                    y = it.get("y", 0)
                    nearby = [
                        n for n in left_items
                        if abs(n.get("y", 0) - y) < 0.04
                        and not n.get("text", "").isdigit()
                        and len(n.get("text", "")) >= 2
                    ]
                    if nearby:
                        contact = max(nearby, key=lambda n: n.get("score", 0))
                        results.append({
                            "contact": contact["text"].strip(),
                            "unread_count": int(text),
                            "preview": "",
                            "is_group": _is_group_name(contact["text"]),
                        })
        except Exception as e:
            logger.debug(f"OCR get_unread_sessions: {e}")
        return results

    def get_current_chat_messages(self, last_n: int = 5) -> Tuple[str, List[Dict]]:
        """OCR 读取当前聊天窗口最新消息"""
        if not self._desktop:
            return "", []
        contact = ""
        messages = []
        try:
            items = self._desktop.ocr_screen()
            if not items:
                return "", []

            title_area = [
                it for it in items
                if it.get("y", 1.0) < 0.08
                and it.get("x", 0) > 0.20
            ]
            if title_area:
                best = max(title_area, key=lambda n: n.get("score", 0))
                contact = best.get("text", "").strip()

            chat_area = sorted(
                [it for it in items if 0.10 < it.get("y", 0) < 0.85 and it.get("x", 0) > 0.20],
                key=lambda n: n.get("y", 0)
            )

            for it in chat_area[-last_n * 2:]:
                text = it.get("text", "").strip()
                if text and len(text) > 1:
                    messages.append({
                        "sender": "",
                        "content": text,
                        "time_str": "",
                        "is_mine": False,
                        "msg_type": "text",
                    })

        except Exception as e:
            logger.debug(f"OCR get_chat_messages: {e}")
        return contact, messages[-last_n:]


# ── 核心监控器 ────────────────────────────────────────────────────────────────

class WeChatMonitor:
    """
    微信消息监控器（UIAutomation + OCR 双轨）

    用法：
        monitor = WeChatMonitor(desktop=desktop_instance)
        monitor.on_message(callback)  # callback(msg: WeChatMessage)
        monitor.start()
        # ... 运行中 ...
        monitor.stop()
    """

    def __init__(self, desktop=None):
        self._desktop = desktop
        self._uia = UIAReader()
        self._ocr = OCRReader(desktop) if desktop else None

        self._callbacks: List[Callable[[WeChatMessage], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 消息指纹缓存（去重用）
        self._fingerprints: Dict[str, float] = {}
        self._fp_lock = threading.Lock()

        # 统计
        self.stats = {
            "uia_reads": 0,
            "ocr_reads": 0,
            "messages_detected": 0,
            "uia_failures": 0,
            "last_scan_time": 0.0,
            "last_scan_found": 0,
        }

        # 控制标志
        self._uia_mode = _uia_available  # 是否尝试 UIA 模式
        self._uia_fail_count = 0         # 连续失败次数，超过阈值降级到 OCR

    # ── 公开 API ────────────────────────────────────────────────────────────

    def on_message(self, callback: Callable[[WeChatMessage], None]):
        """注册消息回调（新消息到达时调用）"""
        self._callbacks.append(callback)

    def start(self):
        """启动后台监控线程"""
        if self._running:
            logger.warning("WeChatMonitor already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="WeChatMonitor",
            daemon=True
        )
        self._thread.start()
        logger.info("✅ WeChatMonitor 已启动（双轨模式）")

    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("WeChatMonitor 已停止")

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    def get_mode(self) -> str:
        """当前使用的读取模式"""
        if self._uia_mode and self._uia_fail_count < 5:
            return "uia"
        return "ocr"

    def manual_scan(self) -> Dict:
        """
        手动触发一次扫描，返回结果（用于调试/测试）。
        不触发回调，只返回读取到的数据。
        """
        result = {
            "wechat_running": _wechat_is_running(),
            "uia_available": _uia_available,
            "mode": self.get_mode(),
            "window_info": {},
            "unread_sessions": [],
            "current_chat": {"contact": "", "messages": []},
        }

        if not result["wechat_running"]:
            return result

        result["window_info"] = self._uia.get_window_info()

        use_uia = self.get_mode() == "uia"
        if use_uia:
            result["unread_sessions"] = self._uia.get_unread_sessions()
            contact, msgs = self._uia.get_current_chat_messages(last_n=5)
        elif self._ocr:
            result["unread_sessions"] = self._ocr.get_unread_sessions()
            contact, msgs = self._ocr.get_current_chat_messages(last_n=5)
        else:
            contact, msgs = "", []

        result["current_chat"] = {"contact": contact, "messages": msgs}
        return result

    def dump_uia_tree(self, max_depth: int = 5) -> List[Dict]:
        """导出微信 UIA 控件树（诊断用）"""
        return self._uia.dump_uia_tree(max_depth=max_depth)

    # ── 内部循环 ────────────────────────────────────────────────────────────

    def _monitor_loop(self):
        interval = SCAN_INTERVAL_UIA
        while self._running:
            try:
                self._scan_once()
            except Exception as e:
                logger.debug(f"Monitor scan error: {e}")
            time.sleep(interval)
            # 清理过期指纹
            self._cleanup_fingerprints()

    def _scan_once(self):
        """执行一次扫描"""
        if not _wechat_is_running():
            return

        use_uia = self._uia_mode and _uia_available and (self._uia_fail_count < 5)
        self.stats["last_scan_time"] = time.time()

        if use_uia:
            unread = self._uia.get_unread_sessions()
            if unread is None:
                self._uia_fail_count += 1
                self.stats["uia_failures"] += 1
                if self._uia_fail_count >= 5:
                    logger.warning("UIA 连续失败 5 次，降级到 OCR 模式")
                return
            self._uia_fail_count = max(0, self._uia_fail_count - 1)
            self.stats["uia_reads"] += 1
        else:
            if self._ocr:
                unread = self._ocr.get_unread_sessions()
                self.stats["ocr_reads"] += 1
            else:
                return

        self.stats["last_scan_found"] = len(unread)

        for session in unread:
            contact = session.get("contact", "").strip()
            if not contact:
                continue
            self._process_session(contact, session, use_uia)

    def _process_session(self, contact: str, session: Dict, use_uia: bool):
        """处理一个有未读消息的会话：切换到该会话，读取消息，触发回调"""
        try:
            switched = False
            if use_uia:
                switched = self._uia.click_session(contact)
            if not switched and self._desktop:
                switched = self._switch_via_search(contact)

            if not switched:
                logger.debug(f"无法切换到会话：{contact}")
                return

            time.sleep(0.8)

            if use_uia:
                _, messages = self._uia.get_current_chat_messages(last_n=5)
            elif self._ocr:
                _, messages = self._ocr.get_current_chat_messages(last_n=5)
            else:
                return

            is_group = session.get("is_group", False)

            for msg_dict in messages:
                content = msg_dict.get("content", "").strip()
                sender = msg_dict.get("sender", "").strip() or contact

                # 跳过空消息、自己发的消息、系统消息
                if not content:
                    continue
                if msg_dict.get("is_mine", False):
                    continue
                if msg_dict.get("msg_type") == "system":
                    continue

                wm = WeChatMessage(
                    contact=contact,
                    sender=sender,
                    content=content,
                    is_group=is_group,
                    at_me=_check_at_me(content),
                    raw_time_str=msg_dict.get("time_str", ""),
                    msg_type=msg_dict.get("msg_type", "text"),
                )

                if self._is_duplicate(wm):
                    continue

                self._mark_seen(wm)
                self.stats["messages_detected"] += 1
                logger.info(f"📩 新消息: {wm}")
                self._dispatch(wm)

        except Exception as e:
            logger.debug(f"process_session({contact}): {e}")

    def _switch_via_search(self, contact: str) -> bool:
        """用 Ctrl+F 搜索切换到指定联系人（降级方案）"""
        if not self._desktop:
            return False
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "f", _pause=False)
            time.sleep(0.6)
            pyautogui.hotkey("ctrl", "a", _pause=False)
            time.sleep(0.1)
            pyautogui.typewrite(contact, interval=0.05, _pause=False)
            time.sleep(1.2)

            items = self._desktop.ocr_screen() if self._ocr else []
            for it in items:
                t = it.get("text", "").strip()
                if contact in t or t in contact:
                    self._desktop.mouse_click(it["x"], it["y"])
                    time.sleep(0.8)
                    return True

            pyautogui.press("escape", _pause=False)
            return False
        except Exception as e:
            logger.debug(f"switch_via_search({contact}): {e}")
            return False

    def _dispatch(self, msg: WeChatMessage):
        """触发所有已注册的消息回调"""
        for cb in self._callbacks:
            try:
                cb(msg)
            except Exception as e:
                logger.error(f"Message callback error: {e}")

    # ── 指纹去重 ─────────────────────────────────────────────────────────────

    def _is_duplicate(self, msg: WeChatMessage) -> bool:
        fp = msg.fingerprint()
        with self._fp_lock:
            return fp in self._fingerprints

    def _mark_seen(self, msg: WeChatMessage):
        fp = msg.fingerprint()
        with self._fp_lock:
            self._fingerprints[fp] = time.time()

    def _cleanup_fingerprints(self):
        now = time.time()
        with self._fp_lock:
            expired = [k for k, t in self._fingerprints.items() if now - t > FINGERPRINT_TTL]
            for k in expired:
                del self._fingerprints[k]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _extract_texts(ctrl, max_depth: int = 4) -> List[str]:
    """递归提取控件树中所有 TextControl 的文本"""
    results = []
    try:
        name = (ctrl.Name or "").strip()
        if name:
            results.append(name)
        if max_depth > 0:
            for child in ctrl.GetChildren():
                results.extend(_extract_texts(child, max_depth - 1))
    except Exception:
        pass
    return results


def _is_mine_by_rect(ctrl, win_rect) -> bool:
    """
    根据消息气泡在窗口中的水平位置判断是否是自己发的。
    微信中自己的消息在右侧（气泡中心 x > 窗口宽度 55%）。
    """
    if not win_rect:
        return False
    try:
        rect = ctrl.BoundingRectangle
        if not rect:
            return False
        win_w = win_rect.right - win_rect.left
        if win_w <= 0:
            return False
        ctrl_center_x = (rect.left + rect.right) / 2
        rel_x = (ctrl_center_x - win_rect.left) / win_w
        return rel_x > 0.55
    except Exception:
        return False


def _is_group_name(name: str) -> bool:
    """简单判断是否群聊（含括号数字 如 "工作群(12)"，或名字超长）"""
    return bool(re.search(r'[\(\（]\d+[\)\）]', name)) or len(name) > 10


def _check_at_me(content: str) -> bool:
    """检测消息是否 @了我（@所有人 或 @具体名字）"""
    return "@所有人" in content or re.search(r'@\S+', content) is not None


def _wechat_is_running() -> bool:
    """检查微信进程是否在运行（兼容 3.x WeChat.exe 和 4.x WeChatAppEx.exe）"""
    if not IS_WINDOWS:
        return False
    try:
        import subprocess
        for proc_name in ["WeChat.exe", "WeChatAppEx.exe"]:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/NH"],
                capture_output=True, text=True, timeout=3
            )
            if proc_name in r.stdout:
                return True
        return False
    except Exception:
        return False
