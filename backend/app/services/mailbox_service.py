"""邮箱服务：创建/查询/凭据管理/Provider 实例构建。"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.db import utcnow
from ..core.ids import new_id
from ..models import CfDomain, Mailbox, MailboxCredential, Message, Pool, Provider
from ..providers import create_provider
from ..providers.base import MailProvider

# 凭据类型常量（数据库仅存 Fernet 加密值）
CRED_PASSWORD = "PASSWORD"
CRED_REFRESH_TOKEN = "OAUTH_REFRESH_TOKEN"
CRED_CLIENT_ID = "OAUTH_CLIENT_ID"
CRED_CLIENT_SECRET = "OAUTH_CLIENT_SECRET"
CRED_TENANT_ID = "TENANT_ID"
CRED_IMAP_HOST = "IMAP_HOST"
CRED_IMAP_PORT = "IMAP_PORT"
CRED_IMAP_USER = "IMAP_USER"
CRED_API_TOKEN = "API_TOKEN"

# 邮箱生命周期（§6）
LIFECYCLE_STATUSES = (
    "IMPORTED", "VALIDATING", "READY", "HEALTHY", "IN_USE", "COOLDOWN",
    "AVAILABLE", "QUARANTINED", "DISABLED", "ARCHIVED",
)
# 健康状态（§3.6）
HEALTH_STATUSES = (
    "HEALTHY", "WARNING", "TOKEN_EXPIRED", "AUTH_FAILED", "SYNC_ERROR",
    "RATE_LIMITED", "NETWORK_ERROR", "MAILBOX_UNAVAILABLE", "QUARANTINED", "DISABLED",
)


async def get_or_create_provider(session: AsyncSession, provider_type: str) -> Provider:
    row = (await session.execute(select(Provider).where(Provider.type == provider_type))).scalar_one_or_none()
    if row is None:
        row = Provider(id=new_id("prov"), name=provider_type.title(), type=provider_type, config_encrypted="")
        session.add(row)
        await session.flush()
    return row


async def create_mailbox(
    session: AsyncSession,
    *,
    email: str,
    provider_type: str,
    credentials: dict[str, str] | None = None,
    pool_id: str | None = None,
    display_name: str = "",
    tags: list | None = None,
    status: str = "IMPORTED",
) -> Mailbox:
    provider = await get_or_create_provider(session, provider_type)
    mailbox = Mailbox(
        id=new_id("mb"),
        provider_id=provider.id,
        provider_type=provider_type,
        email=email.strip().lower(),
        display_name=display_name or email.split("@")[0],
        status=status,
        pool_id=pool_id,
        tags_json=tags or [],
        metadata_json={},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(mailbox)
    await session.flush()
    for ctype, value in (credentials or {}).items():
        if value is None or value == "":
            continue
        session.add(
            MailboxCredential(
                id=new_id("cred"),
                mailbox_id=mailbox.id,
                credential_type=ctype,
                encrypted_value=crypto.encrypt_str(str(value)),
                masked_preview=crypto.mask_secret(str(value)),
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    return mailbox


async def get_credentials(session: AsyncSession, mailbox_id: str) -> dict[str, str]:
    rows = (await session.execute(select(MailboxCredential).where(MailboxCredential.mailbox_id == mailbox_id))).scalars().all()
    return {r.credential_type: crypto.decrypt_str(r.encrypted_value) for r in rows if r.encrypted_value}


async def build_provider(session: AsyncSession, mailbox: Mailbox) -> MailProvider:
    """构建 Provider 实例（凭据解密只在服务端内存中进行）。"""
    credentials = await get_credentials(session, mailbox.id)
    config: dict = {}
    if mailbox.provider_type == "cloudflare":
        domain_part = mailbox.email.split("@")[-1] if "@" in mailbox.email else ""
        domain = (
            await session.execute(select(CfDomain).where(CfDomain.domain == domain_part))
        ).scalar_one_or_none()
        if domain:
            config = {
                "domain_id": domain.id,
                "domain_status": domain.status,
                "dns_status": domain.dns_status,
                "mode": domain.mode,
                "last_mail_at": domain.last_mail_at,
            }
    return create_provider(mailbox.provider_type, mailbox, credentials, config)


def credentials_out(rows: list[MailboxCredential]) -> list[dict]:
    """脱敏输出（§20 后端响应默认脱敏）。"""
    return [
        {
            "credential_type": r.credential_type,
            "masked_preview": r.masked_preview or "••••",
            "status": r.status,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "last_validated_at": r.last_validated_at.isoformat() if r.last_validated_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


async def mailbox_counts_by_provider(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(select(Mailbox.provider_type, func.count(Mailbox.id)).group_by(Mailbox.provider_type))
    return {provider: count for provider, count in rows.all()}


async def find_by_email(session: AsyncSession, email: str) -> Optional[Mailbox]:
    return (
        await session.execute(select(Mailbox).where(Mailbox.email == email.strip().lower()))
    ).scalar_one_or_none()


async def count_messages_today(session: AsyncSession, mailbox_id: str) -> int:
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await session.execute(
            select(func.count(Message.id)).where(Message.mailbox_id == mailbox_id, Message.created_at >= today)
        )
    ).scalar_one()
