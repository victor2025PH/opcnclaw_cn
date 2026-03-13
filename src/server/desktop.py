"""Remote desktop streaming, OCR, and AI-driven control via WebSocket."""

import base64
import io
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import mss
import numpy as np
import pyautogui
import pyperclip
from PIL import Image
from loguru import logger

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0


class DesktopStreamer:
    """Captures the screen, runs OCR, and executes mouse/keyboard commands."""

    def __init__(self, max_width: int = 1280, quality: int = 45, fps: int = 10):
        self.max_width = max_width
        self.quality = quality
        self.fps = fps
        self._screen_w, self._screen_h = pyautogui.size()
        self._ocr = None
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
        """Capture full-resolution screenshot as PIL Image."""
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def ocr_screen(self) -> list[dict]:
        """Capture screen + OCR → list of {text, x, y, score}.
        x, y are normalized center coordinates (0~1)."""
        img = self._capture_raw()
        img_np = np.array(img)
        ocr = self._get_ocr()

        result, _ = ocr(img_np)
        if not result:
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
        return items

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

    def hotkey(self, keys: list[str]):
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
        log = []
        for i, act in enumerate(actions[:15]):  # safety limit
            a = act.get("action", "")
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

        return log

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
        except Exception as e:
            logger.warning(f"Desktop command error ({t}): {e}")
