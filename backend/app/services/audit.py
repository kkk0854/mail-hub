"""审计日志（§20 所有关键操作写 Audit Log）。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import utcnow
from ..models import AuditLog


async def audit(
    session: AsyncSession,
    action: str,
    *,
    resource_type: str = "",
    resource_id: str = "",
    actor_type: str = "user",
    actor_id: str = "",
    ip: str = "",
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip or "",
            metadata_json=metadata or {},
            created_at=utcnow(),
        )
    )
