from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..models import AuditLog, WebhookDelivery
from .deps import require_admin
from .serializers import audit_out, webhook_out

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
async def list_audit_logs(
    action: str = "",
    resource_type: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
        count_stmt = count_stmt.where(AuditLog.resource_type == resource_type)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": [audit_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}


router_webhooks = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router_webhooks.get("")
async def list_webhook_deliveries(
    state: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: object = Depends(require_admin),
):
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc())
    count_stmt = select(func.count(WebhookDelivery.id))
    if state:
        stmt = stmt.where(WebhookDelivery.state == state)
        count_stmt = count_stmt.where(WebhookDelivery.state == state)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": [webhook_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}
