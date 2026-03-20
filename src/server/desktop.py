"""Remote desktop streaming, OCR, and AI-driven control via WebSocket."""

from __future__ import annotations

import base64
import io
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from PIL import Image as _ImageType

# 桌面控制依赖（仅 Windows/Mac 可用，CI/Linux 无头环境延迟导入）
try:
    import mss
    import pyautogui
    import pyperclip
    from PIL import Image
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.0
    _DESKTOP_AVAILABLE = True
except ImportError as _e:
    _DESKTOP_AVAILABLE = False
    mss = None  # type: ignore
    pyautogui = None  # type: ignore
    pyperclip = None  # type: ignore
    Image = None  # type: ignore
    logger.debug(f"Desktop modules not available: {_e}")


class DesktopStreamer:
    """Captures the screen, runs OCR, and executes mouse/keyboard commands."""

    # OCR 缓存 TTL（秒）：屏幕内容在短时间内不会变化
    OCR_CACHE_TTL = 3.0

    def __init__(self, max_width: int = 1280, quality: int = 45, fps: int = 10):
        self.max_width = max_width
        self.quality = quality
        self.fps = fps
        self._screen_w, self._screen_h = pyautogui.size()
        self._ocr = None
        self._monitor_idx = 1
        self._cursor_nx = 0.5
        self._cursor_ny = 0.5
        # OCR 缓存
        self._ocr_cache: list[dict] = []
        self._ocr_cache_ts: float = 0.0
        logger.info(f"Desktop streamer ready — screen {self._screen_w}x{self._screen_h}")

    @property
    def screen_size(self):
        return self._screen_w, self._screen_h

    # ── OCR ──

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            logger.info("RapidOCR engine loaded")
        return self._ocr

    def _capture_raw(self) -> Image.Image:
        """Capture screenshot from the active monitor as PIL Image."""
        with mss.mss() as sct:
            idx = min(self._monitor_idx, len(sct.monitors) - 1)
            raw = sct.grab(sct.monitors[idx])
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def ocr_screen(self, force: bool = False) -> list[dict]:
        """Capture screen + OCR → list of {text, x, y, score}.
        x, y are normalized center coordinates (0~1).

        使用 TTL 缓存（默认 3 秒）避免重复 OCR。
        force=True 强制刷新缓存。
        """
        now = time.time()
        if not force and self._ocr_cache and (now - self._ocr_cache_ts) < self.OCR_CACHE_TTL:
            return self._ocr_cache

        img = self._capture_raw()
        img_np = np.array(img)
        ocr = self._get_ocr()

        result, _ = ocr(img_np)
        if not result:
            self._ocr_cache = []
            self._ocr_cache_ts = now
            return []

        sw, sh = img.width, img.height
        items = []
        for line in result:
            bbox, text, score = line
            score_f = float(score) if not isinstance(score, float) else score
            if score_f < 0.4 or not text.strip():
                continue
            x1, y1 = bbox[0]
            x3, y3 = bbox[2]
            cx = ((x1 + x3) / 2) / sw
            cy = ((y1 + y3) / 2) / sh
            items.append({
                "text": text.strip(),
                "x": round(cx, 4),
                "y": round(cy, 4),
                "score": round(score_f, 2),
            })

        self._ocr_cache = items
        self._ocr_cache_ts = now
        return items

    def invalidate_ocr_cache(self):
        """用户操作（点击/输入）后调用，使 OCR 缓存立即失效"""
        self._ocr_cache_ts = 0.0

    def find_text(self, target: str) -> Optional[dict]:
        """Find text containing `target` on screen, return best match with coords."""
        items = self.ocr_screen()
        exact = [i for i in items if i["text"] == target]
        if exact:
            return max(exact, key=lambda i: i["score"])
        partial = [i for i in items if target in i["text"]]
        if partial:
            return max(partial, key=lambda i: i["score"])
        return None

    def capture_screenshot_b64(self) -> str:
        """Capture a JPEG screenshot and return as base64 string."""
        img = self._capture_raw()
        if img.width > self.max_width:
            ratio = self.max_width / img.width
            img = img.resize((self.max_width, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()

    # ── Frame streaming ──

    def capture_frame(self) -> tuple[str, int, int]:
        """Capture primary monitor → (base64_jpeg, width, height)."""
        img = self._capture_raw()
        if img.width > self.max_width:
            ratio = self.max_width / img.width
            img = img.resize((self.max_width, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.quality)
        return base64.b64encode(buf.getvalue()).decode(), img.width, img.height

    def _resize(self, img: Image.Image) -> Image.Image:
        if img.width > self.max_width:
            r = self.max_width / img.width
            img = img.resize((self.max_width, int(img.height * r)), Image.LANCZOS)
        return img

    def _jpg_b64(self, img: Image.Image, quality: int | None = None) -> str:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality or self.quality)
        return base64.b64encode(buf.getvalue()).decode()

    def _jpg_bytes(self, img: Image.Image, quality: int | None = None) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality or self.quality)
        return buf.getvalue()

    def capture_frame_binary(
        self, prev_np: "np.ndarray | None" = None, force_key: bool = False,
    ) -> "tuple[bytes | None, dict, np.ndarray]":
        """Binary-optimized capture: returns (jpeg_bytes, header_dict, frame_np).

        jpeg_bytes is raw JPEG (no base64). header_dict has metadata only.
        If mode=='skip', jpeg_bytes is None.
        """
        img = self._resize(self._capture_raw())
        frame_np = np.array(img)
        h, w = frame_np.shape[:2]
        sw, sh = self._screen_w, self._screen_h

        if prev_np is None or force_key or prev_np.shape != frame_np.shape:
            return (
                self._jpg_bytes(img),
                {"m": "k", "w": w, "h": h, "sw": sw, "sh": sh},
                frame_np,
            )

        diff = np.any(
            np.abs(frame_np.astype(np.int16) - prev_np.astype(np.int16))
            > self._DELTA_NOISE,
            axis=2,
        )
        if not np.any(diff):
            return None, {"m": "s"}, prev_np

        B = self._DELTA_BLOCK
        changed = []
        for by in range(0, h, B):
            for bx in range(0, w, B):
                bh, bw = min(B, h - by), min(B, w - bx)
                if np.any(diff[by : by + bh, bx : bx + bw]):
                    changed.append((bx, by, bw, bh))

        if not changed:
            return None, {"m": "s"}, prev_np

        total_blocks = ((h + B - 1) // B) * ((w + B - 1) // B)
        if len(changed) > total_blocks * 0.45:
            return (
                self._jpg_bytes(img),
                {"m": "k", "w": w, "h": h, "sw": sw, "sh": sh},
                frame_np,
            )

        x1 = min(b[0] for b in changed)
        y1 = min(b[1] for b in changed)
        x2 = max(b[0] + b[2] for b in changed)
        y2 = max(b[1] + b[3] for b in changed)

        crop = img.crop((x1, y1, x2, y2))
        cx, cy = self._cursor_nx * w, self._cursor_ny * h
        near_cursor = x1 <= cx <= x2 and y1 <= cy <= y2
        q = min(self.quality + (20 if near_cursor else 8), 88)

        return (
            self._jpg_bytes(crop, q),
            {"m": "d", "x": x1, "y": y1, "dw": x2 - x1, "dh": y2 - y1, "w": w, "h": h},
            frame_np,
        )

    _DELTA_BLOCK = 64
    _DELTA_NOISE = 10

    def capture_frame_delta(
        self, prev_np: np.ndarray | None = None, force_key: bool = False,
    ) -> tuple[dict, np.ndarray]:
        """Delta-compressed capture with block-based diff and noise tolerance.

        Returns (msg_dict, frame_numpy).
        msg_dict has key 'mode': 'key' | 'delta' | 'skip'.
        Caller must store frame_numpy for next call's prev_np.
        """
        img = self._resize(self._capture_raw())
        frame_np = np.array(img)
        h, w = frame_np.shape[:2]
        sw, sh = self._screen_w, self._screen_h

        if prev_np is None or force_key or prev_np.shape != frame_np.shape:
            return {
                "type": "frame", "mode": "key",
                "data": self._jpg_b64(img), "w": w, "h": h,
                "sw": sw, "sh": sh,
            }, frame_np

        diff = np.any(
            np.abs(frame_np.astype(np.int16) - prev_np.astype(np.int16))
            > self._DELTA_NOISE,
            axis=2,
        )

        if not np.any(diff):
            return {"type": "frame", "mode": "skip"}, prev_np

        B = self._DELTA_BLOCK
        changed = []
        for by in range(0, h, B):
            for bx in range(0, w, B):
                bh, bw = min(B, h - by), min(B, w - bx)
                if np.any(diff[by : by + bh, bx : bx + bw]):
                    changed.append((bx, by, bw, bh))

        if not changed:
            return {"type": "frame", "mode": "skip"}, prev_np

        total_blocks = ((h + B - 1) // B) * ((w + B - 1) // B)

        if len(changed) > total_blocks * 0.45:
            return {
                "type": "frame", "mode": "key",
                "data": self._jpg_b64(img), "w": w, "h": h,
                "sw": sw, "sh": sh,
            }, frame_np

        x1 = min(b[0] for b in changed)
        y1 = min(b[1] for b in changed)
        x2 = max(b[0] + b[2] for b in changed)
        y2 = max(b[1] + b[3] for b in changed)

        crop = img.crop((x1, y1, x2, y2))
        cx, cy = self._cursor_nx * w, self._cursor_ny * h
        near_cursor = x1 <= cx <= x2 and y1 <= cy <= y2
        q = min(self.quality + (20 if near_cursor else 8), 88)

        return {
            "type": "frame", "mode": "delta",
            "data": self._jpg_b64(crop, q),
            "x": x1, "y": y1, "dw": x2 - x1, "dh": y2 - y1,
            "w": w, "h": h, "bc": len(changed),
        }, frame_np

    # ── Mouse ──

    def _abs(self, nx: float, ny: float):
        return int(nx * self._screen_w), int(ny * self._screen_h)

    def mouse_move(self, nx: float, ny: float):
        x, y = self._abs(nx, ny)
        pyautogui.moveTo(x, y, _pause=False)

    def mouse_click(self, nx: float, ny: float, button: str = "left"):
        x, y = self._abs(nx, ny)
        pyautogui.click(x, y, button=button, _pause=False)

    def mouse_double_click(self, nx: float, ny: float):
        x, y = self._abs(nx, ny)
        pyautogui.doubleClick(x, y, _pause=False)

    def mouse_scroll(self, dy: int):
        pyautogui.scroll(dy, _pause=False)

    def mouse_down(self, nx: float, ny: float, button: str = "left"):
        x, y = self._abs(nx, ny)
        pyautogui.moveTo(x, y, _pause=False)
        pyautogui.mouseDown(button=button, _pause=False)

    def mouse_up(self, button: str = "left"):
        pyautogui.mouseUp(button=button, _pause=False)

    def mouse_drag(self, nx1: float, ny1: float, nx2: float, ny2: float):
        x1, y1 = self._abs(nx1, ny1)
        x2, y2 = self._abs(nx2, ny2)
        pyautogui.moveTo(x1, y1, _pause=False)
        pyautogui.drag(x2 - x1, y2 - y1, duration=0.15, _pause=False)

    # ── Keyboard ──

    def key_press(self, key: str):
        pyautogui.press(key, _pause=False)

    _MEDIA_VK = {
        'play_pause': 0xB3, 'volume_mute': 0xAD,
        'volume_down': 0xAE, 'volume_up': 0xAF,
        'next_track': 0xB0, 'prev_track': 0xB1, 'stop_media': 0xB2,
    }

    def hotkey(self, keys: list[str]):
        if len(keys) == 1 and keys[0] in self._MEDIA_VK:
            import ctypes
            vk = self._MEDIA_VK[keys[0]]
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            return
        pyautogui.hotkey(*keys, _pause=False)

    def type_text(self, text: str):
        pyautogui.write(text, interval=0.02)

    def type_chinese(self, text: str):
        """Type text via clipboard paste (works for CJK characters)."""
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v", _pause=False)
        time.sleep(0.1)

    # ── Screenshot saving ──

    def save_screenshot(self, filepath: Optional[str] = None) -> str:
        """Save a full-resolution screenshot to disk. Returns the saved file path."""
        img = self._capture_raw()
        if not filepath:
            screenshots_dir = Path("data/screenshots")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(screenshots_dir / f"screenshot_{ts}.png")
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        img.save(filepath, format="PNG")
        logger.info(f"Screenshot saved: {filepath} ({img.width}x{img.height})")
        return filepath

    # ── Window management ──

    def get_window_list(self) -> list[dict]:
        """List all visible windows with title and hwnd (Windows only)."""
        windows = []
        if sys.platform != "win32":
            return windows
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def enum_cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title:
                windows.append({"hwnd": hwnd, "title": title})
            return True

        user32.EnumWindows(enum_cb, 0)
        return windows

    def focus_window(self, title_contains: str) -> bool:
        """Find and focus a window by partial title match."""
        if sys.platform != "win32":
            return False
        import ctypes
        user32 = ctypes.windll.user32
        windows = self.get_window_list()
        lower_target = title_contains.lower()
        for w in windows:
            if lower_target in w["title"].lower():
                hwnd = w["hwnd"]
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    time.sleep(0.3)
                user32.SetForegroundWindow(hwnd)
                logger.info(f"Focused window: {w['title']}")
                return True
        return False

    def minimize_all(self):
        """Minimize all windows (show desktop)."""
        pyautogui.hotkey("win", "d", _pause=False)

    def switch_window(self):
        """Switch to next window (Alt+Tab)."""
        pyautogui.hotkey("alt", "tab", _pause=False)

    def close_window(self):
        """Close the current foreground window."""
        pyautogui.hotkey("alt", "F4", _pause=False)

    def ocr_region(self, x1: float, y1: float, x2: float, y2: float) -> list[dict]:
        """OCR a specific region of the screen (normalized coords 0~1)."""
        img = self._capture_raw()
        w, h = img.width, img.height
        left = int(x1 * w)
        top = int(y1 * h)
        right = int(x2 * w)
        bottom = int(y2 * h)
        cropped = img.crop((left, top, right, bottom))
        img_np = np.array(cropped)
        ocr = self._get_ocr()
        result, _ = ocr(img_np)
        if not result:
            return []

        cw, ch = cropped.width, cropped.height
        items = []
        for line in result:
            bbox, text, score = line
            score_f = float(score) if not isinstance(score, float) else score
            if score_f < 0.4 or not text.strip():
                continue
            bx1, by1 = bbox[0]
            bx3, by3 = bbox[2]
            cx = x1 + ((bx1 + bx3) / 2) / w
            cy = y1 + ((by1 + by3) / 2) / h
            items.append({
                "text": text.strip(),
                "x": round(cx, 4),
                "y": round(cy, 4),
                "score": round(score_f, 2),
            })
        return items

    # ── AI Action Executor ──

    def execute_actions(self, actions: list[dict]) -> list[str]:
        """Execute a list of AI-planned actions. Returns execution log lines."""
        # CoworkBus 冲突检测
        try:
            from .cowork_bus import get_bus
            bus = get_bus()
            if not bus.can_operate_desktop():
                return ["[BLOCKED] 用户正在操作，AI 桌面操作已暂停"]
        except Exception:
            pass

        self.invalidate_ocr_cache()
        # 操作日志
        try:
            from .action_journal import get_journal
            journal = get_journal()
        except Exception:
            journal = None

        log = []
        for i, act in enumerate(actions[:15]):
            a = act.get("action", "")

            # 记录到 Journal
            entry_id = None
            if journal:
                try:
                    entry = journal.record(a, act)
                    entry_id = entry.id
                except Exception:
                    pass

            try:
                if a == "click":
                    self.mouse_click(act["x"], act["y"], act.get("button", "left"))
                    log.append(f"[{i+1}] click ({act['x']:.2f}, {act['y']:.2f})")

                elif a == "double_click":
                    self.mouse_double_click(act["x"], act["y"])
                    log.append(f"[{i+1}] double_click ({act['x']:.2f}, {act['y']:.2f})")

                elif a == "type":
                    text = act.get("text", "")
                    has_cjk = any("\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" for c in text)
                    if has_cjk:
                        self.type_chinese(text)
                    else:
                        self.type_text(text)
                    log.append(f"[{i+1}] type \"{text[:30]}\"")

                elif a == "key":
                    self.key_press(act["key"])
                    log.append(f"[{i+1}] key {act['key']}")

                elif a == "hotkey":
                    self.hotkey(act["keys"])
                    log.append(f"[{i+1}] hotkey {'+'.join(act['keys'])}")

                elif a == "scroll":
                    self.mouse_scroll(act.get("dy", 0))
                    log.append(f"[{i+1}] scroll dy={act.get('dy', 0)}")

                elif a == "wait":
                    ms = min(act.get("ms", 500), 5000)
                    time.sleep(ms / 1000)
                    log.append(f"[{i+1}] wait {ms}ms")

                elif a == "find_and_click":
                    target = act.get("text", "")
                    found = self.find_text(target)
                    if found:
                        self.mouse_click(found["x"], found["y"], act.get("button", "left"))
                        log.append(f"[{i+1}] find_and_click \"{target}\" → ({found['x']:.2f}, {found['y']:.2f})")
                    else:
                        log.append(f"[{i+1}] find_and_click \"{target}\" → NOT FOUND")

                elif a == "find_and_double_click":
                    target = act.get("text", "")
                    found = self.find_text(target)
                    if found:
                        self.mouse_double_click(found["x"], found["y"])
                        log.append(f"[{i+1}] find_and_double_click \"{target}\" → ({found['x']:.2f}, {found['y']:.2f})")
                    else:
                        log.append(f"[{i+1}] find_and_double_click \"{target}\" → NOT FOUND")

                elif a == "screenshot":
                    path = self.save_screenshot(act.get("path"))
                    log.append(f"[{i+1}] screenshot → {path}")

                elif a == "focus_window":
                    title = act.get("title", "")
                    ok = self.focus_window(title)
                    log.append(f"[{i+1}] focus_window \"{title}\" → {'OK' if ok else 'NOT FOUND'}")

                elif a == "minimize_all":
                    self.minimize_all()
                    log.append(f"[{i+1}] minimize_all")

                elif a == "close_window":
                    self.close_window()
                    log.append(f"[{i+1}] close_window")

                elif a == "find_and_type":
                    target = act.get("target", "")
                    text = act.get("text", "")
                    found = self.find_text(target)
                    if found:
                        self.mouse_click(found["x"], found["y"])
                        time.sleep(0.3)
                        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
                        if has_cjk:
                            self.type_chinese(text)
                        else:
                            self.type_text(text)
                        log.append(f"[{i+1}] find_and_type \"{target}\" → \"{text[:20]}\"")
                    else:
                        log.append(f"[{i+1}] find_and_type \"{target}\" → NOT FOUND")

                else:
                    log.append(f"[{i+1}] unknown action: {a}")

            except Exception as e:
                log.append(f"[{i+1}] ERROR {a}: {e}")

            # Journal: 操作后截图
            if journal and entry_id:
                try:
                    journal.record_after(entry_id)
                except Exception:
                    pass

        return log

    # ── Z1: Enhanced Remote Control ──

    def get_system_info(self) -> dict:
        import psutil
        cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:\\") + "\\" if sys.platform == "win32" else "/")
        net = psutil.net_io_counters()
        bat = psutil.sensors_battery()
        return {
            "cpu": cpu,
            "mem_used": mem.used // (1024 * 1024),
            "mem_total": mem.total // (1024 * 1024),
            "mem_pct": mem.percent,
            "disk_used": disk.used // (1024 ** 3),
            "disk_total": disk.total // (1024 ** 3),
            "disk_pct": round(disk.percent, 1),
            "net_sent": net.bytes_sent // (1024 * 1024),
            "net_recv": net.bytes_recv // (1024 * 1024),
            "battery": bat.percent if bat else -1,
            "plugged": bat.power_plugged if bat else True,
            "fg_app": self.get_foreground_app(),
        }

    def get_clipboard_text(self) -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def set_clipboard_text(self, text: str):
        try:
            pyperclip.copy(text)
        except Exception as e:
            logger.warning(f"Clipboard write failed: {e}")

    def list_files(self, path_str: str) -> tuple[str, list]:
        p = Path(os.path.expanduser(path_str)).resolve()
        if not p.exists() or not p.is_dir():
            return str(p), []
        entries = []
        try:
            for f in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    st = f.stat()
                    entries.append({
                        "name": f.name,
                        "dir": f.is_dir(),
                        "size": st.st_size if f.is_file() else 0,
                        "ts": int(st.st_mtime * 1000),
                    })
                except (PermissionError, OSError):
                    pass
        except PermissionError:
            pass
        return str(p), entries[:300]

    def open_file(self, path_str: str):
        import subprocess
        p = Path(path_str)
        if not p.exists():
            return
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])

    def get_processes(self, top_n: int = 25) -> list:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                if (info["cpu_percent"] or 0) > 0 or (info["memory_percent"] or 0) > 0.1:
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"] or "?",
                        "cpu": round(info["cpu_percent"] or 0, 1),
                        "mem": round(info["memory_percent"] or 0, 1),
                    })
            except Exception:
                pass
        procs.sort(key=lambda x: x["cpu"] + x["mem"] * 2, reverse=True)
        return procs[:top_n]

    def kill_process(self, pid: int) -> bool:
        import psutil
        try:
            psutil.Process(pid).terminate()
            return True
        except Exception:
            return False

    # ── Q1: OCR at pointer ──

    def ocr_at_point(self, nx: float, ny: float, radius: float = 0.08) -> list[dict]:
        """OCR a small region centered at normalized (nx, ny)."""
        x1, y1 = max(0.0, nx - radius), max(0.0, ny - radius)
        x2, y2 = min(1.0, nx + radius), min(1.0, ny + radius)
        try:
            return self.ocr_region(x1, y1, x2, y2)
        except Exception as e:
            logger.warning(f"OCR at point failed: {e}")
            return []

    # ── Q2: Multi-monitor + foreground app ──

    def get_monitors(self) -> list[dict]:
        with mss.mss() as sct:
            result = []
            for i, m in enumerate(sct.monitors):
                if i == 0:
                    continue
                result.append({
                    "index": i,
                    "width": m["width"], "height": m["height"],
                    "left": m["left"], "top": m["top"],
                    "active": i == self._monitor_idx,
                })
            return result

    def set_monitor(self, index: int):
        with mss.mss() as sct:
            if 0 < index < len(sct.monitors):
                m = sct.monitors[index]
                self._monitor_idx = index
                self._screen_w = m["width"]
                self._screen_h = m["height"]
                logger.info(f"Monitor switched to {index}: {m['width']}x{m['height']}")
                return True
        return False

    def get_foreground_app(self) -> str:
        if sys.platform != "win32":
            return ""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value.strip()
        except Exception:
            return ""

    # ── Command dispatcher (WebSocket) ──

    def handle_command(self, msg: dict):
        """Process a control command from the client."""
        t = msg.get("type", "")
        try:
            if t == "mouse_move":
                self.mouse_move(msg["x"], msg["y"])
            elif t == "mouse_click":
                self.mouse_click(msg["x"], msg["y"], msg.get("button", "left"))
            elif t == "mouse_dblclick":
                self.mouse_double_click(msg["x"], msg["y"])
            elif t == "mouse_scroll":
                self.mouse_scroll(msg.get("dy", 0))
            elif t == "mouse_down":
                self.mouse_down(msg.get("x", 0.5), msg.get("y", 0.5), msg.get("button", "left"))
            elif t == "mouse_up":
                self.mouse_up(msg.get("button", "left"))
            elif t == "mouse_drag":
                self.mouse_drag(msg["x1"], msg["y1"], msg["x2"], msg["y2"])
            elif t == "key":
                self.key_press(msg["key"])
            elif t == "hotkey":
                self.hotkey(msg["keys"])
            elif t == "type":
                self.type_text(msg["text"])
            elif t == "set_fps":
                self.fps = max(1, min(30, int(msg["fps"])))
            elif t == "set_quality":
                self.quality = max(10, min(95, int(msg["quality"])))
            elif t == "scroll":
                self.mouse_scroll(msg.get("dy", 0))
            elif t == "shell":
                import subprocess
                cmd = msg.get("command", "")
                if cmd:
                    subprocess.Popen(cmd, shell=True, creationflags=0x08)
        except Exception as e:
            logger.warning(f"Desktop command error ({t}): {e}")
