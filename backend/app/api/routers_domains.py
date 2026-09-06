import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.db import get_db, utcnow
from ..core.events import bus
from ..models import CfDomain, Message
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import DomainIn, DomainPatchIn
from .serializers import domain_out, message_summary

router = APIRouter(prefix="/cf-domains", tags=["cf-domains"])


@router.get("")
async def list_domains(session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    rows = (await session.execute(select(CfDomain).order_by(CfDomain.created_at.asc()))).scalars().all()
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    items = []
    for d in rows:
        today_messages = (
            await session.execute(
                select(func.count(Message.id)).where(
                    Message.recipient.like(f"%@{d.domain}"), Message.received_at >= today
                )
            )
        ).scalar_one()
        items.append(domain_out(d, today_messages))
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_domain(body: DomainIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    domain = body.domain.strip().lower()
    if "." not in domain:
        raise HTTPException(400, "invalid domain")
    exists = (await session.execute(select(CfDomain).where(CfDomain.domain == domain))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "domain already exists")
    secret = body.inbound_secret or f"cf_{_secrets.token_hex(16)}"
    row = CfDomain(
        id=f"dom_{domain.replace('.', '_')}_{utcnow().strftime('%H%M%S')}",
        domain=domain,
        mode=body.mode,
        notes=body.notes,
        inbound_secret_hash=crypto.sha256_hex(secret),
    )
    session.add(row)
    await audit(session, "domain.create", resource_type="cf_domain", resource_id=row.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request), metadata={"domain": domain})
    await session.commit()
    # inbound_secret 仅在创建响应中返回一次（Secret Store 语义，§20）
    return {**domain_out(row), "inbound_secret": secret}


@router.patch("/{domain_id}")
async def patch_domain(domain_id: str, body: DomainPatchIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    row = await session.get(CfDomain, domain_id)
    if not row:
        raise HTTPException(404, "domain not found")
    data = body.model_dump(exclude_none=True)
    if "routing_config" in data:
        row.routing_config_json = data.pop("routing_config")
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_at = utcnow()
    await audit(session, "domain.update", resource_type="cf_domain", resource_id=row.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return domain_out(row)


@router.delete("/{domain_id}")
async def delete_domain(domain_id: str, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    row = await session.get(CfDomain, domain_id)
    if not row:
        raise HTTPException(404, "domain not found")
    await session.delete(row)
    await audit(session, "domain.delete", resource_type="cf_domain", resource_id=domain_id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    return {"ok": True}


@router.post("/{domain_id}/check-dns")
async def check_dns(domain_id: str, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    """通过 DNS-over-HTTPS 实际检查 MX/SPF/DKIM 记录（无外网时标记 unknown）。"""
    import httpx

    row = await session.get(CfDomain, domain_id)
    if not row:
        raise HTTPException(404, "domain not found")

    async def resolve(name: str, rtype: str) -> list[str] | None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://dns.google/resolve", params={"name": name, "type": rtype})
            if resp.status_code != 200:
                return None
            data = resp.json()
            return [a.get("data", "") for a in data.get("Answer", [])]
        except Exception:
            return None

    mx = await resolve(row.domain, "MX")
    txt = await resolve(row.domain, "TXT")
    if mx is None or txt is None:
        row.mx_status = row.mx_status if row.mx_status != "unknown" else "unknown"
        dns_ok = False
    else:
        row.mx_status = "ok" if mx else "missing"
        spf = any((t or "").startswith("v=spf1") for t in txt)
        dkim = bool(await resolve(f"cf2024-1._domainkey.{row.domain}", "TXT")) or bool(
            await resolve(f"default._domainkey.{row.domain}", "TXT")
        )
        row.spf_status = "ok" if spf else "missing"
        row.dkim_status = "ok" if dkim else "missing"
        dns_ok = bool(mx)
    row.dns_status = "ok" if dns_ok else ("failed" if (mx is not None and not mx) else "unknown")
    row.updated_at = utcnow()
    await audit(session, "domain.check_dns", resource_type="cf_domain", resource_id=row.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request),
                metadata={"dns_status": row.dns_status, "mx_status": row.mx_status})
    await session.commit()
    await bus.publish("mailbox.health.changed", {"domain": row.domain, "dns_status": row.dns_status, "mx_status": row.mx_status})
    return domain_out(row)


@router.get("/{domain_id}/messages")
async def domain_messages(domain_id: str, limit: int = 50, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    row = await session.get(CfDomain, domain_id)
    if not row:
        raise HTTPException(404, "domain not found")
    messages = (
        await session.execute(
            select(Message).where(Message.recipient.like(f"%@{row.domain}")).order_by(Message.received_at.desc()).limit(limit)
        )
    ).scalars().all()
    return {"items": [message_summary(m) for m in messages], "total": len(messages)}
