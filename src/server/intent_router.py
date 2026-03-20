"""
Intent Router — Server-side intent resolution and dispatch.

Receives fused intents from the frontend IntentFusionEngine,
resolves ambiguous intents using context (screen OCR, history),
and dispatches to the appropriate handler (desktop control, AI, skills).

Architecture:
  [Frontend IntentFusionEngine]
       │ POST /api/intent
       ▼
  [IntentRouter.route()]
       │
       ├─ Direct desktop action  → DesktopStreamer
       ├─ Skill execution        → desktop_skills
       ├─ AI disambiguation      → AIBackend
       └─ Workflow trigger        → WorkflowRecorder
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from enum import Enum
from loguru import logger


class IntentCategory(str, Enum):
    DESKTOP_DIRECT = "desktop_direct"
    SKILL = "skill"
    AI_ROUTE = "ai_route"
    WORKFLOW = "workflow"
    AMBIGUOUS = "ambiguous"


@dataclass
class IntentResult:
    category: IntentCategory
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: str = ""
    context_used: bool = False

    def to_dict(self):
        d = asdict(self)
        d["category"] = self.category.value
        return d


# Actions that map directly to desktop commands
DESKTOP_DIRECT_MAP = {
    "click":         {"type": "mouse_click", "button": "left"},
    "right_click":   {"type": "mouse_click", "button": "right"},
    "double_click":  {"type": "mouse_dblclick"},
    "scroll_up":     {"type": "mouse_scroll", "dy": 5},
    "scroll_down":   {"type": "mouse_scroll", "dy": -5},
    "enter":         {"type": "hotkey", "keys": ["enter"]},
    "undo":          {"type": "hotkey", "keys": ["ctrl", "z"]},
    "redo":          {"type": "hotkey", "keys": ["ctrl", "y"]},
    "copy":          {"type": "hotkey", "keys": ["ctrl", "c"]},
    "paste":         {"type": "hotkey", "keys": ["ctrl", "v"]},
    "cut":           {"type": "hotkey", "keys": ["ctrl", "x"]},
    "screenshot":    {"type": "screenshot"},
    "switch_app":    {"type": "hotkey", "keys": ["alt", "tab"]},
    "close_window":  {"type": "hotkey", "keys": ["alt", "F4"]},
    "minimize":      {"type": "hotkey", "keys": ["win", "d"]},
    "show_desktop":  {"type": "hotkey", "keys": ["win", "d"]},
    "confirm":       {"type": "hotkey", "keys": ["enter"]},
    "cancel":        {"type": "hotkey", "keys": ["escape"]},
}

# Actions that should be handled by skills
SKILL_MAP = {
    "open_wechat":  "open_wechat",
    "open_browser": "open_browser",
    "open_notepad": "open_notepad",
    "lock_screen":  "lock_screen",
}


class IntentHistory:
    """Sliding window of recent intents for pattern detection."""

    def __init__(self, max_size: int = 50):
        self._history: List[Dict] = []
        self._max_size = max_size

    def push(self, intent: IntentResult):
        self._history.append({
            **intent.to_dict(),
            "timestamp": time.time(),
        })
        if len(self._history) > self._max_size:
            self._history = self._history[-self._max_size:]

    def recent(self, n: int = 5) -> List[Dict]:
        return self._history[-n:]

    def find_pattern(self, actions: List[str]) -> bool:
        """Check if the given action sequence appears in recent history."""
        recent_actions = [h["action"] for h in self._history[-len(actions) * 2:]]
        pattern_str = ",".join(actions)
        history_str = ",".join(recent_actions)
        return pattern_str in history_str

    def action_frequency(self, action: str, window_s: float = 60.0) -> int:
        cutoff = time.time() - window_s
        return sum(1 for h in self._history
                   if h["action"] == action and h["timestamp"] > cutoff)


class IntentRouter:
    """Routes fused intents to the appropriate handler."""

    def __init__(self):
        self.history = IntentHistory()
        self._context_cache: Dict[str, Any] = {}
        self._screen_text: Optional[str] = None
        self._screen_text_time: float = 0

    def route(self, action: str, params: Dict[str, Any],
              source: str = "", confidence: float = 1.0) -> IntentResult:
        """
        Resolve an intent to a concrete action category.

        Returns IntentResult with category indicating how to handle it.
        """
        # 1. Direct desktop action
        if action in DESKTOP_DIRECT_MAP:
            cmd = dict(DESKTOP_DIRECT_MAP[action])

            # Inject spatial coordinates if provided
            if "x" in params and "y" in params:
                cmd["x"] = params["x"]
                cmd["y"] = params["y"]

            result = IntentResult(
                category=IntentCategory.DESKTOP_DIRECT,
                action=action,
                params=cmd,
                confidence=confidence,
                source=source,
            )
            self.history.push(result)
            return result

        # 2. Skill execution
        if action in SKILL_MAP:
            result = IntentResult(
                category=IntentCategory.SKILL,
                action=action,
                params={"skill_id": SKILL_MAP[action]},
                confidence=confidence,
                source=source,
            )
            self.history.push(result)
            return result

        # 3. AI routing (complex or unknown intents)
        if action == "ai_route" or confidence < 0.5:
            result = IntentResult(
                category=IntentCategory.AI_ROUTE,
                action=action,
                params=params,
                confidence=confidence,
                source=source,
            )
            self.history.push(result)
            return result

        # 4. Workflow trigger
        if action.startswith("workflow:"):
            result = IntentResult(
                category=IntentCategory.WORKFLOW,
                action=action,
                params=params,
                confidence=confidence,
                source=source,
            )
            self.history.push(result)
            return result

        # 5. Fallback: treat as desktop direct if it looks like one
        result = IntentResult(
            category=IntentCategory.AMBIGUOUS,
            action=action,
            params=params,
            confidence=confidence,
            source=source,
        )
        self.history.push(result)
        return result

    def update_screen_context(self, text: str):
        """Update cached screen OCR text for context-aware resolution."""
        self._screen_text = text
        self._screen_text_time = time.time()

    def get_context(self) -> Dict[str, Any]:
        return {
            "screen_text": self._screen_text if (
                time.time() - self._screen_text_time < 30
            ) else None,
            "recent_intents": self.history.recent(5),
            "frequent_actions": self._top_frequent_actions(),
        }

    def _top_frequent_actions(self, n: int = 5) -> List[Dict]:
        from collections import Counter
        counts = Counter(h["action"] for h in self.history._history[-50:])
        return [{"action": a, "count": c} for a, c in counts.most_common(n)]


# Singleton
_router: Optional[IntentRouter] = None

def get_intent_router() -> IntentRouter:
    global _router
    if _router is None:
        _router = IntentRouter()
    return _router
