"""请求体 Schema（Pydantic v2）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class MailboxCreateIn(BaseModel):
    email: str
    provider_type: str = "outlook"
    display_name: str = ""
    pool_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    credentials: dict[str, str] = Field(default_factory=dict)  # {"PASSWORD": "...", ...} 服务端加密存储


class MailboxPatchIn(BaseModel):
    display_name: str | None = None
    pool_id: str | None = None
    status: str | None = None
    tags: list[str] | None = None


class BatchIdsIn(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all: bool = False


class ImportIn(BaseModel):
    provider_type: str = "outlook"
    source_type: str = "PASTE"  # PASTE / CSV / JSON
    delimiter: str = ":"
    field_mapping: list[str] = Field(default_factory=list)
    source_text: str = ""
    pool_id: str | None = None  # 导入后直接加入邮箱池


class ImportCommitIn(BaseModel):
    batch_id: str


class FetchTaskCreateIn(BaseModel):
    mailbox_id: str
    task_type: str = "MAIL_SYNC"  # MAIL_SYNC / HEALTH_CHECK / MAIL_PARSE
    payload: dict = Field(default_factory=dict)


class AliasIn(BaseModel):
    master_mailbox_id: str
    alias_address: str
    alias_type: str = "plus"


class PoolIn(BaseModel):
    name: str
    description: str = ""
    max_concurrent: int = 1
    cooldown_seconds: int = 300
    daily_limit: int = 20
    failure_threshold: int = 3
    auto_quarantine: bool = True


class PoolPatchIn(BaseModel):
    description: str | None = None
    max_concurrent: int | None = None
    cooldown_seconds: int | None = None
    daily_limit: int | None = None
    failure_threshold: int | None = None
    auto_quarantine: bool | None = None
    status: str | None = None


class PoolAllocateIn(BaseModel):
    provider_type: str | None = None


class PoolReleaseIn(BaseModel):
    mailbox_id: str


class MatchIn(BaseModel):
    sender: str = ""
    subject_contains: str = ""


class RegistrationTaskIn(BaseModel):
    pool_id: str | None = None
    target_ref: str = ""
    match: MatchIn = Field(default_factory=MatchIn)
    timeout_seconds: int | None = None
    callback_url: str | None = None
    idempotency_key: str | None = None
    metadata: dict = Field(default_factory=dict)


class RuleIn(BaseModel):
    name: str
    sender_pattern: str = "*"
    subject_pattern: str = ""
    body_regex: str = ""
    output_type: str = "OTP"
    priority: int = 50
    provider_type: str | None = None
    status: str = "active"


class RulePatchIn(BaseModel):
    name: str | None = None
    sender_pattern: str | None = None
    subject_pattern: str | None = None
    body_regex: str | None = None
    output_type: str | None = None
    priority: int | None = None
    provider_type: str | None = None
    status: str | None = None


class DomainIn(BaseModel):
    domain: str
    mode: str = "WORKER"  # WORKER / DESTINATION
    notes: str = ""
    inbound_secret: str | None = None  # 不传则自动生成（仅创建响应中返回一次）


class DomainPatchIn(BaseModel):
    mode: str | None = None
    status: str | None = None
    notes: str | None = None
    routing_config: dict | None = None


class InjectMailIn(BaseModel):
    email: str | None = None
    mailbox_id: str | None = None
    sender: str = "noreply@example.com"
    subject: str = "Your verification code"
    text: str = "Your verification code is 483921. It expires in 10 minutes."
    html: str = ""
    message_id: str | None = None


class InboundMailIn(BaseModel):
    to: str
    from_: str = Field(default="", alias="from")
    subject: str = ""
    text: str = ""
    html: str = ""
    messageId: str | None = None
    headers: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
