"""进程内事件总线 + 事件持久化，用于 SSE 实时推送（§18）。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from .db import get_sessionmaker, utcnow
from .ids import new_event_id

logger = logging.getLogger("mailhub.events")

MAX_QUEUE = 500


def _serialize(payload: dict) -> dict:
    out = {}
    for k, v in payload.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


class EventBus:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._bg_tasks: set[asyncio.Task] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event_type: str, payload: dict | None = None) -> str:
        event_id = new_event_id()
        record = {
            "event_id": event_id,
            "type": event_type,
            "payload": _serialize(payload or {}),
            "created_at": utcnow().isoformat(),
        }
        # 实时分发（内存，永不阻塞业务事务）
        for q in list(self._subscribers):
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                pass
        # 持久化走后台任务 + 重试：避免与请求事务争 SQLite 写锁（database is locked）
        task = asyncio.get_running_loop().create_task(self._persist(record))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return event_id

    async def _persist(self, record: dict, max_attempts: int = 6) -> None:
        for attempt in range(max_attempts):
            try:
                sessionmaker = get_sessionmaker()
                async with sessionmaker() as session:
                    from sqlalchemy import insert

                    from ..models import EventLog

                    await session.execute(
                        insert(EventLog).values(
                            event_type=record["type"], payload_json=record["payload"], event_id=record["event_id"]
                        )
                    )
                    await session.commit()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == max_attempts - 1:
                    logger.exception("failed to persist event %s", record["type"])
                else:
                    await asyncio.sleep(0.3 * (attempt + 1))


bus = EventBus()


async def recent_events(limit: int = 100) -> list[dict]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from sqlalchemy import select

        from ..models import EventLog

        rows = (
            (await session.execute(select(EventLog).order_by(EventLog.id.desc()).limit(limit))).scalars().all()
        )
        return [
            {
                "event_id": r.event_id,
                "type": r.event_type,
                "payload": r.payload_json or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reversed(rows)
        ]


def dumps(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, default=str)
