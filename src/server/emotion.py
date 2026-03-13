"""
Emotion-aware conversation engine.

Bridges STT emotion detection with AI prompt injection and TTS emotion synthesis,
creating a full empathic loop: detect -> adapt -> express.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from loguru import logger


@dataclass
class EmotionState:
    current: str = "neutral"
    confidence: float = 0.0
    history: List[str] = None
    events: List[str] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []
        if self.events is None:
            self.events = []

    def update(self, emotion: str, events: Optional[List[str]] = None):
        if emotion and emotion != "neutral":
            self.history.append(emotion)
            if len(self.history) > 10:
                self.history = self.history[-10:]
        self.current = emotion or "neutral"
        self.events = events or []

    @property
    def dominant(self) -> str:
        if not self.history:
            return self.current
        from collections import Counter
        recent = self.history[-5:]
        counts = Counter(recent)
        top = counts.most_common(1)[0]
        if top[1] >= 2:
            return top[0]
        return self.current


_PROMPT_INJECTION: Dict[str, str] = {
    "happy": (
        "用户当前心情愉悦。你可以用轻松愉快的语气回应，"
        "适当加入幽默或鼓励的元素。"
    ),
    "sad": (
        "用户当前情绪低落。请用温暖关怀的语气回复，"
        "表达理解和同理心，避免说教，给予温柔的陪伴感。"
    ),
    "angry": (
        "用户当前情绪激动。请用冷静、理性、专业的语气回复，"
        "先表示理解，不要争辩，帮助用户解决实际问题。"
    ),
    "surprised": (
        "用户表现出惊讶。简洁明了地回应，提供清晰的信息。"
    ),
    "fearful": (
        "用户似乎有些紧张或担忧。请用平和安抚的语气回应，"
        "提供确定性的信息，帮助缓解焦虑。"
    ),
    "neutral": "",
}

_TTS_EMOTION_MAP: Dict[str, str] = {
    "happy": "cheerful",
    "sad": "gentle",
    "angry": "calm",
    "surprised": "neutral",
    "fearful": "gentle",
    "neutral": "neutral",
}

_EVENT_RESPONSES: Dict[str, str] = {
    "laughter": "听起来你心情不错！",
    "cry": "别难过，我在这里陪你。",
    "applause": "太棒了！",
    "cough": "注意身体，多喝水。",
    "sneeze": "注意保暖哦。",
}


class EmotionEngine:
    """Stateful emotion processor that adapts AI behavior."""

    def __init__(self):
        self._state = EmotionState()
        self._enabled = True

    @property
    def state(self) -> EmotionState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def process_stt_result(self, emotion: str,
                           events: Optional[List[str]] = None):
        if not self._enabled:
            return
        self._state.update(emotion, events)
        if emotion != "neutral":
            logger.debug(f"Emotion detected: {emotion} | events: {events}")

    def get_system_prompt_addon(self) -> str:
        if not self._enabled:
            return ""
        emo = self._state.dominant
        return _PROMPT_INJECTION.get(emo, "")

    def get_tts_emotion(self) -> str:
        if not self._enabled:
            return "neutral"
        return _TTS_EMOTION_MAP.get(self._state.dominant, "neutral")

    def get_event_response(self) -> Optional[str]:
        if not self._enabled or not self._state.events:
            return None
        for ev in self._state.events:
            if ev in _EVENT_RESPONSES:
                return _EVENT_RESPONSES[ev]
        return None

    def build_messages(
        self,
        base_system: str,
        user_text: str,
        history: Optional[List[dict]] = None,
    ) -> List[dict]:
        addon = self.get_system_prompt_addon()
        system_content = base_system
        if addon:
            system_content = f"{base_system}\n\n【情感提示】{addon}"

        messages = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages
