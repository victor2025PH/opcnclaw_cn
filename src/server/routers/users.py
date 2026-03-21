# -*- coding: utf-8 -*-
"""多用户 API 路由

端点：
  - GET  /api/users              — 用户列表
  - POST /api/users/register     — 注册新用户（声纹采集）
  - GET  /api/users/current      — 当前用户
  - POST /api/users/switch       — 切换用户
  - PUT  /api/users/{id}         — 更新用户信息
  - DELETE /api/users/{id}       — 删除用户
"""

from __future__ import annotations

import base64
import io
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from src.server.speaker_id import get_speaker_manager

router = APIRouter(prefix="/api/users", tags=["users"])


# ── 请求模型 ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field(..., description="用户昵称")
    avatar: str = Field("👤", description="头像 emoji")
    audio_segments: List[str] = Field(
        ..., description="3 段音频的 base64 编码（PCM float32, 16kHz, 各约 3 秒）"
    )


class SwitchRequest(BaseModel):
    user_id: str = Field(..., description="要切换到的用户 ID")


class UpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    preferences: Optional[Dict] = None


# ── 端点 ─────────────────────────────────────────────────────

@router.get("")
async def list_users():
    """列出所有注册用户"""
    mgr = get_speaker_manager()
    users = mgr.list_users()
    current = mgr.get_current_id()
    return {"users": users, "count": len(users), "current_user": current}


@router.post("/register")
async def register_user(req: RegisterRequest):
    """注册新用户（提交 3 段语音进行声纹采集）

    前端录 3 句话（各 3 秒），将 PCM float32 数据 base64 编码后上传。
    """
    if len(req.audio_segments) < 1:
        return {"ok": False, "error": "至少需要 1 段音频"}

    try:
        segments = []
        for b64 in req.audio_segments[:3]:
            raw = base64.b64decode(b64)
            audio = np.frombuffer(raw, dtype=np.float32)
            segments.append(audio)

        mgr = get_speaker_manager()
        profile = mgr.register(
            name=req.name,
            avatar=req.avatar,
            audio_segments=segments,
        )
        return {"ok": True, "user": profile.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/current")
async def get_current_user():
    """获取当前识别到的用户"""
    mgr = get_speaker_manager()
    profile = mgr.get_current()
    if profile:
        return {"user": profile.to_dict()}
    return {"user": None}


@router.post("/switch")
async def switch_user(req: SwitchRequest):
    """手动切换用户"""
    mgr = get_speaker_manager()
    ok = mgr.switch_user(req.user_id)
    return {"ok": ok, "current_user": mgr.get_current_id()}


@router.put("/{user_id}")
async def update_user(user_id: str, req: UpdateRequest):
    """更新用户信息"""
    mgr = get_speaker_manager()
    ok = mgr.update_user(user_id, name=req.name, avatar=req.avatar, preferences=req.preferences)
    return {"ok": ok}


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    """删除用户（默认用户不可删除）"""
    mgr = get_speaker_manager()
    ok = mgr.delete_user(user_id)
    return {"ok": ok}
