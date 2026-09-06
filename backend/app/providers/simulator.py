"""Simulator Provider：本地演示/测试用推送型适配器。

真实邮件通过 inject-mail 接口注入（模拟 Provider 事件推送），
sync_incremental 为空操作。仅用于开发联调，不参与生产业务。
"""
from __future__ import annotations

from .base import HealthCheckResult, MailProvider, SyncedMessage


class SimulatorProvider(MailProvider):
    type = "simulator"
    supports_pull_sync = False

    async def test_connection(self) -> HealthCheckResult:
        return HealthCheckResult(details={"mode": "simulator", "note": "本地模拟 Provider，始终返回健康"})

    async def sync_incremental(self, cursor: dict) -> tuple[list[SyncedMessage], dict]:
        return [], dict(cursor or {})
