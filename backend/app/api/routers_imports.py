from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..core.events import bus
from ..models import ImportBatch, ImportRow
from ..services import import_service
from ..services.audit import audit
from .deps import client_ip, get_current_user
from .schemas import ImportCommitIn, ImportIn
from .serializers import batch_out, import_row_out

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/preview")
async def preview(body: ImportIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    if not body.source_text.strip():
        raise HTTPException(400, "source_text is empty")
    batch = await import_service.create_batch(
        session,
        provider_type=body.provider_type,
        source_type=body.source_type,
        delimiter=body.delimiter or ":",
        field_mapping=body.field_mapping,
        source_text=body.source_text,
        created_by=getattr(user, "username", ""),
        pool_id=body.pool_id or None,
    )
    await audit(session, "import.preview", resource_type="import_batch", resource_id=batch.id,
                actor_id=getattr(user, "username", ""), ip=client_ip(request),
                metadata={"total": batch.total_rows, "valid": batch.valid_rows})
    await session.commit()
    rows = (
        await session.execute(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.line_no).limit(500))
    ).scalars().all()
    return {**batch_out(batch), "rows": [import_row_out(r, batch.field_mapping_json or []) for r in rows]}


@router.post("/validate")
async def validate(body: ImportIn, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    """只校验不落库：解析 + 格式校验 + 重复检测。"""
    from ..services.import_service import _normalize_mapping, _validate_row, parse_lines
    from ..models import Mailbox

    if not body.source_text.strip():
        raise HTTPException(400, "source_text is empty")
    mapping = _normalize_mapping(body.field_mapping)
    rows = parse_lines(body.source_type, body.source_text, body.delimiter or ":", mapping)
    seen: set[str] = set()
    counts = {"VALID": 0, "DUPLICATE": 0, "ERROR": 0, "MISSING": 0}
    errors = []
    emails = {(r["parsed"].get("email") or "").strip().lower() for r in rows if r["parsed"].get("email")}
    existing: set[str] = set()
    if emails:
        existing = {e for (e,) in (await session.execute(select(Mailbox.email).where(Mailbox.email.in_(emails)))).all()}
    for row in rows:
        status, error = _validate_row(row["parsed"], body.delimiter or ":", len(row["segments"]), mapping)
        email = (row["parsed"].get("email") or "").strip().lower()
        if status == "VALID":
            if email in seen:
                status, error = "DUPLICATE", "duplicate email within batch"
            elif email in existing:
                status, error = "DUPLICATE", "mailbox already exists"
            seen.add(email)
        counts[status] += 1
        if status != "VALID" and len(errors) < 50:
            errors.append({"line_no": row["line_no"], "status": status, "error": error, "raw_line": row["raw_line"]})
    return {"total": len(rows), **{k.lower(): v for k, v in counts.items()}, "errors": errors}


@router.post("/commit")
async def commit(body: ImportCommitIn, request: Request, session: AsyncSession = Depends(get_db), user: object = Depends(get_current_user)):
    batch = await session.get(ImportBatch, body.batch_id)
    if not batch:
        raise HTTPException(404, "import batch not found")
    if batch.status == "COMMITTED":
        raise HTTPException(409, "batch already committed")
    result = await import_service.commit_batch(session, batch, actor_id=getattr(user, "username", ""), ip=client_ip(request))
    await session.commit()
    await bus.publish("import.completed", {"batch_id": batch.id, "imported": result["imported"], "provider_type": batch.provider_type})
    return result


@router.get("/{batch_id}")
async def get_batch(batch_id: str, page: int = 1, page_size: int = 100, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    batch = await session.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "import batch not found")
    rows = (
        await session.execute(
            select(ImportRow).where(ImportRow.batch_id == batch_id).order_by(ImportRow.line_no).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {**batch_out(batch), "rows": [import_row_out(r, batch.field_mapping_json or []) for r in rows]}


@router.get("/{batch_id}/errors.csv", response_class=PlainTextResponse)
async def error_rows_csv(batch_id: str, session: AsyncSession = Depends(get_db), _: object = Depends(get_current_user)):
    batch = await session.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "import batch not found")
    rows = (await session.execute(select(ImportRow).where(ImportRow.batch_id == batch_id).order_by(ImportRow.line_no))).scalars().all()
    return PlainTextResponse(
        import_service.errors_csv(batch, list(rows)),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=import-{batch_id}-errors.csv"},
    )
