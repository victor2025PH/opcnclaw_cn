# -*- coding: utf-8 -*-
"""
全局事件总线 + SSE/WebSocket 双通道推送 + 关键事件持久化

升级记录：
  v1: 纯 SSE 单向推送
  v2: SSE + WebSocket 双通道、客户端事件过滤
  v3: 关键事件 SQLite 持久化、重启恢复、按 ID 补发

设计决策：
  并非所有事件都需要持久化 —— broadcast_progress 等高频低价值事件
  只走内存；anomaly_alert / daily_report / system_event 等关键事件
  写入 SQLite，重启后自动恢复到 _history 供新客户端补发。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from loguru import logger

from . import db as _db

_PERSIST_TYPES = frozenset({
    "anomaly_alert", "daily_report", "system_event",
    "broadcast_complete", "workflow_event", "circuit_breaker",
})

_DB_PATH = Path("data/events.db")  # keep for compat
_db_lock = threading.Lock()


def _init_db() -> sqlite3.Connection:
    return _db.get_conn("main")


class EventBus:
    """
    轻量级进程内事件总线。
    支持 SSE / WebSocket 双通道，关键事件 SQLite 持久化。
    """

    def __init__(self, max_history: int = 200):
        self._subscribers: Set[asyncio.Queue] = set()
        self._ws_clients: Dict[int, "_WSClient"] = {}
        self._history: List[Dict] = []
        self._max_history = max_history
        self._event_id_counter = 0
        self._db: Optional[sqlite3.Connection] = None
        self._restore_from_db()

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = _init_db()
        return self._db

    def _restore_from_db(self):
        """启动时恢复最近的持久化事件到内存"""
        try:
            conn = self._get_db()
            cutoff = time.time() - 86400
            rows = conn.execute(
                "SELECT id, type, data, timestamp FROM events WHERE timestamp > ? ORDER BY id DESC LIMIT ?",
                (cutoff, self._max_history),
            ).fetchall()
            for row in reversed(rows):
                try:
                    data = json.loads(row["data"])
                except Exception:
                    data = {}
                evt = {"id": row["id"], "type": row["type"], "data": data, "timestamp": row["timestamp"]}
                self._history.append(evt)
                self._event_id_counter = max(self._event_id_counter, row["id"])
            if self._history:
                logger.info(f"EventBus: restored {len(self._history)} events from DB")
        except Exception as e:
            logger.warning(f"EventBus restore failed: {e}")

    def publish(self, event_type: str, data: Any = None, **kwargs):
        """发布事件到所有订阅者（SSE + WebSocket），关键事件持久化"""
        self._event_id_counter += 1
        event = {
            "id": self._event_id_counter,
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            **kwargs,
        }
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        if event_type in _PERSIST_TYPES:
            self._persist(event)

        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

        ws_dead = []
        for cid, client in self._ws_clients.items():
            if client.accepts(event_type):
                try:
                    client.queue.put_nowait(event)
                except asyncio.QueueFull:
                    ws_dead.append(cid)
        for cid in ws_dead:
            self._ws_clients.pop(cid, None)

    def _persist(self, event: Dict):
        try:
            conn = self._get_db()
            data_json = json.dumps(event.get("data"), ensure_ascii=False, default=str)
            with _db_lock:
                conn.execute(
                    "INSERT INTO events (type, data, timestamp) VALUES (?, ?, ?)",
                    (event["type"], data_json, event["timestamp"]),
                )
                # 自动清理 30 天前的事件
                conn.execute("DELETE FROM events WHERE timestamp < ?", (time.time() - 86400 * 30,))
                conn.commit()
        except Exception as e:
            logger.warning(f"Event persist failed: {e}")

    async def subscribe(self, last_event_id: int = 0) -> AsyncGenerator[Dict, None]:
        """订阅事件流（SSE 客户端使用），支持按 ID 补发"""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.add(q)

        if last_event_id > 0:
            for evt in self._history:
                if evt.get("id", 0) > last_event_id:
                    yield evt

        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self._subscribers.discard(q)

    def register_ws(self, client_id: int, filters: Optional[Set[str]] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._ws_clients[client_id] = _WSClient(queue=q, filters=filters)
        return q

    def unregister_ws(self, client_id: int):
        self._ws_clients.pop(client_id, None)

    def update_ws_filters(self, client_id: int, filters: Set[str]):
        client = self._ws_clients.get(client_id)
        if client:
            client.filters = filters if filters else None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers) + len(self._ws_clients)

    @property
    def ws_count(self) -> int:
        return len(self._ws_clients)

    def recent_events(self, limit: int = 20, event_type: str = "") -> List[Dict]:
        events = self._history
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return events[-limit:]

    def get_persist_stats(self) -> Dict:
        try:
            conn = self._get_db()
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            since_24h = conn.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp > ?", (time.time() - 86400,)
            ).fetchone()[0]
            return {"persisted_total": total, "persisted_24h": since_24h, "memory_events": len(self._history)}
        except Exception:
            return {"persisted_total": 0, "persisted_24h": 0, "memory_events": len(self._history)}


class _WSClient:
    __slots__ = ("queue", "filters")

    def __init__(self, queue: asyncio.Queue, filters: Optional[Set[str]] = None):
        self.queue = queue
        self.filters = filters

    def accepts(self, event_type: str) -> bool:
        return self.filters is None or event_type in self.filters


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


def publish(event_type: str, data: Any = None, **kwargs):
    """全局快捷发布"""
    _bus.publish(event_type, data, **kwargs)
