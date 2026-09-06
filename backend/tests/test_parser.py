"""解析引擎规则匹配测试（§11）。"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import Message, ParseResult
from app.services import inbound_service, parser_service

API = "/api/v1"


def test_sender_matching():
    assert parser_service.match_sender("*", "noreply@example.com")
    assert parser_service.match_sender("*@example.com", "noreply@example.com")
    assert parser_service.match_sender("example.com", "noreply@example.com")
    assert parser_service.match_sender("", "anyone@anywhere.io")
    assert not parser_service.match_sender("*@example.com", "noreply@other.org")


def test_subject_matching():
    assert parser_service.match_subject(r"verif|code", "Your verification code")
    assert parser_service.match_subject("验证码", "您的验证码是 483921")
    assert not parser_service.match_subject(r"verif", "Invoice for order")


async def test_message_parsed_with_otp_and_link(client, auth_headers):
    unique = uuid.uuid4().hex[:8]
    # 创建 simulator 邮箱
    resp = await client.post(
        f"{API}/mailboxes",
        headers=auth_headers,
        json={"email": f"parser-{unique}@example.com", "provider_type": "simulator"},
    )
    assert resp.status_code == 201, resp.text

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        mailbox, message, is_new = await inbound_service.handle_inbound(
            session,
            recipient=f"parser-{unique}@example.com",
            sender="noreply@verifier.io",
            subject="Please verify your account",
            text="Your verification code is 483921. Visit https://example.io/verify?token=abc to activate.",
        )
        assert is_new is True
        assert message.parse_status == "PARSED"
        assert message.category == "verification"
        results = (await session.execute(select(ParseResult).where(ParseResult.message_id == message.id))).scalars().all()
        types = {r.result_type for r in results}
        assert "OTP" in types
        values = {parser_service.decrypt_result(r)["value"] for r in results if r.result_type == "OTP"}
        assert "483921" in values
        links = {parser_service.decrypt_result(r)["value"] for r in results if r.result_type == "ACTIVATION_LINK"}
        assert any("https://example.io/verify" in v for v in links)

        # 幂等：同 provider_message_id 再摄取 -> 不重复
        mailbox2, message2, is_new2 = await inbound_service.handle_inbound(
            session,
            recipient=f"parser-{unique}@example.com",
            sender="noreply@verifier.io",
            subject="Please verify your account",
            text="Your verification code is 483921. Visit https://example.io/verify?token=abc to activate.",
            message_id=message.provider_message_id,
        )
        assert is_new2 is False
        assert message2.id == message.id


async def test_parse_failed_keeps_raw(client, auth_headers):
    """§19 Parser 失败 -> 保存原始邮件 -> 允许重跑。"""
    unique = uuid.uuid4().hex[:8]
    resp = await client.post(f"{API}/mailboxes", headers=auth_headers,
                             json={"email": f"pfail-{unique}@example.com", "provider_type": "simulator"})
    mailbox_id = resp.json()["id"]
    resp = await client.post(f"{API}/dev/inject-mail", headers=auth_headers,
                             json={"mailbox_id": mailbox_id, "sender": "a@b.io", "subject": "hello", "text": "plain text"})
    assert resp.status_code == 200
    message_id = resp.json()["message_id"]

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        msg = await session.get(Message, message_id)
        assert msg.parse_status == "NO_MATCH"
        assert msg.raw_storage_ref  # 原始邮件已保存

    # reparse 端点可重跑
    resp = await client.post(f"{API}/messages/{message_id}/reparse", headers=auth_headers)
    assert resp.status_code == 200
