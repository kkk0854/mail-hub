"""Cloudflare Email Routing Provider（推送型）。

收件路径：CF Email Worker 收到邮件 -> POST /api/v1/inbound/cloudflare。
因此 sync_incremental 为空操作；健康状态由域名记录状态 + 最近收件时间推导。
"""
from __future__ import annotations

from datetime import timedelta

from ..core.db import utcnow
from .base import HealthCheckResult, MailProvider, SyncedMessage


class CloudflareProvider(MailProvider):
    type = "cloudflare"
    supports_pull_sync = False

    async def test_connection(self) -> HealthCheckResult:
        result = HealthCheckResult(details={"mode": "worker-push"})
        dns_status = (self.config or {}).get("dns_status", "unknown")
        domain_status = (self.config or {}).get("domain_status", "active")

        result.connectivity = dns_status == "ok"
        result.authorization = domain_status == "active"
        if not result.authorization:
            result.auth_error_code = "AUTH_FAILED"

        # Sync Check：最近 48h 内有新邮件视为取件链路健康（推送型无主动同步）
        last_mail = (self.config or {}).get("last_mail_at")
        if last_mail:
            try:
                age = utcnow() - last_mail
                result.sync = age < timedelta(hours=48)
                result.details["last_mail_age_hours"] = round(age.total_seconds() / 3600, 2)
            except Exception:
                result.sync = True
        result.fetch = True
        return result

    async def sync_incremental(self, cursor: dict) -> tuple[list[SyncedMessage], dict]:
        return [], dict(cursor or {})
