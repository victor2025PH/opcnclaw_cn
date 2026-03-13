"""
HomeAssistant IoT 桥接

通过 HA REST API + WebSocket 对接智能家居设备。
支持：设备发现、状态查询、设备控制、场景触发。
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from .manager import BaseBridge


class HomeAssistantBridge(BaseBridge):

    def __init__(
        self,
        url: str = "",
        token: str = "",
        verify_ssl: bool = False,
    ):
        self.url = (url or os.environ.get("HA_URL", "")).rstrip("/")
        self.token = token or os.environ.get("HA_TOKEN", "")
        self.verify_ssl = verify_ssl
        self._cache_states: Dict[str, Any] = {}
        self._cache_ts: float = 0

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kw) -> Any:
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=10) as c:
            resp = await c.request(method, f"{self.url}/api/{path}", headers=self._headers(), **kw)
            resp.raise_for_status()
            return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text

    # ── Discovery ──

    async def get_states(self, use_cache: bool = True) -> List[Dict]:
        import time
        now = time.time()
        if use_cache and self._cache_states and (now - self._cache_ts) < 30:
            return list(self._cache_states.values())
        raw = await self._request("GET", "states")
        self._cache_states = {s["entity_id"]: s for s in raw}
        self._cache_ts = now
        return raw

    async def get_entity(self, entity_id: str) -> Optional[Dict]:
        try:
            return await self._request("GET", f"states/{entity_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_services(self) -> List[Dict]:
        return await self._request("GET", "services")

    # ── Control ──

    async def call_service(self, domain: str, service: str, entity_id: str = "", data: Optional[Dict] = None) -> Any:
        payload: Dict[str, Any] = data.copy() if data else {}
        if entity_id:
            payload["entity_id"] = entity_id
        result = await self._request("POST", f"services/{domain}/{service}", json=payload)
        logger.info(f"HA service {domain}.{service} → {entity_id or 'global'}")
        return result

    async def turn_on(self, entity_id: str, **kw) -> Any:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_on", entity_id, kw or None)

    async def turn_off(self, entity_id: str) -> Any:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_off", entity_id)

    async def toggle(self, entity_id: str) -> Any:
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "toggle", entity_id)

    async def set_value(self, entity_id: str, value: Any) -> Any:
        domain = entity_id.split(".")[0]
        svc_map = {
            "light": ("light", "turn_on", {"brightness_pct": value}),
            "cover": ("cover", "set_cover_position", {"position": value}),
            "climate": ("climate", "set_temperature", {"temperature": value}),
            "fan": ("fan", "set_percentage", {"percentage": value}),
            "media_player": ("media_player", "volume_set", {"volume_level": value / 100}),
            "number": ("number", "set_value", {"value": value}),
        }
        if domain in svc_map:
            d, s, data = svc_map[domain]
            return await self.call_service(d, s, entity_id, data)
        return await self.call_service(domain, "set_value", entity_id, {"value": value})

    # ── Scenes & Automations ──

    async def activate_scene(self, scene_id: str) -> Any:
        return await self.call_service("scene", "turn_on", scene_id)

    async def trigger_automation(self, automation_id: str) -> Any:
        return await self.call_service("automation", "trigger", automation_id)

    # ── Friendly summaries for AI conversation ──

    async def describe_rooms(self) -> str:
        states = await self.get_states()
        rooms: Dict[str, List[str]] = {}
        for s in states:
            attr = s.get("attributes", {})
            area = attr.get("friendly_name", s["entity_id"])
            domain = s["entity_id"].split(".")[0]
            if domain in ("light", "switch", "fan", "climate", "cover", "media_player", "lock", "vacuum"):
                room = attr.get("area_id", "未分组")
                rooms.setdefault(room, []).append(f"  - {area}: {s['state']}")
        lines = []
        for room, devs in sorted(rooms.items()):
            lines.append(f"[{room}]")
            lines.extend(devs[:20])
        return "\n".join(lines) if lines else "未发现智能设备"

    async def describe_entity(self, entity_id: str) -> str:
        e = await self.get_entity(entity_id)
        if not e:
            return f"设备 {entity_id} 不存在"
        attr = e.get("attributes", {})
        name = attr.get("friendly_name", entity_id)
        parts = [f"{name} ({entity_id}): {e['state']}"]
        for k in ("brightness", "color_temp", "temperature", "current_temperature",
                   "humidity", "battery", "volume_level", "media_title"):
            if k in attr:
                parts.append(f"  {k}: {attr[k]}")
        return "\n".join(parts)

    # ── BaseBridge interface ──

    async def send_text(self, text: str, title: str = "") -> bool:
        if not self.configured:
            return False
        try:
            await self.call_service("notify", "persistent_notification", data={
                "message": text, "title": title or "OpenClaw"
            })
            return True
        except Exception as e:
            logger.warning(f"HA notification failed: {e}")
            return False

    # ── NLP intent → device action mapping ──

    async def execute_intent(self, intent: str, entity_hint: str = "", value: Any = None) -> str:
        """
        Maps natural language intents to HA actions.
        Returns human-readable result string.
        """
        intent = intent.lower().strip()
        entity_id = entity_hint

        if not entity_id:
            return "请指定要控制的设备"

        try:
            if intent in ("开", "打开", "on", "turn_on", "open"):
                await self.turn_on(entity_id)
                return f"已打开 {entity_id}"
            elif intent in ("关", "关闭", "off", "turn_off", "close"):
                await self.turn_off(entity_id)
                return f"已关闭 {entity_id}"
            elif intent in ("切换", "toggle"):
                await self.toggle(entity_id)
                return f"已切换 {entity_id}"
            elif intent in ("设置", "调节", "set") and value is not None:
                await self.set_value(entity_id, value)
                return f"已设置 {entity_id} = {value}"
            elif intent in ("状态", "查询", "status", "query"):
                return await self.describe_entity(entity_id)
            elif intent in ("场景", "scene"):
                await self.activate_scene(entity_id)
                return f"已激活场景 {entity_id}"
            else:
                return f"未识别的指令: {intent}"
        except Exception as e:
            return f"操作失败: {e}"
