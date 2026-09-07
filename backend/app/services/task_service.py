"""注册任务编排（§12/§13/§14）：创建 -> 申请邮箱 -> 等待邮件 -> 匹配 -> 结果 -> 回调。"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.db import utcnow
from ..core.events import bus
from ..core.ids import new_id
from ..models import Mailbox, ParseResult, Pool, RegistrationTask
from . import pool_service, webhook_service
from .audit import audit
from .parser_service import match_sender, match_subject

logger = logging.getLogger("mailhub.task")

WAITING_STATES = ("WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED", "PARSING")
TERMINAL_STATES = ("COMPLETED", "TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR", "CANCELLED")


class TaskError(Exception):
    pass


def default_match() -> dict:
    return {"sender": "", "subject_contains": ""}


async def get_by_idempotency_key(session: AsyncSession, key: str) -> RegistrationTask | None:
    if not key:
        return None
    return (
        await session.execute(select(RegistrationTask).where(RegistrationTask.idempotency_key == key))
    ).scalar_one_or_none()


async def create_task(
    session: AsyncSession,
    *,
    pool_id: str | None,
    target_ref: str,
    match: dict | None,
    timeout_seconds: int | None,
    callback_url: str | None,
    idempotency_key: str | None = None,
    project_key: str | None = None,
    caller_id: str | None = None,
    metadata: dict | None = None,
    actor_type: str = "api",
    actor_id: str = "",
    ip: str = "",
) -> tuple[RegistrationTask, bool]:
    """返回 (task, created)。幂等键命中时返回既有任务（§21）。"""
    if idempotency_key:
        existing = await get_by_idempotency_key(session, idempotency_key)
        if existing:
            return existing, False

    pool = await pool_service.get_pool(session, pool_id)
    task = RegistrationTask(
        id=new_id("task"),
        idempotency_key=idempotency_key,
        external_ref=target_ref or "",
        pool_id=pool.id if pool else None,
        state="CREATED",
        match_json={**default_match(), **(match or {})},
        timeout_seconds=timeout_seconds or settings.task_default_timeout,
        callback_url=callback_url,
        project_key=project_key,
        caller_id=caller_id,
        metadata_json=metadata or {},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(task)
    await session.flush()

    # 立即尝试分配邮箱；失败则进入 WAITING_MAILBOX 由后台重试
    try:
        mailbox = await pool_service.allocate(
            session, pool, project_key=project_key, actor_type=actor_type, actor_id=actor_id, ip=ip
        )
        task.mailbox_id = mailbox.id
        task.state = "WAITING_EMAIL"
    except pool_service.PoolEmptyError:
        task.state = "WAITING_MAILBOX"
    task.expires_at = utcnow() + timedelta(seconds=task.timeout_seconds)
    task.updated_at = utcnow()

    await audit(
        session, "task.create", resource_type="registration_task", resource_id=task.id,
        actor_type=actor_type, actor_id=actor_id, ip=ip,
        metadata={"target_ref": task.external_ref, "state": task.state, "pool_id": task.pool_id,
                  "project_key": project_key, "caller_id": caller_id},
    )
    await bus.publish(
        "task.started",
        {"task_id": task.id, "external_ref": task.external_ref, "state": task.state,
         "mailbox_id": task.mailbox_id, "project_key": project_key},
    )
    return task, True


async def try_allocate_waiting(session: AsyncSession, task: RegistrationTask) -> bool:
    """WAITING_MAILBOX 任务的补分配。"""
    if task.state != "WAITING_MAILBOX":
        return False
    pool = await session.get(Pool, task.pool_id) if task.pool_id else await pool_service.get_pool(session, None)
    try:
        mailbox = await pool_service.allocate(session, pool, actor_type="system", actor_id="task_monitor")
    except pool_service.PoolEmptyError:
        return False
    task.mailbox_id = mailbox.id
    task.state = "WAITING_EMAIL"
    task.updated_at = utcnow()
    await bus.publish("task.started", {"task_id": task.id, "state": task.state, "mailbox_id": mailbox.id})
    return True


def _match_ok(match: dict, message) -> bool:
    sender_pattern = (match or {}).get("sender") or ""
    if sender_pattern and not match_sender(sender_pattern, message.sender):
        return False
    subject_contains = (match or {}).get("subject_contains") or ""
    if subject_contains and subject_contains.lower() not in (message.subject or "").lower():
        return False
    return True


async def match_mail(session: AsyncSession, message, results: list[ParseResult]) -> None:
    """新邮件解析后绑定等待中的任务（Task 与 Message 分离，通过匹配器关联 §26.4）。"""
    tasks = (
        await session.execute(
            select(RegistrationTask)
            .where(
                RegistrationTask.state == "WAITING_EMAIL",
                RegistrationTask.mailbox_id == message.mailbox_id,
            )
        )
    ).scalars().all()
    if not tasks:
        return

    mailbox = await session.get(Mailbox, message.mailbox_id)
    now = utcnow()
    for task in tasks:
        if task.expires_at and task.expires_at < now:
            continue
        # 只匹配任务创建后收到的邮件，避免绑定到邮箱里残留的旧验证码（旧码已过期会导致 wrong code）
        msg_received = getattr(message, "received_at", None)
        if msg_received and task.created_at and msg_received < task.created_at:
            continue
        if not _match_ok(task.match_json, message):
            continue
        task.state = "EMAIL_RECEIVED"
        task.metadata_json = {**(task.metadata_json or {}), "matched_message_id": message.id}
        task.updated_at = now

        best = results[0] if results else None
        if best is not None:
            task.result_id = best.id
            task.state = "WAITING_CALLBACK" if task.callback_url else "COMPLETED"
            task.updated_at = utcnow()
            result_payload = {"type": best.result_type, "value": None}  # 值由查询接口解密返回；webhook 中携带
            from .parser_service import decrypt_result

            decrypted = decrypt_result(best)
            await bus.publish(
                "mail.result.ready",
                {
                    "task_id": task.id,
                    "external_ref": task.external_ref,
                    "message_id": message.id,
                    "result": {"type": decrypted["type"], "value": decrypted["value"]},
                },
            )
            # 触发通知（异步，不阻塞主流程）
            try:
                import asyncio
                from . import notification_service
                asyncio.create_task(notification_service.notify_task_completed(
                    task_id=task.id,
                    external_ref=task.external_ref,
                    mailbox_email=mailbox.email if mailbox else "",
                    result_type=decrypted["type"],
                    result_value=decrypted["value"],
                ))
            except Exception:
                pass
            if task.callback_url:
                payload = webhook_service.build_payload(
                    "mail.result.ready", task, mailbox, {"type": decrypted["type"], "value": decrypted["value"]}
                )
                await webhook_service.enqueue(session, task, "mail.result.ready", payload)
                task.callback_state = "PENDING"
            else:
                await pool_service.release(session, mailbox)
                await bus.publish("task.completed", {"task_id": task.id, "external_ref": task.external_ref})
            await audit(
                session, "task.result_ready", resource_type="registration_task", resource_id=task.id,
                actor_type="system", metadata={"result_type": decrypted["type"], "message_id": message.id},
            )


async def cancel_task(session: AsyncSession, task: RegistrationTask, actor_id: str = "", ip: str = "") -> None:
    if task.state in TERMINAL_STATES:
        raise TaskError(f"task in terminal state {task.state}")
    mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
    task.state = "CANCELLED"
    task.updated_at = utcnow()
    await pool_service.release(session, mailbox)
    await audit(session, "task.cancel", resource_type="registration_task", resource_id=task.id, actor_id=actor_id, ip=ip)
    await bus.publish("task.failed", {"task_id": task.id, "reason": "cancelled"})


async def sweep_timeouts(session: AsyncSession) -> int:
    """超时任务：TIMEOUT + 释放邮箱（§12 异常路径）。"""
    now = utcnow()
    tasks = (
        await session.execute(
            select(RegistrationTask)
            .where(RegistrationTask.state.in_(WAITING_STATES), RegistrationTask.expires_at.is_not(None), RegistrationTask.expires_at < now)
            .limit(100)
        )
    ).scalars().all()
    for task in tasks:
        mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
        task.state = "TIMEOUT"
        task.updated_at = utcnow()
        await pool_service.release(session, mailbox)
        await audit(session, "task.timeout", resource_type="registration_task", resource_id=task.id, actor_type="system")
        await bus.publish("task.failed", {"task_id": task.id, "external_ref": task.external_ref, "reason": "timeout"})
    return len(tasks)


def result_payload(task: RegistrationTask, results: list[ParseResult]) -> dict:
    from .parser_service import decrypt_result

    result = None
    if task.result_id:
        for r in results:
            if r.id == task.result_id:
                d = decrypt_result(r)
                result = {"type": d["type"], "value": d["value"], "confidence": d["confidence"]}
                break
    return {"task_id": task.id, "status": task.state, "result": result}
