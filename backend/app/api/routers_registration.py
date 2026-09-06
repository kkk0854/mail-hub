from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..models import Mailbox, Message, ParseResult, RegistrationTask
from ..services import task_service
from ..services.parser_service import decrypt_result
from ..services.audit import audit
from .deps import client_ip, get_current_user_or_key
from .schemas import RegistrationTaskIn
from .serializers import task_out

router = APIRouter(prefix="/registration-tasks", tags=["registration-tasks"])


@router.post("", status_code=201)
async def create_task(
    body: RegistrationTaskIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: object = Depends(get_current_user_or_key),
):
    task, created = await task_service.create_task(
        session,
        pool_id=body.pool_id,
        target_ref=body.target_ref,
        match=body.match.model_dump(),
        timeout_seconds=body.timeout_seconds,
        callback_url=body.callback_url,
        idempotency_key=body.idempotency_key,
        metadata=body.metadata,
        actor_id=getattr(user, "username", ""),
        ip=client_ip(request),
    )
    await session.commit()
    mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
    return task_out(task, mailbox.email if mailbox else None)


@router.get("")
async def list_tasks(
    state: str = "",
    external_ref: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user_or_key),
):
    stmt = select(RegistrationTask).order_by(RegistrationTask.created_at.desc())
    count_stmt = select(func.count(RegistrationTask.id))
    if state:
        stmt = stmt.where(RegistrationTask.state == state)
        count_stmt = count_stmt.where(RegistrationTask.state == state)
    if external_ref:
        stmt = stmt.where(RegistrationTask.external_ref.like(f"%{external_ref}%"))
        count_stmt = count_stmt.where(RegistrationTask.external_ref.like(f"%{external_ref}%"))
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    mailbox_ids = list({t.mailbox_id for t in rows if t.mailbox_id})
    emails: dict[str, str] = {}
    if mailbox_ids:
        mrows = (await session.execute(select(Mailbox.id, Mailbox.email).where(Mailbox.id.in_(mailbox_ids)))).all()
        emails = {mid: email for mid, email in mrows}
    return {
        "items": [task_out(t, emails.get(t.mailbox_id)) for t in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _load_task(session: AsyncSession, task_id: str) -> RegistrationTask:
    task = await session.get(RegistrationTask, task_id)
    if not task:
        raise HTTPException(404, "registration task not found")
    return task


@router.get("/{task_id}")
async def get_task(task_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user_or_key)):
    task = await _load_task(session, task_id)
    mailbox = await session.get(Mailbox, task.mailbox_id) if task.mailbox_id else None
    result = None
    if task.result_id:
        pr = await session.get(ParseResult, task.result_id)
        if pr:
            d = decrypt_result(pr)
            result = {"type": d["type"], "value": d["value"], "confidence": d["confidence"]}
    out = task_out(task, mailbox.email if mailbox else None, result)
    matched_id = (task.metadata_json or {}).get("matched_message_id")
    if matched_id:
        msg = await session.get(Message, matched_id)
        if msg:
            out["matched_message"] = {
                "id": msg.id, "sender": msg.sender, "subject": msg.subject, "received_at": msg.received_at.isoformat(),
            }
    return out


@router.post("/{task_id}/cancel")
async def cancel(task_id: str, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user_or_key)):
    task = await _load_task(session, task_id)
    try:
        await task_service.cancel_task(session, task, actor_id=getattr(user, "username", ""), ip=client_ip(request))
    except task_service.TaskError as exc:
        raise HTTPException(409, str(exc))
    await session.commit()
    return task_out(task)


@router.get("/{task_id}/result")
async def get_result(task_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user_or_key)):
    task = await _load_task(session, task_id)
    result = None
    if task.result_id:
        pr = await session.get(ParseResult, task.result_id)
        if pr:
            d = decrypt_result(pr)
            result = {"type": d["type"], "value": d["value"]}
    return {"task_id": task.id, "status": task.state, "result": result}
