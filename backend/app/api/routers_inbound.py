"""入站邮件 Webhook：Cloudflare Email Worker 推送（X-Inbound-Token 鉴权）。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.db import get_db
from ..models import CfDomain
from ..services import inbound_service
from ..services.audit import audit
from .deps import client_ip
from .schemas import InboundMailIn

router = APIRouter(prefix="/inbound", tags=["inbound"])


@router.post("/cloudflare", status_code=202)
async def cloudflare_inbound(
    body: InboundMailIn,
    request: Request,
    x_inbound_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
):
    if not x_inbound_token:
        raise HTTPException(401, "X-Inbound-Token required")
    recipient = body.to.strip().lower()
    if "@" not in recipient:
        raise HTTPException(400, "invalid recipient")
    domain_part = recipient.split("@")[-1]
    domain = (await session.execute(select(CfDomain).where(CfDomain.domain == domain_part, CfDomain.status == "active"))).scalar_one_or_none()
    if not domain:
        raise HTTPException(404, f"domain {domain_part} not registered")
    if not domain.inbound_secret_hash or crypto.sha256_hex(x_inbound_token) != domain.inbound_secret_hash:
        raise HTTPException(401, "invalid inbound token")

    mailbox, message, is_new = await inbound_service.handle_inbound(
        session,
        recipient=recipient,
        sender=body.from_,
        subject=body.subject,
        text=body.text,
        html=body.html,
        message_id=body.messageId,
        headers=body.headers,
        auto_create_domain=domain.domain,
    )
    if mailbox is None:
        raise HTTPException(404, "mailbox not found for recipient")
    await audit(session, "inbound.cloudflare", resource_type="message",
                resource_id=message.id if message else "", actor_type="system", ip=client_ip(request),
                metadata={"recipient": recipient, "is_new": is_new})
    await session.commit()
    return {
        "accepted": True,
        "mailbox_id": mailbox.id,
        "message_id": message.id if message else None,
        "duplicate": not is_new,
    }
