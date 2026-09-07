"""Moemail 临时邮箱 Provider。

Moemail 提供免注册临时邮箱 API。
配置：base_url（默认 https://api.moemail.app）。
"""
from __future__ import annotations

import logging

import httpx

from .tempmail_base import TempMailError, TempMailProvider

logger = logging.getLogger("mailhub.tempmail.moemail")


class MoemailProvider(TempMailProvider):
    name = "moemail"
    display_name = "Moemail"

    async def create_email(self, domain: str | None = None) -> dict:
        base_url = (self.config.get("base_url") or "https://api.moemail.app").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{base_url}/api/v1/emails")
                if resp.status_code != 200:
                    raise TempMailError(f"Moemail create failed: HTTP {resp.status_code} {resp.text[:200]}", "MOEMAIL_CREATE_FAILED")
                data = resp.json()
                email = data.get("email") or data.get("address")
                if not email:
                    raise TempMailError("Moemail response missing email", "MOEMAIL_BAD_RESPONSE")
                return {"email": email, "password": None, "extra": {"raw": data}}
        except TempMailError:
            raise
        except Exception as exc:
            raise TempMailError(f"Moemail create error: {exc}", "MOEMAIL_CREATE_ERROR") from exc

    async def get_messages(self, email: str, password: str | None = None) -> list[dict]:
        base_url = (self.config.get("base_url") or "https://api.moemail.app").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(f"{base_url}/api/v1/emails/{email}/messages")
                if resp.status_code != 200:
                    raise TempMailError(f"Moemail fetch failed: HTTP {resp.status_code}", "MOEMAIL_FETCH_FAILED")
                data = resp.json()
                items = data if isinstance(data, list) else data.get("messages", [])
                return [
                    {
                        "id": str(m.get("id") or m.get("message_id") or ""),
                        "from": m.get("from") or m.get("sender") or "",
                        "subject": m.get("subject") or "",
                        "text": m.get("text") or m.get("body") or "",
                        "received_at": m.get("received_at") or m.get("date"),
                    }
                    for m in items
                ]
        except TempMailError:
            raise
        except Exception as exc:
            raise TempMailError(f"Moemail fetch error: {exc}", "MOEMAIL_FETCH_ERROR") from exc

    def get_config_schema(self) -> dict:
        return {
            "properties": {
                "base_url": {"type": "string", "title": "服务地址", "default": "https://api.moemail.app"},
            },
            "required": [],
        }
