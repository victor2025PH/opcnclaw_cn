"""
Local voice command engine — zero network dependency.

Uses jieba tokenization + keyword matching to recognize predefined commands.
Latency: <100ms on any hardware. No LLM, no API calls.

Usage:
    engine = LocalVoiceCommandEngine()
    result = engine.match("帮我打开微信")
    # → {"action": "skill", "skill_id": "open_wechat", "matched": "打开微信", "confidence": 0.95}
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

try:
    import jieba
    jieba.setLogLevel(20)  # suppress jieba debug output
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False
    logger.warning("jieba not available, local voice commands will use simple matching")


@dataclass
class CommandMatch:
    action: str
    params: Dict
    matched_phrase: str
    confidence: float


VOICE_COMMANDS: Dict[str, Dict] = {
    # ── App Launch ──
    "打开微信":       {"action": "skill", "skill_id": "open_wechat"},
    "打开浏览器":     {"action": "skill", "skill_id": "open_browser"},
    "打开记事本":     {"action": "skill", "skill_id": "open_notepad"},
    "打开文件管理":   {"action": "skill", "skill_id": "open_explorer"},
    "打开计算器":     {"action": "skill", "skill_id": "open_calculator"},
    "打开设置":       {"action": "skill", "skill_id": "open_settings"},
    "打开任务管理器": {"action": "skill", "skill_id": "open_task_manager"},
    "打开命令行":     {"action": "skill", "skill_id": "open_terminal"},

    # ── Window Operations ──
    "切换窗口":       {"action": "hotkey", "keys": ["alt", "tab"]},
    "关闭窗口":       {"action": "hotkey", "keys": ["alt", "F4"]},
    "最小化":         {"action": "hotkey", "keys": ["win", "down"]},
    "最小化全部":     {"action": "hotkey", "keys": ["win", "d"]},
    "最大化":         {"action": "hotkey", "keys": ["win", "up"]},
    "全屏":           {"action": "hotkey", "keys": ["F11"]},
    "桌面":           {"action": "hotkey", "keys": ["win", "d"]},

    # ── Editing ──
    "复制":           {"action": "hotkey", "keys": ["ctrl", "c"]},
    "粘贴":           {"action": "hotkey", "keys": ["ctrl", "v"]},
    "剪切":           {"action": "hotkey", "keys": ["ctrl", "x"]},
    "撤销":           {"action": "hotkey", "keys": ["ctrl", "z"]},
    "重做":           {"action": "hotkey", "keys": ["ctrl", "y"]},
    "全选":           {"action": "hotkey", "keys": ["ctrl", "a"]},
    "保存":           {"action": "hotkey", "keys": ["ctrl", "s"]},
    "查找":           {"action": "hotkey", "keys": ["ctrl", "f"]},
    "替换":           {"action": "hotkey", "keys": ["ctrl", "h"]},
    "删除":           {"action": "hotkey", "keys": ["delete"]},
    "回车":           {"action": "hotkey", "keys": ["enter"]},
    "空格":           {"action": "hotkey", "keys": ["space"]},
    "退格":           {"action": "hotkey", "keys": ["backspace"]},

    # ── Scrolling & Navigation ──
    "往上翻":         {"action": "scroll", "dy": 5},
    "往下翻":         {"action": "scroll", "dy": -5},
    "向上滚动":       {"action": "scroll", "dy": 5},
    "向下滚动":       {"action": "scroll", "dy": -5},
    "翻到顶部":       {"action": "hotkey", "keys": ["ctrl", "home"]},
    "翻到底部":       {"action": "hotkey", "keys": ["ctrl", "end"]},
    "后退":           {"action": "hotkey", "keys": ["alt", "left"]},
    "前进":           {"action": "hotkey", "keys": ["alt", "right"]},
    "刷新":           {"action": "hotkey", "keys": ["F5"]},
    "新标签":         {"action": "hotkey", "keys": ["ctrl", "t"]},
    "关闭标签":       {"action": "hotkey", "keys": ["ctrl", "w"]},

    # ── System ──
    "截图":           {"action": "screenshot"},
    "截屏":           {"action": "screenshot"},
    "锁屏":           {"action": "skill", "skill_id": "lock_screen"},
    "静音":           {"action": "volume", "level": 0},
    "音量最大":       {"action": "volume", "level": 100},
    "音量增大":       {"action": "hotkey", "keys": ["volumeup"]},
    "音量减小":       {"action": "hotkey", "keys": ["volumedown"]},

    # ── Control ──
    "停止":           {"action": "stop_all"},
    "暂停":           {"action": "pause_ai"},
    "继续":           {"action": "resume_ai"},
    "取消":           {"action": "cancel"},
    "确认":           {"action": "confirm"},
    "确定":           {"action": "confirm"},
}

# Aliases: multiple phrases map to the same command
ALIASES: Dict[str, str] = {
    "微信": "打开微信",
    "浏览器": "打开浏览器",
    "记事本": "打开记事本",
    "文件管理器": "打开文件管理",
    "拷贝": "复制",
    "ctrl c": "复制",
    "ctrl v": "粘贴",
    "ctrl z": "撤销",
    "上翻": "往上翻",
    "下翻": "往下翻",
    "上滑": "往上翻",
    "下滑": "往下翻",
    "回到顶部": "翻到顶部",
    "回到底部": "翻到底部",
    "存档": "保存",
    "搜索": "查找",
    "不要": "取消",
    "算了": "取消",
    "好的": "确认",
    "可以": "确认",
    "行": "确认",
    "对": "确认",
    "没错": "确认",
    "截个图": "截图",
    "截一下屏": "截屏",
    "关了它": "关闭窗口",
    "关掉": "关闭窗口",
    "停下来": "停止",
    "别动了": "停止",
    "等一下": "暂停",
    "等等": "暂停",
    "继续吧": "继续",
    "接着来": "继续",
}


class LocalVoiceCommandEngine:
    """
    Matches spoken text against predefined commands using jieba segmentation.

    Matching strategy (in order):
    1. Exact match against command phrases
    2. Exact match against aliases
    3. Fuzzy match: check if any command phrase is a substring of the input
    4. Jieba tokenization: tokenize input and score against command keywords
    """

    def __init__(self):
        self._commands = dict(VOICE_COMMANDS)
        self._aliases = dict(ALIASES)
        self._custom_commands: Dict[str, Dict] = {}

        # Build keyword index for fuzzy matching
        self._keyword_index: Dict[str, str] = {}
        self._build_index()

    def _build_index(self):
        """Build keyword-to-command index."""
        for phrase in self._commands:
            if _HAS_JIEBA:
                tokens = jieba.lcut(phrase)
                for token in tokens:
                    if len(token) >= 2:
                        self._keyword_index[token] = phrase

    def add_custom_command(self, phrase: str, action_config: Dict):
        """Add a user-defined voice command."""
        self._custom_commands[phrase] = action_config
        if _HAS_JIEBA:
            for token in jieba.lcut(phrase):
                if len(token) >= 2:
                    self._keyword_index[token] = phrase

    def match(self, text: str) -> Optional[CommandMatch]:
        """
        Match input text against known commands.
        Returns CommandMatch or None.
        """
        if not text or not text.strip():
            return None

        text = text.strip()

        # 1. Exact match
        if text in self._commands:
            return CommandMatch(
                action=self._commands[text]["action"],
                params=self._commands[text],
                matched_phrase=text,
                confidence=1.0,
            )

        if text in self._custom_commands:
            return CommandMatch(
                action=self._custom_commands[text]["action"],
                params=self._custom_commands[text],
                matched_phrase=text,
                confidence=1.0,
            )

        # 2. Alias match
        if text in self._aliases:
            canonical = self._aliases[text]
            if canonical in self._commands:
                return CommandMatch(
                    action=self._commands[canonical]["action"],
                    params=self._commands[canonical],
                    matched_phrase=canonical,
                    confidence=0.95,
                )

        # 3. Substring match: "帮我打开微信" contains "打开微信"
        best_match = None
        best_len = 0
        all_phrases = list(self._commands.keys()) + list(self._custom_commands.keys())
        for phrase in all_phrases:
            if phrase in text and len(phrase) > best_len:
                best_match = phrase
                best_len = len(phrase)

        if best_match:
            cmd = self._commands.get(best_match) or self._custom_commands.get(best_match)
            if cmd:
                ratio = len(best_match) / max(len(text), 1)
                return CommandMatch(
                    action=cmd["action"],
                    params=cmd,
                    matched_phrase=best_match,
                    confidence=min(0.7 + ratio * 0.25, 0.95),
                )

        # Also check alias substrings
        for alias, canonical in self._aliases.items():
            if alias in text and canonical in self._commands:
                cmd = self._commands[canonical]
                ratio = len(alias) / max(len(text), 1)
                return CommandMatch(
                    action=cmd["action"],
                    params=cmd,
                    matched_phrase=canonical,
                    confidence=min(0.6 + ratio * 0.2, 0.85),
                )

        # 4. Jieba token matching
        if _HAS_JIEBA:
            tokens = jieba.lcut(text)
            scores: Dict[str, float] = {}
            for token in tokens:
                if token in self._keyword_index:
                    phrase = self._keyword_index[token]
                    scores[phrase] = scores.get(phrase, 0) + 1

            if scores:
                best_phrase = max(scores, key=scores.get)
                cmd = self._commands.get(best_phrase) or self._custom_commands.get(best_phrase)
                if cmd:
                    return CommandMatch(
                        action=cmd["action"],
                        params=cmd,
                        matched_phrase=best_phrase,
                        confidence=min(scores[best_phrase] * 0.3, 0.8),
                    )

        return None

    def get_all_commands(self) -> List[Dict]:
        """Return all available commands for display."""
        result = []
        for phrase, config in self._commands.items():
            result.append({"phrase": phrase, **config})
        for phrase, config in self._custom_commands.items():
            result.append({"phrase": phrase, "custom": True, **config})
        return result


# Singleton instance
_engine: Optional[LocalVoiceCommandEngine] = None


def get_engine() -> LocalVoiceCommandEngine:
    global _engine
    if _engine is None:
        _engine = LocalVoiceCommandEngine()
    return _engine
