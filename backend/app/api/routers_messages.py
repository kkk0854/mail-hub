from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..core.events import bus
from ..models import Mailbox, Message, ParseResult
from ..services import parser_service, task_service
from ..services.audit import audit
from .deps import get_current_user
from .serializers import decrypt_result, message_detail, message_summary

router = APIRouter(prefix="/messages", tags=["messages"])


def _view_conditions(view: str) -> list:
    if view == "unread":
        return [Message.is_read.is_(False)]
    if view == "verification":
        return [Message.category == "verification"]
    if view == "security":
        return [Message.category == "security"]
    if view == "link":
        return [Message.category == "link"]
    if view == "failed":
        return [Message.parse_status == "PARSE_FAILED"]
    if view == "archived":
        return [Message.is_archived.is_(True)]
    if view == "all":
        return []
    raise HTTPException(400, f"unknown view: {view}")


async def _mailbox_email_map(session: AsyncSession, mailbox_ids: list[str]) -> dict[str, str]:
    ids = list(set(i for i in mailbox_ids if i))
    if not ids:
        return {}
    rows = (await session.execute(select(Mailbox.id, Mailbox.email).where(Mailbox.id.in_(ids)))).all()
    return {mid: email for mid, email in rows}


@router.get("")
async def list_messages(
    view: str = "all",
    mailbox_id: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    stmt = select(Message).order_by(Message.received_at.desc())
    count_stmt = select(func.count(Message.id))
    conditions = _view_conditions(view)
    if mailbox_id:
        conditions.append(Message.mailbox_id == mailbox_id)
    if q:
        like = f"%{q.strip().lower()}%"
        conditions.append(
            func.lower(Message.subject).like(like)
            | func.lower(Message.sender).like(like)
            | func.lower(Message.body_text).like(like)
        )
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    email_map = await _mailbox_email_map(session, [m.mailbox_id for m in rows])
    has_results: dict[str, bool] = {}
    if rows:
        msg_ids = [m.id for m in rows]
        counts = await session.execute(
            select(ParseResult.message_id, func.count(ParseResult.id))
            .where(ParseResult.message_id.in_(msg_ids))
            .group_by(ParseResult.message_id)
        )
        has_results = {mid: n > 0 for mid, n in counts.all()}

    return {
        "items": [message_summary(m, email_map.get(m.mailbox_id), has_results.get(m.id, False)) for m in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{message_id}")
async def get_message(message_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    message = await _load_detail(session, message_id)
    results = (await session.execute(select(ParseResult).where(ParseResult.message_id == message.id))).scalars().all()
    mailbox = await session.get(Mailbox, message.mailbox_id)
    return message_detail(message, mailbox.email if mailbox else None, [decrypt_result(r) for r in results])


@router.post("/{message_id}/reparse")
async def reparse(message_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    message = await _load_detail(session, message_id)
    mailbox = await session.get(Mailbox, message.mailbox_id)
    try:
        results = await parser_service.parse_message(session, message, provider_type=mailbox.provider_type if mailbox else None)
    except Exception:
        message.parse_status = "PARSE_FAILED"
        raise HTTPException(500, "parse failed, message kept raw (§19)")
    parsed_out = [decrypt_result(r) for r in results]
    await bus.publish(
        "mail.parsed",
        {
            "message_id": message.id,
            "mailbox_id": message.mailbox_id,
            "parse_status": message.parse_status,
            "results": [{"type": r["type"], "value": r["value"]} for r in parsed_out],
        },
    )
    await task_service.match_mail(session, message, results)
    await audit(session, "message.reparse", resource_type="message", resource_id=message.id, actor_type="user")
    await session.commit()
    return {"message_id": message.id, "parse_status": message.parse_status, "results": parsed_out}


@router.get("/{message_id}/results")
async def get_results(message_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    await _load_detail(session, message_id)
    results = (await session.execute(select(ParseResult).where(ParseResult.message_id == message_id))).scalars().all()
    items = [decrypt_result(r) for r in results]
    return {"items": items, "total": len(items)}


@router.post("/{message_id}/read")
async def mark_read(message_id: str, read: bool = True, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    message = await _load_detail(session, message_id)
    message.is_read = read
    await session.commit()
    return {"ok": True}


@router.post("/{message_id}/archive")
async def archive(message_id: str, archived: bool = True, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    message = await _load_detail(session, message_id)
    message.is_archived = archived
    await session.commit()
    return {"ok": True}


async def _load_detail(session: AsyncSession, message_id: str) -> Message:
    message = await session.get(Message, message_id)
    if not message:
        raise HTTPException(404, "message not found")
    return message
