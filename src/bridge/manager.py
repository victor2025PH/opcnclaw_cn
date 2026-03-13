"""
IM 平台桥接管理器

设计原则：
- 每种 IM 只实现最简单的接入方式，减少配置门槛
- 飞书/企业微信/钉钉都支持 Webhook 机器人（最简单，只需一个URL）
- 高级版本（接收消息）可后续接入
"""
import asyncio
from typing import Optional, Dict

from loguru import logger


class BridgeManager:
    """统一管理所有 IM 平台的桥接"""

    def __init__(self, cfg=None):
        self.cfg = cfg
        self._bridges: Dict[str, "BaseBridge"] = {}
        self._loaded = False

    def load_from_config(self):
        """从配置加载启用的桥接"""
        if not self.cfg:
            return
        try:
            # 飞书
            feishu_url = self.cfg._cfg.get("bridge.feishu", "webhook_url", fallback="")
            if feishu_url:
                from .feishu import FeishuBridge
                self._bridges["feishu"] = FeishuBridge(webhook_url=feishu_url)
                logger.info("✅ 飞书桥接已启动")

            # 企业微信桥接已禁用（如需启用请去掉下方注释）
            # wecom_url = self.cfg._cfg.get("bridge.wecom", "webhook_url", fallback="")
            # if wecom_url:
            #     from .wecom import WeComBridge
            #     self._bridges["wecom"] = WeComBridge(webhook_url=wecom_url)
            #     logger.info("✅ 企业微信桥接已启动")

            # 钉钉
            dingtalk_url = self.cfg._cfg.get("bridge.dingtalk", "webhook_url", fallback="")
            if dingtalk_url:
                from .dingtalk import DingTalkBridge
                self._bridges["dingtalk"] = DingTalkBridge(webhook_url=dingtalk_url)
                logger.info("✅ 钉钉桥接已启动")

        except Exception as e:
            logger.warning(f"IM 桥接加载失败: {e}")

        self._loaded = True

    async def broadcast(self, message: str, title: str = ""):
        """向所有已配置的 IM 平台发送消息"""
        for name, bridge in self._bridges.items():
            try:
                await bridge.send_text(message, title=title)
            except Exception as e:
                logger.warning(f"{name} 发送失败: {e}")

    async def send_to(self, platform: str, message: str, title: str = ""):
        """向指定平台发送消息"""
        bridge = self._bridges.get(platform)
        if bridge:
            await bridge.send_text(message, title=title)

    @property
    def active_platforms(self):
        return list(self._bridges.keys())


class BaseBridge:
    """IM 桥接基类"""
    async def send_text(self, text: str, title: str = "") -> bool:
        raise NotImplementedError

    async def send_markdown(self, content: str, title: str = "") -> bool:
        return await self.send_text(content, title)


# 全局实例
_manager: Optional[BridgeManager] = None


def get_bridge_manager() -> BridgeManager:
    global _manager
    if _manager is None:
        _manager = BridgeManager()
    return _manager
