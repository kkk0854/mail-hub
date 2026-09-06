"""安全设计验证（§20）：认证、脱敏、审计、限流头安全。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.models import AuditLog, MailboxCredential

API = "/api/v1"


async def test_login_rejects_bad_password(client):
    resp = await client.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


async def test_protected_endpoints_require_auth(client):
    for path in ("/mailboxes", "/messages", "/registration-tasks", "/dashboard/summary"):
        resp = await client.get(f"{API}{path}")
        assert resp.status_code == 401, path


async def test_registration_api_accepts_api_key(client, api_key):
    resp = await client.get(f"{API}/registration-tasks", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    resp = await client.get(f"{API}/registration-tasks", headers={"X-API-Key": "mh_invalid_key"})
    assert resp.status_code == 401


async def test_credentials_never_leak_plaintext(client, auth_headers):
    unique = uuid.uuid4().hex[:8]
    secret_password = "SuperSecret-Passw0rd!"
    resp = await client.post(
        f"{API}/mailboxes",
        headers=auth_headers,
        json={"email": f"sec-{unique}@outlook.com", "provider_type": "outlook",
              "credentials": {"PASSWORD": secret_password, "OAUTH_REFRESH_TOKEN": "RT-secret-token"}},
    )
    mailbox_id = resp.json()["id"]

    detail = await client.get(f"{API}/mailboxes/{mailbox_id}", headers=auth_headers)
    assert detail.status_code == 200
    text = detail.text
    assert secret_password not in text
    assert "RT-secret-token" not in text
    creds = detail.json()["credentials"]
    for c in creds:
        assert "encrypted_value" not in c
        assert c["masked_preview"].startswith("•")

    # 列表响应同样不泄漏
    listing = await client.get(f"{API}/mailboxes?q=sec-{unique}", headers=auth_headers)
    assert secret_password not in listing.text


async def test_audit_log_records_key_operations(client, auth_headers):
    unique = uuid.uuid4().hex[:8]
    await client.post(f"{API}/mailboxes", headers=auth_headers,
                      json={"email": f"audit-{unique}@example.com", "provider_type": "simulator"})
    await client.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"})

    resp = await client.get(f"{API}/audit-logs?page_size=50", headers=auth_headers)
    assert resp.status_code == 200
    actions = {item["action"] for item in resp.json()["items"]}
    assert "mailbox.create" in actions
    assert "auth.login" in actions


async def test_inbound_rejects_bad_token(client, auth_headers):
    unique = uuid.uuid4().hex[:6]
    resp = await client.post(f"{API}/cf-domains", headers=auth_headers, json={"domain": f"sec-{unique}.io"})
    assert resp.status_code == 201
    secret = resp.json()["inbound_secret"]

    # 正确 token + 未注册邮箱（域名下自动建箱）
    resp = await client.post(
        f"{API}/inbound/cloudflare",
        json={"to": f"catchall@sec-{unique}.io", "from": "noreply@verifier.io",
              "subject": "Your verification code", "text": "Your verification code is 778899"},
        headers={"X-Inbound-Token": secret},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["accepted"] is True

    # 错误 token
    resp = await client.post(
        f"{API}/inbound/cloudflare",
        json={"to": f"catchall@sec-{unique}.io", "from": "noreply@verifier.io", "subject": "x", "text": "y"},
        headers={"X-Inbound-Token": "wrong-token"},
    )
    assert resp.status_code == 401
