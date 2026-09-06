from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..models import Alias, CfDomain, Mailbox
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import AliasIn
from .serializers import alias_out

router = APIRouter(prefix="/aliases", tags=["aliases"])


@router.get("")
async def list_aliases(master_mailbox_id: str = "", session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    stmt = select(Alias).order_by(Alias.created_at.desc())
    if master_mailbox_id:
        stmt = stmt.where(Alias.master_mailbox_id == master_mailbox_id)
    rows = (await session.execute(stmt)).scalars().all()
    master_ids = list({a.master_mailbox_id for a in rows})
    emails: dict[str, str] = {}
    if master_ids:
        rows2 = (await session.execute(select(Mailbox.id, Mailbox.email).where(Mailbox.id.in_(master_ids)))).all()
        emails = {mid: email for mid, email in rows2}
    return {"items": [alias_out(a, emails.get(a.master_mailbox_id)) for a in rows], "total": len(rows)}


@router.post("", status_code=201)
async def create_alias(body: AliasIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    alias_address = body.alias_address.strip().lower()
    if "@" not in alias_address:
        raise HTTPException(400, "invalid alias address")
    master = await session.get(Mailbox, body.master_mailbox_id)
    if not master:
        raise HTTPException(404, "master mailbox not found")
    exists = (await session.execute(select(Alias).where(Alias.alias_address == alias_address))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "alias already exists")
    # 别名域名必须与主邮箱域名一致（plus 寻址）或属于已注册的 CF 域名
    alias_domain = alias_address.split("@")[-1]
    master_domain = master.email.split("@")[-1]
    if alias_domain != master_domain:
        cf = (await session.execute(select(CfDomain).where(CfDomain.domain == alias_domain))).scalar_one_or_none()
        if not cf:
            raise HTTPException(400, "alias domain must match master domain or a registered CF domain")
    alias = Alias(id=f"al_{alias_address.replace('@', '_at_').replace('+', '_p_').replace('.', '_d_')[:32]}{utcnow_ms()}", master_mailbox_id=master.id, alias_address=alias_address, alias_type=body.alias_type)
    session.add(alias)
    await audit(session, "alias.create", resource_type="alias", resource_id=alias.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request),
                metadata={"alias": alias_address, "master": master.email})
    await session.commit()
    return alias_out(alias, master.email)


@router.delete("/{alias_id}")
async def delete_alias(alias_id: str, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    alias = await session.get(Alias, alias_id)
    if not alias:
        raise HTTPException(404, "alias not found")
    await session.delete(alias)
    await audit(session, "alias.delete", resource_type="alias", resource_id=alias_id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return {"ok": True}


def utcnow_ms() -> str:
    from ..core.db import utcnow

    return str(int(utcnow().timestamp() * 1000))[-6:]
