"""邮箱健康检查（§8）：四维检查 + 健康评分 + 自动隔离/自动回池。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import utcnow
from ..core.events import bus
from ..core.ids import new_id
from ..models import HealthCheckRecord, Mailbox, Pool
from . import mailbox_service
from .audit import audit

logger = logging.getLogger("mailhub.health")

# §8.3 评分权重：认证 30 / 同步 25 / 取件 20 / 失败次数 15 / 网络 10
SCORE_WEIGHTS = {"auth": 30, "sync": 25, "fetch": 20, "failure": 15, "network": 10}


def compute_score(result, failure_count: int) -> int:
    failure_component = SCORE_WEIGHTS["failure"] if failure_count == 0 else max(0, SCORE_WEIGHTS["failure"] - failure_count * 5)
    score = 0
    score += SCORE_WEIGHTS["auth"] if result.authorization else 0
    score += SCORE_WEIGHTS["sync"] if result.sync else 0
    score += SCORE_WEIGHTS["fetch"] if result.fetch else 0
    score += SCORE_WEIGHTS["network"] if result.connectivity else 0
    score += failure_component
    return int(score)


def score_band(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 50:
        return "Warning"
    if score >= 1:
        return "Critical"
    return "Dead"


def health_status_from(result) -> str:
    if not result.connectivity:
        return "NETWORK_ERROR"
    if not result.authorization:
        return result.auth_error_code or "AUTH_FAILED"
    if not result.sync:
        return "SYNC_ERROR"
    if not result.fetch:
        return "WARNING"
    return "HEALTHY"


async def run_health_check(session: AsyncSession, mailbox: Mailbox, *, actor_type: str = "system", actor_id: str = "scheduler") -> HealthCheckRecord:
    old_status = mailbox.health_status
    old_lifecycle = mailbox.status
    error = ""
    result = None
    try:
        provider = await mailbox_service.build_provider(session, mailbox)
        result = await provider.health_check()
    except Exception as exc:
        logger.warning("health check provider error for %s: %s", mailbox.email, exc)
        from ..providers.base import HealthCheckResult

        error = f"{type(exc).__name__}: {exc}"
        result = HealthCheckResult(connectivity=False, authorization=False, sync=False, fetch=False, details={"error": error})

    score = compute_score(result, mailbox.failure_count or 0)
    new_status = health_status_from(result)

    now = utcnow()
    mailbox.last_check_at = now
    mailbox.health_status = new_status
    mailbox.health_score = score
    mailbox.updated_at = now

    quarantine_reason = None
    if result.ok:
        mailbox.failure_count = 0
        # §6 生命周期推进：导入/校验通过 -> READY；§8.2 恢复：隔离邮箱检查通过后自动回池
        if mailbox.status in ("IMPORTED", "VALIDATING", "QUARANTINED"):
            mailbox.status = "READY"
            await audit(session, "mailbox.ready", resource_type="mailbox", resource_id=mailbox.id,
                        actor_type=actor_type, actor_id=actor_id, metadata={"email": mailbox.email, "score": score,
                                                                            "recovered": old_lifecycle == "QUARANTINED"})
    else:
        mailbox.failure_count = (mailbox.failure_count or 0) + 1
        pool = await session.get(Pool, mailbox.pool_id) if mailbox.pool_id else None
        threshold = pool.failure_threshold if pool else 3
        if pool and pool.auto_quarantine and mailbox.failure_count >= threshold and mailbox.status != "QUARANTINED":
            mailbox.status = "QUARANTINED"
            quarantine_reason = f"failure_count={mailbox.failure_count} >= threshold={threshold}"

    record = HealthCheckRecord(
        id=new_id("hc"),
        mailbox_id=mailbox.id,
        score=score,
        health_status=new_status,
        checks_json=result.to_dict(),
        error=error,
        created_at=utcnow(),
    )
    session.add(record)

    await audit(session, "mailbox.health_check", resource_type="mailbox", resource_id=mailbox.id,
                actor_type=actor_type, actor_id=actor_id, metadata={"status": new_status, "score": score})
    await bus.publish(
        "mailbox.health.changed",
        {"mailbox_id": mailbox.id, "email": mailbox.email, "health_status": new_status,
         "previous": old_status, "score": score, "band": score_band(score)},
    )
    if mailbox.status != old_lifecycle:
        await bus.publish(
            "mailbox.status.changed",
            {"mailbox_id": mailbox.id, "email": mailbox.email, "status": mailbox.status, "previous": old_lifecycle,
             "reason": quarantine_reason},
        )
    return record


async def mark_validating(session: AsyncSession, mailbox: Mailbox) -> None:
    mailbox.status = "VALIDATING"
    mailbox.updated_at = utcnow()
