"""入站邮件服务：Cloudflare Email Worker 推送 + Simulator 注入。"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import utcnow
from ..core.ids import new_id
from ..models import Alias, CfDomain, Mailbox
from . import mailbox_service, message_service
from .audit import audit

logger = logging.getLogger("mailhub.inbound")


def _first_address(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if "<" in value and ">" in value:
        return value.split("<")[-1].split(">")[0].strip().lower()
    return value.split(",")[0].strip().lower()


def split_plus_alias(address: str) -> tuple[str, str | None]:
    """解析 +tag 别名：user+tag@domain -> (user@domain, tag)。非别名返回 (原地址, None)。"""
    address = (address or "").strip().lower()
    if "@" not in address:
        return address, None
    local, domain = address.rsplit("@", 1)
    if "+" in local:
        base, tag = local.split("+", 1)
        if base and tag:
            return f"{base}@{domain}", tag
    return address, None


async def resolve_mailbox(
    session: AsyncSession, recipient: str, *, auto_create_domain: str | None = None
) -> tuple[Mailbox | None, bool]:
    """定位收件邮箱：+tag别名 -> 精确匹配 -> （注册域名下）自动创建。返回 (mailbox, created)。"""
    recipient = recipient.strip().lower()
    if not recipient:
        return None, False

    alias = (
        await session.execute(select(Alias).where(Alias.alias_address == recipient, Alias.status == "active"))
    ).scalar_one_or_none()
    if alias:
        master = await session.get(Mailbox, alias.master_mailbox_id)
        if master:
            return master, False

    mailbox = await mailbox_service.find_by_email(session, recipient)
    if mailbox:
        return mailbox, False

    # v1.2.0: +tag 别名识别（Outlook 风格 user+tag@domain 投递到主邮箱）
    base_address, tag = split_plus_alias(recipient)
    if tag and base_address != recipient:
        master = await mailbox_service.find_by_email(session, base_address)
        if master:
            # 绑定到主邮箱，邮件不新建独立邮箱记录
            logger.info("plus-alias %s -> master %s (tag=%s)", recipient, base_address, tag)
            await audit(session, "mailbox.plus_alias_resolve", resource_type="mailbox", resource_id=master.id,
                        actor_type="system", metadata={"alias": recipient, "master": base_address, "tag": tag})
            return master, False
        if auto_create_domain:
            domain = (
                await session.execute(select(CfDomain).where(CfDomain.domain == auto_create_domain, CfDomain.status == "active"))
            ).scalar_one_or_none()
            if domain:
                # 注册域名下：创建主邮箱，并登记为别名
                master = await mailbox_service.create_mailbox(
                    session,
                    email=base_address,
                    provider_type="cloudflare",
                    status="READY",
                    display_name=base_address.split("@")[0],
                )
                session.add(
                    Alias(
                        id=new_id("al"),
                        master_mailbox_id=master.id,
                        alias_address=recipient,
                        alias_type="plus",
                        status="active",
                        created_at=utcnow(),
                    )
                )
                await audit(session, "mailbox.plus_alias_create", resource_type="mailbox", resource_id=master.id,
                            actor_type="system", metadata={"alias": recipient, "master": base_address, "tag": tag})
                return master, True

    if auto_create_domain:
        domain = (
            await session.execute(select(CfDomain).where(CfDomain.domain == auto_create_domain, CfDomain.status == "active"))
        ).scalar_one_or_none()
        if domain:
            mailbox = await mailbox_service.create_mailbox(
                session,
                email=recipient,
                provider_type="cloudflare",
                status="READY",
                display_name=recipient.split("@")[0],
            )
            await audit(session, "mailbox.auto_create", resource_type="mailbox", resource_id=mailbox.id,
                        actor_type="system", metadata={"email": recipient, "domain": auto_create_domain, "reason": "inbound_catch_all"})
            return mailbox, True
    return None, False


async def handle_inbound(
    session: AsyncSession,
    *,
    recipient: str,
    sender: str,
    subject: str,
    text: str = "",
    html: str = "",
    message_id: str | None = None,
    headers: dict | None = None,
    raw: bytes | None = None,
    auto_create_domain: str | None = None,
) -> tuple[Mailbox | None, object | None, bool]:
    """统一入站入口（CF Worker 推送 / Simulator 注入共用）。"""
    recipient = _first_address(recipient)
    mailbox, created = await resolve_mailbox(session, recipient, auto_create_domain=auto_create_domain)
    if mailbox is None:
        return None, None, False

    if not message_id:
        digest = hashlib.sha256(f"{sender}|{recipient}|{subject}|{text[:200]}".encode()).hexdigest()[:24]
        message_id = f"inbound-{digest}"

    from ..providers.base import SyncedMessage

    msg = SyncedMessage(
        provider_message_id=message_id,
        sender=sender or "",
        recipient=recipient,
        subject=subject or "",
        text_body=text or "",
        html_body=html or "",
        headers=dict(headers or {}),
        raw=raw,
    )
    message, is_new = await message_service.ingest_message(session, mailbox, msg)
    return mailbox, message, is_new
