# -*- coding: utf-8 -*-
"""
微信三轨融合适配器

统一管理 DB直读 / wxauto / UIA+OCR 三条轨道，
自动探测最优轨道，故障时自动降级。

优先级：DB > wxauto > UIA > OCR

使用方式：
    adapter = WeChatAdapter(desktop=desktop_instance)
    adapter.start()

    # 读取新消息（自动选择最优轨道）
    messages = adapter.get_new_messages()

    # 发送消息（优先 wxauto，降级到 desktop_skills）
    adapter.send_message("张三", "你好")

    # 获取所有轨道状态
    status = adapter.get_status()
"""

import asyncio
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from .anti_risk import AntiRiskEngine
from .db_reader import WeChatDBReader
from .models import TrackStatus, WxChat, WxMessage
from .wxauto_reader import WxAutoReader

# 尝试导入旧版读取器（保持兼容）
try:
    from ..wechat_monitor import UIAReader, OCRReader, _wechat_is_running
    _legacy_available = True
except ImportError:
    _legacy_available = False

    def _wechat_is_running():
        return False


class WeChatAdapter:
    """
    三轨融合适配器

    轨道A: DB直读  — 零UI干扰，读取完整消息记录
    轨道B: wxauto  — 后台监听，无需切换窗口
    轨道C: UIA/OCR — 旧版方案，兜底
    """

    def __init__(self, desktop=None, ai_backend=None):
        self._desktop = desktop
        self._backend = ai_backend

        # 三条轨道
        self._db_reader = WeChatDBReader()
        self._wxauto_reader = WxAutoReader()
        self._uia_reader = UIAReader() if _legacy_available else None
        self._ocr_reader = OCRReader(desktop) if _legacy_available and desktop else None

        # 轨道状态
        self._tracks: Dict[str, TrackStatus] = {
            "db": TrackStatus(name="db"),
            "wxauto": TrackStatus(name="wxauto"),
            "uia": TrackStatus(name="uia"),
            "ocr": TrackStatus(name="ocr"),
        }

        # 反风控
        self.anti_risk = AntiRiskEngine()

        # 消息回调
        self._callbacks: List[Callable[[WxMessage], None]] = []

        # 去重
        self._seen_fps: Dict[str, float] = {}
        self._fp_lock = threading.Lock()

        # 监控线程
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_db_check: float = 0
        self._last_scan_time: float = 0

        # 统计
        self.stats = {
            "messages_detected": 0,
            "messages_dispatched": 0,
            "sends_success": 0,
            "sends_failed": 0,
            "scans": 0,
        }

    # ── 公开 API ──────────────────────────────────────────────────────────

    def on_message(self, callback: Callable[[WxMessage], None]):
        """注册新消息回调"""
        self._callbacks.append(callback)

    def start(self):
        """启动适配器：初始化所有轨道 + 启动监控循环"""
        if self._running:
            logger.warning("WeChatAdapter already running")
            return

        logger.info("[WeChatAdapter] 正在初始化三轨...")
        self._init_tracks()

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="WeChatAdapter",
            daemon=True,
        )
        self._thread.start()

        mode = self.active_track
        logger.info(f"✅ WeChatAdapter 已启动（活跃轨道: {mode}）")

    def stop(self):
        """停止适配器"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._db_reader.cleanup()
        logger.info("WeChatAdapter 已停止")

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def active_track(self) -> str:
        """当前最优可用轨道"""
        best_name = "none"
        best_score = -1
        for name, ts in self._tracks.items():
            if ts.available and ts.score > best_score:
                best_score = ts.score
                best_name = name
        return best_name

    def get_new_messages(self) -> List[WxMessage]:
        """从最优轨道获取新消息"""
        messages = []

        # 优先 DB 轨道
        if self._tracks["db"].available:
            try:
                since = self._last_db_check or (time.time() - 60)
                msgs = self._db_reader.get_new_messages(since_ts=since)
                self._last_db_check = time.time()
                self._track_success("db")
                messages.extend(msgs)
            except Exception as e:
                self._track_fail("db", str(e))

        # wxauto 轨道（可与 DB 并行，用于补充/验证）
        if self._tracks["wxauto"].available and not messages:
            try:
                msgs = self._wxauto_reader.get_new_messages()
                self._track_success("wxauto")
                messages.extend(msgs)
            except Exception as e:
                self._track_fail("wxauto", str(e))

        # UIA 轨道
        if not messages and self._tracks["uia"].available and self._uia_reader:
            try:
                contact, raw_msgs = self._uia_reader.get_current_chat_messages(last_n=5)
                self._track_success("uia")
                for m in raw_msgs:
                    if not m.get("is_mine", False):
                        messages.append(WxMessage(
                            contact=contact,
                            sender=m.get("sender", ""),
                            content=m.get("content", ""),
                            msg_type=m.get("msg_type", "text"),
                            source="uia",
                        ))
            except Exception as e:
                self._track_fail("uia", str(e))

        # OCR 轨道（最终兜底，截图识别消息）
        if not messages and self._tracks["ocr"].available and self._ocr_reader:
            try:
                contact, raw_msgs = self._ocr_reader.get_current_chat_messages(last_n=5)
                self._track_success("ocr")
                for m in raw_msgs:
                    if not m.get("is_mine", False):
                        messages.append(WxMessage(
                            contact=contact,
                            sender=m.get("sender", ""),
                            content=m.get("content", ""),
                            msg_type=m.get("msg_type", "text"),
                            source="ocr",
                        ))
            except Exception as e:
                self._track_fail("ocr", str(e))

        # 去重
        unique = self._dedup(messages)
        return unique

    def send_message(self, contact: str, text: str) -> bool:
        """
        发送消息。优先 wxauto，降级到 desktop_skills。
        """
        # 优先 wxauto
        if self._tracks["wxauto"].available:
            try:
                ok = self._wxauto_reader.send_message(contact, text)
                if ok:
                    self.stats["sends_success"] += 1
                    return True
            except Exception as e:
                logger.warning(f"wxauto 发送失败: {e}")

        # 降级到 desktop_skills
        if self._desktop:
            try:
                from ..desktop_skills import execute_send_wechat_message
                result = execute_send_wechat_message(self._desktop, contact, text)
                if result.success:
                    self.stats["sends_success"] += 1
                    return True
                else:
                    logger.warning(f"desktop_skills 发送失败: {result.message}")
            except Exception as e:
                logger.warning(f"desktop_skills 发送失败: {e}")

        self.stats["sends_failed"] += 1
        return False

    def add_listen(self, contacts: List[str]) -> int:
        """添加 wxauto 后台监听目标"""
        if self._tracks["wxauto"].available:
            return self._wxauto_reader.add_listen(contacts)
        return 0

    def get_status(self) -> Dict:
        """完整状态信息"""
        return {
            "running": self.is_running,
            "active_track": self.active_track,
            "wechat_running": _wechat_is_running(),
            "tracks": {
                name: {
                    "available": ts.available,
                    "healthy": ts.healthy,
                    "score": round(ts.score, 2),
                    "error": ts.error,
                    "reads": ts.read_count,
                    "fails": ts.fail_count,
                    "success_rate": f"{ts.success_rate:.0%}",
                }
                for name, ts in self._tracks.items()
            },
            "db_info": self._db_reader.get_status(),
            "stats": self.stats,
            "anti_risk": self.anti_risk.get_stats(),
        }

    def manual_scan(self) -> Dict:
        """手动触发一次完整扫描（调试用，不触发回调）"""
        result = {
            "active_track": self.active_track,
            "wechat_running": _wechat_is_running(),
            "tracks": {},
            "messages": [],
        }

        for name, ts in self._tracks.items():
            result["tracks"][name] = {
                "available": ts.available,
                "score": round(ts.score, 2),
            }

        messages = self.get_new_messages()
        result["messages"] = [
            {
                "contact": m.contact,
                "sender": m.sender,
                "content": m.content[:100],
                "is_mine": m.is_mine,
                "msg_type": m.msg_type,
                "source": m.source,
                "timestamp": m.timestamp,
            }
            for m in messages
        ]
        return result

    # ── 轨道初始化 ────────────────────────────────────────────────────────

    def _init_tracks(self):
        """探测并初始化所有轨道"""
        # DB 轨道
        try:
            if self._db_reader.initialize():
                self._tracks["db"].available = True
                self._tracks["db"].healthy = True
                logger.info("✅ 轨道A (DB直读) 就绪")
            else:
                self._tracks["db"].error = "初始化失败"
        except Exception as e:
            self._tracks["db"].error = str(e)
            logger.info(f"轨道A (DB直读) 不可用: {e}")

        # wxauto 轨道
        try:
            if self._wxauto_reader.available and self._wxauto_reader.initialize():
                self._tracks["wxauto"].available = True
                self._tracks["wxauto"].healthy = True
                logger.info("✅ 轨道B (wxauto) 就绪")
            else:
                self._tracks["wxauto"].error = "wxauto 不可用或连接失败"
        except Exception as e:
            self._tracks["wxauto"].error = str(e)
            logger.info(f"轨道B (wxauto) 不可用: {e}")

        # UIA 轨道
        if _legacy_available and self._uia_reader:
            try:
                from ..wechat_monitor import _uia_available
                if _uia_available:
                    self._tracks["uia"].available = True
                    self._tracks["uia"].healthy = True
                    logger.info("✅ 轨道C-UIA 就绪")
            except Exception:
                pass

        # OCR 轨道
        if self._ocr_reader and self._desktop:
            self._tracks["ocr"].available = True
            self._tracks["ocr"].healthy = True
            logger.info("✅ 轨道C-OCR 就绪")

        available = [n for n, t in self._tracks.items() if t.available]
        if not available:
            logger.warning("⚠️ 所有轨道不可用！微信自动化功能将无法工作")
        else:
            logger.info(f"可用轨道: {', '.join(available)}")

    # ── 监控循环 ──────────────────────────────────────────────────────────

    def _monitor_loop(self):
        """后台监控主循环"""
        while self._running:
            try:
                interval = self._get_scan_interval()
                self._scan_cycle()
                time.sleep(interval)
            except Exception as e:
                logger.debug(f"[WeChatAdapter] monitor error: {e}")
                time.sleep(3.0)

    def _scan_cycle(self):
        """执行一次完整的扫描→去重→分发周期"""
        self.stats["scans"] += 1
        self._last_scan_time = time.time()

        messages = self.get_new_messages()

        for msg in messages:
            # 跳过自己发的和系统消息
            if msg.is_mine or msg.msg_type == "system":
                continue

            self.stats["messages_detected"] += 1

            # 分发给所有回调
            for cb in self._callbacks:
                try:
                    cb(msg)
                    self.stats["messages_dispatched"] += 1
                except Exception as e:
                    logger.error(f"Message callback error: {e}")

        # 清理过期指纹
        self._cleanup_fps()

    def _get_scan_interval(self) -> float:
        """根据活跃轨道动态调整扫描间隔"""
        track = self.active_track
        if track == "db":
            return 2.0   # DB 轮询不重，可以频繁
        elif track == "wxauto":
            return 1.5   # wxauto 后台监听，主要是取回消息
        elif track == "uia":
            return 2.0   # UIA 有一定开销
        else:
            return 4.0   # OCR 较慢

    # ── 轨道健康管理 ──────────────────────────────────────────────────────

    def _track_success(self, name: str):
        ts = self._tracks.get(name)
        if ts:
            ts.read_count += 1
            ts.last_success = time.time()
            ts.healthy = True
            ts.error = ""

    def _track_fail(self, name: str, error: str = ""):
        ts = self._tracks.get(name)
        if ts:
            ts.fail_count += 1
            ts.last_fail = time.time()
            ts.error = error
            if ts.success_rate < 0.3 and ts.read_count + ts.fail_count > 5:
                ts.healthy = False

    # ── 去重 ─────────────────────────────────────────────────────────────

    def _dedup(self, messages: List[WxMessage]) -> List[WxMessage]:
        unique = []
        with self._fp_lock:
            for m in messages:
                fp = m.fingerprint()
                if fp not in self._seen_fps:
                    self._seen_fps[fp] = time.time()
                    unique.append(m)
        return unique

    def _cleanup_fps(self):
        now = time.time()
        with self._fp_lock:
            expired = [k for k, t in self._seen_fps.items() if now - t > 120]
            for k in expired:
                del self._seen_fps[k]
