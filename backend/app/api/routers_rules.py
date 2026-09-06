from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..models import ParserRule
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import RuleIn, RulePatchIn
from .serializers import rule_out

router = APIRouter(prefix="/parser-rules", tags=["parser-rules"])


@router.get("")
async def list_rules(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    rows = (await session.execute(select(ParserRule).order_by(ParserRule.priority.asc()))).scalars().all()
    return {"items": [rule_out(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201)
async def create_rule(body: RuleIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    if body.output_type not in ("OTP", "URL", "SECURITY_EVENT", "ORDER_ID", "ACTIVATION_LINK", "CUSTOM"):
        raise HTTPException(400, "invalid output_type")
    rule = ParserRule(**body.model_dump())
    session.add(rule)
    await audit(session, "rule.create", resource_type="parser_rule", resource_id=rule.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"name": body.name})
    await session.commit()
    return rule_out(rule)


@router.patch("/{rule_id}")
async def patch_rule(rule_id: str, body: RulePatchIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    rule = await session.get(ParserRule, rule_id)
    if not rule:
        raise HTTPException(404, "rule not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    await audit(session, "rule.update", resource_type="parser_rule", resource_id=rule.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return rule_out(rule)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    rule = await session.get(ParserRule, rule_id)
    if not rule:
        raise HTTPException(404, "rule not found")
    await session.delete(rule)
    await audit(session, "rule.delete", resource_type="parser_rule", resource_id=rule_id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return {"ok": True}
