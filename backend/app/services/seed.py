"""启动种子数据：管理员账号、默认 API Key、默认邮箱池、内置解析规则。"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto, security
from ..core.config import settings
from ..core.ids import new_id
from ..models import ApiKey, ParserRule, Pool, User

logger = logging.getLogger("mailhub.seed")

DEFAULT_RULES = [
    # 优先级数字越小越优先
    {"name": "otp_6digit", "sender_pattern": "*", "subject_pattern": "",
     "body_regex": r"\b(\d{6})\b", "output_type": "OTP", "priority": 10},
    {"name": "otp_keyword", "sender_pattern": "*",
     "subject_pattern": r"verif|code|otp|验证码|动态码|确认码",
     "body_regex": r"\b(\d{4,8})\b", "output_type": "OTP", "priority": 20},
    {"name": "activation_link", "sender_pattern": "*",
     "subject_pattern": r"verif|confirm|activate|激活|验证|注册",
     "body_regex": r"(https?://[^\s<>\"']+)", "output_type": "ACTIVATION_LINK", "priority": 20},
    {"name": "security_notice", "sender_pattern": "*",
     "subject_pattern": r"security|alert|安全|异常登录|告警",
     "body_regex": "", "output_type": "SECURITY_EVENT", "priority": 30},
    {"name": "generic_url", "sender_pattern": "*", "subject_pattern": "",
     "body_regex": r"(https?://[^\s<>\"']+)", "output_type": "URL", "priority": 90},
]


async def seed(session: AsyncSession) -> None:
    # 管理员账号
    user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    if user_count == 0:
        session.add(
            User(
                id=new_id("usr"),
                username=settings.admin_username,
                password_hash=security.hash_password(settings.admin_password),
                role="admin",
            )
        )
        logger.info("seeded admin user %r", settings.admin_username)

    # 默认 API Key（外部系统调用注册任务接口）
    api_key_count = (await session.execute(select(func.count(ApiKey.id)))).scalar_one()
    if api_key_count == 0:
        key = settings.api_key
        session.add(
            ApiKey(
                id=new_id("key"),
                name="default",
                key_hash=crypto.sha256_hex(key),
                prefix=key[:8],
            )
        )
        logger.info("seeded default API key (%s...)", key[:8])

    # 默认邮箱池
    pool_count = (await session.execute(select(func.count(Pool.id)))).scalar_one()
    if pool_count == 0:
        session.add(
            Pool(
                id=new_id("pool"),
                name="default",
                description="默认邮箱池",
                max_concurrent=1,
                cooldown_seconds=300,
                daily_limit=20,
                failure_threshold=3,
                auto_quarantine=True,
            )
        )
        logger.info("seeded default pool")

    # 内置解析规则
    rule_count = (await session.execute(select(func.count(ParserRule.id)))).scalar_one()
    if rule_count == 0:
        for spec in DEFAULT_RULES:
            session.add(ParserRule(id=new_id("rule"), **spec))
        logger.info("seeded %d parser rules", len(DEFAULT_RULES))

    await session.commit()
