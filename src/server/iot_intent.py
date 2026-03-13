"""
IoT Intent Parser — 语音/文本 → 智能家居动作

解析中英文自然语言指令，映射到 HomeAssistant 设备控制。
与 skill_executor 管道集成，在 AI 调用前预处理。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


_ACTION_PATTERNS = {
    "turn_on": [
        r"(?:打开|开启|开|启动|点亮|开灯)\s*(.+)",
        r"(?:turn\s+on|switch\s+on|enable|open)\s+(.+)",
    ],
    "turn_off": [
        r"(?:关闭|关掉|关|熄灭|关灯|停止)\s*(.+)",
        r"(?:turn\s+off|switch\s+off|disable|close)\s+(.+)",
    ],
    "toggle": [
        r"(?:切换|翻转)\s*(.+)",
        r"(?:toggle)\s+(.+)",
    ],
    "set": [
        r"(?:把|将)\s*(.+?)\s*(?:调到|设为|设置为|调整为|调成)\s*(\d+)",
        r"(?:set)\s+(.+?)\s+(?:to)\s+(\d+)",
        r"(.+?)\s*(?:温度|亮度|音量)\s*(?:调到|设为)\s*(\d+)",
    ],
    "status": [
        r"(.+?)\s*(?:状态|什么状态|怎么样|是开是关)",
        r"(?:status\s+of|what\s+is|check)\s+(.+)",
    ],
    "scene": [
        r"(?:激活|启动|执行)\s*(?:场景|模式)\s*(.+)",
        r"(?:activate|run)\s+(?:scene)\s+(.+)",
    ],
}

_DEVICE_ALIASES = {
    "客厅灯": "light.living_room",
    "卧室灯": "light.bedroom",
    "厨房灯": "light.kitchen",
    "浴室灯": "light.bathroom",
    "走廊灯": "light.hallway",
    "阳台灯": "light.balcony",
    "台灯": "light.desk_lamp",
    "吊灯": "light.chandelier",
    "客厅空调": "climate.living_room",
    "卧室空调": "climate.bedroom",
    "空调": "climate.main",
    "电视": "media_player.tv",
    "客厅电视": "media_player.living_room_tv",
    "音箱": "media_player.speaker",
    "窗帘": "cover.curtain",
    "客厅窗帘": "cover.living_room_curtain",
    "卧室窗帘": "cover.bedroom_curtain",
    "风扇": "fan.main",
    "加湿器": "humidifier.main",
    "扫地机": "vacuum.robot",
    "门锁": "lock.front_door",
    "热水器": "switch.water_heater",
    "all lights": "light.all",
    "living room": "light.living_room",
    "bedroom": "light.bedroom",
    "kitchen": "light.kitchen",
    "tv": "media_player.tv",
    "ac": "climate.main",
    "fan": "fan.main",
    "curtain": "cover.curtain",
}

_IOT_KEYWORDS = (
    "打开", "关闭", "关掉", "开灯", "关灯", "开启", "调到", "设为", "设置",
    "空调", "灯", "窗帘", "电视", "音箱", "风扇", "turn on", "turn off",
    "switch", "brightness", "temperature", "场景", "scene", "toggle",
    "开", "关", "亮度", "温度", "音量",
)


def is_iot_intent(text: str) -> bool:
    """Fast check: does the text likely contain an IoT command?"""
    lower = text.lower().strip()
    return any(kw in lower for kw in _IOT_KEYWORDS)


def parse_intent(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse natural language into an IoT intent dict.
    Returns None if no IoT intent detected.
    """
    text = text.strip()
    if not is_iot_intent(text):
        return None

    for action, patterns in _ACTION_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                groups = m.groups()
                target_raw = groups[0].strip() if groups else ""
                value = None

                if action == "set" and len(groups) >= 2:
                    target_raw = groups[0].strip()
                    try:
                        value = int(groups[1])
                    except (ValueError, IndexError):
                        value = None

                entity_id = _resolve_entity(target_raw)
                if entity_id or target_raw:
                    return {
                        "action": action,
                        "entity_id": entity_id,
                        "entity_hint": target_raw,
                        "value": value,
                        "raw_text": text,
                    }
    return None


def _resolve_entity(name: str) -> str:
    """Resolve a Chinese/English device name to an entity_id."""
    name_clean = name.strip().rstrip("的了吧呢")
    if "." in name_clean and name_clean.count(".") == 1:
        return name_clean

    for alias, eid in _DEVICE_ALIASES.items():
        if alias in name_clean or name_clean in alias:
            return eid

    return ""


def update_aliases_from_ha(states: List[Dict]):
    """
    Dynamically update device alias mapping from HA state list.
    Called periodically to keep aliases in sync with actual devices.
    """
    for s in states:
        eid = s.get("entity_id", "")
        name = s.get("attributes", {}).get("friendly_name", "")
        if name and eid:
            _DEVICE_ALIASES[name] = eid
            _DEVICE_ALIASES[name.lower()] = eid


async def execute_iot(intent: Dict[str, Any]) -> str:
    """
    Execute an IoT intent via the HA bridge.
    Returns a result string for the AI to naturalize.
    """
    try:
        from src.bridge.homeassistant import HomeAssistantBridge
        ha = HomeAssistantBridge()
        if not ha.configured:
            return f"[IoT] 智能家居未配置，用户想{intent['action']} {intent['entity_hint']}"
    except Exception:
        return f"[IoT] HomeAssistant 模块不可用"

    action = intent["action"]
    entity_id = intent["entity_id"]
    entity_hint = intent["entity_hint"]
    value = intent.get("value")

    if not entity_id:
        try:
            states = await ha.get_states()
            update_aliases_from_ha(states)
            entity_id = _resolve_entity(entity_hint)
        except Exception:
            pass

    if not entity_id:
        return f"[IoT] 找不到设备「{entity_hint}」，请告诉用户可以在设置中配置设备别名"

    result = await ha.execute_intent(action, entity_id, value)
    return f"[IoT执行结果] {result}"
