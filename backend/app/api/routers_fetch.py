from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db, utcnow
from ..models import FetchTask, Mailbox
from ..providers import PROVIDER_TYPES
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import FetchTaskCreateIn
from .serializers import fetch_task_out

router = APIRouter(prefix="/fetch-tasks", tags=["fetch"])


async def _mailbox_map(session: AsyncSession, ids: list[str]) -> dict[str, str]:
    ids = list(set(i for i in ids if i))
    if not ids:
        return {}
    rows = (await session.execute(select(Mailbox.id, Mailbox.email).where(Mailbox.id.in_(ids)))).all()
    return {mid: email for mid, email in rows}


@router.get("")
async def list_fetch_tasks(
    state: str = "",
    task_type: str = "",
    mailbox_id: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    stmt = select(FetchTask).order_by(FetchTask.scheduled_at.desc())
    count_stmt = select(func.count(FetchTask.id))
    for field, value in (("state", state), ("task_type", task_type), ("mailbox_id", mailbox_id)):
        if value:
            stmt = stmt.where(getattr(FetchTask, field) == value)
            count_stmt = count_stmt.where(getattr(FetchTask, field) == value)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    email_map = await _mailbox_map(session, [t.mailbox_id for t in rows])
    return {
        "items": [fetch_task_out(t, email_map.get(t.mailbox_id)) for t in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=202)
async def create_fetch_task(
    body: FetchTaskCreateIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    if body.task_type not in ("MAIL_SYNC", "HEALTH_CHECK", "MAIL_PARSE"):
        raise HTTPException(400, "task_type must be MAIL_SYNC/HEALTH_CHECK/MAIL_PARSE")
    mailbox = await session.get(Mailbox, body.mailbox_id)
    if not mailbox:
        raise HTTPException(404, "mailbox not found")
    task = FetchTask(
        mailbox_id=mailbox.id,
        task_type=body.task_type,
        state="QUEUED",
        next_run_at=utcnow(),
        payload_json=body.payload,
    )
    session.add(task)
    await audit(session, "fetch_task.create", resource_type="fetch_task", resource_id=task.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"task_type": body.task_type})
    await session.commit()
    return fetch_task_out(task, mailbox.email)


@router.post("/{task_id}/retry")
async def retry_fetch_task(
    task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user),
):
    task = await session.get(FetchTask, task_id)
    if not task:
        raise HTTPException(404, "fetch task not found")
    if task.state not in ("FAILED",):
        raise HTTPException(409, f"only FAILED tasks can retry (state={task.state})")
    task.state = "QUEUED"
    task.next_run_at = utcnow()
    task.error_code = None
    task.error_message = None
    await audit(session, "fetch_task.retry", resource_type="fetch_task", resource_id=task.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return fetch_task_out(task)
