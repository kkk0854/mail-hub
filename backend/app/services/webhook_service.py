"""Webhook 分发（§13）：HMAC 签名、时间戳、幂等 event_id、指数退避重试。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import utcnow
from ..core.ids import new_event_id
from ..core.config import settings
from ..models import Mailbox, RegistrationTask, WebhookDelivery
from . import pool_service

logger = logging.getLogger("mailhub.webhook")

RETRY_SCHEDULE_SECONDS = [60, 300, 1800, 7200]  # §13 重试策略


def sign(timestamp: str, event_id: str, body: str, secret: str | None = None) -> str:
    secret = secret or settings.webhook_secret
    mac = hmac.new(secret.encode(), f"{timestamp}.{event_id}.{body}".encode(), hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def build_payload(event: str, task: RegistrationTask, mailbox: Mailbox | None, result: dict | None) -> dict:
    return {
        "event": event,
        "event_id": new_event_id(),
        "task_id": task.id,
        "mailbox_id": mailbox.id if mailbox else task.mailbox_id,
        "result": result,
        "timestamp": utcnow().isoformat(),
    }


async def enqueue(
    session: AsyncSession,
    task: RegistrationTask,
    event: str,
    payload: dict,
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        id=new_event_id().replace("evt_", "wh_"),
        event_id=payload["event_id"],
        task_id=task.id,
        url=task.callback_url or "",
        payload_json=payload,
        attempt=0,
        max_attempt=settings.webhook_max_attempts,
        state="PENDING",
        next_run_at=utcnow(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def deliver(delivery: WebhookDelivery) -> tuple[bool, int | None, str | None]:
    """发送一次 webhook。返回 (成功, 状态码, 错误)。body 序列化一次保证签名一致。"""
    body = json.dumps(delivery.payload_json, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-MailHub-Event-Id": delivery.event_id,
        "X-MailHub-Timestamp": timestamp,
        "X-MailHub-Signature": sign(timestamp, delivery.event_id, body),
    }
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.post(delivery.url, content=body.encode("utf-8"), headers=headers)
        return resp.status_code < 300, resp.status_code, None if resp.status_code < 300 else f"HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


async def dispatch_due(session: AsyncSession, limit: int = 10) -> int:
    """原子领取到期投递（SENDING 防多进程重复投递），成功回调驱动任务 COMPLETED（§14 状态机）。

    领取后进程崩溃的任务由调度器 stale-recover 兜底回收（§19）。
    """
    now = utcnow()
    subq = (
        select(WebhookDelivery.id)
        .where(WebhookDelivery.state.in_(("PENDING", "RETRYING")), WebhookDelivery.next_run_at <= now)
        .order_by(WebhookDelivery.next_run_at.asc())
        .limit(limit)
        .scalar_subquery()
    )
    stmt = (
        update(WebhookDelivery)
        .where(WebhookDelivery.id.in_(subq))
        .values(state="SENDING", updated_at=now)
        .returning(WebhookDelivery)
    )
    rows = (await session.execute(stmt)).scalars().all()
    await session.commit()

    for delivery in rows:
        task = await session.get(RegistrationTask, delivery.task_id) if delivery.task_id else None
        mailbox = await session.get(Mailbox, task.mailbox_id) if task and task.mailbox_id else None
        delivery.attempt += 1
        ok, status_code, error = await deliver(delivery)
        delivery.last_status_code = status_code
        delivery.last_error = error
        delivery.updated_at = utcnow()
        if ok:
            delivery.state = "SUCCESS"
            delivery.delivered_at = utcnow()
            if task and task.state == "WAITING_CALLBACK":
                task.state = "COMPLETED"
                task.callback_state = "DELIVERED"
                task.updated_at = utcnow()
                await pool_service.release(session, mailbox)
                from ..core.events import bus

                await bus.publish("task.completed", {"task_id": task.id, "external_ref": task.external_ref})
        else:
            if delivery.attempt >= delivery.max_attempt:
                delivery.state = "EXHAUSTED"
                if task:
                    task.callback_state = "FAILED"
                    task.updated_at = utcnow()
                from ..core.events import bus

                await bus.publish(
                    "task.failed",
                    {"task_id": task.id, "reason": "webhook_exhausted", "error": error},
                )
            else:
                delivery.state = "RETRYING"
                delay = RETRY_SCHEDULE_SECONDS[min(delivery.attempt - 1, len(RETRY_SCHEDULE_SECONDS) - 1)]
                delivery.next_run_at = utcnow() + timedelta(seconds=delay)
                from ..core.events import bus

                await bus.publish(
                    "task.retrying",
                    {"task_id": task.id, "kind": "webhook", "attempt": delivery.attempt, "next_run_at": delivery.next_run_at.isoformat()},
                )
    return len(rows)
