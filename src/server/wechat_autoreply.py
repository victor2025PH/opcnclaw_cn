# -*- coding: utf-8 -*-
"""
微信自动回复引擎

安全设计原则：
  1. 白名单制度 — 默认不回复任何人，必须显式添加才启用
  2. 双重 OCR 验证 — 发送前验证联系人身份（复用 desktop_skills）
  3. 静默时段 — 深夜不打扰
  4. 每日上限 — 防止 AI 刷屏
  5. 关键词黑名单 — 遇到敏感词跳过
  6. 人工审核模式 — 可选，所有回复先入队列等人确认
  7. 随机延迟 — 模拟真人打字节奏
  8. 一键紧急停止

数据持久化：
  配置和日志存储在 data/wechat_autoreply.json
"""

import asyncio
import json
import os
import random
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from loguru import logger

from .wechat_monitor import WeChatMessage, WeChatMonitor

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_FILE = DATA_DIR / "wechat_autoreply.json"

# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class ContactRule:
    """单个联系人的自动回复规则"""
    name: str                        # 联系人名（必须与微信好友名一致）
    enabled: bool = True             # 是否启用自动回复
    is_group: bool = False           # 是否群聊
    group_reply_only_at_me: bool = True  # 群聊时只在被 @ 时回复
    persona: str = ""                # 专属人设（空=使用全局人设）
    daily_limit: int = 20            # 每日最多回复条数
    reply_count_today: int = 0       # 今日已回复
    last_reset_date: str = ""        # 最后重置日期 (YYYY-MM-DD)
    context_window: int = 8          # 保留的历史轮次数
    history: List[Dict] = field(default_factory=list)  # 对话历史

    def reset_daily_count_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.last_reset_date != today:
            self.reply_count_today = 0
            self.last_reset_date = today

    def can_reply(self) -> bool:
        self.reset_daily_count_if_needed()
        return self.enabled and self.reply_count_today < self.daily_limit

    def record_reply(self):
        self.reset_daily_count_if_needed()
        self.reply_count_today += 1

    def add_history(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        # 保留最近 N 轮（每轮 user+assistant 共 2 条）
        max_msgs = self.context_window * 2
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]


@dataclass
class PendingReply:
    """等待人工审核的回复"""
    id: str
    contact: str
    incoming_msg: str
    ai_reply: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / approved / rejected / expired


@dataclass
class ReplyLog:
    """回复日志记录"""
    timestamp: float
    contact: str
    incoming: str
    reply: str
    success: bool
    mode: str = "auto"  # auto / manual


# ── 配置 ──────────────────────────────────────────────────────────────────────

@dataclass
class AutoReplyConfig:
    """全局配置"""
    enabled: bool = False              # 总开关
    manual_review: bool = False        # 人工审核模式
    smart_mode: bool = True            # v2.0 智能模式（意图分类+情感分析+批处理+升级决策）
    global_persona: str = (
        "你是用户的智能助理，正在代替用户回复微信消息。"
        "回复要自然简短，符合中文聊天习惯，不要太正式。"
        "不要暴露你是 AI。"
    )
    quiet_start: str = "23:00"        # 静默开始时间
    quiet_end: str = "07:00"          # 静默结束时间
    min_reply_delay: float = 1.5      # 最短回复延迟（秒）
    max_reply_delay: float = 5.0      # 最长回复延迟（秒）
    batch_timeout: float = 4.0        # 消息批处理等待时间（秒）
    keyword_blacklist: List[str] = field(default_factory=lambda: [
        "密码", "验证码", "银行卡", "转账", "汇款",
        "身份证", "刷脸", "紧急", "救命",
    ])
    contacts: Dict[str, ContactRule] = field(default_factory=dict)
    reply_all: bool = False            # 全局回复模式（回复所有人，不需要白名单）


# ── 主引擎 ────────────────────────────────────────────────────────────────────

class WeChatAutoReply:
    """
    微信自动回复引擎

    与 WeChatMonitor 结合使用：
        monitor = WeChatMonitor(desktop)
        engine  = WeChatAutoReply(ai_backend, desktop)
        monitor.on_message(engine.handle_message)
        engine.start()
        monitor.start()
    """

    def __init__(self, ai_backend=None, desktop=None):
        self._backend = ai_backend      # src.server.backend.AIBackend 实例
        self._desktop = desktop         # src.server.desktop.DesktopStreamer 实例
        self._config = AutoReplyConfig()
        self._pending: Dict[str, PendingReply] = {}
        self._logs: List[ReplyLog] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 审核回调（前端 SSE 推送用）
        self._review_callbacks: List[Callable] = []
        # 升级回调
        self._escalation_callbacks: List[Callable] = []

        # v2.0 智能回复引擎
        self._smart_engine = None

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_config()

    # ── 公开 API ─────────────────────────────────────────────────────────────

    def start(self):
        """启动引擎（获取当前事件循环）"""
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()

        # 初始化智能回复引擎
        if self._config.smart_mode and self._backend:
            try:
                from .wechat.reply_engine import SmartReplyEngine
                from .wechat.anti_risk import AntiRiskEngine

                anti_risk = AntiRiskEngine()
                self._smart_engine = SmartReplyEngine(
                    ai_fn=self._backend.chat_simple,
                    anti_risk=anti_risk,
                    batch_timeout=self._config.batch_timeout,
                )
                self._smart_engine.set_event_loop(self._loop)

                # 智能引擎回复回调 → 发送消息
                self._smart_engine.on_reply(self._on_smart_reply)
                # 智能引擎升级回调 → 推送前端
                self._smart_engine.on_escalation(self._on_smart_escalation)

                logger.info("✅ 智能回复引擎 (SmartReplyEngine) 已启动")
            except Exception as e:
                logger.warning(f"智能回复引擎启动失败，降级到基础模式: {e}")
                self._smart_engine = None

        logger.info("✅ WeChatAutoReply 引擎已启动")

    def handle_message(self, msg: WeChatMessage):
        """消息回调入口（由 WeChatMonitor 调用）"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._process_message(msg), self._loop
            )
        else:
            # 降级：在新线程中跑同步版本
            threading.Thread(
                target=self._process_message_sync,
                args=(msg,),
                daemon=True
            ).start()

    def on_review_needed(self, callback: Callable):
        """注册人工审核回调（新待审核消息时触发）"""
        self._review_callbacks.append(callback)

    def approve_reply(self, reply_id: str) -> bool:
        """人工审核：批准发送"""
        with self._lock:
            pr = self._pending.get(reply_id)
            if not pr or pr.status != "pending":
                return False
            pr.status = "approved"
        threading.Thread(
            target=self._send_reply,
            args=(pr.contact, pr.ai_reply, pr.incoming_msg),
            daemon=True
        ).start()
        return True

    def reject_reply(self, reply_id: str) -> bool:
        """人工审核：拒绝发送"""
        with self._lock:
            pr = self._pending.get(reply_id)
            if not pr or pr.status != "pending":
                return False
            pr.status = "rejected"
        return True

    def get_pending_reviews(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "id": pr.id,
                    "contact": pr.contact,
                    "incoming": pr.incoming_msg,
                    "reply": pr.ai_reply,
                    "created_at": pr.created_at,
                }
                for pr in self._pending.values()
                if pr.status == "pending"
            ]

    def on_escalation(self, callback: Callable):
        """注册升级通知回调"""
        self._escalation_callbacks.append(callback)

    def get_escalations(self) -> List[Dict]:
        """获取待处理的升级列表"""
        if self._smart_engine:
            return self._smart_engine.get_escalations(status="pending")
        return []

    def handle_escalation(self, eid: str, action: str, reply: str = "") -> bool:
        """处理升级项（send_draft/send_custom/dismiss）"""
        if self._smart_engine:
            return self._smart_engine.handle_escalation(eid, action, reply)
        return False

    def get_stats(self) -> Dict:
        cfg = self._config
        result = {
            "enabled": cfg.enabled,
            "manual_review": cfg.manual_review,
            "smart_mode": cfg.smart_mode,
            "contacts": {
                name: {
                    "enabled": rule.enabled,
                    "daily_limit": rule.daily_limit,
                    "reply_count_today": rule.reply_count_today,
                    "is_group": rule.is_group,
                }
                for name, rule in cfg.contacts.items()
            },
            "pending_count": len([p for p in self._pending.values() if p.status == "pending"]),
            "total_replied": len(self._logs),
            "today_replied": sum(
                1 for log in self._logs
                if datetime.fromtimestamp(log.timestamp).strftime("%Y-%m-%d")
                   == datetime.now().strftime("%Y-%m-%d")
            ),
            "logs": [
                {
                    "time": datetime.fromtimestamp(log.timestamp).strftime("%H:%M"),
                    "contact": log.contact,
                    "incoming": log.incoming[:30],
                    "reply": log.reply[:30],
                    "success": log.success,
                    "mode": log.mode,
                }
                for log in self._logs[-20:]
            ],
        }
        # 智能引擎统计
        if self._smart_engine:
            result["smart_engine"] = self._smart_engine.get_stats()
        return result

    # ── 智能引擎回调 ──────────────────────────────────────────────────────

    def _on_smart_reply(self, contact: str, reply_text: str, analysis):
        """SmartReplyEngine 生成回复后的回调"""
        rule = self._config.contacts.get(contact)
        if not rule:
            return

        if self._config.manual_review:
            self._queue_for_review_ext(contact, reply_text, analysis)
        else:
            self._send_reply(contact, reply_text, "")
            rule.record_reply()
            if rule.history is not None:
                rule.add_history("assistant", reply_text)
            self._save_config()

        # 记录日志带意图/情感标签
        intent = getattr(analysis, 'intent', '')
        emotion = getattr(analysis, 'emotion', '')
        mode = f"smart:{intent}" if intent else "smart"
        self._logs.append(ReplyLog(
            timestamp=time.time(),
            contact=contact,
            incoming=f"[{emotion}] " if emotion and emotion != "neutral" else "",
            reply=reply_text,
            success=True,
            mode=mode,
        ))
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]

    def _on_smart_escalation(self, item):
        """SmartReplyEngine 触发升级的回调"""
        logger.warning(f"🚨 升级通知: {item.contact} — {item.reason}")
        for cb in self._escalation_callbacks:
            try:
                cb(item)
            except Exception:
                pass

    def _queue_for_review_ext(self, contact: str, reply: str, analysis):
        """将智能回复加入审核队列（含分析信息）"""
        import uuid
        intent = getattr(analysis, 'intent', '')
        emotion = getattr(analysis, 'emotion', '')
        pr = PendingReply(
            id=str(uuid.uuid4())[:8],
            contact=contact,
            incoming_msg=f"[{intent}/{emotion}]",
            ai_reply=reply,
        )
        with self._lock:
            self._pending[pr.id] = pr
        for cb in self._review_callbacks:
            try:
                cb(pr)
            except Exception:
                pass

    # ── 配置管理 ─────────────────────────────────────────────────────────────

    def update_config(self, updates: Dict) -> bool:
        """更新全局配置"""
        try:
            for k, v in updates.items():
                if hasattr(self._config, k) and k != "contacts":
                    setattr(self._config, k, v)
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"update_config: {e}")
            return False

    def add_contact(self, name: str, **kwargs) -> ContactRule:
        """添加联系人到白名单"""
        rule = ContactRule(name=name, **kwargs)
        self._config.contacts[name] = rule
        self._save_config()
        logger.info(f"✅ 白名单新增：{name}")
        return rule

    def remove_contact(self, name: str) -> bool:
        """从白名单移除联系人"""
        if name in self._config.contacts:
            del self._config.contacts[name]
            self._save_config()
            return True
        return False

    def toggle_contact(self, name: str, enabled: bool) -> bool:
        """启用/禁用某联系人的自动回复"""
        if name in self._config.contacts:
            self._config.contacts[name].enabled = enabled
            self._save_config()
            return True
        return False

    # ── 消息处理核心 ─────────────────────────────────────────────────────────

    async def _process_message(self, msg: WeChatMessage):
        """异步处理一条新消息"""
        try:
            # 写入统一收件箱 + 健康度追踪 + 通知聚合
            try:
                from .wechat.unified_inbox import ingest_message
                from .wechat.account_health import get_health_monitor
                from .notification_aggregator import get_aggregator
                acct_id = getattr(self, '_account_id', 'default')
                ingest_message(acct_id, msg.contact, msg.sender, msg.content,
                               is_group=msg.is_group, is_mine=msg.is_mine, timestamp=msg.timestamp)
                get_health_monitor().record_receive(acct_id)
                get_aggregator().ingest(acct_id, msg.contact, msg.sender, msg.content,
                                        is_group=msg.is_group, at_me=msg.at_me, timestamp=msg.timestamp)
                # 情感分析记录
                from .sentiment_analyzer import record as sentiment_record
                sentiment_record(acct_id, msg.contact, msg.content, msg.timestamp)
                # 群聊管理
                if msg.is_group:
                    from .wechat.group_manager import get_group_manager
                    gm_result = get_group_manager().process_message(
                        msg.contact, msg.sender, msg.content, msg.timestamp)
                    if gm_result.get("welcome") and not msg.is_mine:
                        self._send_reply(msg.contact, gm_result["welcome"], msg.content)
            except Exception:
                pass

            # ⓪ 评论链跟进：检测"回复了你的评论"通知
            if self._config.enabled and msg.content:
                await self._check_comment_chain(msg)

            # ⓪b 消息智能路由：关键词匹配 → 自动触发动作
            if msg.content:
                await self._check_msg_route(msg)

            # ① 总开关检查
            if not self._config.enabled:
                return

            # ② 白名单检查（或全局回复模式）
            rule = self._config.contacts.get(msg.contact)
            reply_all = getattr(self._config, 'reply_all', False)
            if not rule and not reply_all:
                logger.debug(f"[AutoReply] 跳过非白名单联系人：{msg.contact}")
                return

            # reply_all 模式：为未注册联系人创建/复用临时规则（保留上下文）
            if not rule and reply_all:
                if not hasattr(self, '_temp_rules'):
                    self._temp_rules = {}
                if msg.contact not in self._temp_rules:
                    self._temp_rules[msg.contact] = ContactRule(name=msg.contact)
                rule = self._temp_rules[msg.contact]

            # ③ 单人开关
            if not rule.enabled:
                return

            # ④ 群聊规则
            if msg.is_group and rule.group_reply_only_at_me and not msg.at_me:
                logger.debug(f"[AutoReply] 群聊未@我，跳过")
                return

            # ⑤ 静默时段
            if self._in_quiet_hours():
                logger.debug(f"[AutoReply] 静默时段，跳过")
                return

            # ⑥ 每日上限
            if not rule.can_reply():
                logger.debug(f"[AutoReply] {msg.contact} 今日已达上限 {rule.daily_limit}")
                return

            # ⑦ 关键词黑名单
            blocked = self._check_blacklist(msg.content)
            if blocked:
                logger.warning(f"[AutoReply] 消息含黑名单词「{blocked}」，跳过")
                return

            # ⑧ 智能模式 vs 基础模式
            if self._smart_engine and self._config.smart_mode:
                # v2.0 智能模式：消息进入批处理队列
                persona = rule.persona or self._config.global_persona
                self._smart_engine.queue_message(
                    contact=msg.contact,
                    sender=msg.sender or msg.contact,
                    content=msg.content,
                    history=list(rule.history),
                    persona=persona,
                    is_group=msg.is_group,
                    at_me=msg.at_me,
                    daily_count=rule.reply_count_today,
                    daily_limit=rule.daily_limit,
                )
                # 回复由 SmartReplyEngine 异步触发 _on_smart_reply 回调
            else:
                # 基础模式：直接生成回复
                reply = await self._generate_reply(msg, rule)
                if not reply:
                    return

                if self._config.manual_review:
                    self._queue_for_review(msg, reply)
                else:
                    delay = random.uniform(
                        self._config.min_reply_delay,
                        self._config.max_reply_delay
                    )
                    await asyncio.sleep(delay)
                    self._send_reply(msg.contact, reply, msg.content)
                    rule.record_reply()
                    self._save_config()

        except Exception as e:
            logger.error(f"[AutoReply] process_message error: {e}")

    async def _check_msg_route(self, msg: WeChatMessage):
        """消息智能路由：检查是否匹配自动触发规则"""
        try:
            from .wechat.msg_router import MessageRouter
            if not hasattr(self.__class__, '_msg_router'):
                self.__class__._msg_router = MessageRouter()
            result = await self.__class__._msg_router.route(msg.contact, msg.content)
            if result:
                logger.info(f"[MsgRoute] 触发规则: {result.get('rule_name', '?')}")
        except Exception as e:
            logger.debug(f"[MsgRoute] 路由检查失败: {e}")

    async def _check_comment_chain(self, msg: WeChatMessage):
        """检测微信通知中的评论回复，自动生成二次回复"""
        try:
            if not ("回复了你" in msg.content or "评论了你" in msg.content):
                return

            from .wechat.moments_tracker import CommentChainTracker
            global _chain_tracker_instance
            if "_chain_tracker_instance" not in globals() or _chain_tracker_instance is None:
                ai_call = self._backend.chat_simple if self._backend else None
                _chain_tracker_instance = CommentChainTracker(ai_call=ai_call)

            followup = await _chain_tracker_instance.check_notification(
                msg.contact, msg.content
            )
            if followup:
                logger.info(f"[CommentChain] 评论链跟进 → {msg.contact}: {followup[:30]}")
        except Exception as e:
            logger.debug(f"[CommentChain] 检测失败: {e}")

    def _process_message_sync(self, msg: WeChatMessage):
        """同步版本的消息处理（备用）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._process_message(msg))
        finally:
            loop.close()

    async def _generate_reply(self, msg: WeChatMessage, rule: ContactRule) -> str:
        """调用 AI 后端生成回复"""
        if not self._backend:
            return ""
        try:
            persona = rule.persona or self._config.global_persona
            system_prompt = (
                f"{persona}\n\n"
                f"当前对话联系人：{msg.contact}\n"
                f"{'（群聊）' if msg.is_group else '（私聊）'}"
            )
            # 构建带历史的消息列表
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(rule.history)
            messages.append({"role": "user", "content": msg.content})

            reply = await self._backend.chat_simple(messages)

            if reply:
                rule.add_history("user", msg.content)
                rule.add_history("assistant", reply)

            return reply or ""

        except Exception as e:
            logger.error(f"[AutoReply] generate_reply: {e}")
            return ""

    def _send_reply(self, contact: str, reply: str, incoming: str):
        """发送回复。优先 adapter（支持4.x），回退到 desktop_skills"""
        success = False

        # 1. 优先用 v2 adapter（支持微信 4.x UIA 发送）
        try:
            if _adapter is not None:
                success = _adapter.send_message(contact, reply)
                if success:
                    logger.info(f"[AutoReply] ✅ 已回复 {contact}: {reply[:30]}...")
        except Exception as e:
            logger.debug(f"[AutoReply] adapter send: {e}")

        # 2. 回退到 desktop_skills
        if not success:
            try:
                from .desktop_skills import execute_send_wechat_message
                if self._desktop:
                    result = execute_send_wechat_message(self._desktop, contact, reply)
                    success = result.success
                    if not success:
                        logger.warning(f"[AutoReply] 发送失败: {result.message}")
                else:
                    logger.warning("[AutoReply] 无 desktop 实例，无法发送")
            except Exception as e:
                logger.error(f"[AutoReply] send_reply: {e}")

        # 记录健康度指标
        try:
            from .wechat.account_health import get_health_monitor
            acct_id = getattr(self, '_account_id', 'default')
            if success:
                get_health_monitor().record_send(acct_id)
            else:
                get_health_monitor().record_error(acct_id, "send_failed")
        except Exception:
            pass

        self._logs.append(ReplyLog(
            timestamp=time.time(),
            contact=contact,
            incoming=incoming,
            reply=reply,
            success=success,
        ))
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]

    def _queue_for_review(self, msg: WeChatMessage, reply: str):
        """将回复加入人工审核队列"""
        import uuid
        pr = PendingReply(
            id=str(uuid.uuid4())[:8],
            contact=msg.contact,
            incoming_msg=msg.content,
            ai_reply=reply,
        )
        with self._lock:
            self._pending[pr.id] = pr

        logger.info(f"[AutoReply] 待审核回复已入队: {pr.id}")
        for cb in self._review_callbacks:
            try:
                cb(pr)
            except Exception:
                pass

    # ── 工具方法 ─────────────────────────────────────────────────────────────

    def _in_quiet_hours(self) -> bool:
        """检查是否处于静默时段"""
        try:
            now = datetime.now().time()
            qs = dtime(*map(int, self._config.quiet_start.split(":")))
            qe = dtime(*map(int, self._config.quiet_end.split(":")))
            if qs <= qe:
                return qs <= now <= qe
            else:  # 跨午夜（如 23:00 - 07:00）
                return now >= qs or now <= qe
        except Exception:
            return False

    def _check_blacklist(self, content: str) -> Optional[str]:
        """检查是否含黑名单关键词，返回命中的词或 None"""
        for kw in self._config.keyword_blacklist:
            if kw in content:
                return kw
        return None

    # ── 配置持久化 ────────────────────────────────────────────────────────────

    def _save_config(self):
        try:
            data = {
                "enabled": self._config.enabled,
                "manual_review": self._config.manual_review,
                "smart_mode": self._config.smart_mode,
                "global_persona": self._config.global_persona,
                "quiet_start": self._config.quiet_start,
                "quiet_end": self._config.quiet_end,
                "min_reply_delay": self._config.min_reply_delay,
                "max_reply_delay": self._config.max_reply_delay,
                "batch_timeout": self._config.batch_timeout,
                "keyword_blacklist": self._config.keyword_blacklist,
                "contacts": {
                    name: {
                        "name": rule.name,
                        "enabled": rule.enabled,
                        "is_group": rule.is_group,
                        "group_reply_only_at_me": rule.group_reply_only_at_me,
                        "persona": rule.persona,
                        "daily_limit": rule.daily_limit,
                        "reply_count_today": rule.reply_count_today,
                        "last_reset_date": rule.last_reset_date,
                        "context_window": rule.context_window,
                        "history": rule.history,
                    }
                    for name, rule in self._config.contacts.items()
                },
            }
            CONFIG_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[AutoReply] save_config: {e}")

    def _load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k in ("enabled", "manual_review", "smart_mode",
                      "global_persona", "quiet_start", "quiet_end",
                      "min_reply_delay", "max_reply_delay",
                      "batch_timeout", "keyword_blacklist"):
                if k in data:
                    setattr(self._config, k, data[k])

            for name, rd in data.get("contacts", {}).items():
                rule = ContactRule(
                    name=rd.get("name", name),
                    enabled=rd.get("enabled", True),
                    is_group=rd.get("is_group", False),
                    group_reply_only_at_me=rd.get("group_reply_only_at_me", True),
                    persona=rd.get("persona", ""),
                    daily_limit=rd.get("daily_limit", 20),
                    reply_count_today=rd.get("reply_count_today", 0),
                    last_reset_date=rd.get("last_reset_date", ""),
                    context_window=rd.get("context_window", 8),
                    history=rd.get("history", []),
                )
                self._config.contacts[name] = rule
            logger.info(f"[AutoReply] 配置已加载，{len(self._config.contacts)} 个白名单联系人")
        except Exception as e:
            logger.error(f"[AutoReply] load_config: {e}")


# ── 全局单例 ──────────────────────────────────────────────────────────────────
_monitor: Optional[WeChatMonitor] = None
_engine: Optional[WeChatAutoReply] = None
_adapter = None  # WeChatAdapter（v2.0 三轨融合）


def get_monitor() -> Optional[WeChatMonitor]:
    return _monitor


def get_engine() -> Optional[WeChatAutoReply]:
    return _engine


def get_adapter():
    """获取 v2.0 三轨融合适配器"""
    return _adapter


def init_wechat_autoreply(ai_backend=None, desktop=None) -> Tuple[WeChatMonitor, WeChatAutoReply]:
    """初始化并返回监控器和回复引擎"""
    global _monitor, _engine
    _monitor = WeChatMonitor(desktop=desktop)
    _engine = WeChatAutoReply(ai_backend=ai_backend, desktop=desktop)
    _monitor.on_message(_engine.handle_message)
    _engine.start()
    return _monitor, _engine


def init_wechat_v2(ai_backend=None, desktop=None):
    """
    初始化 v2.0 三轨融合系统。
    自动探测最优轨道（DB > wxauto > UIA > OCR），
    兼容旧版 API。
    """
    global _adapter, _monitor, _engine, _engine

    # 初始化新适配器
    try:
        from .wechat.adapter import WeChatAdapter

        _adapter = WeChatAdapter(desktop=desktop, ai_backend=ai_backend)

        # 初始化旧引擎（保持 API 兼容）
        _engine = WeChatAutoReply(ai_backend=ai_backend, desktop=desktop)
        _engine.start()

        # 新适配器的消息 → 旧引擎处理
        def _bridge_message(msg):
            wm = WeChatMessage(
                contact=msg.contact,
                sender=msg.sender,
                content=msg.content,
                is_group=msg.is_group,
                at_me=msg.at_me,
                raw_time_str=msg.raw_time_str if hasattr(msg, 'raw_time_str') else "",
            )
            _engine.handle_message(wm)

        _adapter.on_message(_bridge_message)

        # 旧监控器也保留，作为兼容层
        _monitor = WeChatMonitor(desktop=desktop)

        # 后台启动新适配器
        import threading
        threading.Thread(
            target=_adapter.start,
            name="WeChatAdapter-Init",
            daemon=True,
        ).start()

        # 自动将白名单联系人加入 wxauto 监听
        if _engine._config.contacts:
            names = list(_engine._config.contacts.keys())
            threading.Thread(
                target=lambda: (
                    __import__("time").sleep(3),
                    _adapter.add_listen(names),
                ),
                name="WeChatAdapter-Listen",
                daemon=True,
            ).start()

        logger.info("✅ 微信 v2.0 三轨融合系统已初始化")
        return _adapter, _engine

    except Exception as e:
        logger.warning(f"v2.0 初始化失败，降级到 v1.0: {e}")
        return init_wechat_autoreply(ai_backend, desktop)
