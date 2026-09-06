"""Provider 统一接口（§5）。业务层不写 if provider，新增供应商只加 Adapter。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..core.db import utcnow


@dataclass
class SyncedMessage:
    provider_message_id: str
    sender: str
    recipient: str
    subject: str
    text_body: str = ""
    html_body: str = ""
    headers: dict = field(default_factory=dict)
    received_at: Optional[datetime] = None
    raw: Optional[bytes] = None
    thread_id: Optional[str] = None


@dataclass
class HealthCheckResult:
    """§8.1 四个检查维度。"""
    connectivity: bool = True      # Connectivity Check
    authorization: bool = True     # Authorization Check
    sync: bool = True              # Sync Check
    fetch: bool = True             # Fetch Check
    auth_error_code: Optional[str] = None  # TOKEN_EXPIRED / AUTH_FAILED
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.connectivity and self.authorization and self.sync and self.fetch

    def to_dict(self) -> dict:
        return {
            "connectivity": self.connectivity,
            "authorization": self.authorization,
            "sync": self.sync,
            "fetch": self.fetch,
            "auth_error_code": self.auth_error_code,
            "details": self.details,
            "ok": self.ok,
        }


class ProviderError(Exception):
    def __init__(self, message: str, error_code: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.error_code = error_code


class MailProvider(ABC):
    """所有邮箱来源的统一抽象。"""

    type = "base"
    supports_pull_sync = True  # False 表示推送型（如 Cloudflare Email Worker）

    def __init__(self, mailbox, credentials: dict[str, str], config: dict[str, Any]):
        self.mailbox = mailbox
        self.credentials = credentials
        self.config = config

    @abstractmethod
    async def test_connection(self) -> HealthCheckResult: ...

    async def health_check(self) -> HealthCheckResult:
        return await self.test_connection()

    @abstractmethod
    async def sync_incremental(self, cursor: dict) -> tuple[list[SyncedMessage], dict]:
        """返回 (新消息列表, 新游标)。"""

    async def fetch_message(self, message_id: str) -> Optional[SyncedMessage]:
        return None

    async def list_folders(self) -> list[str]:
        return ["INBOX"]

    async def acknowledge(self, message_id: str) -> None:
        return None

    @staticmethod
    def _now() -> datetime:
        return utcnow()
