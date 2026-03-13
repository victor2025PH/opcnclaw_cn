"""
Voice-controlled computer operation via OmniParser V2 + LLM vision.

Architecture:
  1. Capture screenshot
  2. Parse UI elements (OmniParser V2 or fallback OCR)
  3. LLM decides action based on user voice command + screen state
  4. Execute action (click, type, scroll, key combo)
  5. Verify result with another screenshot
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class UIElement:
    id: int
    label: str
    bbox: Tuple[int, int, int, int]
    element_type: str = "unknown"
    interactable: bool = True


@dataclass
class ScreenState:
    elements: List[UIElement] = field(default_factory=list)
    foreground_app: str = ""
    screenshot_path: str = ""
    timestamp: float = 0.0


@dataclass
class Action:
    type: str
    target: Optional[UIElement] = None
    text: str = ""
    key: str = ""
    x: int = 0
    y: int = 0


class ScreenCapture:
    """Cross-platform screenshot capture."""

    @staticmethod
    def capture() -> Optional[str]:
        try:
            import mss
            with mss.mss() as sct:
                path = Path("data/screenshots/latest.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                sct.shot(output=str(path))
                return str(path)
        except ImportError:
            logger.debug("mss not installed — trying pyautogui")
        try:
            import pyautogui
            path = Path("data/screenshots/latest.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            pyautogui.screenshot(str(path))
            return str(path)
        except ImportError:
            logger.warning("No screenshot library available")
        return None


class UIParser:
    """Parse screenshot into structured UI elements."""

    def __init__(self):
        self._omniparser = None
        self._ocr = None
        self._init_parser()

    def _init_parser(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            logger.info("UI parser ready (RapidOCR)")
        except ImportError:
            logger.info("RapidOCR not available — UI parsing limited")

    def parse(self, screenshot_path: str) -> List[UIElement]:
        if self._ocr:
            return self._parse_ocr(screenshot_path)
        return []

    def _parse_ocr(self, path: str) -> List[UIElement]:
        try:
            result, _ = self._ocr(path)
            elements = []
            if result:
                for i, (bbox, text, conf) in enumerate(result):
                    if conf < 0.5:
                        continue
                    x1 = int(min(p[0] for p in bbox))
                    y1 = int(min(p[1] for p in bbox))
                    x2 = int(max(p[0] for p in bbox))
                    y2 = int(max(p[1] for p in bbox))
                    elements.append(UIElement(
                        id=i, label=text, bbox=(x1, y1, x2, y2),
                        element_type="text"))
            return elements
        except Exception as e:
            logger.error(f"OCR parse failed: {e}")
            return []


class ActionExecutor:
    """Execute UI actions on the desktop."""

    @staticmethod
    def click(x: int, y: int):
        try:
            import pyautogui
            pyautogui.click(x, y)
            return True
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    @staticmethod
    def type_text(text: str):
        try:
            import pyperclip
            import pyautogui
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            return True
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return False

    @staticmethod
    def hotkey(*keys):
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            logger.error(f"Hotkey failed: {e}")
            return False

    @staticmethod
    def scroll(amount: int):
        try:
            import pyautogui
            pyautogui.scroll(amount)
            return True
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return False


class VisionController:
    """Orchestrates voice-to-action pipeline."""

    def __init__(self):
        self.capture = ScreenCapture()
        self.parser = UIParser()
        self.executor = ActionExecutor()
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def get_screen_state(self) -> Optional[ScreenState]:
        path = self.capture.capture()
        if not path:
            return None
        elements = self.parser.parse(path)
        app = self._get_foreground_app()
        return ScreenState(
            elements=elements, foreground_app=app,
            screenshot_path=path, timestamp=time.time())

    def execute_action(self, action: Action) -> bool:
        if not self._enabled:
            logger.warning("Vision control is disabled")
            return False

        if action.type == "click":
            if action.target:
                cx = (action.target.bbox[0] + action.target.bbox[2]) // 2
                cy = (action.target.bbox[1] + action.target.bbox[3]) // 2
                return self.executor.click(cx, cy)
            return self.executor.click(action.x, action.y)

        if action.type == "type":
            return self.executor.type_text(action.text)

        if action.type == "hotkey":
            keys = action.key.split("+")
            return self.executor.hotkey(*keys)

        if action.type == "scroll":
            return self.executor.scroll(int(action.text) if action.text else -3)

        logger.warning(f"Unknown action type: {action.type}")
        return False

    def describe_screen(self) -> str:
        state = self.get_screen_state()
        if not state:
            return "无法获取屏幕状态"

        lines = [f"当前应用: {state.foreground_app}"]
        lines.append(f"检测到 {len(state.elements)} 个界面元素:")
        for el in state.elements[:20]:
            lines.append(
                f"  [{el.id}] \"{el.label}\" "
                f"({el.bbox[0]},{el.bbox[1]})-"
                f"({el.bbox[2]},{el.bbox[3]})")
        return "\n".join(lines)

    def _get_foreground_app(self) -> str:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            return buf.value
        except Exception:
            return ""
