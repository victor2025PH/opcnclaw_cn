# -*- coding: utf-8 -*-
"""自定义 Agent 角色 — 用户创建/编辑/导入导出"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from .agent_team import AgentRole

CUSTOM_ROLES_FILE = Path("data/custom_agent_roles.json")


class CustomRoleManager:
    """用户自定义角色管理"""

    def __init__(self):
        self._roles: Dict[str, AgentRole] = {}
        self._load()

    def _load(self):
        if not CUSTOM_ROLES_FILE.exists():
            return
        try:
            data = json.loads(CUSTOM_ROLES_FILE.read_text(encoding="utf-8"))
            for item in data.get("roles", []):
                role = AgentRole(
                    id=item["id"], name=item["name"], avatar=item.get("avatar", "🤖"),
                    description=item.get("description", ""),
                    system_prompt=item.get("system_prompt", ""),
                    preferred_model=item.get("preferred_model", ""),
                    tools=item.get("tools", []),
                    can_delegate=item.get("can_delegate", False),
                )
                self._roles[role.id] = role
            logger.info(f"[CustomRoles] 加载 {len(self._roles)} 个自定义角色")
        except Exception as e:
            logger.warning(f"[CustomRoles] 加载失败: {e}")

    def _save(self):
        CUSTOM_ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "roles": [r.to_dict() | {"system_prompt": r.system_prompt} for r in self._roles.values()],
            "updated_at": time.time(),
        }
        CUSTOM_ROLES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(self, id: str, name: str, avatar: str, description: str,
               system_prompt: str, preferred_model: str = "",
               tools: list = None, can_delegate: bool = False) -> AgentRole:
        if id in self._roles:
            raise ValueError(f"角色 ID '{id}' 已存在")
        # 注册到全局角色表
        from .agent_templates import AGENT_ROLES
        if id in AGENT_ROLES:
            raise ValueError(f"角色 ID '{id}' 与预置角色冲突")

        role = AgentRole(
            id=id, name=name, avatar=avatar, description=description,
            system_prompt=system_prompt, preferred_model=preferred_model,
            tools=tools or [], can_delegate=can_delegate,
        )
        self._roles[id] = role
        AGENT_ROLES[id] = role  # 注入全局
        self._save()
        logger.info(f"[CustomRoles] 创建: {name} ({id})")
        return role

    def update(self, id: str, **kwargs) -> bool:
        role = self._roles.get(id)
        if not role:
            return False
        for k, v in kwargs.items():
            if hasattr(role, k) and v is not None:
                setattr(role, k, v)
        self._save()
        return True

    def delete(self, id: str) -> bool:
        if id not in self._roles:
            return False
        del self._roles[id]
        from .agent_templates import AGENT_ROLES
        AGENT_ROLES.pop(id, None)
        self._save()
        return True

    def list_roles(self) -> List[dict]:
        return [r.to_dict() for r in self._roles.values()]

    def export_all(self) -> str:
        return json.dumps(
            [r.to_dict() | {"system_prompt": r.system_prompt} for r in self._roles.values()],
            ensure_ascii=False, indent=2,
        )

    def import_roles(self, json_str: str) -> int:
        items = json.loads(json_str)
        count = 0
        for item in items:
            try:
                self.create(
                    id=item["id"], name=item["name"],
                    avatar=item.get("avatar", "🤖"),
                    description=item.get("description", ""),
                    system_prompt=item.get("system_prompt", ""),
                    preferred_model=item.get("preferred_model", ""),
                    tools=item.get("tools", []),
                )
                count += 1
            except Exception:
                pass
        return count


_manager: Optional[CustomRoleManager] = None

def get_custom_role_manager() -> CustomRoleManager:
    global _manager
    if _manager is None:
        _manager = CustomRoleManager()
    return _manager
