"""邮箱池调度（§9）：分配/释放/冷却扫描。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import utcnow
from ..models import Mailbox, Pool, RegistrationTask
from .audit import audit

# 任务在途状态（占用邮箱）
IN_FLIGHT_STATES = ("WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED", "PARSING", "RESULT_READY", "WAITING_CALLBACK")
# 可被分配的邮箱状态
ALLOCATABLE_STATUSES = ("READY", "AVAILABLE")
# 任务成功终态
SUCCESS_STATES = ("COMPLETED",)


class PoolEmptyError(Exception):
    pass


async def get_pool(session: AsyncSession, pool_id: str | None) -> Pool | None:
    if pool_id:
        return await session.get(Pool, pool_id)
    return (
        await session.execute(select(Pool).where(Pool.name == "default"))
    ).scalar_one_or_none()


async def list_in_flight(session: AsyncSession, mailbox_id: str) -> int:
    return (
        await session.execute(
            select(func.count(RegistrationTask.id)).where(
                RegistrationTask.mailbox_id == mailbox_id,
                RegistrationTask.state.in_(IN_FLIGHT_STATES),
            )
        )
    ).scalar_one()


async def count_today_tasks(session: AsyncSession, mailbox_id: str) -> int:
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await session.execute(
            select(func.count(RegistrationTask.id)).where(
                RegistrationTask.mailbox_id == mailbox_id,
                RegistrationTask.created_at >= today,
                RegistrationTask.state.notin_(("CANCELLED", "TIMEOUT")),
            )
        )
    ).scalar_one()


async def list_project_success_mailbox_ids(session: AsyncSession, project_key: str, pool_id: str | None) -> set[str]:
    """同项目已 success 的邮箱 ID 集合（防重复领取）。"""
    if not project_key:
        return set()
    stmt = select(RegistrationTask.mailbox_id).where(
        RegistrationTask.project_key == project_key,
        RegistrationTask.claim_result == "success",
        RegistrationTask.mailbox_id.is_not(None),
    )
    if pool_id:
        stmt = stmt.where(RegistrationTask.pool_id == pool_id)
    rows = (await session.execute(stmt)).all()
    return {r[0] for r in rows if r[0]}


async def allocate(
    session: AsyncSession,
    pool: Pool | None,
    *,
    provider_type: str | None = None,
    project_key: str | None = None,
    actor_type: str = "system",
    actor_id: str = "pool",
    ip: str = "",
) -> Mailbox:
    """§9 选择规则：Provider 匹配 → Healthy → 非 Cooling → 同项目未 success → 最近使用时间 → Health Score。"""
    stmt = (
        select(Mailbox)
        .where(
            Mailbox.pool_id == pool.id if pool else Mailbox.pool_id.is_(None),
            Mailbox.status.in_(ALLOCATABLE_STATUSES),
            Mailbox.health_status == "HEALTHY",
            Mailbox.is_demo == False,  # noqa: E712 演示数据永不进入真实分配
        )
        .order_by(Mailbox.last_used_at.is_(None).desc(), Mailbox.last_used_at.asc(), Mailbox.health_score.desc())
        .limit(100)
    )
    if provider_type:
        stmt = stmt.where(Mailbox.provider_type == provider_type)
    candidates = (await session.execute(stmt)).scalars().all()

    # 项目隔离：排除同项目已 success 的邮箱
    excluded_ids = await list_project_success_mailbox_ids(session, project_key or "", pool.id if pool else None)

    for mailbox in candidates:
        if mailbox.id in excluded_ids:
            continue
        if await list_in_flight(session, mailbox.id) >= (pool.max_concurrent if pool else 1):
            continue
        if pool and await count_today_tasks(session, mailbox.id) >= pool.daily_limit:
            continue
        mailbox.status = "IN_USE"
        mailbox.last_used_at = utcnow()
        mailbox.updated_at = utcnow()
        await audit(
            session, "pool.allocate", resource_type="mailbox", resource_id=mailbox.id,
            actor_type=actor_type, actor_id=actor_id, ip=ip,
            metadata={"pool_id": pool.id if pool else None, "email": mailbox.email, "project_key": project_key},
        )
        return mailbox
    raise PoolEmptyError("no available mailbox in pool")


async def release(session: AsyncSession, mailbox: Mailbox | None) -> None:
    """任务结束后释放邮箱：进入冷却（有池）或直接可用（无池）。失效邮箱自动移出可用池但保留数据（§6）。"""
    if mailbox is None:
        return
    if mailbox.status != "IN_USE":
        return
    pool = await session.get(Pool, mailbox.pool_id) if mailbox.pool_id else None
    if pool and pool.cooldown_seconds > 0:
        mailbox.status = "COOLDOWN"
        mailbox.metadata_json = {
            **(mailbox.metadata_json or {}),
            "cooldown_until": (utcnow() + timedelta(seconds=pool.cooldown_seconds)).isoformat(),
        }
    else:
        mailbox.status = "AVAILABLE"
    mailbox.updated_at = utcnow()


async def claim_complete(
    session: AsyncSession,
    task: RegistrationTask,
    result: str = "success",
    note: str = "",
    actor_id: str = "",
    ip: str = "",
) -> None:
    """外部调用方显式标记任务完成并释放邮箱。

    - result=success 且有 project_key：邮箱直接回到 AVAILABLE（跳过冷却），可被其他项目立即复用；
      同项目内该邮箱被标记为已 success，不再分配给同一 project_key。
    - result=success 且无 project_key：走正常 release（冷却后回池）。
    - result=failed：邮箱走正常 release，不标记项目 success。
    """
    mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
    task.claim_result = result
    task.updated_at = utcnow()
    if result == "success" and task.project_key and mailbox:
        # 项目维度成功复用：跳过冷却，直接可用
        if mailbox.status == "IN_USE":
            mailbox.status = "AVAILABLE"
            mailbox.updated_at = utcnow()
        await audit(
            session, "pool.claim_complete", resource_type="registration_task", resource_id=task.id,
            actor_type="api", actor_id=actor_id, ip=ip,
            metadata={"result": result, "mailbox_id": mailbox.id, "project_key": task.project_key, "note": note},
        )
    else:
        await release(session, mailbox)
        await audit(
            session, "pool.claim_complete", resource_type="registration_task", resource_id=task.id,
            actor_type="api", actor_id=actor_id, ip=ip,
            metadata={"result": result, "mailbox_id": mailbox.id if mailbox else None, "note": note},
        )


async def sweep_cooldowns(session: AsyncSession) -> int:
    """冷却结束 -> AVAILABLE。"""
    now = utcnow()
    rows = (
        await session.execute(select(Mailbox).where(Mailbox.status == "COOLDOWN").limit(200))
    ).scalars().all()
    released = 0
    for mailbox in rows:
        until = (mailbox.metadata_json or {}).get("cooldown_until")
        if not until:
            mailbox.status = "AVAILABLE"
            released += 1
            continue
        try:
            if datetime.fromisoformat(until) <= now:
                mailbox.status = "AVAILABLE"
                metadata = dict(mailbox.metadata_json or {})
                metadata.pop("cooldown_until", None)
                mailbox.metadata_json = metadata
                released += 1
        except ValueError:
            mailbox.status = "AVAILABLE"
    return released
