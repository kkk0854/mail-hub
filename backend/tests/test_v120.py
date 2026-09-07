"""v1.2.0 回归测试：临时邮箱插件化 / +tag 别名 / LLM 兜底 / 演示种子 / 自动迁移。"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt_str
from app.core.ids import new_id
from app.models import (
    Base,
    Mailbox,
    Message,
    ParseAttempt,
    ParseResult,
    RegistrationTask,
    TempMailProviderSetting,
)
from app.providers.custom_http_provider import CustomHttpProvider
from app.providers.provider_manager import ProviderManager
from app.services import inbound_service, parser_service, pool_service
from app.services import llm_fallback
from app.core.db import utcnow


@pytest.fixture
async def session():
    from app.core.db import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as s:
        yield s
        await s.rollback()


def test_provider_manager_registers_builtins():
    ProviderManager._loaded = False  # 强制重新加载（幂等测试）
    ProviderManager.load_all()
    names = set(ProviderManager.names())
    assert {"gptmail", "moemail", "custom_http"} <= names


def test_custom_http_config_validation():
    p = CustomHttpProvider
    ok, err = p.validate_config(p, {"create_url": "https://x/api/emails", "fetch_url": "https://x/api/messages/{email}"})
    assert ok
    ok2, err2 = p.validate_config(p, {"create_url": ""})
    assert not ok2


def test_plus_alias_split():
    assert inbound_service.split_plus_alias("user+tag@example.com") == ("user@example.com", "tag")
    assert inbound_service.split_plus_alias("user@example.com") == ("user@example.com", None)
    assert inbound_service.split_plus_alias("user+@example.com") == ("user+@example.com", None)
    assert inbound_service.split_plus_alias("user+tag1+tag2@example.com") == ("user@example.com", "tag1+tag2")


async def test_plus_alias_resolves_to_master(session):
    # 主邮箱存在时，+tag 收件映射到主邮箱
    master = Mailbox(
        id=new_id("mb"), provider_type="imap", email="master@example.com",
        status="READY", health_status="HEALTHY", created_at=utcnow(), updated_at=utcnow(),
    )
    session.add(master)
    await session.flush()

    mailbox, created = await inbound_service.resolve_mailbox(session, "master+reg@example.com")
    assert mailbox is not None
    assert mailbox.id == master.id
    assert created is False


async def test_plus_alias_creates_master_under_domain(session):
    from app.models import CfDomain

    session.add(CfDomain(id=new_id("dom"), domain="demo.example.com", status="active", created_at=utcnow(), updated_at=utcnow()))
    await session.flush()

    mailbox, created = await inbound_service.resolve_mailbox(
        session, "fresh+tag@demo.example.com", auto_create_domain="demo.example.com"
    )
    assert mailbox is not None
    assert created is True
    assert mailbox.email == "fresh@demo.example.com"  # 主邮箱


def test_llm_prompt_contract():
    assert "code" in llm_fallback.LLM_PROMPT
    assert "confidence" in llm_fallback.LLM_PROMPT


def test_llm_extract_json():
    assert llm_fallback._extract_json('{"code": "123456", "link": "", "confidence": 0.9}') == {
        "code": "123456", "link": "", "confidence": 0.9,
    }
    assert llm_fallback._extract_json('```json\n{"code": "ABC123", "link": "https://x", "confidence": 0.8}\n```') == {
        "code": "ABC123", "link": "https://x", "confidence": 0.8,
    }
    assert llm_fallback._extract_json("no json here") is None


def test_llm_prompt_survives_braces_in_body():
    """邮件正文含花括号（HTML/JSON）不得导致提示词构造崩溃。"""
    prompt = llm_fallback._build_prompt(
        sender="a@b.com", subject="验证", body='{"code": 123} 请使用 {placeholder} 变量'
    )
    assert "发件人：a@b.com" in prompt
    assert '{"code": 123}' in prompt  # 原文保留


async def test_demo_mailboxes_never_allocated(session):
    """演示邮箱（is_demo）不得被真实池分配。"""
    from app.services import pool_service

    pool = await pool_service.get_pool(session, None)
    if pool is None:
        from app.models import Pool

        pool = Pool(id=new_id("pool"), name="default", max_concurrent=1, cooldown_seconds=300, daily_limit=20)
        session.add(pool)
        await session.flush()

    demo = Mailbox(
        id=new_id("mb"), provider_type="simulator", email="demo@example.com",
        status="READY", health_status="HEALTHY", pool_id=pool.id, is_demo=True,
        created_at=utcnow(), updated_at=utcnow(),
    )
    real = Mailbox(
        id=new_id("mb"), provider_type="simulator", email="real@example.com",
        status="READY", health_status="HEALTHY", pool_id=pool.id, is_demo=False,
        created_at=utcnow(), updated_at=utcnow(),
    )
    session.add_all([demo, real])
    await session.flush()

    allocated = await pool_service.allocate(session, pool)
    assert allocated.id == real.id
    assert allocated.is_demo is False


def test_provider_config_masking():
    """敏感配置字段必须脱敏；掩码值回写时保留原值。"""
    from app.api.routers_tempmail_providers import _mask_config, _merge_masked_config

    masked = _mask_config({"base_url": "https://x", "api_key": "sk-123", "headers_json": '{"Authorization": "Bearer abc"}'})
    assert masked["base_url"] == "https://x"
    assert masked["api_key"] == "******"
    assert masked["headers_json"] == "******"

    merged = _merge_masked_config(
        {"base_url": "https://old", "api_key": "sk-secret"},
        {"base_url": "https://new", "api_key": "******"},
    )
    assert merged == {"base_url": "https://new", "api_key": "sk-secret"}


async def test_seed_demo_creates_marked_data(session):
    from scripts.seed import clean_demo, seed_demo

    n = await clean_demo(session)
    await session.commit()
    stats = await seed_demo(session)
    assert stats["mailboxes"] == 3
    assert stats["tasks"] == 5

    mbs = (await session.execute(select(Mailbox).where(Mailbox.is_demo == True))).scalars().all()  # noqa: E712
    assert len(mbs) == 3
    tasks = (await session.execute(select(RegistrationTask).where(RegistrationTask.is_demo == True))).scalars().all()  # noqa: E712
    assert len(tasks) == 5
    attempts = (await session.execute(select(ParseAttempt).where(ParseAttempt.is_demo == True))).scalars().all()  # noqa: E712
    assert len(attempts) >= 6

    # 清理
    n2 = await clean_demo(session)
    await session.commit()
    assert n2 >= 6


async def test_parse_writes_attempts(session):
    mb = Mailbox(
        id=new_id("mb"), provider_type="simulator", email="p@example.com",
        status="READY", health_status="HEALTHY", created_at=utcnow(), updated_at=utcnow(),
    )
    session.add(mb)
    await session.flush()
    msg = Message(
        id=new_id("msg"), mailbox_id=mb.id, provider_message_id="m1", dedupe_key="m1",
        sender="a@b.com", subject="Your code", body_text="code is 483921",
        received_at=utcnow(), created_at=utcnow(),
    )
    session.add(msg)
    await session.flush()

    results = await parser_service.parse_message(session, msg, provider_type="simulator")
    assert len(results) >= 1
    attempts = (await session.execute(select(ParseAttempt).where(ParseAttempt.message_id == msg.id))).scalars().all()
    assert len(attempts) >= 1
    assert any(a.rule_name for a in attempts)
