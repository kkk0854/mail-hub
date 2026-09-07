"""Custom HTTP 临时邮箱 Provider。

适配任意第三方临时邮箱 HTTP 接口：
- create_url: POST 申请邮箱，返回 {"email": "..."} 或字符串
- fetch_url: GET 获取消息（支持 {email} 占位符），返回列表
- delete_url: DELETE 销毁邮箱（可选）
- headers_json: 自定义请求头（JSON 对象，可含 Authorization 等）
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .tempmail_base import TempMailError, TempMailProvider

logger = logging.getLogger("mailhub.tempmail.custom_http")


class CustomHttpProvider(TempMailProvider):
    name = "custom_http"
    display_name = "自定义 HTTP"

    def _headers(self) -> dict:
        try:
            raw = self.config.get("headers_json") or "{}"
            headers = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            headers = {}
        headers.setdefault("Content-Type", "application/json")
        return headers

    def _url(self, key: str) -> str:
        url = (self.config.get(key) or "").strip()
        if not url:
            raise TempMailError(f"{key} 未配置", "CUSTOM_HTTP_NOT_CONFIGURED")
        if not url.startswith(("http://", "https://")):
            raise TempMailError(f"{key} 必须是 http(s):// 开头的地址", "CUSTOM_HTTP_BAD_URL")
        return url

    async def create_email(self, domain: str | None = None) -> dict:
        url = self._url("create_url")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, headers=self._headers())
                if resp.status_code not in (200, 201):
                    raise TempMailError(f"Custom create failed: HTTP {resp.status_code} {resp.text[:200]}", "CUSTOM_CREATE_FAILED")
                try:
                    data = resp.json()
                except Exception:
                    data = {"email": resp.text.strip().strip('"')}
                email = None
                if isinstance(data, dict):
                    email = data.get("email") or data.get("address") or data.get("data", {}).get("email")
                elif isinstance(data, str):
                    email = data.strip().strip('"')
                if not email:
                    raise TempMailError("Custom response missing email", "CUSTOM_BAD_RESPONSE")
                return {"email": email, "password": None, "extra": {"raw": data}}
        except TempMailError:
            raise
        except Exception as exc:
            raise TempMailError(f"Custom create error: {exc}", "CUSTOM_CREATE_ERROR") from exc

    async def get_messages(self, email: str, password: str | None = None) -> list[dict]:
        url = self._url("fetch_url").replace("{email}", email)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    raise TempMailError(f"Custom fetch failed: HTTP {resp.status_code}", "CUSTOM_FETCH_FAILED")
                data = resp.json()
                items = data if isinstance(data, list) else data.get("messages") or data.get("data") or []
                if not isinstance(items, list):
                    items = []
                return [
                    {
                        "id": str(m.get("id") or m.get("message_id") or m.get("mid") or ""),
                        "from": m.get("from") or m.get("sender") or m.get("from_address") or "",
                        "subject": m.get("subject") or "",
                        "text": m.get("text") or m.get("body") or m.get("content") or "",
                        "received_at": m.get("received_at") or m.get("date") or m.get("created_at"),
                    }
                    for m in items
                ]
        except TempMailError:
            raise
        except Exception as exc:
            raise TempMailError(f"Custom fetch error: {exc}", "CUSTOM_FETCH_ERROR") from exc

    async def delete_email(self, email: str, password: str | None = None) -> None:
        url = (self.config.get("delete_url") or "").strip()
        if not url:
            return
        url = url.replace("{email}", email)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(url, headers=self._headers())
        except Exception as exc:
            logger.debug("custom delete ignore error: %s", exc)

    def get_config_schema(self) -> dict:
        return {
            "properties": {
                "create_url": {"type": "string", "title": "创建邮箱 URL（POST）"},
                "fetch_url": {"type": "string", "title": "获取消息 URL（GET，支持 {email} 占位符）"},
                "delete_url": {"type": "string", "title": "销毁邮箱 URL（DELETE，可选）"},
                "headers_json": {"type": "string", "title": "自定义请求头（JSON）", "default": "{}"},
            },
            "required": ["create_url", "fetch_url"],
        }

    def validate_config(self, config: dict) -> tuple[bool, str]:
        for key in ("create_url", "fetch_url"):
            if not (config or {}).get(key):
                return False, f"{key} 必填"
        return True, ""
