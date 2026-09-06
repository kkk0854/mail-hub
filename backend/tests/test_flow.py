"""端到端业务闭环（§25/§28）：导入 -> 健康检查 -> 任务 -> 邮件 -> 解析 -> 结果 -> Webhook 回调。"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_sessionmaker, utcnow
from app.models import Mailbox, Message, ParseResult, RegistrationTask, WebhookDelivery
from app.services import task_service, webhook_service

API = "/api/v1"


async def _make_mailbox(client, auth_headers, pool_id=None):
    email = f"flow-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        f"{API}/mailboxes",
        headers=auth_headers,
        json={"email": email, "provider_type": "simulator", "pool_id": pool_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_closed_loop(client, auth_headers, api_key):
    unique = uuid.uuid4().hex[:6]

    # 1. 建池并放入健康邮箱
    resp = await client.post(f"{API}/pools", headers=auth_headers,
                             json={"name": f"pool-{unique}", "cooldown_seconds": 0, "max_concurrent": 1})
    pool_id = resp.json()["id"]
    mb = await _make_mailbox(client, auth_headers, pool_id=pool_id)

    # 2. 手动健康检查 -> HEALTHY / score 100
    resp = await client.post(f"{API}/mailboxes/{mb['id']}/health-check", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    check = resp.json()
    assert check["health_status"] == "HEALTHY"
    assert check["score"] == 100
    assert check["checks"]["connectivity"] is True

    # 3. 创建注册任务（带 callback + 幂等键）
    idem = f"ext-{unique}"
    task_body = {
        "pool_id": pool_id,
        "target_ref": f"external-job-{unique}",
        "match": {"sender": "verifier.io", "subject_contains": "verification"},
        "timeout_seconds": 60,
        "callback_url": "http://127.0.0.1:9/unreachable",  # 先用不可达地址验证重试
        "idempotency_key": idem,
    }
    resp = await client.post(f"{API}/registration-tasks", headers={"X-API-Key": api_key}, json=task_body)
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["state"] == "WAITING_EMAIL"
    assert task["mailbox"] == mb["email"]

    # 幂等：同 idempotency_key 再次创建 -> 返回同一任务
    resp = await client.post(f"{API}/registration-tasks", headers={"X-API-Key": api_key}, json=task_body)
    assert resp.json()["id"] == task["id"]

    # 4. 注入匹配邮件 -> 解析 -> 结果绑定
    code = "483921"
    resp = await client.post(f"{API}/dev/inject-mail", headers=auth_headers, json={
        "mailbox_id": mb["id"],
        "sender": "noreply@verifier.io",
        "subject": "Your verification code",
        "text": f"Your verification code is {code}. It expires soon.",
        "message_id": f"mid-{unique}-1",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["type"] == "OTP"

    # 5. 查询结果（§13）
    resp = await client.get(f"{API}/registration-tasks/{task['id']}/result", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] in ("WAITING_CALLBACK", "RESULT_READY")
    assert result["result"]["type"] == "OTP"
    assert result["result"]["value"] == code

    # 6. Webhook 投递：不可达 -> 进入重试（RETRYING），task 保持 WAITING_CALLBACK
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        n = await webhook_service.dispatch_due(session)
        await session.commit()
    assert n >= 1
    async with sessionmaker() as session:
        deliveries = (await session.execute(select(WebhookDelivery).where(WebhookDelivery.task_id == task["id"]))).scalars().all()
        assert len(deliveries) == 1  # §21 幂等：同一任务一次回调投递
        assert deliveries[0].state == "RETRYING"
        assert deliveries[0].attempt == 1
        t = await session.get(RegistrationTask, task["id"])
        assert t.state == "WAITING_CALLBACK"

    # 7. 本地回调接收器验证 HMAC 签名（§13 Webhook 必须签名验证）
    received: list[dict] = []
    server = None
    port = None

    async def _handle(reader, writer):
        raw = await reader.read(65536)
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        received.append({"headers": headers, "body": body})
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = await asyncio.start_server(_handle, "127.0.0.1", port)

    try:
        # 把投递指向本地接收器并立即重试
        async with sessionmaker() as session:
            d = (await session.execute(select(WebhookDelivery).where(WebhookDelivery.task_id == task["id"]))).scalar_one()
            d.url = f"http://127.0.0.1:{port}/callback"
            d.next_run_at = utcnow()
            await session.commit()
            n = await webhook_service.dispatch_due(session)
            await session.commit()
        assert n == 1
        await asyncio.wait_for(_wait_received(received), timeout=5)

        webhook_req = received[0]
        assert webhook_req["headers"]["x-mailhub-event-id"]
        ts = webhook_req["headers"]["x-mailhub-timestamp"]
        sig = webhook_req["headers"]["x-mailhub-signature"]
        body_str = webhook_req["body"].decode("utf-8")
        expected = "sha256=" + hmac.new(
            settings.webhook_secret.encode(), f"{ts}.{webhook_req['headers']['x-mailhub-event-id']}.{body_str}".encode(), hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(sig, expected)
        payload = json.loads(body_str)
        assert payload["event"] == "mail.result.ready"
        assert payload["result"] == {"type": "OTP", "value": code}

        # 回调成功 -> 任务 COMPLETED（§14 状态机）
        resp = await client.get(f"{API}/registration-tasks/{task['id']}", headers=auth_headers)
        assert resp.json()["state"] == "COMPLETED"
        assert resp.json()["callback_state"] == "DELIVERED"
    finally:
        server.close()
        await server.wait_closed()


async def _wait_received(received, timeout=5):
    for _ in range(int(timeout * 20)):
        if received:
            return
        await asyncio.sleep(0.05)


async def test_duplicate_message_no_duplicate_result(client, auth_headers):
    """§21 同一封邮件不能生成 2 个结果。"""
    unique = uuid.uuid4().hex[:6]
    mb = await _make_mailbox(client, auth_headers)
    inject = {"mailbox_id": mb["id"], "sender": "noreply@dup.io", "subject": "Your verification code",
              "text": "Your verification code is 112233", "message_id": f"dup-{unique}"}
    r1 = await client.post(f"{API}/dev/inject-mail", headers=auth_headers, json=inject)
    r2 = await client.post(f"{API}/dev/inject-mail", headers=auth_headers, json=inject)
    assert r1.json()["duplicate"] is False
    assert r2.json()["duplicate"] is True
    # 幂等核心：同 provider_message_id 两次注入 -> 同一条消息，不产生重复结果
    assert r2.json()["message_id"] == r1.json()["message_id"]

    resp = await client.get(f"{API}/messages/{r1.json()['message_id']}/results", headers=auth_headers)
    assert resp.json()["total"] >= 1
    # 数据库中该 dedupe_key 只有一条消息
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        msgs = (
            await session.execute(select(Message).where(Message.provider_message_id == f"dup-{unique}"))
        ).scalars().all()
        assert len(msgs) == 1


async def test_task_timeout_and_cancel(client, auth_headers):
    unique = uuid.uuid4().hex[:6]
    resp = await client.post(f"{API}/pools", headers=auth_headers,
                             json={"name": f"pool-t-{unique}", "cooldown_seconds": 0})
    pool_id = resp.json()["id"]
    await _make_mailbox(client, auth_headers, pool_id=pool_id)

    # 超时路径
    resp = await client.post(f"{API}/registration-tasks", headers=auth_headers,
                             json={"pool_id": pool_id, "target_ref": "t1", "timeout_seconds": 1})
    task_id = resp.json()["id"]
    sessionmaker = get_sessionmaker()
    await asyncio.sleep(1.1)
    async with sessionmaker() as session:
        await task_service.sweep_timeouts(session)
        await session.commit()
    resp = await client.get(f"{API}/registration-tasks/{task_id}", headers=auth_headers)
    assert resp.json()["state"] == "TIMEOUT"

    # 取消路径
    resp = await client.post(f"{API}/registration-tasks", headers=auth_headers,
                             json={"pool_id": pool_id, "target_ref": "t2", "timeout_seconds": 60})
    task_id2 = resp.json()["id"]
    resp = await client.post(f"{API}/registration-tasks/{task_id2}/cancel", headers=auth_headers)
    assert resp.json()["state"] == "CANCELLED"
    resp = await client.post(f"{API}/registration-tasks/{task_id2}/cancel", headers=auth_headers)
    assert resp.status_code == 409
