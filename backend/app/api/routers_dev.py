from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..models import Mailbox, ParseResult
from ..services import inbound_service, mailbox_service
from ..services.audit import audit
from ..services.parser_service import decrypt_result
from .deps import client_ip, require_admin
from .schemas import InjectMailIn

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/inject-mail")
async def inject_mail(body: InjectMailIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(require_admin)):
    """模拟 Provider 事件：向指定邮箱注入一封入站邮件，走完整摄取/解析/任务绑定管道。"""
    mailbox = None
    if body.mailbox_id:
        mailbox = await mailbox_service.find_by_email(session, body.mailbox_id) or await session.get(Mailbox, body.mailbox_id)
    elif body.email:
        mailbox = await mailbox_service.find_by_email(session, body.email)
    if mailbox is None:
        raise HTTPException(404, "mailbox not found")

    mailbox_obj, message, is_new = await inbound_service.handle_inbound(
        session,
        recipient=mailbox.email,
        sender=body.sender,
        subject=body.subject,
        text=body.text,
        html=body.html,
        message_id=body.message_id,
    )
    if message is None:
        raise HTTPException(500, "ingest failed")
    await audit(session, "dev.inject_mail", resource_type="message", resource_id=message.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request),
                metadata={"mailbox": mailbox.email, "sender": body.sender, "subject": body.subject})
    await session.commit()

    results = (await session.execute(select(ParseResult).where(ParseResult.message_id == message.id))).scalars().all()
    return {
        "message_id": message.id,
        "mailbox_id": mailbox.id,
        "duplicate": not is_new,
        "parse_status": message.parse_status,
        "results": [decrypt_result(r) for r in results],
    }
