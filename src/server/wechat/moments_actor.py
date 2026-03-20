# -*- coding: utf-8 -*-
"""
朋友圈操作执行层

执行层负责"手脚"动作：点赞、评论、发布朋友圈。
所有操作都经过 MomentsGuard 风控后才执行。

三条执行路径（优先级递减）：
  1. wxauto API（如 PublishMoment, 直接调用）
  2. UIAutomation 定位 + 模拟点击
  3. PyAutoGUI 图像识别 + 键鼠模拟

关键安全设计：
  - 每次点击添加随机像素偏移（MomentsGuard.get_click_offset）
  - 操作间自动注入自然延迟
  - 发布朋友圈前可进入人工审核队列
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from .moments_guard import MomentsGuard
from .moments_reader import MomentPost
from .contact_profile import record_interaction


@dataclass
class PublishRequest:
    """待发布的朋友圈"""
    text: str = ""
    media_files: List[str] = field(default_factory=list)
    privacy: str = "all"            # all / friends / whitelist / blacklist
    tags: List[str] = field(default_factory=list)
    status: str = "pending"         # pending / approved / published / rejected
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "media_files": self.media_files,
            "privacy": self.privacy,
            "tags": self.tags,
            "status": self.status,
            "created_at": self.created_at,
        }


class MomentsActor:
    """
    朋友圈操作执行器

    使用方式：
        actor = MomentsActor(wxauto_reader=wxauto, guard=guard)
        ok = await actor.like_post(post)
        ok = await actor.comment_post(post, "好看！")
        ok = await actor.publish_moment("今天天气真好", ["photo.jpg"])
    """

    def __init__(
        self,
        wxauto_reader=None,
        guard: Optional[MomentsGuard] = None,
        require_approval: bool = False,
    ):
        self._wxauto = wxauto_reader
        self._guard = guard or MomentsGuard()
        self._require_approval = require_approval
        self._publish_queue: List[PublishRequest] = []
        self._lock = threading.Lock()

    # ── 点赞 ─────────────────────────────────────────────────────────────────────

    async def like_post(self, post: MomentPost) -> bool:
        """对一条朋友圈点赞"""
        ok, delay = self._guard.can_like(post.fingerprint())
        if not ok:
            logger.debug(f"[MomentsActor] 点赞被风控拦截: {post.author}")
            return False

        if delay > 0:
            await asyncio.sleep(delay)

        success = await self._execute_like(post)

        if success:
            self._guard.record_like(post.fingerprint())
            record_interaction(post.author, "like", post_text=post.text[:100])
            self._record_analytics("like", post)
            logger.info(f"✅ 已点赞: {post.author} 的动态")

        return success

    async def _execute_like(self, post: MomentPost) -> bool:
        """执行点赞操作"""
        # 路径1: wxauto API
        if await self._try_wxauto_like(post):
            return True

        # 路径2: PyAutoGUI 模拟
        return await self._try_gui_like(post)

    async def _try_wxauto_like(self, post: MomentPost) -> bool:
        if not self._wxauto:
            return False
        try:
            wx = self._wxauto._wx if hasattr(self._wxauto, "_wx") else None
            if not wx or not hasattr(wx, "LikeMoment"):
                return False
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, wx.LikeMoment, post.post_id)
            return True
        except Exception as e:
            logger.debug(f"wxauto 点赞失败: {e}")
            return False

    async def _try_gui_like(self, post: MomentPost) -> bool:
        """通过 GUI 模拟点赞（在朋友圈页面中找到并点击点赞按钮）"""
        try:
            import pyautogui
            # 朋友圈中，每条动态右下角有评论/点赞的操作按钮
            # 策略：找到文字区域右侧的操作图标，点击展开，再点赞
            # 由于 UI 布局可能变化，这里做最佳努力尝试
            ox, oy = self._guard.get_click_offset()

            if sys.platform == "win32":
                try:
                    import uiautomation as uia
                    # 尝试找到点赞按钮
                    # 兼容 3.x 和 4.x
                    wechat_win = None
                    for cls in ["mmui::MainWindow", "WeChatMainWndForPC"]:
                        w = uia.WindowControl(ClassName=cls, searchDepth=1)
                        if w.Exists(1, 0):
                            wechat_win = w
                            break
                    if not wechat_win:
                        wechat_win = uia.WindowControl(Name="WeChat", searchDepth=1)
                    if wechat_win.Exists(2):
                        like_btns = wechat_win.GetChildren()
                        # 在朋友圈窗口中查找 "赞" 或心形按钮
                        # 这部分高度依赖微信版本，最佳努力
                        pass
                except Exception:
                    pass

            logger.debug("[MomentsActor] GUI 点赞：需要朋友圈页面处于正确位置")
            return False

        except ImportError:
            return False

    # ── 评论 ─────────────────────────────────────────────────────────────────────

    async def comment_post(self, post: MomentPost, comment: str) -> bool:
        """对一条朋友圈发表评论"""
        if not comment:
            return False

        ok, delay = self._guard.can_comment(post.fingerprint())
        if not ok:
            logger.debug(f"[MomentsActor] 评论被风控拦截: {post.author}")
            return False

        if delay > 0:
            await asyncio.sleep(delay)

        success = await self._execute_comment(post, comment)

        if success:
            self._guard.record_comment(post.fingerprint())
            record_interaction(
                post.author, "comment",
                content=comment, post_text=post.text[:100],
            )
            self._track_comment(post, comment)
            self._record_analytics("comment", post, content=comment)
            logger.info(f"✅ 已评论: {post.author} → {comment[:30]}")

        return success

    def _track_comment(self, post: MomentPost, comment: str):
        """将评论记录到 CommentChainTracker 以支持后续跟进"""
        try:
            from .moments_tracker import CommentChainTracker
            if not hasattr(self.__class__, '_chain_tracker'):
                self.__class__._chain_tracker = CommentChainTracker()
            self.__class__._chain_tracker.record_my_comment(
                post_author=post.author,
                comment=comment,
                post_text=post.text[:200],
            )
        except Exception:
            pass

    @staticmethod
    def _record_analytics(event_type: str, post: MomentPost, content: str = ""):
        """记录互动数据到分析引擎"""
        try:
            from .moments_analytics import record_event
            record_event(
                event_type=event_type,
                target_author=post.author,
                content_text=content or post.text[:200],
            )
        except Exception:
            pass

    async def _execute_comment(self, post: MomentPost, comment: str) -> bool:
        # 路径1: wxauto API
        if await self._try_wxauto_comment(post, comment):
            return True

        # 路径2: PyAutoGUI + 剪贴板
        return await self._try_gui_comment(post, comment)

    async def _try_wxauto_comment(self, post: MomentPost, comment: str) -> bool:
        if not self._wxauto:
            return False
        try:
            wx = self._wxauto._wx if hasattr(self._wxauto, "_wx") else None
            if not wx or not hasattr(wx, "CommentMoment"):
                return False
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, wx.CommentMoment, post.post_id, comment
            )
            return True
        except Exception as e:
            logger.debug(f"wxauto 评论失败: {e}")
            return False

    async def _try_gui_comment(self, post: MomentPost, comment: str) -> bool:
        """通过 GUI 模拟评论"""
        try:
            import pyautogui
            import pyperclip

            ox, oy = self._guard.get_click_offset()

            if sys.platform == "win32":
                try:
                    import uiautomation as uia
                    # 兼容 3.x 和 4.x
                    wechat_win = None
                    for cls in ["mmui::MainWindow", "WeChatMainWndForPC"]:
                        w = uia.WindowControl(ClassName=cls, searchDepth=1)
                        if w.Exists(1, 0):
                            wechat_win = w
                            break
                    if not wechat_win:
                        wechat_win = uia.WindowControl(Name="WeChat", searchDepth=1)
                    if wechat_win.Exists(2):
                        # 尝试找到评论输入框
                        edit = wechat_win.EditControl(Name="评论")
                        if not edit.Exists(1):
                            edit = wechat_win.EditControl()
                        if edit.Exists(1):
                            edit.Click()
                            time.sleep(0.3)
                            pyperclip.copy(comment)
                            pyautogui.hotkey("ctrl", "v")
                            time.sleep(0.2)
                            pyautogui.press("enter")
                            return True
                except Exception as e:
                    logger.debug(f"UIA 评论失败: {e}")

            return False

        except ImportError:
            return False

    # ── 发布朋友圈 ────────────────────────────────────────────────────────────────

    async def publish_moment(
        self,
        text: str,
        media_files: List[str] = None,
        privacy: str = "all",
        tags: List[str] = None,
    ) -> bool:
        """发布一条朋友圈"""
        ok, delay = self._guard.can_publish()
        if not ok:
            logger.debug("[MomentsActor] 发圈被风控拦截")
            return False

        req = PublishRequest(
            text=text,
            media_files=media_files or [],
            privacy=privacy,
            tags=tags or [],
        )

        if self._require_approval:
            with self._lock:
                self._publish_queue.append(req)
            logger.info(f"📝 朋友圈文案已入审核队列: {text[:30]}...")
            return True

        if delay > 0:
            await asyncio.sleep(delay)

        return await self._execute_publish(req)

    async def _execute_publish(self, req: PublishRequest) -> bool:
        """执行发布"""
        # 路径1: wxauto PublishMoment
        if await self._try_wxauto_publish(req):
            self._guard.record_publish()
            req.status = "published"
            logger.info(f"✅ 朋友圈已发布: {req.text[:30]}...")
            return True

        # 路径2: GUI 模拟（较脆弱，作为兜底）
        logger.warning("[MomentsActor] wxauto 发圈不可用，请手动发布")
        return False

    async def _try_wxauto_publish(self, req: PublishRequest) -> bool:
        if not self._wxauto:
            return False
        try:
            wx = self._wxauto._wx if hasattr(self._wxauto, "_wx") else None
            if not wx or not hasattr(wx, "PublishMoment"):
                return False

            privacy_config = {}
            if req.privacy == "whitelist" and req.tags:
                privacy_config = {"privacy": "白名单", "tags": req.tags}
            elif req.privacy == "blacklist" and req.tags:
                privacy_config = {"privacy": "黑名单", "tags": req.tags}

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                wx.PublishMoment,
                req.text,
                req.media_files if req.media_files else None,
                privacy_config if privacy_config else None,
            )
            return True

        except Exception as e:
            logger.warning(f"wxauto 发圈失败: {e}")
            return False

    # ── 审核队列 ─────────────────────────────────────────────────────────────────

    def get_pending_publishes(self) -> List[Dict]:
        with self._lock:
            return [
                r.to_dict() for r in self._publish_queue
                if r.status == "pending"
            ]

    async def approve_publish(self, index: int) -> bool:
        with self._lock:
            pending = [r for r in self._publish_queue if r.status == "pending"]
            if 0 <= index < len(pending):
                req = pending[index]
                req.status = "approved"

        if req.status == "approved":
            return await self._execute_publish(req)
        return False

    def reject_publish(self, index: int) -> bool:
        with self._lock:
            pending = [r for r in self._publish_queue if r.status == "pending"]
            if 0 <= index < len(pending):
                pending[index].status = "rejected"
                return True
        return False

    # ── 状态 ─────────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        guard_stats = self._guard.get_stats()
        with self._lock:
            pending = sum(1 for r in self._publish_queue if r.status == "pending")
            published = sum(1 for r in self._publish_queue if r.status == "published")
        return {
            **guard_stats,
            "pending_publishes": pending,
            "published_total": published,
            "require_approval": self._require_approval,
        }
