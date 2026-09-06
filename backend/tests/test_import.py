"""Outlook 四段式导入：预览 -> 校验 -> 提交（§7）+ 凭据加密验证。"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models import Mailbox, MailboxCredential

API = "/api/v1"

SAMPLE = "\n".join(
    [
        "alice01@outlook.com:SecretPass1!:RT-AAAA1111:CID-AAAA",
        "alice02@outlook.com:SecretPass2!:RT-BBBB2222:CID-BBBB",
        "alice03@outlook.com:SecretPass3!:RT-CCCC3333:CID-CCCC",
        "alice01@outlook.com:SecretPass1!:RT-AAAA1111:CID-AAAA",  # 批内重复
        "not-an-email:Pass!:RT-DDDD4444:CID-DDDD",  # 格式错误
    ]
)


async def test_preview_counts(client, auth_headers):
    resp = await client.post(
        f"{API}/imports/preview",
        headers=auth_headers,
        json={"provider_type": "outlook", "source_type": "PASTE", "delimiter": ":",
              "field_mapping": ["email", "password", "refresh_token", "client_id"], "source_text": SAMPLE},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_rows"] == 5
    assert data["valid_rows"] == 3
    assert data["duplicate_rows"] == 1
    assert data["error_rows"] == 1
    statuses = {r["line_no"]: r["status"] for r in data["rows"]}
    assert statuses[1] == "VALID"
    assert statuses[4] == "DUPLICATE"
    assert statuses[5] == "ERROR"


async def test_validate_and_commit(client, auth_headers):
    unique = uuid.uuid4().hex[:6]
    text = "\n".join([
        f"bob{unique}1@outlook.com:Pass1!:RT-{unique}1:CID-{unique}1",
        f"bob{unique}2@outlook.com:Pass2!:RT-{unique}2:CID-{unique}2",
    ])
    resp = await client.post(
        f"{API}/imports/validate",
        headers=auth_headers,
        json={"provider_type": "outlook", "source_type": "PASTE", "delimiter": ":",
              "field_mapping": ["email", "password", "refresh_token", "client_id"], "source_text": text},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] == 2

    # preview -> commit 全流程
    preview = await client.post(
        f"{API}/imports/preview",
        headers=auth_headers,
        json={"provider_type": "outlook", "source_type": "PASTE", "delimiter": ":",
              "field_mapping": ["email", "password", "refresh_token", "client_id"], "source_text": text},
    )
    batch_id = preview.json()["id"]
    resp = await client.post(f"{API}/imports/commit", headers=auth_headers, json={"batch_id": batch_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2

    # 已提交批次再次提交 -> 409
    resp = await client.post(f"{API}/imports/commit", headers=auth_headers, json={"batch_id": batch_id})
    assert resp.status_code == 409

    # 邮箱已创建且状态 IMPORTED；凭据已加密存储（数据库中不含明文）
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        emails = [f"bob{unique}1@outlook.com", f"bob{unique}2@outlook.com"]
        mbs = (await session.execute(select(Mailbox).where(Mailbox.email.in_(emails)))).scalars().all()
        assert len(mbs) == 2
        creds = (await session.execute(select(MailboxCredential).where(MailboxCredential.mailbox_id == mbs[0].id))).scalars().all()
        types = {c.credential_type for c in creds}
        assert {"PASSWORD", "OAUTH_REFRESH_TOKEN", "OAUTH_CLIENT_ID"} <= types
        for c in creds:
            assert "Pass" not in c.encrypted_value
            assert "RT-" not in c.encrypted_value


async def test_errors_csv_export(client, auth_headers):
    resp = await client.post(
        f"{API}/imports/preview",
        headers=auth_headers,
        json={"provider_type": "outlook", "source_type": "PASTE", "delimiter": ":",
              "field_mapping": ["email", "password", "refresh_token", "client_id"], "source_text": SAMPLE},
    )
    batch_id = resp.json()["id"]
    resp = await client.get(f"{API}/imports/{batch_id}/errors.csv", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "invalid email format" in resp.text
