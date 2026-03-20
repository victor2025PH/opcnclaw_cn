# -*- coding: utf-8 -*-
"""
朋友圈内容读取器

三轨策略（与消息读取一脉相承）：
  轨道A: wxauto / wxautox4 API（最干净，需要库支持）
  轨道B: 截图 + 多模态 Vision AI 提取（最可靠，不依赖 UI 控件树）
  轨道C: UIAutomation 控件遍历（兜底，Qt Quick 下可能失效）

核心优化思路：
  - Vision AI 提取是 PRIMARY 方案（而非 fallback），因为 WeChat 4.0+ Qt Quick
    对 UIAutomation 支持极差，但截图+大模型理解是稳定且强大的
  - 每条动态返回 MomentPost 对象，包含文字/图片描述/作者/时间
  - 图片不做下载，而是通过 Vision AI 直接在截图中理解
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger


# ── 数据模型 ─────────────────────────────────────────────────────────────────────

@dataclass
class MomentPost:
    """一条朋友圈动态"""
    post_id: str = ""               # 唯一标识（hash生成）
    author: str = ""                # 发布者昵称
    text: str = ""                  # 文字内容
    image_desc: str = ""            # 图片的 AI 描述（Vision 分析结果）
    image_count: int = 0            # 图片数量
    has_video: bool = False
    time_str: str = ""              # 时间文本（如"2小时前"）
    like_count: int = 0
    comment_count: int = 0
    i_liked: bool = False           # 我是否已点赞
    location: str = ""              # 定位信息
    link_title: str = ""            # 分享链接标题
    raw_screenshot: bytes = field(default=b"", repr=False)  # 该条动态的截图区域
    source: str = "unknown"         # wxauto / vision / uia
    timestamp: float = field(default_factory=time.time)

    def fingerprint(self) -> str:
        if self.post_id:
            return self.post_id
        key = f"{self.author}|{self.text[:80]}|{self.time_str}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()


@dataclass
class MomentsPage:
    """一页朋友圈（一次滚动的结果）"""
    posts: List[MomentPost] = field(default_factory=list)
    has_more: bool = True
    scroll_position: int = 0
    source: str = "unknown"


# ── 朋友圈读取器 ─────────────────────────────────────────────────────────────────

class MomentsReader:
    """
    朋友圈内容读取器

    使用方式：
        reader = MomentsReader(ai_backend=backend)
        page = await reader.browse()      # 打开朋友圈并读取当前页
        page2 = await reader.scroll_next() # 向下滚动一页
    """

    def __init__(self, ai_backend=None, wxauto_reader=None):
        self._ai = ai_backend
        self._wxauto = wxauto_reader
        self._seen_fps: set = set()
        self._scroll_pos = 0
        self._moments_open = False
        self._lock = threading.Lock()

    # ── 公开接口 ─────────────────────────────────────────────────────────────────

    async def browse(self, max_posts: int = 10) -> MomentsPage:
        """打开朋友圈并读取可见动态"""
        page = await self._try_wxauto_browse(max_posts)
        if page and page.posts:
            return page

        page = await self._try_vision_browse(max_posts)
        if page and page.posts:
            return page

        return MomentsPage(posts=[], has_more=False, source="none")

    async def scroll_next(self, max_posts: int = 10) -> MomentsPage:
        """向下滚动并读取新的动态（智能滚动+到底检测）"""
        # 滚动前截图用于到底检测
        pre_screenshot = self._take_moments_screenshot()

        self._scroll_pos += 1
        self._scroll_moments_page()

        page = await self._try_vision_browse(max_posts)
        if page and page.posts:
            # 去重：只保留新内容
            new_posts = self.dedup(page.posts)
            page.posts = new_posts
            page.scroll_position = self._scroll_pos

            # 到底检测：无新内容 = 到底了
            if not new_posts:
                page.has_more = False
                logger.info(f"[Moments] 滚动到底（位置={self._scroll_pos}，无新内容）")
            return page

        # Vision 失败时用截图对比检测到底
        post_screenshot = self._take_moments_screenshot()
        at_bottom = self._detect_scroll_end(pre_screenshot, post_screenshot)

        return MomentsPage(
            posts=[], has_more=not at_bottom,
            scroll_position=self._scroll_pos,
        )

    async def browse_pages(self, max_pages: int = 5, max_posts: int = 50) -> List[MomentPost]:
        """多页浏览：自动滚动直到收集够或到底

        Args:
            max_pages: 最多滚动页数
            max_posts: 最多收集动态数

        Returns:
            去重后的所有动态列表
        """
        all_posts: List[MomentPost] = []

        # 先读首页
        page = await self.browse(max_posts=max_posts)
        if page.posts:
            new = self.dedup(page.posts)
            all_posts.extend(new)

        # 逐页滚动
        for i in range(max_pages - 1):
            if len(all_posts) >= max_posts:
                break

            page = await self.scroll_next(max_posts=max_posts - len(all_posts))
            if page.posts:
                all_posts.extend(page.posts)  # scroll_next 内部已去重

            if not page.has_more:
                logger.info(f"[Moments] 多页浏览结束：共 {len(all_posts)} 条，{i+2} 页")
                break

        return all_posts[:max_posts]

    def dedup(self, posts: List[MomentPost]) -> List[MomentPost]:
        """去重：只返回未见过的动态"""
        result = []
        for p in posts:
            fp = p.fingerprint()
            if fp not in self._seen_fps:
                self._seen_fps.add(fp)
                result.append(p)
        return result

    def reset(self):
        """重置状态"""
        self._seen_fps.clear()
        self._scroll_pos = 0
        self._moments_open = False

    # ── 轨道A: wxauto ─────────────────────────────────────────────────────────────

    async def _try_wxauto_browse(self, max_posts: int) -> Optional[MomentsPage]:
        """尝试通过 wxauto 读取朋友圈"""
        if not self._wxauto:
            return None

        try:
            wx = self._wxauto._wx if hasattr(self._wxauto, "_wx") else None
            if not wx:
                return None

            if not hasattr(wx, "GetMoments"):
                return None

            import asyncio
            raw = await asyncio.get_event_loop().run_in_executor(
                None, wx.GetMoments
            )
            if not raw:
                return None

            posts = []
            items = raw if isinstance(raw, list) else [raw]
            for item in items[:max_posts]:
                post = self._parse_wxauto_moment(item)
                if post:
                    posts.append(post)

            return MomentsPage(posts=posts, source="wxauto")

        except Exception as e:
            logger.debug(f"wxauto 朋友圈读取失败: {e}")
            return None

    def _parse_wxauto_moment(self, item) -> Optional[MomentPost]:
        """将 wxauto 返回的朋友圈数据解析为 MomentPost"""
        try:
            if isinstance(item, dict):
                return MomentPost(
                    author=item.get("author", item.get("nickname", "")),
                    text=item.get("text", item.get("content", "")),
                    image_count=len(item.get("images", [])),
                    time_str=item.get("time", ""),
                    source="wxauto",
                )
            if hasattr(item, "content"):
                return MomentPost(
                    author=getattr(item, "nickname", getattr(item, "author", "")),
                    text=getattr(item, "content", ""),
                    source="wxauto",
                )
        except Exception:
            pass
        return None

    # ── 轨道B: 截图 + Vision AI ────────────────────────────────────────────────

    async def _try_vision_browse(self, max_posts: int) -> Optional[MomentsPage]:
        """截图 + 多模态 Vision AI 提取朋友圈内容"""
        if not self._ai:
            return None

        try:
            if not self._moments_open:
                self._open_moments_page()
                self._moments_open = True
                import asyncio
                await asyncio.sleep(1.5)

            screenshot_b64 = self._take_moments_screenshot()
            if not screenshot_b64:
                return None

            posts = await self._extract_via_vision(screenshot_b64, max_posts)
            return MomentsPage(posts=posts, source="vision")

        except Exception as e:
            logger.warning(f"Vision 朋友圈读取失败: {e}")
            return None

    def _open_moments_page(self):
        """通过键鼠操作打开朋友圈页面"""
        try:
            import pyautogui
            pyautogui.FAILSAFE = True

            if sys.platform == "win32":
                import ctypes
                hwnd = ctypes.windll.user32.FindWindowW(None, "微信")
                if not hwnd:
                    hwnd = ctypes.windll.user32.FindWindowW(None, "WeChat")
                if hwnd:
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    time.sleep(0.5)

            # 微信 PC 中打开朋友圈的通用方法：
            # 1. 点击左侧「发现」图标（通常在第三个位置）
            # 2. 然后点击「朋友圈」入口
            # 这里用 UIA 尝试定位，失败则记录日志
            try:
                if sys.platform == "win32":
                    import uiautomation as uia
                    # 兼容 3.x 和 4.x 窗口
                    wechat_win = None
                    for cls in ["mmui::MainWindow", "WeChatMainWndForPC"]:
                        w = uia.WindowControl(ClassName=cls, searchDepth=1)
                        if w.Exists(2, 0):
                            wechat_win = w
                            break
                    if not wechat_win:
                        wechat_win = uia.WindowControl(Name="WeChat", searchDepth=1)
                    if wechat_win and wechat_win.Exists(2):
                        # 4.x: mmui::XTabBarItem Name="朋友圈"
                        moments_btn = wechat_win.Control(
                            searchDepth=10, Name="朋友圈"
                        )
                        if moments_btn.Exists(2, 0):
                            moments_btn.Click()
                            time.sleep(1)
                            return
                        # 3.x 回退
                        discover = wechat_win.ButtonControl(Name="发现")
                        if discover.Exists(2):
                            discover.Click()
                            time.sleep(0.5)
                            fb = wechat_win.Control(Name="朋友圈", searchDepth=8)
                            if fb.Exists(1, 0):
                                fb.Click()
                                time.sleep(1)
                                return
            except Exception as e:
                logger.debug(f"UIA 导航朋友圈失败: {e}")

            logger.info("朋友圈导航：请手动打开朋友圈页面")

        except ImportError:
            logger.warning("pyautogui 未安装")

    def _scroll_moments_page(self):
        """在朋友圈页面向下滚动（混合策略：滚轮+PageDown）"""
        try:
            import pyautogui
            # 策略：前3页用滚轮（平滑），之后用 PageDown（可靠）
            if self._scroll_pos <= 3:
                pyautogui.scroll(-5)
            else:
                pyautogui.press("pagedown")
            time.sleep(1.0)  # 等待内容加载（0.8→1.0 更稳定）
        except Exception as e:
            logger.debug(f"滚动失败: {e}")

    def _detect_scroll_end(self, before_b64: Optional[str], after_b64: Optional[str]) -> bool:
        """截图对比检测是否滚到底（图片相似度 > 95% = 到底）"""
        if not before_b64 or not after_b64:
            return False
        try:
            # 快速比较：前1000字符的 hash（截图几乎相同 = 没有新内容加载）
            import hashlib
            h1 = hashlib.md5(before_b64[:2000].encode()).hexdigest()
            h2 = hashlib.md5(after_b64[:2000].encode()).hexdigest()
            if h1 == h2:
                return True

            # 精确比较：像素级差异（需要 PIL）
            import base64
            from io import BytesIO
            from PIL import Image
            img1 = Image.open(BytesIO(base64.b64decode(before_b64)))
            img2 = Image.open(BytesIO(base64.b64decode(after_b64)))

            # 缩放到相同小尺寸比较
            size = (160, 90)
            img1 = img1.resize(size).convert("L")  # 灰度
            img2 = img2.resize(size).convert("L")

            pixels1 = list(img1.getdata())
            pixels2 = list(img2.getdata())

            diff = sum(abs(a - b) for a, b in zip(pixels1, pixels2))
            max_diff = 255 * len(pixels1)
            similarity = 1.0 - (diff / max_diff)

            at_bottom = similarity > 0.95
            if at_bottom:
                logger.info(f"[Moments] 截图对比：相似度 {similarity:.2%}，判定到底")
            return at_bottom

        except Exception as e:
            logger.debug(f"截图对比失败: {e}")
            return False

    # Vision AI 缓存（同一截图 30 秒内不重复调 API）
    _vision_cache: Dict = {}
    _VISION_CACHE_TTL = 30.0

    def _take_moments_screenshot(self) -> Optional[str]:
        """截取朋友圈区域并转为 base64"""
        try:
            import pyautogui
            import base64
            from io import BytesIO

            screenshot = pyautogui.screenshot()
            buffer = BytesIO()
            screenshot.save(buffer, format="JPEG", quality=60)  # JPEG 比 PNG 小 3-5x
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return b64

        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None

    def _get_vision_cache(self, screenshot_b64: str) -> Optional[List]:
        """检查 Vision AI 缓存"""
        import hashlib, time
        key = hashlib.md5(screenshot_b64[:1000].encode()).hexdigest()
        entry = self._vision_cache.get(key)
        if entry and (time.time() - entry["ts"]) < self._VISION_CACHE_TTL:
            logger.debug("[Vision] 缓存命中")
            return entry["posts"]
        return None

    def _set_vision_cache(self, screenshot_b64: str, posts: List):
        """设置 Vision AI 缓存"""
        import hashlib, time
        key = hashlib.md5(screenshot_b64[:1000].encode()).hexdigest()
        self._vision_cache[key] = {"posts": posts, "ts": time.time()}
        # 清理过期缓存
        now = time.time()
        expired = [k for k, v in self._vision_cache.items() if now - v["ts"] > self._VISION_CACHE_TTL * 3]
        for k in expired:
            del self._vision_cache[k]

    async def _extract_via_vision(
        self, screenshot_b64: str, max_posts: int
    ) -> List[MomentPost]:
        """用 Vision AI 从截图中提取朋友圈内容（带缓存）"""
        cached = self._get_vision_cache(screenshot_b64)
        if cached is not None:
            return cached
        prompt = f"""请分析这张微信朋友圈截图，提取所有可见的朋友圈动态。

对每条动态，提取以下信息并以 JSON 数组格式返回（最多{max_posts}条）：
[
  {{
    "author": "发布者昵称",
    "text": "文字内容（完整）",
    "image_desc": "图片内容描述（如有图片，描述图片中的场景/物体/人物/情绪）",
    "image_count": 图片数量,
    "has_video": false,
    "time_str": "时间标记（如'2小时前'）",
    "i_liked": false,
    "location": "定位（如有）",
    "link_title": "分享链接标题（如有）"
  }}
]

注意：
- 只返回 JSON 数组，不要其他文字
- 如果无法识别某个字段，留空字符串
- image_desc 要详细描述图片内容，这对后续AI评论生成很重要
- 如果截图中没有朋友圈内容，返回空数组 []"""

        try:
            if hasattr(self._ai, "_vision_client") and self._ai._vision_client:
                result = await self._call_vision_api(screenshot_b64, prompt)
            elif hasattr(self._ai, "chat_simple"):
                result = await self._call_text_with_image_hint(prompt)
            else:
                return []

            posts = self._parse_vision_result(result)
            self._set_vision_cache(screenshot_b64, posts)
            return posts

        except Exception as e:
            logger.warning(f"Vision AI 提取失败: {e}")
            return []

    async def _call_vision_api(self, image_b64: str, prompt: str) -> str:
        """调用视觉模型（GLM-4V-Flash / GPT-4V 等）"""
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ]

            if self._ai._vision_client:
                resp = await self._ai._vision_client.chat.completions.create(
                    model=self._ai._vision_model,
                    messages=messages,
                    max_tokens=2000,
                )
                return resp.choices[0].message.content or ""

        except Exception as e:
            logger.warning(f"Vision API 调用失败: {e}")
        return "[]"

    async def _call_text_with_image_hint(self, prompt: str) -> str:
        """无视觉模型时退化为纯文本提示"""
        fallback_prompt = (
            "我无法发送截图。请返回一个空的 JSON 数组: []"
        )
        result = await self._ai.chat_simple(
            [{"role": "user", "content": fallback_prompt}]
        )
        return result

    def _parse_vision_result(self, raw: str) -> List[MomentPost]:
        """解析 Vision AI 返回的 JSON"""
        raw = raw.strip()
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []

        try:
            items = json.loads(json_match.group())
        except json.JSONDecodeError:
            return []

        posts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            post = MomentPost(
                author=item.get("author", ""),
                text=item.get("text", ""),
                image_desc=item.get("image_desc", ""),
                image_count=item.get("image_count", 0),
                has_video=item.get("has_video", False),
                time_str=item.get("time_str", ""),
                i_liked=item.get("i_liked", False),
                location=item.get("location", ""),
                link_title=item.get("link_title", ""),
                source="vision",
            )
            post.post_id = post.fingerprint()
            posts.append(post)

        return posts
