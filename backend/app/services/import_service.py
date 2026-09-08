"""Outlook 四段式批量导入（§3.3/§7）：解析 -> 校验 -> 去重 -> 加密 -> 预览 -> 提交。"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import crypto
from ..core.db import utcnow
from ..core.ids import new_id
from ..models import FetchTask, ImportBatch, ImportRow, Mailbox, MailboxCredential
from . import mailbox_service
from .audit import audit

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Segment -> 业务字段（四段式不固定绑定机密字段，可配置映射 §3.3）
FIELD_TARGETS = [
    "email", "password", "refresh_token", "client_id", "client_secret",
    "tenant_id", "imap_host", "imap_port", "imap_user", "display_name", "ignore",
]
DEFAULT_MAPPING = ["email", "password", "refresh_token", "client_id"]

FIELD_TO_CREDENTIAL = {
    "password": "PASSWORD",
    "refresh_token": "OAUTH_REFRESH_TOKEN",
    "client_id": "OAUTH_CLIENT_ID",
    "client_secret": "OAUTH_CLIENT_SECRET",
    "tenant_id": "TENANT_ID",
    "imap_host": "IMAP_HOST",
    "imap_port": "IMAP_PORT",
    "imap_user": "IMAP_USER",
}

MANDATORY_FIELDS = ("email",)

# ---------------------------------------------------------------- 凭据字段加解密（§20）
# 凡映射到凭据的字段值（password/refresh_token/client_secret/imap_* 等）一律加密落库，
# 读库/导出时再解密，保证数据库不落任何明文凭据。非加密前缀的历史明文数据解密函数直接兼容。
ENC_PREFIX = "enc://"
SENSITIVE_TARGETS = frozenset(FIELD_TO_CREDENTIAL.keys())


def _enc_value(value) -> str:
    """加密单值；空值不加密。"""
    s = str(value or "")
    return ENC_PREFIX + crypto.encrypt_str(s) if s else s


def _dec_value(value) -> str:
    """解密单值；非加密前缀（历史明文）原样返回。"""
    s = str(value or "")
    return crypto.decrypt_str(s[len(ENC_PREFIX):]) if s.startswith(ENC_PREFIX) else s


def encrypt_parsed(parsed: dict) -> dict:
    """写库前：对 parsed 中敏感字段加密。"""
    return {k: _enc_value(v) if k in SENSITIVE_TARGETS and v else v for k, v in (parsed or {}).items()}


def decrypt_parsed(parsed: dict | None) -> dict:
    """读库/预览前：解密 parsed 中敏感字段。"""
    return {k: _dec_value(v) if k in SENSITIVE_TARGETS else v for k, v in (parsed or {}).items()}


def encrypt_segments(segments: list, mapping: list[str]) -> list:
    """写库前：按 field_mapping 对齐加密敏感列（PASTE/CSV 场景）。"""
    mapping = list(mapping or [])
    out = []
    for idx, seg in enumerate(segments or []):
        target = mapping[idx] if idx < len(mapping) else None
        out.append(_enc_value(seg) if target in SENSITIVE_TARGETS and seg else seg)
    return out


def decrypt_segments(segments: list, mapping: list[str]) -> list:
    """读库前：按 field_mapping 对齐解密敏感列。"""
    mapping = list(mapping or [])
    out = []
    for idx, seg in enumerate(segments or []):
        target = mapping[idx] if idx < len(mapping) else None
        out.append(_dec_value(seg) if target in SENSITIVE_TARGETS else seg)
    return out


def encrypt_raw_line(raw: str) -> str:
    """写库前：原始文本行整体加密，确保无法从 DB 直接还原含凭据的原始行。"""
    s = str(raw or "")
    return _enc_value(s) if s else s


def decrypt_raw_line(raw: str) -> str:
    """读库/导出前：解密原始文本行。"""
    s = str(raw or "")
    return _dec_value(s)


def _normalize_mapping(mapping: list[str] | None, expected_len: int | None = None) -> list[str]:
    if not mapping:
        mapping = list(DEFAULT_MAPPING)
    clean = [m if m in FIELD_TARGETS else "ignore" for m in mapping]
    if expected_len and len(clean) < expected_len:
        clean += ["ignore"] * (expected_len - len(clean))
    return clean


def _validate_row(parsed: dict, delimiter: str, segment_count: int, mapping: list[str]) -> tuple[str, str]:
    """返回 (status, error_message)。"""
    required_targets = [t for t in mapping if t != "ignore"]
    email = (parsed.get("email") or "").strip().lower()
    if not email:
        missing = [t for t in required_targets if not (parsed.get(t) or "").strip()]
        if missing:
            return "MISSING", f"missing fields: {', '.join(missing)}"
        return "ERROR", "email is empty"
    if not EMAIL_RE.match(email):
        return "ERROR", f"invalid email format: {email}"
    missing = [t for t in required_targets if t not in MANDATORY_FIELDS and not (parsed.get(t) or "").strip()]
    if missing:
        return "MISSING", f"missing fields: {', '.join(missing)}"
    return "VALID", ""


def _build_parsed(segments: list[str], mapping: list[str]) -> dict:
    parsed: dict = {}
    for idx, target in enumerate(mapping):
        if target == "ignore" or idx >= len(segments):
            continue
        parsed[target] = (segments[idx] or "").strip()
    return parsed


def parse_lines(source_type: str, source_text: str, delimiter: str, mapping: list[str]) -> list[dict]:
    """把原始文本解析成行记录：{line_no, raw_line, segments, parsed}。"""
    rows: list[dict] = []
    text = (source_text or "").replace("\r\n", "\n").strip("\n")
    mapping = _normalize_mapping(mapping)

    if source_type == "JSON":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return [{"line_no": 1, "raw_line": text[:200], "segments": [], "parsed": {},
                     "status": "ERROR", "error_message": f"invalid JSON: {exc}"}]
        if not isinstance(data, list):
            data = [data]
        for i, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                rows.append({"line_no": i, "raw_line": str(item)[:200], "segments": [], "parsed": {},
                             "status": "ERROR", "error_message": "JSON item must be object"})
                continue
            parsed = {}
            for target in FIELD_TARGETS:
                if target == "ignore":
                    continue
                if target in item and item[target] is not None:
                    parsed[target] = str(item[target]).strip()
            rows.append({"line_no": i, "raw_line": json.dumps(item, ensure_ascii=False), "segments": [],
                         "parsed": parsed, "status": "VALID", "error_message": ""})
        return rows

    if source_type == "CSV":
        reader = csv.reader(io.StringIO(text))
        records = [r for r in reader if any((c or "").strip() for c in r)]
        if not records:
            return []
        header = [c.strip().lower() for c in records[0]]
        header_mode = all(h in FIELD_TARGETS for h in header if h) and any(h == "email" for h in header)
        if header_mode:
            mapping = [h if h else "ignore" for h in header]
            records = records[1:]
        for i, cells in enumerate(records, start=1):
            parsed = _build_parsed([c.strip() for c in cells], mapping)
            rows.append({"line_no": i, "raw_line": delimiter.join(cells), "segments": cells,
                         "parsed": parsed, "status": "VALID", "error_message": ""})
        return rows

    # PASTE：四段式文本（§7）
    for i, line in enumerate(text.split("\n"), start=1):
        line = line.strip()
        if not line:
            continue
        segments = [s.strip() for s in line.split(delimiter)]
        parsed = _build_parsed(segments, mapping)
        rows.append({"line_no": i, "raw_line": line, "segments": segments,
                     "parsed": parsed, "status": "VALID", "error_message": ""})
    return rows


async def create_batch(
    session: AsyncSession,
    *,
    provider_type: str,
    source_type: str,
    delimiter: str,
    field_mapping: list[str],
    source_text: str,
    created_by: str = "",
    pool_id: str | None = None,
) -> ImportBatch:
    """解析 + 校验 + 去重，落库为批次（PREVIEWED）。"""
    mapping = _normalize_mapping(field_mapping)
    rows = parse_lines(source_type, source_text, delimiter, mapping)

    batch = ImportBatch(
        id=new_id("imp"),
        provider_type=provider_type,
        source_type=source_type,
        delimiter=delimiter,
        field_mapping_json=mapping,
        total_rows=len(rows),
        status="PREVIEWED",
        created_by=created_by,
        created_at=utcnow(),
    )
    if pool_id:
        batch.pool_id = pool_id
    session.add(batch)
    await session.flush()

    seen_emails: set[str] = set()
    counts = {"VALID": 0, "DUPLICATE": 0, "ERROR": 0, "MISSING": 0}
    # 批量预取已存在邮箱，避免逐行 N+1 查询
    all_emails = {(r["parsed"].get("email") or "").strip().lower() for r in rows if r["parsed"].get("email")}
    existing_emails: set[str] = set()
    if all_emails:
        existing_emails = {
            e
            for (e,) in (
                await session.execute(select(Mailbox.email).where(Mailbox.email.in_(all_emails)))
            ).all()
        }
    for row in rows:
        status, error = _validate_row(row["parsed"], delimiter, len(row["segments"]), mapping)
        email = (row["parsed"].get("email") or "").strip().lower()
        if status == "VALID":
            if email in seen_emails:
                status, error = "DUPLICATE", "duplicate email within batch"
            elif email in existing_emails:
                status, error = "DUPLICATE", "mailbox already exists"
            seen_emails.add(email)
        counts[status] += 1
        session.add(
            ImportRow(
                id=new_id("imr"),
                batch_id=batch.id,
                line_no=row["line_no"],
                raw_line=encrypt_raw_line(row["raw_line"][:2000]),
                segments_json=encrypt_segments(row["segments"], mapping),
                parsed_json=encrypt_parsed(row["parsed"]),
                status=status,
                error_message=error,
            )
        )
    batch.valid_rows = counts["VALID"]
    batch.duplicate_rows = counts["DUPLICATE"]
    batch.error_rows = counts["ERROR"]
    batch.missing_rows = counts["MISSING"]
    await session.flush()
    return batch


async def commit_batch(
    session: AsyncSession,
    batch: ImportBatch,
    *,
    actor_id: str = "",
    ip: str = "",
) -> dict:
    if batch.status == "COMMITTED":
        return {"imported": 0, "skipped": 0, "batch_id": batch.id, "already_committed": True}
    rows = (
        await session.execute(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.line_no))
    ).scalars().all()

    imported, skipped = 0, 0
    credential_fields = [f for f in batch.field_mapping_json if f in FIELD_TO_CREDENTIAL]
    for row in rows:
        if row.status != "VALID":
            continue
        parsed = decrypt_parsed(row.parsed_json or {})
        email = (parsed.get("email") or "").strip().lower()
        if await mailbox_service.find_by_email(session, email):
            row.status = "DUPLICATE"
            row.error_message = "mailbox already exists (commit re-check)"
            batch.duplicate_rows += 1
            batch.valid_rows -= 1
            skipped += 1
            continue

        mailbox = await mailbox_service.create_mailbox(
            session,
            email=email,
            provider_type=batch.provider_type,
            credentials={FIELD_TO_CREDENTIAL[f]: parsed.get(f, "") for f in credential_fields},
            display_name=parsed.get("display_name", ""),
            pool_id=batch.pool_id,
        )
        imported += 1
        # 导入后建立健康检查任务（§7 导入 -> 建立健康检查任务）
        session.add(
            FetchTask(
                id=new_id("ft"),
                mailbox_id=mailbox.id,
                task_type="HEALTH_CHECK",
                state="QUEUED",
                next_run_at=utcnow(),
                scheduled_at=utcnow(),
                payload_json={"source": "import"},
            )
        )

    batch.status = "COMMITTED"
    batch.committed_at = utcnow()
    await audit(session, "import.commit", resource_type="import_batch", resource_id=batch.id,
                actor_id=actor_id, ip=ip,
                metadata={"provider_type": batch.provider_type, "imported": imported, "skipped": skipped})
    return {"imported": imported, "skipped": skipped, "batch_id": batch.id, "already_committed": False}


def errors_csv(batch: ImportBatch, rows: list[ImportRow]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["line_no", "status", "error", "raw_line"])
    for r in rows:
        if r.status in ("DUPLICATE", "ERROR", "MISSING"):
            writer.writerow([r.line_no, r.status, r.error_message, decrypt_raw_line(r.raw_line or "")])
    return buf.getvalue()
