# -*- coding: utf-8 -*-
"""微信模块共享数据模型"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class WxMessage:
    """统一消息模型（三轨通用）"""
    contact: str            # 联系人/群名
    sender: str             # 发送人（群聊时与 contact 不同）
    content: str            # 消息内容
    msg_id: str = ""        # 消息唯一 ID（DB轨道有，其他轨道为空）
    is_group: bool = False
    at_me: bool = False
    is_mine: bool = False
    timestamp: float = field(default_factory=time.time)
    raw_time_str: str = ""
    msg_type: str = "text"  # text/image/voice/file/video/link/system
    source: str = "unknown" # db/wxauto/uia/ocr — 消息来自哪个轨道

    def fingerprint(self) -> str:
        if self.msg_id:
            return self.msg_id
        key = f"{self.contact}|{self.sender}|{self.content[:80]}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def __repr__(self):
        src = f"[{self.source}]" if self.source != "unknown" else ""
        flag = "[@我]" if self.at_me else ""
        mine = "[我]" if self.is_mine else ""
        return f"<WxMsg{src} {self.contact}/{self.sender}{flag}{mine}: {self.content[:30]}>"


@dataclass
class WxChat:
    """一个聊天会话"""
    name: str
    unread_count: int = 0
    is_group: bool = False
    last_msg: str = ""
    last_time: str = ""


@dataclass
class TrackStatus:
    """单个轨道的运行状态"""
    name: str               # db / wxauto / uia / ocr
    available: bool = False  # 是否可用
    healthy: bool = False    # 是否健康（最近N次操作成功率 > 阈值）
    error: str = ""          # 最近错误信息
    read_count: int = 0      # 累计读取次数
    fail_count: int = 0      # 累计失败次数
    last_success: float = 0  # 最后成功时间戳
    last_fail: float = 0     # 最后失败时间戳

    @property
    def success_rate(self) -> float:
        total = self.read_count + self.fail_count
        if total == 0:
            return 0.0
        return self.read_count / total

    @property
    def score(self) -> float:
        """综合健康评分 0~1，用于轨道选择"""
        if not self.available:
            return 0.0
        if not self.healthy:
            return 0.1
        # 成功率权重 + 最近活跃度权重
        rate_score = self.success_rate
        recency = 1.0
        if self.last_success > 0:
            age = time.time() - self.last_success
            recency = max(0.1, 1.0 - age / 300)  # 5 分钟内 → 高分
        return rate_score * 0.7 + recency * 0.3
