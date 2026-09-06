"""ORM -> 响应字典序列化。所有输出均不含明文凭据（§20）。"""
from __future__ import annotations

from ..models import (
    Alias,
    AuditLog,
    CfDomain,
    FetchTask,
    HealthCheckRecord,
    ImportBatch,
    ImportRow,
    Mailbox,
    Message,
    ParserRule,
    Pool,
    RegistrationTask,
    WebhookDelivery,
)
from ..services.parser_service import decrypt_result


def _dt(v):
    return v.isoformat() if v else None


def pool_out(p: Pool) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "max_concurrent": p.max_concurrent,
        "cooldown_seconds": p.cooldown_seconds,
        "daily_limit": p.daily_limit,
        "failure_threshold": p.failure_threshold,
        "auto_quarantine": p.auto_quarantine,
        "status": p.status,
        "created_at": _dt(p.created_at),
    }


def mailbox_out(m: Mailbox, pool_name: str | None = None, today_mail: int | None = None) -> dict:
    return {
        "id": m.id,
        "email": m.email,
        "display_name": m.display_name,
        "provider_type": m.provider_type,
        "status": m.status,
        "health_status": m.health_status,
        "health_score": m.health_score,
        "pool_id": m.pool_id,
        "pool_name": pool_name,
        "last_check_at": _dt(m.last_check_at),
        "last_sync_at": _dt(m.last_sync_at),
        "last_mail_at": _dt(m.last_mail_at),
        "last_used_at": _dt(m.last_used_at),
        "failure_count": m.failure_count,
        "tags": m.tags_json or [],
        "today_mail_count": today_mail,
        "created_at": _dt(m.created_at),
    }


def message_summary(m: Message, mailbox_email: str | None = None, has_results: bool = False) -> dict:
    return {
        "id": m.id,
        "mailbox_id": m.mailbox_id,
        "mailbox": mailbox_email,
        "sender": m.sender,
        "recipient": m.recipient,
        "subject": m.subject,
        "preview": (m.body_text or "")[:140],
        "received_at": _dt(m.received_at),
        "is_read": m.is_read,
        "is_archived": m.is_archived,
        "category": m.category,
        "parse_status": m.parse_status,
        "has_results": has_results,
    }


def message_detail(m: Message, mailbox_email: str | None, results: list[dict]) -> dict:
    return {
        **message_summary(m, mailbox_email, bool(results)),
        "body_text": m.body_text,
        "body_html": m.body_html,
        "headers": m.headers_json or {},
        "raw_storage_ref": m.raw_storage_ref,
        "created_at": _dt(m.created_at),
        "results": results,
    }


def task_out(t: RegistrationTask, mailbox_email: str | None = None, result: dict | None = None) -> dict:
    return {
        "id": t.id,
        "idempotency_key": t.idempotency_key,
        "external_ref": t.external_ref,
        "pool_id": t.pool_id,
        "mailbox_id": t.mailbox_id,
        "mailbox": mailbox_email,
        "state": t.state,
        "match": t.match_json or {},
        "timeout_seconds": t.timeout_seconds,
        "expires_at": _dt(t.expires_at),
        "result": result,
        "callback_url": t.callback_url,
        "callback_state": t.callback_state,
        "metadata": t.metadata_json or {},
        "created_at": _dt(t.created_at),
        "updated_at": _dt(t.updated_at),
    }


def fetch_task_out(t: FetchTask, mailbox_email: str | None = None) -> dict:
    return {
        "id": t.id,
        "mailbox_id": t.mailbox_id,
        "mailbox": mailbox_email,
        "task_type": t.task_type,
        "state": t.state,
        "attempt": t.attempt,
        "max_attempt": t.max_attempt,
        "next_run_at": _dt(t.next_run_at),
        "scheduled_at": _dt(t.scheduled_at),
        "started_at": _dt(t.started_at),
        "finished_at": _dt(t.finished_at),
        "error_code": t.error_code,
        "error_message": t.error_message,
        "payload": t.payload_json or {},
    }


def rule_out(r: ParserRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "provider_type": r.provider_type,
        "sender_pattern": r.sender_pattern,
        "subject_pattern": r.subject_pattern,
        "body_regex": r.body_regex,
        "output_type": r.output_type,
        "priority": r.priority,
        "status": r.status,
        "created_at": _dt(r.created_at),
    }


def alias_out(a: Alias, master_email: str | None = None) -> dict:
    return {
        "id": a.id,
        "master_mailbox_id": a.master_mailbox_id,
        "master": master_email,
        "alias_address": a.alias_address,
        "alias_type": a.alias_type,
        "status": a.status,
        "created_at": _dt(a.created_at),
    }


def domain_out(d: CfDomain, today_messages: int | None = None) -> dict:
    return {
        "id": d.id,
        "domain": d.domain,
        "status": d.status,
        "mode": d.mode,
        "dns_status": d.dns_status,
        "mx_status": d.mx_status,
        "spf_status": d.spf_status,
        "dkim_status": d.dkim_status,
        "has_inbound_secret": bool(d.inbound_secret_hash),
        "routing_config": d.routing_config_json or {},
        "notes": d.notes,
        "last_mail_at": _dt(d.last_mail_at),
        "today_messages": today_messages,
        "created_at": _dt(d.created_at),
    }


def batch_out(b: ImportBatch) -> dict:
    return {
        "id": b.id,
        "provider_type": b.provider_type,
        "source_type": b.source_type,
        "delimiter": b.delimiter,
        "field_mapping": b.field_mapping_json or [],
        "total_rows": b.total_rows,
        "valid_rows": b.valid_rows,
        "duplicate_rows": b.duplicate_rows,
        "error_rows": b.error_rows,
        "missing_rows": b.missing_rows,
        "status": b.status,
        "created_at": _dt(b.created_at),
        "committed_at": _dt(b.committed_at),
    }


def import_row_out(r: ImportRow) -> dict:
    return {
        "id": r.id,
        "line_no": r.line_no,
        "raw_line": r.raw_line,
        "segments": r.segments_json or [],
        "parsed": r.parsed_json or {},
        "status": r.status,
        "error": r.error_message,
    }


def health_check_out(h: HealthCheckRecord) -> dict:
    return {
        "id": h.id,
        "mailbox_id": h.mailbox_id,
        "score": h.score,
        "health_status": h.health_status,
        "checks": h.checks_json or {},
        "error": h.error,
        "created_at": _dt(h.created_at),
    }


def webhook_out(w: WebhookDelivery) -> dict:
    return {
        "id": w.id,
        "event_id": w.event_id,
        "task_id": w.task_id,
        "url": w.url,
        "attempt": w.attempt,
        "max_attempt": w.max_attempt,
        "state": w.state,
        "next_run_at": _dt(w.next_run_at),
        "last_status_code": w.last_status_code,
        "last_error": w.last_error,
        "delivered_at": _dt(w.delivered_at),
        "payload": w.payload_json or {},
        "created_at": _dt(w.created_at),
    }


def audit_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "actor_type": a.actor_type,
        "actor_id": a.actor_id,
        "action": a.action,
        "resource_type": a.resource_type,
        "resource_id": a.resource_id,
        "ip": a.ip,
        "metadata": a.metadata_json or {},
        "created_at": _dt(a.created_at),
    }


__all__ = [name for name in dir() if name.endswith("_out")] + ["decrypt_result"]
