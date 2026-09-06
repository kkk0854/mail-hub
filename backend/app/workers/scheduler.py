"""后台 Worker 调度器：fetch_tasks 队列消费 + 周期任务（§10 事件驱动 + §19 退避重试）。"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from ..core.config import settings
from ..core.db import get_sessionmaker, utcnow
from ..core.events import bus
from ..models import FetchTask, Mailbox, Message
from ..services import (
    health_service,
    mailbox_service,
    message_service,
    parser_service,
    pool_service,
    task_service,
    webhook_service,
)

logger = logging.getLogger("mailhub.worker")

SYNC_BACKOFF_SECONDS = [30, 120, 300]  # §19 Attempt 1→30s→2m→5m→Warning
QUEUE_POLL_SECONDS = 2
MONITOR_INTERVAL_SECONDS = 5
WEBHOOK_INTERVAL_SECONDS = 10
COOLDOWN_INTERVAL_SECONDS = 30

EXCLUDED_FROM_SYNC = ("ARCHIVED", "DISABLED", "QUARANTINED")


async def claim_due_tasks(session, limit: int = 20) -> list[FetchTask]:
    now = utcnow()
    rows = (
        await session.execute(
            select(FetchTask)
            .where(FetchTask.state.in_(("QUEUED", "RETRYING")), FetchTask.next_run_at <= now)
            .order_by(FetchTask.next_run_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    for task in rows:
        task.state = "RUNNING"
        task.started_at = utcnow()
    await session.commit()
    return list(rows)


async def run_sync(session, task: FetchTask) -> None:
    mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
    if mailbox is None:
        raise RuntimeError("mailbox not found")
    provider = await mailbox_service.build_provider(session, mailbox)
    cursor = (mailbox.metadata_json or {}).get("sync_cursor", {})
    messages, new_cursor = await provider.sync_incremental(cursor)
    for msg in messages:
        await message_service.ingest_message(session, mailbox, msg)
    metadata = dict(mailbox.metadata_json or {})
    metadata["sync_cursor"] = new_cursor
    mailbox.metadata_json = metadata
    mailbox.last_sync_at = utcnow()
    logger.info("sync %s: %d new message(s)", mailbox.email, len(messages))


async def run_parse(session, task: FetchTask) -> None:
    message_id = (task.payload_json or {}).get("message_id")
    message = await session.get(Message, message_id) if message_id else None
    if message is None:
        raise RuntimeError("message not found")
    mailbox = await session.get(Mailbox, message.mailbox_id)
    results = await parser_service.parse_message(session, message, provider_type=mailbox.provider_type if mailbox else None)
    parsed_out = [parser_service.decrypt_result(r) for r in results]
    await bus.publish("mail.parsed", {"message_id": message.id, "mailbox_id": message.mailbox_id,
                                      "parse_status": message.parse_status,
                                      "results": [{"type": r["type"], "value": r["value"]} for r in parsed_out]})
    await task_service.match_mail(session, message, results)


async def execute_task(session, task: FetchTask) -> None:
    try:
        if task.task_type == "MAIL_SYNC":
            await run_sync(session, task)
        elif task.task_type == "HEALTH_CHECK":
            mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
            if mailbox is None:
                raise RuntimeError("mailbox not found")
            await health_service.run_health_check(session, mailbox, actor_type="worker", actor_id="queue")
        elif task.task_type == "MAIL_PARSE":
            await run_parse(session, task)
        else:
            raise RuntimeError(f"unknown task type {task.task_type}")
        task.state = "SUCCESS"
        task.finished_at = utcnow()
    except Exception as exc:
        task.attempt += 1
        task.error_code = getattr(exc, "error_code", type(exc).__name__)
        task.error_message = str(exc)[:500]
        logger.warning("fetch task %s (%s) failed: %s (attempt %s)", task.id, task.task_type, exc, task.attempt)
        if task.attempt >= task.max_attempt:
            task.state = "FAILED"
            task.finished_at = utcnow()
            if task.mailbox_id and task.task_type == "MAIL_SYNC":
                mailbox = await session.get(Mailbox, task.mailbox_id)
                if mailbox and mailbox.health_status in ("HEALTHY", None):
                    mailbox.health_status = "WARNING"  # §19 连续失败 → Warning
        else:
            task.state = "RETRYING"
            delay = SYNC_BACKOFF_SECONDS[min(task.attempt - 1, len(SYNC_BACKOFF_SECONDS) - 1)]
            task.next_run_at = utcnow() + timedelta(seconds=delay)
            await bus.publish("task.retrying", {"task_id": task.id, "kind": task.task_type,
                                                "attempt": task.attempt, "next_run_at": task.next_run_at.isoformat()})
    await session.commit()


class Scheduler:
    """进程内后台 Worker。API 内嵌或以独立进程运行（python -m app.workers.runner）。"""

    def __init__(self, concurrency: int | None = None):
        self.concurrency = concurrency or settings.worker_concurrency
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------ loops
    async def _queue_consumer(self, worker_id: int):
        sessionmaker = get_sessionmaker()
        logger.info("queue worker #%d started", worker_id)
        while not self._stopping.is_set():
            try:
                async with sessionmaker() as session:
                    tasks = await claim_due_tasks(session, limit=10)
                if not tasks:
                    await asyncio.sleep(QUEUE_POLL_SECONDS)
                    continue
                for task in tasks:
                    async with sessionmaker() as session:
                        fresh = await session.get(FetchTask, task.id)
                        if fresh and fresh.state == "RUNNING":
                            await execute_task(session, fresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("queue worker loop error")
                await asyncio.sleep(3)

    async def _periodic(self, name: str, interval: float, fn):
        sessionmaker = get_sessionmaker()
        while not self._stopping.is_set():
            try:
                async with sessionmaker() as session:
                    await fn(session)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("periodic %s error", name)
            await asyncio.sleep(interval)

    async def _schedule_sync(self, session):
        now = utcnow()
        mailboxes = (
            await session.execute(
                select(Mailbox).where(Mailbox.status.notin_(EXCLUDED_FROM_SYNC)).limit(500)
            )
        ).scalars().all()
        for mailbox in mailboxes:
            last = mailbox.last_sync_at
            if last and (now - last).total_seconds() < settings.sync_interval_seconds:
                continue
            session.add(FetchTask(id=f"ft_{mailbox.id[-8:]}sync{int(now.timestamp())}", mailbox_id=mailbox.id,
                                  task_type="MAIL_SYNC", state="QUEUED", next_run_at=now, scheduled_at=now,
                                  payload_json={"source": "scheduler"}))

    async def _schedule_health(self, session):
        now = utcnow()
        threshold = timedelta(seconds=settings.health_check_interval_seconds)
        mailboxes = (
            await session.execute(select(Mailbox).where(Mailbox.status.notin_(("ARCHIVED",))).limit(500))
        ).scalars().all()
        for mailbox in mailboxes:
            if mailbox.last_check_at and (now - mailbox.last_check_at) < threshold:
                continue
            session.add(FetchTask(id=f"ft_{mailbox.id[-8:]}hc{int(now.timestamp())}", mailbox_id=mailbox.id,
                                  task_type="HEALTH_CHECK", state="QUEUED", next_run_at=now, scheduled_at=now,
                                  payload_json={"source": "scheduler"}))

    async def _monitor_tasks(self, session):
        from ..models import RegistrationTask

        await task_service.sweep_timeouts(session)
        rows = (
            await session.execute(select(RegistrationTask).where(RegistrationTask.state == "WAITING_MAILBOX").limit(50))
        ).scalars().all()
        for task in rows:
            await task_service.try_allocate_waiting(session, task)

    async def _dispatch_webhooks(self, session):
        await webhook_service.dispatch_due(session)

    async def _sweep_cooldowns(self, session):
        await pool_service.sweep_cooldowns(session)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self._stopping.clear()
        for i in range(self.concurrency):
            self._tasks.append(asyncio.create_task(self._queue_consumer(i), name=f"queue-worker-{i}"))
        self._tasks.append(asyncio.create_task(
            self._periodic("sync", max(settings.sync_interval_seconds, 10), self._schedule_sync), name="sync-scheduler"))
        self._tasks.append(asyncio.create_task(
            self._periodic("health", max(settings.health_check_interval_seconds // 4, 30), self._schedule_health), name="health-scheduler"))
        self._tasks.append(asyncio.create_task(
            self._periodic("task-monitor", MONITOR_INTERVAL_SECONDS, self._monitor_tasks), name="task-monitor"))
        self._tasks.append(asyncio.create_task(
            self._periodic("webhook", WEBHOOK_INTERVAL_SECONDS, self._dispatch_webhooks), name="webhook-dispatcher"))
        self._tasks.append(asyncio.create_task(
            self._periodic("cooldown", COOLDOWN_INTERVAL_SECONDS, self._sweep_cooldowns), name="cooldown-sweeper"))
        logger.info("scheduler started (workers=%d)", self.concurrency)

    async def stop(self):
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("scheduler stopped")


scheduler = Scheduler()
