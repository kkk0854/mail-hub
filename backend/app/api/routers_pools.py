from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db, utcnow
from ..core.events import bus
from ..models import Mailbox, Pool, RegistrationTask
from ..services import pool_service
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import PoolAllocateIn, PoolIn, PoolPatchIn, PoolReleaseIn
from .serializers import mailbox_out, pool_out

router = APIRouter(prefix="/pools", tags=["pools"])


async def _pool_stats(session: AsyncSession) -> dict[str, dict]:
    rows = (await session.execute(select(Mailbox.pool_id, Mailbox.status, func.count(Mailbox.id)).group_by(Mailbox.pool_id, Mailbox.status))).all()
    stats: dict[str, dict] = {}
    for pool_id, status, n in rows:
        bucket = stats.setdefault(pool_id or "", {})
        bucket[status] = bucket.get(status, 0) + n
    return stats


@router.get("")
async def list_pools(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    pools = (await session.execute(select(Pool).order_by(Pool.created_at.asc()))).scalars().all()
    stats = await _pool_stats(session)
    items = []
    for p in pools:
        bucket = stats.get(p.id, {})
        in_flight = (
            await session.execute(
                select(func.count(RegistrationTask.id)).where(
                    RegistrationTask.pool_id == p.id, RegistrationTask.state.in_(pool_service.IN_FLIGHT_STATES)
                )
            )
        ).scalar_one()
        items.append(
            {
                **pool_out(p),
                "stats": {
                    "available": bucket.get("READY", 0) + bucket.get("AVAILABLE", 0),
                    "in_use": bucket.get("IN_USE", 0),
                    "cooldown": bucket.get("COOLDOWN", 0),
                    "quarantine": bucket.get("QUARANTINED", 0),
                    "warning": bucket.get("WARNING", 0),
                    "disabled": bucket.get("DISABLED", 0) + bucket.get("ARCHIVED", 0),
                    "in_flight_tasks": in_flight,
                },
            }
        )
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_pool(body: PoolIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    exists = (await session.execute(select(Pool).where(Pool.name == body.name))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "pool name already exists")
    pool = Pool(id=f"pool_{body.name.lower().replace(' ', '-')}_{utcnow().strftime('%H%M%S')}", **body.model_dump())
    session.add(pool)
    await audit(session, "pool.create", resource_type="pool", resource_id=pool.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"name": body.name})
    await session.commit()
    return pool_out(pool)


@router.patch("/{pool_id}")
async def patch_pool(pool_id: str, body: PoolPatchIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    pool = await session.get(Pool, pool_id)
    if not pool:
        raise HTTPException(404, "pool not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(pool, field, value)
    await audit(session, "pool.update", resource_type="pool", resource_id=pool.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return pool_out(pool)


@router.post("/{pool_id}/allocate")
async def allocate(pool_id: str, body: PoolAllocateIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    pool = await session.get(Pool, pool_id)
    if not pool:
        raise HTTPException(404, "pool not found")
    try:
        mailbox = await pool_service.allocate(
            session, pool, provider_type=body.provider_type,
            actor_type="user", actor_id=getattr(user, "username", ""), ip=client_ip(request),
        )
    except pool_service.PoolEmptyError:
        raise HTTPException(409, "no available mailbox in pool")
    await session.commit()
    await bus.publish("mailbox.status.changed", {"mailbox_id": mailbox.id, "email": mailbox.email, "status": mailbox.status, "previous": None})
    return mailbox_out(mailbox, pool.name)


@router.post("/{pool_id}/release")
async def release(pool_id: str, body: PoolReleaseIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    pool = await session.get(Pool, pool_id)
    if not pool:
        raise HTTPException(404, "pool not found")
    mailbox = await session.get(Mailbox, body.mailbox_id)
    if not mailbox or mailbox.pool_id != pool.id:
        raise HTTPException(404, "mailbox not in this pool")
    await pool_service.release(session, mailbox)
    await audit(session, "pool.release", resource_type="mailbox", resource_id=mailbox.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    await bus.publish("mailbox.status.changed", {"mailbox_id": mailbox.id, "email": mailbox.email, "status": mailbox.status, "previous": "IN_USE"})
    return mailbox_out(mailbox, pool.name)
