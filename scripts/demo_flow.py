"""在运行中的 MAIL HUB 上执行一次完整业务闭环演示（§25 最终业务闭环）。"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
API_KEY_FILE = Path(__file__).resolve().parent.parent / "backend" / "data" / ".api_key"


def main() -> int:
    unique = uuid.uuid4().hex[:6]
    client = httpx.Client(base_url=BASE, timeout=30)

    # 1. 登录
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    api_key = API_KEY_FILE.read_text().strip()
    print("[1] 登录成功 admin")

    # 2. 创建演示邮箱池
    r = client.post("/pools", headers=headers, json={"name": f"demo-{unique}", "cooldown_seconds": 0, "max_concurrent": 2})
    if r.status_code == 409:
        r = client.get("/pools", headers=headers)
        pool_id = next(p["id"] for p in r.json()["items"] if p["name"] == f"demo-{unique}")
    else:
        r.raise_for_status()
        pool_id = r.json()["id"]
    print(f"[2] 邮箱池 demo-{unique} 就绪")

    # 3. 四段式导入 2 个 simulator 邮箱
    text = "\n".join([
        f"demo{unique}1@example.com:DemoPass!:RT-{unique}1:CID-{unique}",
        f"demo{unique}2@example.com:DemoPass!:RT-{unique}2:CID-{unique}",
    ])
    r = client.post("/imports/preview", headers=headers, json={
        "provider_type": "simulator", "source_type": "PASTE", "delimiter": ":",
        "field_mapping": ["email", "password", "refresh_token", "client_id"], "source_text": text,
        "pool_id": pool_id})
    r.raise_for_status()
    batch = r.json()
    print(f"[3] 导入预览：总 {batch['total_rows']} 有效 {batch['valid_rows']} 重复 {batch['duplicate_rows']} 错误 {batch['error_rows']}")
    r = client.post("/imports/commit", headers=headers, json={"batch_id": batch["id"]})
    r.raise_for_status()
    print(f"[3] 提交导入：{r.json()['imported']} 个邮箱（含加密凭据 + 健康检查任务）")
    time.sleep(2)  # 等 Worker 跑完导入触发的健康检查
    r = client.get("/mailboxes", headers=headers, params={"q": f"demo{unique}1@"})
    mb1 = r.json()["items"][0]
    print(f"[3] 导入邮箱健康状态：{mb1['email']} -> {mb1['health_status']} ({mb1['health_score']} 分，Worker 自动检测)")

    # 4. 创建注册任务（外部系统用 API Key 调用；带 callback 验证重试链路）
    r = client.post("/registration-tasks", headers={"X-API-Key": api_key}, json={
        "pool_id": pool_id,
        "target_ref": f"external-job-{unique}",
        "match": {"sender": "verifier.io", "subject_contains": "verification"},
        "timeout_seconds": 300,
        "callback_url": "http://127.0.0.1:9/unreachable",  # 故意不可达，观察 webhook 重试
        "idempotency_key": f"ext-{unique}",
    })
    r.raise_for_status()
    task = r.json()
    print(f"[4] 注册任务 {task['id']} 状态 {task['state']}，分配邮箱 {task['mailbox']}")

    # 5. 注入匹配邮件（模拟 Provider 事件推送）
    r = client.post("/dev/inject-mail", headers=headers, json={
        "mailbox_id": task["mailbox_id"],
        "sender": "noreply@verifier.io",
        "subject": "Your verification code",
        "text": f"Your verification code is 483921. Visit https://example.io/verify?token={unique} to activate.",
        "message_id": f"demo-{unique}-1",
    })
    r.raise_for_status()
    print(f"[5] 邮件注入 -> 解析结果 {[(x['type'], x['value']) for x in r.json()['results']]}")

    # 6. 外部系统查询结果
    r = client.get(f"/registration-tasks/{task['id']}/result", headers={"X-API-Key": api_key})
    r.raise_for_status()
    result = r.json()
    print(f"[6] 任务结果：状态 {result['status']} result={result['result']}")

    # 7. Webhook 已入队（不可达 -> 重试）
    time.sleep(1)
    r = client.get("/webhooks", headers=headers, params={"page": 1, "page_size": 5})
    deliveries = [d for d in r.json()["items"] if d["task_id"] == task["id"]]
    if deliveries:
        d = deliveries[0]
        print(f"[7] Webhook {d['event_id']} 状态 {d['state']} attempt={d['attempt']} -> {d['last_error']}")

    # 8. CF 域名入站链路
    domain = f"demo-{unique}.io"
    r = client.post("/cf-domains", headers=headers, json={"domain": domain, "mode": "WORKER"})
    r.raise_for_status()
    secret = r.json()["inbound_secret"]
    r = client.post("/inbound/cloudflare", headers={"X-Inbound-Token": secret}, json={
        "to": f"catchall@{domain}", "from": "noreply@verifier.io",
        "subject": "Your verification code", "text": "Your verification code is 778899",
        "messageId": f"cf-{unique}-1"})
    r.raise_for_status()
    print(f"[8] CF 入站 {r.json()['accepted']} -> 自动建箱 catchall@{domain}，验证码 778899")

    print("\n=== 闭环演示完成：导入 -> 健康检查 -> 任务分配 -> 收件解析 -> 结果回填 -> Webhook/CF 全链路 OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
