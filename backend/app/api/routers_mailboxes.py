from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db, utcnow
from ..core.events import bus
from ..models import FetchTask, HealthCheckRecord, Mailbox, MailboxCredential, Message, Pool
from ..providers import PROVIDER_TYPES
from ..services import health_service, mailbox_service
from ..services.audit import audit
from ..services.mailbox_service import credentials_out
from .deps import client_ip, get_current_user
from .schemas import BatchIdsIn, MailboxCreateIn, MailboxPatchIn
from .serializers import health_check_out, mailbox_out, message_summary

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


async def _pool_names(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Pool))).scalars().all()
    return {p.id: p.name for p in rows}


@router.get("")
async def list_mailboxes(
    q: str = "",
    provider_type: str = "",
    status: str = "",
    health_status: str = "",
    pool_id: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    stmt = select(Mailbox).order_by(Mailbox.created_at.desc())
    count_stmt = select(func.count(Mailbox.id))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Mailbox.email).like(like) | func.lower(Mailbox.display_name).like(like))
        count_stmt = count_stmt.where(func.lower(Mailbox.email).like(like) | func.lower(Mailbox.display_name).like(like))
    for field, value in (("provider_type", provider_type), ("status", status), ("health_status", health_status), ("pool_id", pool_id)):
        if value:
            stmt = stmt.where(getattr(Mailbox, field) == value)
            count_stmt = count_stmt.where(getattr(Mailbox, field) == value)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    pool_names = await _pool_names(session)
    ids = [m.id for m in rows]
    today_counts: dict[str, int] = {}
    if ids:
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        counts = await session.execute(
            select(Message.mailbox_id, func.count(Message.id))
            .where(Message.mailbox_id.in_(ids), Message.received_at >= today)
            .group_by(Message.mailbox_id)
        )
        today_counts = {mid: n for mid, n in counts.all()}

    return {
        "items": [mailbox_out(m, pool_names.get(m.pool_id), today_counts.get(m.id, 0)) for m in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201)
async def create_mailbox(
    body: MailboxCreateIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(400, f"provider_type must be one of {PROVIDER_TYPES}")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "invalid email")
    if await mailbox_service.find_by_email(session, email):
        raise HTTPException(409, "mailbox already exists")
    mailbox = await mailbox_service.create_mailbox(
        session,
        email=email,
        provider_type=body.provider_type,
        credentials=body.credentials,
        pool_id=body.pool_id or None,
        display_name=body.display_name,
        tags=body.tags,
    )
    await audit(session, "mailbox.create", resource_type="mailbox", resource_id=mailbox.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"email": email, "provider_type": body.provider_type})
    await session.commit()
    await bus.publish("mailbox.status.changed", {"mailbox_id": mailbox.id, "email": mailbox.email, "status": mailbox.status, "previous": None})
    pool_names = await _pool_names(session)
    return mailbox_out(mailbox, pool_names.get(mailbox.pool_id), 0)


@router.get("/{mailbox_id}")
async def get_mailbox(
    mailbox_id: str,
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    mailbox = await session.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    pool_names = await _pool_names(session)
    cred_rows = (
        await session.execute(select(MailboxCredential).where(MailboxCredential.mailbox_id == mailbox.id))
    ).scalars().all()
    messages = (
        await session.execute(select(Message).where(Message.mailbox_id == mailbox.id).order_by(Message.received_at.desc()).limit(10))
    ).scalars().all()
    checks = (
        await session.execute(
            select(HealthCheckRecord).where(HealthCheckRecord.mailbox_id == mailbox.id).order_by(HealthCheckRecord.created_at.desc()).limit(5)
        )
    ).scalars().all()

    return {
        **mailbox_out(mailbox, pool_names.get(mailbox.pool_id)),
        "credentials": credentials_out(list(cred_rows)),
        "recent_messages": [message_summary(m, mailbox.email) for m in messages],
        "recent_health_checks": [health_check_out(c) for c in checks],
    }


@router.patch("/{mailbox_id}")
async def patch_mailbox(
    mailbox_id: str,
    body: MailboxPatchIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    mailbox = await session.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    changes = {}
    if body.display_name is not None:
        mailbox.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.pool_id is not None:
        mailbox.pool_id = body.pool_id or None
        changes["pool_id"] = mailbox.pool_id
    if body.tags is not None:
        mailbox.tags_json = body.tags
        changes["tags"] = body.tags
    if body.status is not None:
        allowed = {"DISABLED", "ARCHIVED", "READY", "AVAILABLE", "QUARANTINED"}
        if body.status not in allowed:
            raise HTTPException(400, f"status must be one of {allowed}")
        old = mailbox.status
        mailbox.status = body.status
        changes["status"] = {"from": old, "to": body.status}
        await bus.publish("mailbox.status.changed", {"mailbox_id": mailbox.id, "email": mailbox.email, "status": body.status, "previous": old})
    mailbox.updated_at = utcnow()
    await audit(session, "mailbox.update", resource_type="mailbox", resource_id=mailbox.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata=changes)
    await session.commit()
    pool_names = await _pool_names(session)
    return mailbox_out(mailbox, pool_names.get(mailbox.pool_id))


@router.delete("/{mailbox_id}")
async def delete_mailbox(
    mailbox_id: str,
    hard: bool = False,
    request: Request = None,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    from sqlalchemy import delete as sa_delete

    mailbox = await session.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    if hard:
        await session.execute(sa_delete(Message).where(Message.mailbox_id == mailbox.id))
        await session.execute(sa_delete(MailboxCredential).where(MailboxCredential.mailbox_id == mailbox.id))
        await session.execute(sa_delete(HealthCheckRecord).where(HealthCheckRecord.mailbox_id == mailbox.id))
        await session.execute(sa_delete(FetchTask).where(FetchTask.mailbox_id == mailbox.id))
        await session.delete(mailbox)
        action = "mailbox.delete"
    else:
        mailbox.status = "ARCHIVED"
        mailbox.updated_at = utcnow()
        await bus.publish("mailbox.status.changed", {"mailbox_id": mailbox.id, "email": mailbox.email, "status": "ARCHIVED", "previous": None})
        action = "mailbox.archive"
    await audit(session, action, resource_type="mailbox", resource_id=mailbox_id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request) if request else "")
    await session.commit()
    return {"ok": True, "hard": hard}


@router.post("/{mailbox_id}/health-check")
async def run_health_check(
    mailbox_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    mailbox = await session.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    record = await health_service.run_health_check(
        session, mailbox, actor_type="user", actor_id=getattr(user, "username", "console")
    )
    await audit(session, "mailbox.health_check_manual", resource_type="mailbox", resource_id=mailbox.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return health_check_out(record)


@router.post("/batch-health-check")
async def batch_health_check(
    body: BatchIdsIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    stmt = select(Mailbox).where(Mailbox.status != "ARCHIVED")
    if not body.all:
        if not body.ids:
            raise HTTPException(400, "ids required")
        stmt = stmt.where(Mailbox.id.in_(body.ids))
    mailboxes = (await session.execute(stmt)).scalars().all()
    now = utcnow()
    for mailbox in mailboxes:
        session.add(FetchTask(id=f"ft_bhc_{mailbox.id[-8:]}{int(now.timestamp()*1000)%10**9}", mailbox_id=mailbox.id,
                              task_type="HEALTH_CHECK", state="QUEUED", next_run_at=now, scheduled_at=now,
                              payload_json={"source": "batch"}))
    await audit(session, "mailbox.batch_health_check", resource_type="mailbox_batch", resource_id="",
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"count": len(mailboxes)})
    await session.commit()
    return {"enqueued": len(mailboxes)}


@router.post("/{mailbox_id}/sync")
async def sync_mailbox(
    mailbox_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    mailbox = await session.get(Mailbox, mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    task = FetchTask(
        id=f"ft_sync_{mailbox.id[-8:]}_{int(utcnow().timestamp()*1000)%10**9}",
        mailbox_id=mailbox.id,
        task_type="MAIL_SYNC",
        state="QUEUED",
        payload_json={"source": "manual"},
    )
    session.add(task)
    await audit(session, "mailbox.sync_manual", resource_type="mailbox", resource_id=mailbox.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return {"task_id": task.id, "state": task.state}
