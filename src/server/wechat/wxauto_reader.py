# -*- coding: utf-8 -*-
"""
轨道B: wxauto 读取器

基于 wxauto 库实现后台消息监听，核心优势：
  - AddListenChat() 后台监听，无需切换窗口
  - 成熟的微信 3.9/4.0 兼容性处理
  - 消息类型自动识别（text/image/voice/file 等）
  - SendMsg() 稳定发送
"""

import re
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set

from loguru import logger

from .models import WxChat, WxMessage

_wxauto_available = False
_wxauto = None

if sys.platform == "win32":
    try:
        import wxauto as _wxauto
        _wxauto_available = True
        logger.info(f"✅ wxauto 已加载 (version: {getattr(_wxauto, '__version__', '?')})")

        # Monkey-patch: wxauto 硬编码了 WeChatMainWndForPC，微信 4.x 改为 mmui::MainWindow
        try:
            import win32gui
            _orig_find = win32gui.FindWindow

            def _patched_find_window(classname=None, windowname=None):
                """兼容微信 3.x 和 4.x 的 FindWindow"""
                if classname == "WeChatMainWndForPC":
                    hwnd = _orig_find(classname, windowname)
                    if not hwnd:
                        hwnd = _orig_find("mmui::MainWindow", windowname)
                    return hwnd
                return _orig_find(classname, windowname)

            # 替换 wxauto 内部使用的 FindWindow
            if hasattr(_wxauto, 'uicontrol'):
                _wxauto.uicontrol.FindWindow = _patched_find_window
            if hasattr(_wxauto, 'utils'):
                if hasattr(_wxauto.utils, 'FindWindow'):
                    _wxauto.utils.FindWindow = _patched_find_window
            # 也替换全局的
            import wxauto.uicontrol as _uc
            if hasattr(_uc, 'FindWindow'):
                _uc.FindWindow = _patched_find_window
            logger.debug("[wxauto] 已 patch FindWindow 兼容微信 4.x")
        except Exception as _pe:
            logger.debug(f"[wxauto] patch FindWindow 失败（非致命）: {_pe}")

    except ImportError:
        logger.info("wxauto 未安装，轨道B不可用 (pip install wxauto)")
    except Exception as e:
        logger.warning(f"wxauto 加载失败: {e}")


class WxAutoReader:
    """
    wxauto 消息读取器

    关键能力：
      - 后台监听多个联系人/群（无需切换窗口）
      - 实时获取新消息
      - 发送消息
      - 获取聊天列表
    """

    def __init__(self):
        self._wx = None
        self._listen_targets: Set[str] = set()
        self._initialized = False
        self._lock = threading.Lock()
        self._last_msg_fingerprints: Dict[str, Set[str]] = {}

    @property
    def available(self) -> bool:
        return _wxauto_available

    def initialize(self) -> bool:
        """连接微信实例"""
        if not _wxauto_available:
            return False
        try:
            self._wx = _wxauto.WeChat()
            self._initialized = True
            logger.info("✅ wxauto 已连接微信")
            return True
        except Exception as e:
            logger.warning(f"wxauto 连接微信失败: {e}")
            self._initialized = False
            return False

    def add_listen(self, contacts: List[str]) -> int:
        """
        添加监听目标（联系人/群名）。
        wxauto 会在后台监听这些聊天，无需切换窗口。
        返回成功添加的数量。
        """
        if not self._ensure_connected():
            return 0
        added = 0
        for name in contacts:
            if name in self._listen_targets:
                continue
            try:
                self._wx.AddListenChat(who=name, savepic=False)
                self._listen_targets.add(name)
                self._last_msg_fingerprints.setdefault(name, set())
                added += 1
                logger.info(f"wxauto 添加监听: {name}")
            except Exception as e:
                logger.warning(f"wxauto 添加监听失败 [{name}]: {e}")
        return added

    def get_new_messages(self) -> List[WxMessage]:
        """
        获取所有监听目标的新消息。
        自动去重（只返回上次调用后的新消息）。
        """
        if not self._ensure_connected() or not self._listen_targets:
            return []

        all_messages: List[WxMessage] = []
        try:
            raw_msgs = self._wx.GetListenMessage()
            if not raw_msgs:
                return []

            for chat_obj in raw_msgs:
                who = getattr(chat_obj, "who", "") or ""
                msgs_list = raw_msgs.get(chat_obj, [])
                contact_fps = self._last_msg_fingerprints.setdefault(who, set())

                for msg in msgs_list:
                    try:
                        wx_msg = self._convert_message(msg, who)
                        if not wx_msg:
                            continue

                        fp = wx_msg.fingerprint()
                        if fp in contact_fps:
                            continue
                        contact_fps.add(fp)

                        # 保持指纹集合在合理大小
                        if len(contact_fps) > 500:
                            oldest = list(contact_fps)[:250]
                            contact_fps.difference_update(oldest)

                        all_messages.append(wx_msg)
                    except Exception:
                        continue

        except Exception as e:
            logger.debug(f"wxauto GetListenMessage error: {e}")

        return all_messages

    def get_current_chat_messages(self, last_n: int = 10) -> List[WxMessage]:
        """获取当前打开的聊天窗口的消息"""
        if not self._ensure_connected():
            return []
        results = []
        try:
            raw_msgs = self._wx.GetAllMessage()
            if not raw_msgs:
                return []
            for msg in raw_msgs[-last_n:]:
                wx_msg = self._convert_message(msg, "")
                if wx_msg:
                    results.append(wx_msg)
        except Exception as e:
            logger.debug(f"wxauto GetAllMessage error: {e}")
        return results

    def send_message(self, contact: str, text: str) -> bool:
        """发送文字消息"""
        if not self._ensure_connected():
            return False
        try:
            self._wx.SendMsg(msg=text, who=contact)
            logger.info(f"wxauto 发送消息 → {contact}: {text[:30]}...")
            return True
        except Exception as e:
            logger.error(f"wxauto 发送失败 [{contact}]: {e}")
            return False

    def send_file(self, contact: str, filepath: str) -> bool:
        """发送文件"""
        if not self._ensure_connected():
            return False
        try:
            self._wx.SendFiles(filepath=filepath, who=contact)
            return True
        except Exception as e:
            logger.error(f"wxauto 发送文件失败 [{contact}]: {e}")
            return False

    def get_chat_list(self) -> List[WxChat]:
        """获取会话列表"""
        if not self._ensure_connected():
            return []
        results = []
        try:
            sessions = self._wx.GetSessionList() if hasattr(self._wx, "GetSessionList") else []
            for s in sessions:
                name = s if isinstance(s, str) else getattr(s, "name", str(s))
                results.append(WxChat(name=name))
        except Exception as e:
            logger.debug(f"wxauto GetSessionList error: {e}")
        return results

    def _ensure_connected(self) -> bool:
        if self._initialized and self._wx:
            return True
        return self.initialize()

    def _convert_message(self, msg, default_contact: str) -> Optional[WxMessage]:
        """将 wxauto 消息对象转换为统一 WxMessage"""
        try:
            msg_type_raw = getattr(msg, "type", "friend")
            content = getattr(msg, "content", "") or ""
            sender = getattr(msg, "sender", "") or ""

            if not content:
                return None

            # 自己发的消息
            is_mine = (msg_type_raw == "self")
            # 系统消息
            if msg_type_raw == "sys":
                return WxMessage(
                    contact=default_contact,
                    sender="system",
                    content=content,
                    is_mine=False,
                    msg_type="system",
                    source="wxauto",
                )

            # 消息类型推断
            msg_type = "text"
            if content.startswith("[图片]") or content.startswith("[Picture]"):
                msg_type = "image"
            elif content.startswith("[语音]") or content.startswith("[Voice]"):
                msg_type = "voice"
            elif content.startswith("[文件]") or content.startswith("[File]"):
                msg_type = "file"
            elif content.startswith("[视频]") or content.startswith("[Video]"):
                msg_type = "video"
            elif content.startswith("[链接]") or content.startswith("[Link]"):
                msg_type = "link"

            contact = default_contact or sender
            is_group = bool(re.search(r'[\(\（]\d+[\)\）]', contact)) or len(contact) > 10
            at_me = "@所有人" in content or bool(re.search(r'@\S+', content))

            return WxMessage(
                contact=contact,
                sender=sender if sender != contact else "",
                content=content,
                is_group=is_group,
                at_me=at_me,
                is_mine=is_mine,
                msg_type=msg_type,
                source="wxauto",
            )
        except Exception:
            return None
