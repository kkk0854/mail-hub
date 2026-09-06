"""邮件摄取管道（§10 自动取件引擎）：去重 -> 存储 -> 解析 -> 任务绑定 -> 事件。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.config import DATA_DIR
from ..core.db import utcnow
from ..core.events import bus
from ..core.ids import new_id
from ..models import CfDomain, Mailbox, Message
from . import parser_service, task_service
from .audit import audit

logger = logging.getLogger("mailhub.message")

RAW_DIR = DATA_DIR / "raw"


def _dedupe_key(mailbox: Mailbox, provider_message_id: str) -> str:
    return f"{mailbox.provider_type}:{provider_message_id}"


def _fallback_message_id(sender: str, subject: str, received_at) -> str:
    """无 provider_message_id 时的稳定兜底 ID。

    使用 SHA-256 而非内置 hash()：Python hash 受 PYTHONHASHSEED 随机化影响，
    进程重启后同一封邮件会生成不同 ID，导致跨重启重复入库（幂等失效 §21）。
    """
    digest = hashlib.sha256(
        f"{sender}|{subject}|{received_at}".encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    return f"auto-{digest}"


def _store_raw(message_id: str, raw: bytes | None, fallback_text: str) -> str:
    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path = RAW_DIR / f"{message_id}.eml"
        if raw:
            path.write_bytes(raw)
        else:
            path.write_text(fallback_text, encoding="utf-8", errors="replace")
        return str(path)
    except OSError:
        logger.exception("failed to store raw message %s", message_id)
        return ""


async def ingest_message(session: AsyncSession, mailbox: Mailbox, msg) -> tuple[Message | None, bool]:
    """摄取一封新邮件。返回 (message, is_new)。幂等：同 provider_message_id 不重复入库（§21）。"""
    provider_message_id = msg.provider_message_id or _fallback_message_id(msg.sender, msg.subject, msg.received_at)
    dedupe_key = _dedupe_key(mailbox, provider_message_id)
    existing = (
        await session.execute(select(Message).where(Message.dedupe_key == dedupe_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    now = utcnow()
    received_at = msg.received_at or now
    if isinstance(received_at, datetime) and received_at.tzinfo is not None:
        received_at = received_at.replace(tzinfo=None)
    if received_at > now:
        received_at = now

    message_id = new_id("msg")
    raw_ref = _store_raw(
        message_id,
        msg.raw,
        f"From: {msg.sender}\r\nTo: {msg.recipient}\r\nSubject: {msg.subject}\r\nDate: {received_at.isoformat()}\r\n\r\n{msg.text_body or ''}",
    )
    message = Message(
        id=message_id,
        mailbox_id=mailbox.id,
        provider_message_id=provider_message_id,
        dedupe_key=dedupe_key,
        thread_id=msg.thread_id,
        sender=msg.sender or "",
        recipient=msg.recipient or mailbox.email,
        subject=msg.subject or "",
        body_text=msg.text_body or "",
        body_html=msg.html_body or "",
        headers_json=dict(msg.headers or {}),
        received_at=received_at,
        parse_status="PENDING",
        raw_storage_ref=raw_ref,
        created_at=now,
    )
    session.add(message)
    mailbox.last_mail_at = received_at
    mailbox.updated_at = now
    domain_part = mailbox.email.split("@")[-1] if "@" in mailbox.email else ""
    domain = (
        await session.execute(select(CfDomain).where(CfDomain.domain == domain_part))
    ).scalar_one_or_none()
    if domain:
        domain.last_mail_at = received_at
        domain.updated_at = now
    await session.flush()

    await bus.publish(
        "mail.received",
        {"message_id": message.id, "mailbox_id": mailbox.id, "mailbox": mailbox.email, "sender": message.sender, "subject": message.subject},
    )

    # 解析（§11）；解析失败不影响邮件已保存（§19 Parser 失败隔离）
    results = []
    try:
        results = await parser_service.parse_message(session, message, provider_type=mailbox.provider_type)
    except Exception:
        logger.exception("parse failed for message %s", message.id)
        message.parse_status = "PARSE_FAILED"
    parsed_out = [parser_service.decrypt_result(r) for r in results]
    await bus.publish(
        "mail.parsed",
        {
            "message_id": message.id,
            "mailbox_id": mailbox.id,
            "parse_status": message.parse_status,
            "results": [{"type": r["type"], "value": r["value"]} for r in parsed_out],
        },
    )

    # 任务匹配绑定
    try:
        await task_service.match_mail(session, message, results)
    except Exception:
        logger.exception("task match failed for message %s", message.id)

    await audit(
        session, "message.ingest", resource_type="message", resource_id=message.id,
        actor_type="system", metadata={"mailbox_id": mailbox.id, "dedupe_key": dedupe_key},
    )
    return message, True
