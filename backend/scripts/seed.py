"""演示种子数据生成器（v1.2.0）。

用法：
    cd backend
    python scripts/seed.py --demo          # 生成演示数据（可重复运行，先清旧）
    python scripts/seed.py --demo --clean  # 仅清理演示数据

演示数据全部带 is_demo=true 标记，不污染真实业务数据。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.core import crypto  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import get_engine, get_sessionmaker, utcnow  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Mailbox,
    MailboxCredential,
    Message,
    ParseAttempt,
    ParseResult,
    Pool,
    RegistrationTask,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mailhub.seed_demo")

DEMO_PROVIDER_TYPES = ("outlook", "imap", "cloudflare")
DEMO_DOMAINS = ("demo1.example.com", "demo2.example.com")


def _now() -> None:
    return utcnow()


async def clean_demo(session) -> int:
    """清理全部 is_demo 数据。返回删除条数。按外键依赖顺序：先子后父。"""
    total = 0
    for model in (ParseResult, ParseAttempt, RegistrationTask, Message, MailboxCredential, Mailbox):
        result = await session.execute(delete(model).where(model.is_demo == True))  # noqa: E712
        total += result.rowcount or 0
    return total


async def seed_demo(session) -> dict:
    # 1. 默认池
    pool = (
        await session.execute(select(Pool).where(Pool.name == "default"))
    ).scalar_one_or_none()
    if pool is None:
        pool = Pool(id=new_id("pool"), name="default", description="默认邮箱池",
                    max_concurrent=1, cooldown_seconds=300, daily_limit=20)
        session.add(pool)
        await session.flush()

    # 2. 演示邮箱（3 个）
    emails = []
    for i in range(3):
        provider_type = DEMO_PROVIDER_TYPES[i % len(DEMO_PROVIDER_TYPES)]
        email = f"demo{i + 1}@{DEMO_DOMAINS[i % len(DEMO_DOMAINS)]}"
        mb = Mailbox(
            id=new_id("mb"),
            provider_type=provider_type,
            email=email,
            display_name=f"演示邮箱 {i + 1}",
            status="READY",
            health_status="HEALTHY",
            health_score=random.randint(80, 100),
            pool_id=pool.id,
            is_demo=True,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(mb)
        emails.append(mb)

    # 3. 模拟消息 + 解析结果 + 解析尝试日志
    for idx, mb in enumerate(emails):
        # 每箱 2 封消息
        for j in range(2):
            otp = f"{random.randint(100000, 999999)}"
            msg = Message(
                id=new_id("msg"),
                mailbox_id=mb.id,
                provider_message_id=f"demo-{mb.id}-{j}",
                dedupe_key=f"demo|{mb.id}|{j}",
                sender="noreply@example.com" if j == 0 else "verify@demo-site.com",
                recipient=mb.email,
                subject="Your verification code" if j == 0 else "激活你的账号",
                body_text=f"Your verification code is {otp}. It expires in 10 minutes.",
                received_at=_now() - timedelta(minutes=random.randint(1, 60)),
                parse_status="PARSED",
                category="verification",
                is_demo=True,
                created_at=_now(),
            )
            session.add(msg)
            await session.flush()

            pr = ParseResult(
                id=new_id("pr"),
                message_id=msg.id,
                rule_id=None,
                rule_name="demo_otp",
                result_type="OTP",
                result_value_encrypted=crypto.encrypt_str(otp),
                confidence=0.97,
                is_demo=True,
                created_at=_now(),
            )
            session.add(pr)

            for k in range(3):
                hit = k == 0
                session.add(ParseAttempt(
                    id=new_id("pa"),
                    message_id=msg.id,
                    mailbox_id=mb.id,
                    rule_id=None,
                    rule_name=("demo_otp" if hit else "demo_other"),
                    provider_type=mb.provider_type,
                    outcome="HIT" if hit else "NO_MATCH",
                    output_type="OTP" if hit else "",
                    confidence=0.97 if hit else 0,
                    duration_ms=random.randint(5, 60),
                    error="",
                    is_demo=True,
                    created_at=_now(),
                ))

    # 4. 模拟注册任务（覆盖各状态）
    task_specs = [
        ("COMPLETED", "success"),
        ("COMPLETED", "success"),
        ("WAITING_EMAIL", None),
        ("TIMEOUT", None),
        ("RESULT_READY", None),
    ]
    for i, (state, claim) in enumerate(task_specs):
        mb = emails[i % len(emails)]
        task = RegistrationTask(
            id=new_id("task"),
            external_ref=f"demo-job-{i + 1}",
            pool_id=pool.id,
            mailbox_id=mb.id,
            state=state,
            match_json={"sender": "*", "subject_contains": "verif"},
            timeout_seconds=300,
            expires_at=_now() + timedelta(minutes=5),
            project_key="demo-project",
            caller_id="demo",
            claim_result=claim,
            is_demo=True,
            created_at=_now() - timedelta(minutes=random.randint(5, 120)),
            updated_at=_now(),
        )
        session.add(task)

    await session.commit()
    return {"mailboxes": len(emails), "tasks": len(task_specs)}


async def main() -> None:
    parser = argparse.ArgumentParser(description="MAIL HUB 演示种子数据")
    parser.add_argument("--demo", action="store_true", help="生成演示数据（先清理旧的）")
    parser.add_argument("--clean", action="store_true", help="仅清理演示数据")
    args = parser.parse_args()

    get_engine()
    async with get_sessionmaker()() as session:
        await session.run_sync(lambda s: Base.metadata.create_all(s.bind))
        # 已有库补 v1.2.0 新列（幂等）
        from app.core.db import ensure_schema_updates

        await ensure_schema_updates()

        if args.clean:
            n = await clean_demo(session)
            await session.commit()
            logger.info("已清理 %d 条演示数据", n)
            return

        if not args.demo:
            parser.print_help()
            return

        cleaned = await clean_demo(session)
        await session.commit()
        created = await seed_demo(session)
        logger.info("演示数据就绪：%s（清理旧数据 %d 条）", created, cleaned)
        logger.info("提示：演示数据带 is_demo 标记，不会影响真实业务数据；可运行 --clean 清理。")


if __name__ == "__main__":
    asyncio.run(main())
