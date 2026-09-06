"""优化回归测试：原子领取防重复消费 / 调度器防重入队 / 稳定兜底 ID / 登录防爆破 / 僵死任务回收。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.db import get_sessionmaker, utcnow
from app.core.ids import new_id
from app.models import FetchTask, Mailbox, WebhookDelivery
from app.services import message_service
from app.services.message_service import _fallback_message_id
from app.workers import scheduler as scheduler_mod
from app.workers.scheduler import Scheduler, claim_due_tasks

API = "/api/v1"


async def _make_mailbox(client, auth_headers):
    email = f"opt-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        f"{API}/mailboxes",
        headers=auth_headers,
        json={"email": email, "provider_type": "simulator"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _queue_task(session, mailbox_id: str, task_type: str = "MAIL_SYNC", state: str = "QUEUED", **kw):
    now = utcnow()
    task = FetchTask(
        id=new_id("ft"),
        mailbox_id=mailbox_id,
        task_type=task_type,
        state=state,
        next_run_at=kw.get("next_run_at", now),
        scheduled_at=now,
        payload_json={"source": "test"},
        **{k: v for k, v in kw.items() if k in ("started_at", "attempt", "max_attempt")},
    )
    session.add(task)
    await session.flush()
    return task


async def test_claim_due_tasks_atomic_no_double_claim(client, auth_headers):
    """并发领取同一批到期任务：每个任务只能被领取一次（防重复同步 §19）。"""
    mb = await _make_mailbox(client, auth_headers)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        ids = []
        for _ in range(6):
            t = await _queue_task(session, mb["id"])
            ids.append(t.id)
        await session.commit()

    async def _claim_once():
        async with sessionmaker() as s:
            return await claim_due_tasks(s, limit=20)

    first, second = await asyncio.gather(_claim_once(), _claim_once())
    claimed_ids = [t.id for t in first] + [t.id for t in second]
    # 全局无重复领取
    assert len(claimed_ids) == len(set(claimed_ids)), f"double claim detected: {claimed_ids}"
    # 本次创建的 6 个任务必须全部被领取且各恰好一次
    assert len(set(claimed_ids) & set(ids)) == 6

    async with sessionmaker() as session:
        rows = (await session.execute(select(FetchTask).where(FetchTask.id.in_(ids)))).scalars().all()
        assert all(r.state == "RUNNING" and r.started_at is not None for r in rows)


async def test_scheduler_sync_dedup_and_sql_filter(client, auth_headers):
    """同一调度周期重复触发 _schedule_sync：每邮箱只入队一条 MAIL_SYNC（防多实例重复入队）。"""
    mb = await _make_mailbox(client, auth_headers)
    sched = Scheduler(concurrency=1)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await sched._schedule_sync(session)
        await sched._schedule_sync(session)
        await session.commit()
        tasks = (
            await session.execute(
                select(FetchTask).where(
                    FetchTask.mailbox_id == mb["id"],
                    FetchTask.task_type == "MAIL_SYNC",
                    FetchTask.state == "QUEUED",
                )
            )
        ).scalars().all()
        assert len(tasks) == 1, "重复入队：同一邮箱同一周期出现多条 MAIL_SYNC"

        # 任务 ID 为稳定周期桶，重复入队时主键冲突天然去重
        assert tasks[0].id == f"ft_{mb['id'][-8:]}_sync_{int(utcnow().timestamp()) // 3600}"


async def test_scheduler_health_dedup(client, auth_headers):
    mb = await _make_mailbox(client, auth_headers)
    sched = Scheduler(concurrency=1)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await sched._schedule_health(session)
        await sched._schedule_health(session)
        await session.commit()
        n = (
            await session.execute(
                select(FetchTask).where(
                    FetchTask.mailbox_id == mb["id"],
                    FetchTask.task_type == "HEALTH_CHECK",
                    FetchTask.state == "QUEUED",
                )
            )
        ).scalars().all()
        assert len(n) == 1


async def test_fallback_message_id_stable_and_dedupe(client, auth_headers):
    """无 provider_message_id 时：稳定 ID 跨调用/跨重启一致，重复注入不重复入库（§21）。"""
    a = _fallback_message_id("noreply@x.io", "Hello", "2026-09-06 10:00:00")
    b = _fallback_message_id("noreply@x.io", "Hello", "2026-09-06 10:00:00")
    assert a == b and a.startswith("auto-")

    mb = await _make_mailbox(client, auth_headers)
    inject = {"mailbox_id": mb["id"], "sender": "noreply@stable.io", "subject": "no message id",
              "text": "Your verification code is 778899"}
    r1 = await client.post(f"{API}/dev/inject-mail", headers=auth_headers, json=inject)
    r2 = await client.post(f"{API}/dev/inject-mail", headers=auth_headers, json=inject)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["duplicate"] is False
    assert r2.json()["duplicate"] is True
    assert r2.json()["message_id"] == r1.json()["message_id"]


async def test_login_lockout_after_failed_attempts(client):
    """连续 5 次登录失败后锁定该 (IP, 用户名)，第 6 次返回 429（防爆破）。"""
    username = f"ghost-{uuid.uuid4().hex[:8]}"
    for _ in range(5):
        resp = await client.post(f"{API}/auth/login", json={"username": username, "password": "wrong"})
        assert resp.status_code == 401
    resp = await client.post(f"{API}/auth/login", json={"username": username, "password": "wrong"})
    assert resp.status_code == 429
    # 正确密码也被锁定（不泄露账号有效性）
    resp = await client.post(f"{API}/auth/login", json={"username": username, "password": "right"})
    assert resp.status_code == 429


async def test_stale_running_recovery(client, auth_headers):
    """进程崩溃遗留的 RUNNING / SENDING 任务被兜底回收（§19 失败隔离）。"""
    mb = await _make_mailbox(client, auth_headers)
    sched = Scheduler(concurrency=1)
    sessionmaker = get_sessionmaker()
    stale = utcnow() - timedelta(seconds=scheduler_mod.STALE_RUNNING_SECONDS + 10)

    async with sessionmaker() as session:
        ft = await _queue_task(session, mb["id"], task_type="MAIL_SYNC", state="RUNNING",
                               started_at=stale, attempt=1, max_attempt=4)
        wh = WebhookDelivery(
            id=new_id("wh"), event_id=f"evt_{uuid.uuid4().hex[:24]}", task_id="task_x",
            url="http://127.0.0.1:9/x", payload_json={}, state="SENDING",
            next_run_at=utcnow(), updated_at=stale, created_at=utcnow(),
        )
        session.add(wh)
        await session.commit()

    async with sessionmaker() as session:
        await sched._sweep_stale_running(session)
        await session.commit()

    async with sessionmaker() as session:
        ft2 = await session.get(FetchTask, ft.id)
        assert ft2.state == "RETRYING"
        assert ft2.attempt == 2
        assert ft2.next_run_at is not None
        wh2 = await session.get(WebhookDelivery, wh.id)
        assert wh2.state == "RETRYING"
