"""
Accessibility control configuration manager.

Persists expression/gesture/gaze control mappings.
Storage: data/access_config.json

Provides API endpoints for the settings panel and preset management.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


CONFIG_PATH = Path("data/access_config.json")


PRESETS = {
    "hands_free": {
        "label": "🙌 完全免手",
        "description": "表情全开 + 头部动作 + 语音，适合无法使用双手的用户",
        "expression_enabled": True,
        "gesture_enabled": False,
        "gaze_enabled": True,
        "sensitivity": 1.0,
        "expressions": {
            "smile_hold": True, "mouth_open": True, "brow_up": True,
            "brow_down": True, "wink_left": True, "wink_right": True,
            "both_blink": True, "kiss": True,
        },
        "head_movements": {
            "nod": True, "shake": True, "tilt_left": True, "tilt_right": True,
        },
    },
    "one_hand": {
        "label": "🤚 单手辅助",
        "description": "表情辅助 + 语音，配合单手手势使用",
        "expression_enabled": True,
        "gesture_enabled": True,
        "gaze_enabled": False,
        "sensitivity": 1.0,
        "expressions": {
            "wink_left": True, "wink_right": True, "mouth_open": True,
        },
        "head_movements": {"nod": True, "shake": True},
    },
    "voice_only": {
        "label": "🎤 语音为主",
        "description": "张嘴自动开始录音，点头/摇头确认/取消",
        "expression_enabled": True,
        "gesture_enabled": False,
        "gaze_enabled": False,
        "sensitivity": 0.9,
        "expressions": {"mouth_open": True},
        "head_movements": {"nod": True, "shake": True},
    },
    "mouse_assist": {
        "label": "🖱️ 鼠标辅助",
        "description": "可以用鼠标但打字困难，语音输入 + 表情快捷",
        "expression_enabled": True,
        "gesture_enabled": False,
        "gaze_enabled": False,
        "sensitivity": 1.0,
        "expressions": {"mouth_open": True, "smile_hold": True, "wink_left": True},
        "head_movements": {"nod": True},
    },
    "power_user": {
        "label": "⚡ 效率极客",
        "description": "全部开启，快速触发",
        "expression_enabled": True,
        "gesture_enabled": True,
        "gaze_enabled": True,
        "sensitivity": 1.2,
        "expressions": {
            "smile_hold": True, "mouth_open": True, "brow_up": True,
            "brow_down": True, "wink_left": True, "wink_right": True,
            "both_blink": True, "kiss": True,
        },
        "head_movements": {
            "nod": True, "shake": True, "tilt_left": True, "tilt_right": True,
        },
    },
    "gentle": {
        "label": "🌿 轻柔模式",
        "description": "长触发时间，少量映射，适合初次使用或老年人",
        "expression_enabled": True,
        "gesture_enabled": True,
        "gaze_enabled": False,
        "sensitivity": 0.8,
        "expressions": {"smile_hold": True, "wink_left": True, "mouth_open": True},
        "head_movements": {"nod": True},
    },
}


def _ensure_dir():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """Load config from disk. Returns default config if file missing."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read access config: {e}")
    return _default_config()


def save_config(config: Dict[str, Any]):
    """Persist config to disk."""
    _ensure_dir()
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Access config saved")


def _default_config() -> Dict[str, Any]:
    return {
        "expression_enabled": False,
        "gesture_enabled": True,
        "gaze_enabled": False,
        "sensitivity": 1.0,
        "expressions": {},
        "head_movements": {},
        "active_preset": None,
    }


def get_presets() -> Dict[str, Any]:
    """Return all available presets."""
    return {k: {"label": v["label"], "description": v["description"]} for k, v in PRESETS.items()}


def get_preset_detail(name: str) -> Optional[Dict[str, Any]]:
    """Return full preset configuration."""
    return PRESETS.get(name)


def apply_preset(name: str) -> Dict[str, Any]:
    """Apply a preset and save. Returns updated config."""
    preset = PRESETS.get(name)
    if not preset:
        raise ValueError(f"Unknown preset: {name}")

    config = load_config()
    config["expression_enabled"] = preset.get("expression_enabled", False)
    config["gesture_enabled"] = preset.get("gesture_enabled", True)
    config["gaze_enabled"] = preset.get("gaze_enabled", False)
    config["sensitivity"] = preset.get("sensitivity", 1.0)
    config["expressions"] = preset.get("expressions", {})
    config["head_movements"] = preset.get("head_movements", {})
    config["active_preset"] = name

    save_config(config)
    return config
