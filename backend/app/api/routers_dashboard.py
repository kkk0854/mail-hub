from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.db import get_db, utcnow
from ..models import (
    FetchTask,
    HealthCheckRecord,
    Mailbox,
    Message,
    ParseResult,
    Pool,
    RegistrationTask,
)
from .deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    total_mailboxes = (await session.execute(select(func.count(Mailbox.id)))).scalar_one()
    healthy = (await session.execute(select(func.count(Mailbox.id)).where(Mailbox.health_status == "HEALTHY"))).scalar_one()
    warning = (await session.execute(
        select(func.count(Mailbox.id)).where(Mailbox.health_status.in_(("WARNING", "SYNC_ERROR", "RATE_LIMITED")))
    )).scalar_one()
    error = (await session.execute(
        select(func.count(Mailbox.id)).where(Mailbox.health_status.in_(("AUTH_FAILED", "TOKEN_EXPIRED", "NETWORK_ERROR", "MAILBOX_UNAVAILABLE")))
    )).scalar_one()
    quarantine = (await session.execute(select(func.count(Mailbox.id)).where(Mailbox.status == "QUARANTINED"))).scalar_one()

    provider_rows = await session.execute(select(Mailbox.provider_type, func.count(Mailbox.id)).group_by(Mailbox.provider_type))
    by_provider = {p: n for p, n in provider_rows.all()}

    today_mail = (await session.execute(select(func.count(Message.id)).where(Message.received_at >= today))).scalar_one()
    today_parsed = (await session.execute(select(func.count(ParseResult.id)).where(ParseResult.created_at >= today))).scalar_one()

    running_tasks = (await session.execute(
        select(func.count(RegistrationTask.id)).where(RegistrationTask.state.in_(
            ("CREATED", "WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED", "PARSING", "RESULT_READY", "WAITING_CALLBACK"))
        )
    )).scalar_one()
    completed = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.state == "COMPLETED"))).scalar_one()
    failed = (await session.execute(
        select(func.count(RegistrationTask.id)).where(RegistrationTask.state.in_(("TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR")))
    )).scalar_one()
    cancelled = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.state == "CANCELLED"))).scalar_one()
    done = completed + failed + cancelled
    success_rate = round(completed / done, 4) if done else None

    queues = await session.execute(select(FetchTask.state, func.count(FetchTask.id)).group_by(FetchTask.state))
    queue_states = {s: n for s, n in queues.all()}

    pools = (await session.execute(select(Pool))).scalars().all()
    pool_health = []
    for p in pools:
        available = (await session.execute(
            select(func.count(Mailbox.id)).where(
                Mailbox.pool_id == p.id, Mailbox.status.in_(("READY", "AVAILABLE")), Mailbox.health_status == "HEALTHY"
            )
        )).scalar_one()
        total_in_pool = (await session.execute(select(func.count(Mailbox.id)).where(Mailbox.pool_id == p.id))).scalar_one()
        pool_health.append({"id": p.id, "name": p.name, "available": available, "total": total_in_pool,
                            "health_rate": round(available / total_in_pool, 3) if total_in_pool else None})

    recent_errors = (await session.execute(
        select(FetchTask).where(FetchTask.state == "FAILED").order_by(FetchTask.finished_at.desc()).limit(5)
    )).scalars().all()

    return {
        "mailboxes": {
            "total": total_mailboxes,
            "healthy": healthy,
            "warning": warning,
            "error": error,
            "quarantine": quarantine,
            "by_provider": by_provider,
        },
        "mail": {"today_received": today_mail, "today_parsed": today_parsed},
        "tasks": {"running": running_tasks, "completed": completed, "failed": failed, "cancelled": cancelled, "success_rate": success_rate},
        "workers": {"count": settings.worker_concurrency if settings.embed_workers else 0, "embedded": settings.embed_workers,
                    "queue_depth": queue_states.get("QUEUED", 0) + queue_states.get("RETRYING", 0)},
        "pools": pool_health,
        "recent_errors": [
            {"id": t.id, "mailbox_id": t.mailbox_id, "task_type": t.task_type, "error_code": t.error_code,
             "error_message": t.error_message, "finished_at": t.finished_at.isoformat() if t.finished_at else None}
            for t in recent_errors
        ],
    }


@router.get("/charts")
async def charts(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    from datetime import timedelta

    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]

    mail_7d = []
    for day in days:
        nxt = day + timedelta(days=1)
        n = (await session.execute(
            select(func.count(Message.id)).where(Message.received_at >= day, Message.received_at < nxt)
        )).scalar_one()
        mail_7d.append({"date": day.strftime("%m-%d"), "count": n})

    health_trend = []
    for day in days:
        nxt = day + timedelta(days=1)
        row = (await session.execute(
            select(func.avg(HealthCheckRecord.score)).where(HealthCheckRecord.created_at >= day, HealthCheckRecord.created_at < nxt)
        )).scalar_one()
        health_trend.append({"date": day.strftime("%m-%d"), "avg_score": round(float(row), 1) if row is not None else None})

    provider_rows = await session.execute(select(Mailbox.provider_type, func.count(Mailbox.id)).group_by(Mailbox.provider_type))
    provider_distribution = [{"provider": p, "value": n} for p, n in provider_rows.all()]

    completed = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.state == "COMPLETED"))).scalar_one()
    failed = (await session.execute(
        select(func.count(RegistrationTask.id)).where(RegistrationTask.state.in_(("TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR")))
    )).scalar_one()
    cancelled = (await session.execute(select(func.count(RegistrationTask.id)).where(RegistrationTask.state == "CANCELLED"))).scalar_one()

    return {
        "mail_7d": mail_7d,
        "health_trend": health_trend,
        "provider_distribution": provider_distribution,
        "task_success": {"completed": completed, "failed": failed, "cancelled": cancelled},
    }
