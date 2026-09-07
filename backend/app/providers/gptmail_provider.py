"""GPTMail 临时邮箱 Provider。

GPTMail（https://gptmail.plus）提供免费/付费临时邮箱 API。
配置：base_url + api_key（可选）。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .tempmail_base import TempMailError, TempMailProvider

logger = logging.getLogger("mailhub.tempmail.gptmail")


class GPTMailProvider(TempMailProvider):
    name = "gptmail"
    display_name = "GPTMail"

    async def create_email(self, domain: str | None = None) -> dict:
        base_url = (self.config.get("base_url") or "https://api.gptmail.plus").rstrip("/")
        api_key = self.config.get("api_key", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f"{base_url}/api/v1/emails", headers=headers)
                if resp.status_code != 200:
                    raise TempMailError(f"GPTMail create failed: HTTP {resp.status_code} {resp.text[:200]}", "GPTMAIL_CREATE_FAILED")
                data = resp.json()
                email = data.get("email") or data.get("address")
                if not email:
                    raise TempMailError("GPTMail response missing email", "GPTMAIL_BAD_RESPONSE")
                return {"email": email, "password": None, "extra": {"raw": data}}
        except TempMailError:
            raise
        except Exception as exc:
            raise TempMailError(f"GPTMail create error: {exc}", "GPTMAIL_CREATE_ERROR") from exc

    async def get_messages(self, email: str, password: str | None = None) -> list[dict]:
        base_url = (self.config.get("base_url") or "https://api.gptmail.plus").rstrip("/")
        api_key = self.config.get("api_key", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(f"{base_url}/api/v1/emails/{email}/messages", headers=headers)
                if resp.status_code != 200:
                    raise TempMailError(f"GPTMail fetch failed: HTTP {resp.status_code}", "GPTMAIL_FETCH_FAILED")
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
            raise TempMailError(f"GPTMail fetch error: {exc}", "GPTMAIL_FETCH_ERROR") from exc

    def get_config_schema(self) -> dict:
        return {
            "properties": {
                "base_url": {"type": "string", "title": "服务地址", "default": "https://api.gptmail.plus"},
                "api_key": {"type": "string", "title": "API Key（可选）"},
            },
            "required": [],
        }

    def validate_config(self, config: dict) -> tuple[bool, str]:
        base_url = (config or {}).get("base_url") or "https://api.gptmail.plus"
        if not base_url.startswith(("http://", "https://")):
            return False, "base_url 必须是 http(s):// 开头的地址"
        return True, ""
