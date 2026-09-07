# MAIL HUB

**多邮箱接入、注册任务编排与自动取件回填平台** —— 邮箱自动化基础设施（v1.2.0）

外部业务系统不需要关心邮箱到底是 Outlook 还是 Cloudflare 域名邮箱：只需向 MAIL HUB 请求一个可用邮箱、创建等待任务，然后等待一个结构化结果（OTP / 激活链接 / 安全事件）即可。

> 安全边界：系统用于管理**用户拥有或已获授权**的邮箱与注册流程。凭据全部加密存储，不包含绕过 CAPTCHA / 平台风控的能力。生产接入推荐 OAuth/OIDC 等官方授权机制。

---

## 0. v1.2.0 更新日志（2026-09-07）

| # | 新功能 | 说明 |
|---|--------|------|
| 1 | 🔌 临时邮箱 Provider 插件化 | 新增 `gptmail` / `moemail` / `custom_http` 三个临时邮箱源，支持动态启用/停用、优先级排序、配置管理（`/api/v1/tempmail-providers/*`），支持 entry-points 第三方插件扩展 |
| 2 | 📬 Outlook `+tag` 别名识别 | 收件 `user+tag@domain` 自动映射归档到主邮箱 `user@domain`（含注册域名下自动创建主邮箱+登记别名）；`split_plus_alias` 统一解析 |
| 3 | 🤖 LLM 验证码兜底 | 规则解析置信度低于阈值（默认 0.65）时调用 LLM 二次提取；固定 JSON 契约；连续失败 5 次自动熔断；环境变量 `MAILHUB_LLM_*` 控制开关 |
| 4 | 🎛️ 前端系统设置页 | 四个 Tab：通知渠道（含测试发送）、系统更新（版本检查 + Watchtower 一键更新）、OAuth 诊断（可视化错误指引）、临时邮箱 Provider 管理 |
| 5 | 🧪 演示种子数据 | `python scripts/seed.py --demo` 一键生成 3 演示邮箱 + 5 演示任务 + 解析日志，全部带 `is_demo` 标记不污染生产；`--clean` 清理 |
| 6 | 📦 自动数据库迁移 | 启动时自动补齐 v1.2.0 新列（`ensure_schema_updates`），老库无缝升级；另提供 `backend/migrations/migrate_v110_to_v120.sql` 手动脚本 |
| 7 | 🔐 Provider 配置脱敏 | 前端回显敏感字段（key/token/secret/header 等）自动打码为 `******`，掩码值回写不覆盖原配置，杜绝密钥泄漏 |
| 8 | 🧪 Provider 连通性测试 | `POST /api/v1/tempmail-providers/{name}/test` 实际申请+释放一个临时邮箱验证配置可用，前端一键「测试连接」 |
| 9 | 🧹 演示数据隔离 | `is_demo` 邮箱/任务永不进入真实池分配、真实同步与健康检查，大盘统计自动排除并单列演示计数 |
| 10 | 🧩 测试扩充 | 新增 12 项 v1.2.0 回归测试，套件由 22 项增至 34 项 |

### 升级说明（v1.1.0 → v1.2.0）

```bash
docker compose pull
# 方式一：自动迁移（推荐，启动时自动补列）
docker compose up -d
# 方式二：手动迁移（可选）
sqlite3 ./backend/data/mailhub.db < ./backend/migrations/migrate_v110_to_v120.sql
docker compose up -d
```

### LLM 兜底配置（可选）

```env
MAILHUB_LLM_FALLBACK_ENABLE=true
MAILHUB_LLM_API_BASE=https://api.openai.com/v1
MAILHUB_LLM_API_KEY=sk-xxx
MAILHUB_LLM_MODEL=gpt-4o-mini
MAILHUB_LLM_CONFIDENCE_THRESHOLD=0.65
```

不配置则默认关闭，零 API 开销。

---

## 0.1. v1.1.0 更新日志（2026-09-07）

| # | 新功能 | 说明 |
|---|--------|------|
| 1 | 🔑 邮箱池项目隔离 | `project_key` + `caller_id` 维度隔离，同项目已 success 的邮箱不再重复分配；success 后邮箱跳过冷却直接回到 available，可被其他项目立即复用 |
| 2 | 📢 统一通知服务 | Telegram / 钉钉 / Webhook 三通道抽象，验证码提取成功、任务完成、健康告警自动推送；支持 `/api/v1/system/notify/test` 测试通道 |
| 3 | 📊 解析可观测性 | 新增 `parse_attempts` 表，记录每条规则的命中/未命中/正则错误、置信度、耗时；`/api/v1/system/stats/overview` 提供系统大盘数据 |
| 4 | 🔧 OAuth 诊断工具 | `/api/v1/system/oauth/diagnose` 验证 refresh_token 有效性，自动识别 AADSTS 错误码并给出解决方案指引 |
| 5 | 🔄 一键热更新 | 集成 Watchtower，`/api/v1/system/update/check` 检查 GitHub 最新版本，`/api/v1/system/update/trigger` 触发容器更新；docker-compose 已内置 watchtower 服务 |
| 6 | 🌐 浏览器扩展 MVP | Chrome/Edge MV3 扩展：一键申领邮箱 → 自动轮询验证码 → 一键复制 → 完成释放，无需切换标签页（`browser-extension/`） |
| 7 | 🚀 CI/CD 完善 | GitHub Actions：后端多版本 Python 测试、前端 lint+build、Docker 多架构镜像构建推送（amd64/arm64） |
| 8 | 📈 版本号升级 | v1.0.1-mvp → v1.1.0 |

---

## 0.1. v1.0.1 优化日志（2026-09-06）

| # | 优化项 | 说明 |
|---|--------|------|
| 1 | 队列领取原子化 | `claim_due_tasks` / `dispatch_due` 改为单语句 `UPDATE...RETURNING`，杜绝并发消费者重复领取同一任务（此前实测同一邮箱同一秒被同步 2 次） |
| 2 | 调度器防重入队 | `_schedule_sync` / `_schedule_health` 入队前检查在途任务，任务 ID 改为稳定周期桶，多调度器实例重复入队由主键天然去重；`last_sync_at`/`last_check_at` 下沉为 SQL 过滤 |
| 3 | 僵死任务兜底回收 | 进程崩溃遗留的 `RUNNING`/`SENDING` 任务由 stale-recover 周期任务回收（5 分钟阈值），重试或失败隔离，不再永久卡死 |
| 4 | 兜底 ID 稳定化 | 无 `provider_message_id` 的邮件改用 SHA-256 生成兜底 ID（原 `hash()` 受 PYTHONHASHSEED 影响，进程重启后同一邮件会重复入库） |
| 5 | 登录防爆破 | 登录按 (IP, 用户名) 失败 5 次锁定 15 分钟，返回 429 |
| 6 | 复合索引迁移 | 启动时 `CREATE INDEX IF NOT EXISTS` 补建 `fetch_tasks(state,next_run_at)`、`fetch_tasks(mailbox_id,task_type,state)`、`webhook_deliveries(state,next_run_at)` |
| 7 | 前端分包 | Vite 8 构建拆分为 index/vendor/charts 三包，主包 765 kB → 80 kB，无单包超 500 kB，构建 19.4s → 0.9s |
| 8 | 死代码清理 | 删除未使用的 `get_optional_user` 依赖 |

配套新增 6 项回归测试（`tests/test_optimizations.py`），套件由 16 项增至 22 项。

---

## 1. 快速启动

### 方式 A：本地运行（Windows）

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（首次需要构建；构建产物由后端静态托管，单端口访问）
cd frontend
npm install
npm run build
```

打开 **http://127.0.0.1:8000** —— 单端口同时提供控制台与 API。

- 默认账号：`admin / admin123`（请立即修改 `MAILHUB_ADMIN_PASSWORD`）
- 外部系统 API Key：首次启动生成于 `backend/data/.api_key`
- 加密密钥 / JWT 密钥 / Webhook 密钥：独立存放于 `backend/data/.*`（§20：密钥与数据库分离）

### 方式 B：Docker Compose

```bash
docker compose up -d --build
# 控制台: http://127.0.0.1:8080  (nginx 反代 /api -> backend)
```

### 体验完整闭环

```bash
backend\.venv\Scripts\python scripts\demo_flow.py
```

脚本依次执行：登录 → 建池 → 四段式导入 → Worker 自动健康检查 → 创建注册任务（API Key）→ 注入邮件 → 解析 OTP → 查询结果 → Webhook 入队 → CF 域名入站自动建箱。

### 运行测试

```bash
cd backend && .venv\Scripts\python -m pytest tests/ -q   # 22 passed
```

---

## 2. 架构

```text
                 控制台 (React+TS+Vite+Tailwind, 由后端静态托管)
                              │ REST / SSE
                       ┌──────▼──────┐
                       │   FastAPI   │  ← 内嵌 Worker（EMBED_WORKERS=true）
                       └──────┬──────┘
          ┌───────────────────┼───────────────────┐
     Mailbox Service     Task Service        Parser Service
          │                   │                   │
          └───────────────────┼───────────────────┘
                       fetch_tasks 队列（DB 持久化，重试/退避/幂等）
                              │
        ┌─────────────────────┼─────────────────────┐
   Outlook(Graph)     Cloudflare(Worker推送)      IMAP        [+ Simulator]
        └─────────────────────┼─────────────────────┘
                          SQLite(WAL) ←→ 生产可切 PostgreSQL（改 DATABASE_URL）
```

- **Provider 统一接口（§5）**：`app/providers/`，新增 Gmail/QQ 等只需新增 Adapter。
- **事件驱动 + 定时兜底（§10）**：推送型入站（CF/Simulator）直接进管道；拉取型（Outlook/IMAP）由调度器周期增量同步。
- **Worker（§19）**：队列消费 + 指数退避重试（30s/2m/5m）+ 失败隔离；可用 `python -m app.workers.runner` 独立进程运行。
- **SSE 实时推送（§18）**：`/api/v1/events/stream`，Dashboard/取件中心无需刷新。

---

## 3. 外部系统接入（§13）

外部系统只用两个调用：**申请邮箱（创建任务）** 和 **取结果（轮询或 Webhook）**。

### 创建注册任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/registration-tasks \
  -H "X-API-Key: <backend/data/.api_key 中的内容>" \
  -H "Content-Type: application/json" \
  -d '{
    "pool_id": "pool_xxx",
    "target_ref": "external-job-123",
    "match": {"sender": "example.com", "subject_contains": "verification"},
    "timeout_seconds": 300,
    "callback_url": "https://client.example/callback",
    "idempotency_key": "your-unique-key-123"
  }'
```

响应（已自动从池中分配健康邮箱）：

```json
{
  "id": "task_xxx", "state": "WAITING_EMAIL",
  "mailbox": "demo123@example.com", "expires_at": "...",
  "match": {"sender": "example.com", "subject_contains": "verification"}
}
```

- `idempotency_key` 幂等：重复提交返回同一任务（§21）
- 无可用邮箱时进入 `WAITING_MAILBOX`，由后台自动补分配

### 轮询结果

```bash
curl http://127.0.0.1:8000/api/v1/registration-tasks/{task_id}/result -H "X-API-Key: ..."
# {"task_id":"task_xxx","status":"RESULT_READY","result":{"type":"OTP","value":"483921"}}
```

### 或接收 Webhook 回调

```text
POST {callback_url}
X-MailHub-Event-Id: evt_xxx          ← 幂等 ID
X-MailHub-Timestamp: 1788670000      ← 时间戳（重放防护）
X-MailHub-Signature: sha256=...      ← HMAC-SHA256(secret, "{ts}.{event_id}.{body}")

{"event":"mail.result.ready","task_id":"task_xxx","mailbox_id":"mb_xxx",
 "result":{"type":"OTP","value":"483921"},"timestamp":"..."}
```

签名密钥在 `backend/data/.webhook_secret`。失败自动重试（1m/5m/30m/2h，共 5 次），投递成功后任务自动 `COMPLETED` 并释放邮箱进冷却。

### 任务状态机（§12/§14）

```text
CREATED → WAITING_MAILBOX → WAITING_EMAIL → EMAIL_RECEIVED → RESULT_READY
                                                ↓                  ↓
                                          (解析中)        WAITING_CALLBACK → COMPLETED
异常：TIMEOUT / PARSING_FAILED / MAILBOX_ERROR / CANCELLED
```

---

## 4. Cloudflare 域名邮箱接入（§3.4）

1. 控制台「CF 域名」添加域名，获得一次性 `X-Inbound-Token`
2. 部署 Email Worker（Email Routing → Catch-all → Worker）：

```js
export default {
  async email(message, env, ctx) {
    const raw = await new Response(message.raw).text();
    await fetch("https://your-mailhub/api/v1/inbound/cloudflare", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Inbound-Token": env.MAILHUB_TOKEN },
      body: JSON.stringify({
        to: message.to, from: message.from,
        subject: message.headers.get("subject") || "",
        text: raw.slice(0, 60000),              // MVP：转发原文，服务端解析
        messageId: message.headers.get("message-id"),
      }),
    });
    message.setAccept(true);
  },
};
```

3. 未登记的收件地址（catch-all）会自动创建为 `cloudflare` 类型邮箱；已登记 Alias 收件自动归档到主邮箱。
4. 「检查 DNS」按钮通过 DNS-over-HTTPS 实测 MX/SPF/DKIM 并记录状态。

---

## 5. 功能清单（对照设计文档 §24 MVP）

| # | 功能 | 位置 | 状态 |
|---|------|------|------|
| 1 | Dashboard（统计卡 + 4 图表 + 池健康度 + 最近异常） | 前端 `/`，`/dashboard/*` | ✅ |
| 2 | 邮箱管理（搜索/筛选/分页/批量检测/归档/单条添加） | `/mailboxes` | ✅ |
| 3 | Outlook 四段式导入（4 步向导、字段映射、CSV/JSON、预览、去重、错误行 CSV 导出、凭据加密） | `/import`，`/imports/*` | ✅ |
| 4 | CF 域名接入（域名卡片、Worker 推送入站、DNS 实测、收件流水） | `/domains`，`/cf-domains/*` | ✅ |
| 5 | 健康检查（四维检查 + §8.3 评分 + 自动隔离/自动回池） | `/keepalive`，`/mailboxes/{id}/health-check` | ✅ |
| 6 | 邮件同步（增量游标、队列化、手动/定时触发） | Worker `MAIL_SYNC` | ✅ |
| 7 | 邮件解析（规则引擎：sender/subject/regex/优先级/输出类型） | `/rules`，`/parser-rules/*` | ✅ |
| 8 | 取件中心（SSE 实时事件流 + 任务队列 + 重试） | `/fetch` | ✅ |
| 9 | 邮箱池（分配规则 §9、冷却、并发/每日限额、自动隔离） | `/pools` | ✅ |
| 10 | 注册任务 API（§12 状态机全覆盖 + 幂等键） | `/registration-tasks/*` | ✅ |
| 11 | Webhook 回调（HMAC 签名 + 时间戳 + 幂等 + 重试） | `webhook_deliveries` | ✅ |

二阶段预留：Alias Center（已有基础 CRUD + 入站归档）、规则编辑器（已有）、高级评分、RBAC、审计中心（审计日志已全量落库）。

## 6. 交付标准对照（§28）

```text
✓ 可导入邮箱            四段式/CSV/JSON + 单条添加，错误行隔离可导出
✓ 可区分 Provider       outlook / cloudflare / imap / simulator 统一抽象
✓ 可检测健康状态        四维检查 + 评分 + 自动隔离/回池
✓ 可同步新邮件          增量游标 + 队列 + 定时兜底
✓ 可保存原始邮件        data/raw/{msg_id}.eml
✓ 可解析验证码/链接     规则引擎 + 置信度 + 结果加密存储
✓ 可绑定任务            匹配器（sender/subject）→ EMAIL_RECEIVED → RESULT_READY
✓ 可 API 查询结果       GET /registration-tasks/{id}/result
✓ 可 Webhook 回调       HMAC 签名 + event_id 幂等 + 指数退避
✓ 失败可重试            fetch_tasks + webhook 双队列退避重试
✓ 失效邮箱可隔离        QUARANTINED，保留全部数据，检查通过自动回池
✓ 凭据不明文            Fernet 加密 + 接口脱敏 + 日志脱敏过滤器
✓ 可审计                audit_logs 覆盖登录/导入/任务/规则/池/入站等关键操作
```

## 7. 目录结构

```text
├── backend/
│   ├── app/
│   │   ├── core/          配置·加密·认证·DB·事件总线·限流
│   │   ├── models.py      §15 全部数据表
│   │   ├── providers/     base + outlook + cloudflare + imap + simulator
│   │   ├── services/      导入·健康·解析·消息·池·任务·Webhook·审计·种子
│   │   ├── api/           §16 全部路由（deps/schemas/serializers）
│   │   └── workers/       队列消费 + 周期调度（可独立进程）
│   ├── tests/             16 项测试（导入/解析/闭环/安全）
│   └── data/              SQLite + 密钥文件 + 原始邮件（运行时生成）
├── frontend/              React+TS+Vite+Tailwind 控制台（11 页面）
├── scripts/demo_flow.py   全链路闭环演示
└── docker-compose.yml     backend + frontend(nginx)
```

## 8. 主要配置（环境变量，前缀 `MAILHUB_`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATABASE_URL` | SQLite WAL | 生产换 PostgreSQL 连接串 |
| `EMBED_WORKERS` | true | API 进程内嵌 Worker；分离部署设 false 并运行 `app.workers.runner` |
| `WORKER_CONCURRENCY` | 2 | 队列消费者数量 |
| `SYNC_INTERVAL_SECONDS` | 60 | 增量同步周期 |
| `HEALTH_CHECK_INTERVAL_SECONDS` | 300 | 健康检查周期 |
| `TASK_DEFAULT_TIMEOUT` | 300 | 注册任务默认超时（秒） |
| `RATE_LIMIT_PER_MINUTE` | 600 | API 限流 |
| `ADMIN_USERNAME/PASSWORD` | admin/admin123 | 初始管理员 |
| `SECRET_KEY / ENCRYPTION_KEY / WEBHOOK_SECRET / API_KEY` | 自动生成到 data/ | 生产用 Secret Store 注入 |

## 9. 安全设计落实（§20）

- 数据库中的凭据 / 解析结果值均为 Fernet 密文；API 响应只输出脱敏预览
- 日志过滤器自动抹除含 `authorization` / `token` / `api_key` 的记录
- Webhook HMAC-SHA256 签名 + 时间戳 + event_id 重放防护
- 全部关键操作写 `audit_logs`；API 滑动窗口限流
- 前端永远不直接访问邮箱 Provider，业务系统永远通过 API/Webhook 取结果
