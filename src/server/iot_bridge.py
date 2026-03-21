# -*- coding: utf-8 -*-
"""
IoT 桥接 — HomeAssistant / MQTT 智能家居控制

支持：
  - HomeAssistant REST API（设备发现/状态/控制）
  - 设备缓存（60s TTL）
  - 房间分组
  - AI 工具集成（语音"关灯"→ iot_control）
"""

from __future__ import annotations

import time
import threading
from typing import Dict, List, Optional

import httpx
from loguru import logger


class IoTDevice:
    """智能设备"""
    def __init__(self, id: str, name: str, type: str, room: str = "",
                 state: str = "off", attributes: dict = None):
        self.id = id
        self.name = name
        self.type = type       # light / switch / climate / sensor / cover
        self.room = room
        self.state = state     # on / off / unavailable
        self.attributes = attributes or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "room": self.room,
            "state": self.state,
            "attributes": self.attributes,
        }


class IoTBridge:
    """智能家居桥接器"""

    CACHE_TTL = 60.0  # 设备列表缓存

    def __init__(self):
        self._ha_url = ""
        self._ha_token = ""
        self._devices: List[IoTDevice] = []
        self._devices_ts = 0.0
        self._lock = threading.Lock()

    def configure(self, ha_url: str, ha_token: str):
        """配置 HomeAssistant 连接"""
        self._ha_url = ha_url.rstrip("/")
        self._ha_token = ha_token
        self._devices_ts = 0  # 清缓存
        logger.info(f"[IoT] HomeAssistant 配置: {self._ha_url}")

    @property
    def is_configured(self) -> bool:
        return bool(self._ha_url and self._ha_token)

    async def get_devices(self, force: bool = False) -> List[IoTDevice]:
        """获取设备列表（带缓存）"""
        if not self.is_configured:
            return []

        now = time.time()
        if not force and self._devices and (now - self._devices_ts) < self.CACHE_TTL:
            return self._devices

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{self._ha_url}/api/states",
                    headers={"Authorization": f"Bearer {self._ha_token}"},
                )
                if r.status_code != 200:
                    logger.warning(f"[IoT] HA 请求失败: {r.status_code}")
                    return self._devices

                states = r.json()
                devices = []
                for s in states:
                    entity_id = s.get("entity_id", "")
                    domain = entity_id.split(".")[0] if "." in entity_id else ""
                    if domain not in ("light", "switch", "climate", "sensor", "cover", "fan"):
                        continue

                    attrs = s.get("attributes", {})
                    devices.append(IoTDevice(
                        id=entity_id,
                        name=attrs.get("friendly_name", entity_id),
                        type=domain,
                        room=attrs.get("room", ""),
                        state=s.get("state", "unknown"),
                        attributes={
                            k: v for k, v in attrs.items()
                            if k in ("brightness", "color_temp", "temperature",
                                    "current_temperature", "hvac_mode", "unit_of_measurement")
                        },
                    ))

                with self._lock:
                    self._devices = devices
                    self._devices_ts = now
                logger.info(f"[IoT] 发现 {len(devices)} 个设备")
                return devices

        except Exception as e:
            logger.warning(f"[IoT] 获取设备失败: {e}")
            return self._devices

    async def control(self, entity_id: str, action: str, value: dict = None) -> dict:
        """控制设备"""
        if not self.is_configured:
            return {"error": "HomeAssistant 未配置"}

        domain = entity_id.split(".")[0] if "." in entity_id else ""
        service = action  # turn_on / turn_off / toggle

        # 简化动作名
        if action in ("on", "open", "开"):
            service = "turn_on"
        elif action in ("off", "close", "关"):
            service = "turn_off"
        elif action in ("toggle", "切换"):
            service = "toggle"

        try:
            data = {"entity_id": entity_id}
            if value:
                data.update(value)

            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{self._ha_url}/api/services/{domain}/{service}",
                    headers={"Authorization": f"Bearer {self._ha_token}",
                            "Content-Type": "application/json"},
                    json=data,
                )
                if r.status_code in (200, 201):
                    self._devices_ts = 0  # 操作后清缓存
                    return {"ok": True, "entity_id": entity_id, "action": service}
                return {"error": f"HA 返回 {r.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    def get_device_by_name(self, name: str) -> Optional[IoTDevice]:
        """按名称模糊查找设备"""
        for d in self._devices:
            if name in d.name or d.name in name:
                return d
        return None


# ── 全局单例 ──────────────────────────────────────────────────

_bridge: Optional[IoTBridge] = None


def get_iot_bridge() -> IoTBridge:
    global _bridge
    if _bridge is None:
        _bridge = IoTBridge()
        # 尝试从配置读取
        try:
            import configparser
            cfg = configparser.ConfigParser()
            cfg.read("config.ini", encoding="utf-8")
            ha_url = cfg.get("iot", "homeassistant_url", fallback="")
            ha_token = cfg.get("iot", "homeassistant_token", fallback="")
            if ha_url and ha_token:
                _bridge.configure(ha_url, ha_token)
        except Exception:
            pass
    return _bridge
