# -*- coding: utf-8 -*-
"""
OpenClaw 微信自动化模块 v2.0

三轨融合架构：
  轨道A (DB直读)   → 解密微信本地 SQLite 数据库，零 UI 干扰
  轨道B (wxauto)   → 基于 UIAutomation 的成熟库，后台监听
  轨道C (OCR)      → 截图 + OCR 识别，兜底方案

朋友圈自动化：
  MomentsReader    → 朋友圈内容读取（wxauto → Vision AI → UIA）
  MomentsAIEngine  → 多模态AI理解 + 互动决策 + 评论生成
  MomentsActor     → 点赞/评论/发圈执行
  MomentsGuard     → 朋友圈专用风控
  ContactProfile   → 社交画像 + 亲密度系统
  MomentsTracker   → 评论链跟进 + 30天内容日历
"""

from .adapter import WeChatAdapter
from .models import WxMessage, WxChat, TrackStatus

__all__ = ["WeChatAdapter", "WxMessage", "WxChat", "TrackStatus"]
