"""MAIL HUB 数据模型（§15 数据库设计 + MVP 扩展表）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .core.db import utcnow
from .core.ids import new_id


class Base(DeclarativeBase):
    pass


def _pk(prefix: str) -> Mapped[str]:
    return mapped_column(String(40), primary_key=True, default=lambda: new_id(prefix))


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- users / auth
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _pk("usr")
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="admin")
    status: Mapped[str] = mapped_column(String(16), default="active")
    # 初始管理员（内置默认口令）必须改密后才能正常使用（§20 强制改密）
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = _pk("key")
    name: Mapped[str] = mapped_column(String(64), default="default")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _ts()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------- providers
class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = _pk("prov")
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    config_encrypted: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()


class TempMailProviderSetting(Base):
    """临时邮箱 Provider 插件配置（v1.2.0 插件化）。"""

    __tablename__ = "temp_mail_provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=10)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- pools
class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[str] = _pk("pool")
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    daily_limit: Mapped[int] = mapped_column(Integer, default=20)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)
    auto_quarantine: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- mailboxes
class Mailbox(Base):
    __tablename__ = "mailboxes"

    id: Mapped[str] = _pk("mb")
    provider_id: Mapped[Optional[str]] = mapped_column(ForeignKey("providers.id"), nullable=True)
    provider_type: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    # 生命周期: IMPORTED/VALIDATING/READY/IN_USE/COOLDOWN/AVAILABLE/QUARANTINED/DISABLED/ARCHIVED
    status: Mapped[str] = mapped_column(String(24), default="IMPORTED", index=True)
    # 健康状态: HEALTHY/WARNING/TOKEN_EXPIRED/AUTH_FAILED/SYNC_ERROR/RATE_LIMITED/NETWORK_ERROR/MAILBOX_UNAVAILABLE/QUARANTINED/DISABLED
    health_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True, index=True)
    health_score: Mapped[int] = mapped_column(Integer, default=0)
    pool_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pools.id"), nullable=True, index=True)
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_mail_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # v1.2.0: +tag 别名识别（user+tag@domain -> 主邮箱 user@domain）
    is_alias: Mapped[bool] = mapped_column(Boolean, default=False)
    real_main_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # v1.2.0: 演示数据标记（seed --demo 生成，便于清理）
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class MailboxCredential(Base):
    __tablename__ = "mailbox_credentials"

    id: Mapped[str] = _pk("cred")
    mailbox_id: Mapped[str] = mapped_column(ForeignKey("mailboxes.id"), index=True)
    credential_type: Mapped[str] = mapped_column(String(32))
    encrypted_value: Mapped[str] = mapped_column(Text)  # Fernet 加密，永不返回明文
    masked_preview: Mapped[str] = mapped_column(String(32), default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Alias(Base):
    __tablename__ = "aliases"

    id: Mapped[str] = _pk("al")
    master_mailbox_id: Mapped[str] = mapped_column(ForeignKey("mailboxes.id"), index=True)
    alias_address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    alias_type: Mapped[str] = mapped_column(String(16), default="plus")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- messages
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_message_dedupe"),)

    id: Mapped[str] = _pk("msg")
    mailbox_id: Mapped[str] = mapped_column(ForeignKey("mailboxes.id"), index=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), default="")
    dedupe_key: Mapped[str] = mapped_column(String(320), index=True)  # provider_id + provider_message_id 幂等（§21）
    thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender: Mapped[str] = mapped_column(String(255), default="", index=True)
    recipient: Mapped[str] = mapped_column(String(255), default="", index=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    headers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(24), default="normal", index=True)
    # PENDING / PARSED / PARSE_FAILED / NO_MATCH
    parse_status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    raw_storage_ref: Mapped[str] = mapped_column(String(255), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class ParseResult(Base):
    __tablename__ = "parse_results"

    id: Mapped[str] = _pk("pr")
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(64), default="")
    result_type: Mapped[str] = mapped_column(String(24), index=True)  # OTP/URL/SECURITY_EVENT/ORDER_ID/ACTIVATION_LINK/CUSTOM
    result_value_encrypted: Mapped[str] = mapped_column(Text)  # 结果值加密存储
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class ParseAttempt(Base):
    """解析尝试日志：记录每次解析的规则、置信度、耗时、结果，用于可观测性大盘。"""
    __tablename__ = "parse_attempts"

    id: Mapped[str] = _pk("pa")
    message_id: Mapped[str] = mapped_column(String(40), index=True)
    mailbox_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(64), default="")
    provider_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # HIT / NO_MATCH / REGEX_ERROR / EMPTY_VALUE
    outcome: Mapped[str] = mapped_column(String(16), default="NO_MATCH", index=True)
    output_type: Mapped[str] = mapped_column(String(24), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _ts()


class ParserRule(Base):
    __tablename__ = "parser_rules"

    id: Mapped[str] = _pk("rule")
    name: Mapped[str] = mapped_column(String(64))
    provider_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sender_pattern: Mapped[str] = mapped_column(String(255), default="*")
    subject_pattern: Mapped[str] = mapped_column(String(255), default="")
    body_regex: Mapped[str] = mapped_column(Text, default="")
    output_type: Mapped[str] = mapped_column(String(24), default="OTP")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- registration tasks
class RegistrationTask(Base):
    __tablename__ = "registration_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_task_idempotency"),)

    id: Mapped[str] = _pk("task")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    external_ref: Mapped[str] = mapped_column(String(255), default="", index=True)
    pool_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pools.id"), nullable=True)
    mailbox_id: Mapped[Optional[str]] = mapped_column(ForeignKey("mailboxes.id"), nullable=True, index=True)
    # CREATED/WAITING_MAILBOX/WAITING_EMAIL/EMAIL_RECEIVED/PARSING/RESULT_READY/WAITING_CALLBACK/COMPLETED
    # /TIMEOUT/PARSING_FAILED/MAILBOX_ERROR/CANCELLED
    state: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    match_json: Mapped[dict] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    callback_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    callback_state: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # 项目隔离：显式携带 project_key + caller_id 时，同项目 success 后邮箱回到 available 可跨项目复用；
    # 同项目内防重复领取（已 success 的邮箱不再分配给同一 project_key）
    project_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    caller_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    claim_result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # success/failed/none
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- background jobs
class FetchTask(Base):
    __tablename__ = "fetch_tasks"

    id: Mapped[str] = _pk("ft")
    mailbox_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    # MAIL_SYNC / HEALTH_CHECK / MAIL_PARSE
    task_type: Mapped[str] = mapped_column(String(24), index=True)
    state: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)  # QUEUED/RUNNING/RETRYING/SUCCESS/FAILED
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempt: Mapped[int] = mapped_column(Integer, default=4)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    scheduled_at: Mapped[datetime] = _ts()
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = _pk("imp")
    provider_type: Mapped[str] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(16), default="PASTE")  # PASTE/CSV/JSON
    delimiter: Mapped[str] = mapped_column(String(8), default=":")
    field_mapping_json: Mapped[list] = mapped_column(JSON, default=list)
    pool_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    missing_rows: Mapped[int] = mapped_column(Integer, default=0)
    # PENDING / PREVIEWED / COMMITTED / FAILED
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = _ts()
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[str] = _pk("imr")
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    raw_line: Mapped[str] = mapped_column(Text, default="")
    segments_json: Mapped[list] = mapped_column(JSON, default=list)
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # VALID / DUPLICATE / ERROR / MISSING
    status: Mapped[str] = mapped_column(String(16), default="VALID", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- cloudflare domains
class CfDomain(Base):
    __tablename__ = "cf_domains"

    id: Mapped[str] = _pk("dom")
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    mode: Mapped[str] = mapped_column(String(16), default="WORKER")  # WORKER / DESTINATION
    dns_status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok / failed / unknown
    mx_status: Mapped[str] = mapped_column(String(16), default="unknown")
    spf_status: Mapped[str] = mapped_column(String(16), default="unknown")
    dkim_status: Mapped[str] = mapped_column(String(16), default="unknown")
    inbound_secret_hash: Mapped[str] = mapped_column(String(64), default="")
    routing_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    last_mail_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- webhooks
class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("event_id", name="uq_webhook_event"),)

    id: Mapped[str] = _pk("wh")
    event_id: Mapped[str] = mapped_column(String(40), index=True)  # 幂等 ID（§21）
    task_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempt: Mapped[int] = mapped_column(Integer, default=5)
    state: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)  # PENDING/SUCCESS/RETRYING/EXHAUSTED
    next_run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# ---------------------------------------------------------------- health / audit / events
class HealthCheckRecord(Base):
    __tablename__ = "health_checks"

    id: Mapped[str] = _pk("hc")
    mailbox_id: Mapped[str] = mapped_column(String(40), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    health_status: Mapped[str] = mapped_column(String(24))
    checks_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _ts()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")
    actor_id: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="")
    resource_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(40), default="")
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _ts()
