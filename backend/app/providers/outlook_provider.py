"""Outlook Provider（Microsoft Graph + OAuth2 refresh token）。

凭据：OAUTH_REFRESH_TOKEN / OAUTH_CLIENT_ID / 可选 TENANT_ID。
使用官方授权 API（§3.3 推荐生产使用 OAuth/OIDC 官方授权机制）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from .base import HealthCheckResult, MailProvider, ProviderError, SyncedMessage

logger = logging.getLogger("mailhub.provider.outlook")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookProvider(MailProvider):
    type = "outlook"

    def __init__(self, mailbox, credentials: dict, config: dict):
        super().__init__(mailbox, credentials, config)
        self._access_token: str | None = None

    @property
    def tenant(self) -> str:
        return self.credentials.get("TENANT_ID") or "common"

    @property
    def client_id(self) -> str:
        return self.credentials.get("OAUTH_CLIENT_ID") or ""

    async def _refresh_access_token(self) -> str:
        refresh_token = self.credentials.get("OAUTH_REFRESH_TOKEN") or ""
        if not refresh_token or not self.client_id:
            raise ProviderError("outlook credentials missing (refresh_token/client_id)", "CONFIG_MISSING")
        token_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "https://graph.microsoft.com/Mail.Read offline_access",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            detail = resp.text[:200]
            code = "AUTH_FAILED"
            if resp.status_code in (400, 401) and "expired" in resp.text.lower():
                code = "TOKEN_EXPIRED"
            logger.warning("outlook token refresh failed: %s", detail)
            raise ProviderError(f"token refresh failed: {detail}", code)
        token = resp.json().get("access_token")
        if not token:
            raise ProviderError("no access_token in response", "AUTH_FAILED")
        self._access_token = token
        return token

    async def _graph_get(self, url: str, params: dict | None = None) -> dict:
        token = self._access_token or await self._refresh_access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if resp.status_code == 401:
            # token 过期，刷新一次重试
            token = await self._refresh_access_token()
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if resp.status_code != 200:
            raise ProviderError(f"graph error {resp.status_code}: {resp.text[:200]}", "GRAPH_ERROR")
        return resp.json()

    async def test_connection(self) -> HealthCheckResult:
        result = HealthCheckResult()
        try:
            await self._refresh_access_token()
            result.authorization = True
        except ProviderError as exc:
            result.authorization = False
            result.auth_error_code = exc.error_code if exc.error_code in ("TOKEN_EXPIRED", "AUTH_FAILED") else "AUTH_FAILED"
            result.connectivity = exc.error_code != "CONFIG_MISSING"
            result.details["error"] = str(exc)
            return result
        try:
            await self._graph_get(f"{GRAPH_BASE}/me")
            result.connectivity = True
        except ProviderError as exc:
            # 纯 Mail.Read scope 的 MSA token 访问 /me 会 401（缺 User.Read），
            # 但 inbox 端点可用——以收件箱探测为准
            try:
                await self._graph_get(f"{GRAPH_BASE}/me/mailFolders/inbox/messages", params={"$top": 1, "$select": "id"})
                result.connectivity = True
            except ProviderError:
                result.connectivity = False
                result.details["error"] = str(exc)
            return result
        try:
            data = await self._graph_get(f"{GRAPH_BASE}/me/mailFolders/inbox/messages", params={"$top": 1, "$select": "id"})
            result.fetch = True
            result.sync = True
            result.details["sample_count"] = len(data.get("value", []))
        except ProviderError as exc:
            result.fetch = False
            result.sync = False
            result.details["error"] = str(exc)
        return result

    async def sync_incremental(self, cursor: dict) -> tuple[list[SyncedMessage], dict]:
        cursor = dict(cursor or {})
        since = cursor.get("received_since")
        since_dt: datetime | None = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                since_dt = None
        params = {
            "$orderby": "receivedDateTime desc",
            "$top": "50",
            "$select": "id,subject,from,toRecipients,body,bodyPreview,receivedDateTime,internetMessageId,conversationId",
        }
        if since:
            params["$filter"] = f"receivedDateTime ge {since}"
        data = await self._graph_get(f"{GRAPH_BASE}/me/mailFolders/inbox/messages", params=params)
        messages: list[SyncedMessage] = []
        max_dt = since_dt
        for item in data.get("value", []):
            received = item.get("receivedDateTime")
            try:
                received_dt = datetime.fromisoformat(received.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                received_dt = self._now()
            from_obj = item.get("from") or {}
            sender = (from_obj.get("emailAddress") or {}).get("address", "")
            recipients = [(r.get("emailAddress") or {}).get("address", "") for r in item.get("toRecipients", [])]
            body_obj = item.get("body") or {}
            messages.append(
                SyncedMessage(
                    provider_message_id=item.get("internetMessageId") or item.get("id", ""),
                    sender=sender,
                    recipient=",".join(r for r in recipients if r),
                    subject=item.get("subject") or "",
                    text_body=body_obj.get("content", "") if body_obj.get("contentType") == "text" else item.get("bodyPreview", ""),
                    html_body=body_obj.get("content", "") if body_obj.get("contentType") == "html" else "",
                    headers={"internetMessageId": item.get("internetMessageId") or ""},
                    received_at=received_dt,
                    thread_id=item.get("conversationId"),
                )
            )
            if not max_dt or received_dt > max_dt:
                max_dt = received_dt
        new_cursor = dict(cursor)
        if max_dt:
            iso = max_dt.replace(tzinfo=timezone.utc).isoformat()
            new_cursor["received_since"] = iso
        return messages, new_cursor

    async def list_folders(self) -> list[str]:
        data = await self._graph_get(f"{GRAPH_BASE}/me/mailFolders", params={"$top": 30, "$select": "displayName"})
        return [f.get("displayName", "") for f in data.get("value", []) if f.get("displayName")]
