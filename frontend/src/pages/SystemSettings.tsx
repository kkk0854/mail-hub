import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, PageHeader } from "../components/ui";
import { clsx } from "clsx";

type Tab = "notify" | "update" | "oauth" | "providers";

const TABS: { key: Tab; label: string }[] = [
  { key: "notify", label: "通知渠道" },
  { key: "update", label: "系统更新" },
  { key: "oauth", label: "OAuth 诊断" },
  { key: "providers", label: "临时邮箱 Provider" },
];

export default function SystemSettings() {
  const [tab, setTab] = useState<Tab>("notify");
  return (
    <div>
      <PageHeader title="系统设置" desc="通知渠道 · 一键更新 · OAuth 诊断 · 临时邮箱 Provider" />
      <div className="mb-4 flex gap-1 border-b border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              "px-4 py-2 text-sm border-b-2 -mb-px transition-colors",
              tab === t.key ? "border-indigo-500 text-indigo-300 font-medium" : "border-transparent text-slate-400 hover:text-slate-200"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "notify" && <NotifyTab />}
      {tab === "update" && <UpdateTab />}
      {tab === "oauth" && <OAuthTab />}
      {tab === "providers" && <ProvidersTab />}
    </div>
  );
}

/* ---------------------------------------------------------------- 通知渠道 */
function NotifyTab() {
  const { data: channels } = useQuery({
    queryKey: ["notify-channels"],
    queryFn: () => api<{ channels: { name: string; enabled: boolean }[] }>("/system/notify/channels"),
  });
  const test = useMutation({
    mutationFn: () =>
      api("/system/notify/test", {
        method: "POST",
        body: { channel: "all", title: "MAIL HUB 通知测试", body: "这是一条测试通知。" },
      }),
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="panel p-4">
        <h3 className="mb-1 text-sm font-medium text-slate-300">已配置通道</h3>
        <p className="mb-3 text-xs text-slate-500">通过环境变量 MAILHUB_NOTIFY_* 配置，重启生效</p>
        <div className="space-y-2">
          {channels?.channels.length ? (
            channels.channels.map((c) => (
              <div key={c.name} className="flex items-center justify-between rounded-lg bg-slate-900 px-3 py-2">
                <span className="text-sm text-slate-200">{c.name}</span>
                <Badge tone="green">已启用</Badge>
              </div>
            ))
          ) : (
            <div className="text-sm text-slate-500">未配置任何通知通道</div>
          )}
        </div>
        <button
          onClick={() => test.mutate()}
          disabled={test.isPending}
          className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {test.isPending ? "发送中..." : "发送测试通知"}
        </button>
        {test.data && (
          <div className="mt-2 text-xs text-emerald-400">
            已发送：{Object.entries(test.data.sent ?? {}).map(([k, v]) => `${k}:${v ? "✓" : "✗"}`).join("  ")}
          </div>
        )}
        {test.isError && <div className="mt-2 text-xs text-rose-400">发送失败：{(test.error as Error).message}</div>}
      </div>
      <div className="panel p-4">
        <h3 className="mb-1 text-sm font-medium text-slate-300">支持的通道</h3>
        <ul className="space-y-2 text-sm text-slate-400">
          <li>• <b className="text-slate-200">Telegram</b> — MAILHUB_NOTIFY_TELEGRAM_BOT_TOKEN + CHAT_ID</li>
          <li>• <b className="text-slate-200">钉钉</b> — MAILHUB_NOTIFY_DINGTALK_WEBHOOK + SECRET（加签）</li>
          <li>• <b className="text-slate-200">通用 Webhook</b> — MAILHUB_NOTIFY_WEBHOOK_URL + SECRET（HMAC 签名）</li>
        </ul>
        <p className="mt-3 text-xs text-slate-500">
          触发场景：验证码提取成功 / 注册任务完成 / 邮箱健康告警
        </p>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 系统更新 */
function UpdateTab() {
  const { data: version } = useQuery({
    queryKey: ["system-version"],
    queryFn: () => api<{ current: string }>("/system/version"),
  });
  const check = useMutation({
    mutationFn: () => api("/system/update/check"),
  });
  const trigger = useMutation({
    mutationFn: () => api("/system/update/trigger", { method: "POST", body: { force: false } }),
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="panel p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-300">当前版本</h3>
        <div className="text-2xl font-bold text-slate-100">v{version?.current ?? "-"}</div>
        <div className="mt-4 flex gap-2">
          <button
            onClick={() => check.mutate()}
            disabled={check.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {check.isPending ? "检查中..." : "检查更新"}
          </button>
          <button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {trigger.isPending ? "触发中..." : "立即更新（Watchtower）"}
          </button>
        </div>
        {check.data && (
          <div className="mt-3 rounded-lg bg-slate-900 p-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-slate-400">最新版本</span>
              <Badge tone={check.data.update_available ? "green" : "slate"}>
                {check.data.update_available ? `v${check.data.latest} 可更新` : "已是最新"}
              </Badge>
            </div>
            {check.data.release_notes && <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{check.data.release_notes}</pre>}
          </div>
        )}
        {trigger.data && <div className="mt-2 text-xs text-emerald-400">{trigger.data.message}</div>}
        {trigger.isError && <div className="mt-2 text-xs text-rose-400">{(trigger.error as Error).message}</div>}
      </div>
      <div className="panel p-4">
        <h3 className="mb-2 text-sm font-medium text-slate-300">说明</h3>
        <ul className="space-y-2 text-sm text-slate-400">
          <li>• 检查更新需要配置 <b className="text-slate-200">MAILHUB_GITHUB_REPO</b></li>
          <li>• 一键更新仅在 docker-compose 部署 + Watchtower 服务下生效</li>
          <li>• 更新期间服务会短暂重启，建议在低峰期操作</li>
        </ul>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- OAuth 诊断 */
function OAuthTab() {
  const [form, setForm] = useState({ refresh_token: "", client_id: "", tenant: "consumers", scope: "offline_access https://outlook.office.com/IMAP.AccessAsUser.All" });
  const diagnose = useMutation({
    mutationFn: () => api("/system/oauth/diagnose", { method: "POST", body: form }),
  });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="panel p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-300">Refresh Token 诊断</h3>
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-slate-400">refresh_token *</label>
            <input
              type="password"
              value={form.refresh_token}
              onChange={(e) => setForm({ ...form, refresh_token: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
              placeholder="粘贴 refresh token"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">client_id（可选）</label>
            <input
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
              placeholder="Azure 应用 Client ID"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">tenant</label>
            <input
              value={form.tenant}
              onChange={(e) => setForm({ ...form, tenant: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">scope</label>
            <input
              value={form.scope}
              onChange={(e) => setForm({ ...form, scope: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500"
            />
          </div>
          <button
            onClick={() => diagnose.mutate()}
            disabled={diagnose.isPending || !form.refresh_token}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {diagnose.isPending ? "诊断中..." : "开始诊断"}
          </button>
        </div>
      </div>
      <div className="panel p-4">
        <h3 className="mb-2 text-sm font-medium text-slate-300">诊断结果</h3>
        {diagnose.data?.valid ? (
          <div className="rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-300">
            <div className="font-medium">✅ Token 有效</div>
            <div className="mt-2 space-y-1 text-xs text-emerald-200/80">
              <div>scope: {diagnose.data.scope}</div>
              <div>aud: {diagnose.data.jwt_aud}</div>
              <div>tid: {diagnose.data.jwt_tid}</div>
              <div>username: {diagnose.data.jwt_preferred_username}</div>
              <div>scp: {diagnose.data.jwt_scp}</div>
            </div>
          </div>
        ) : diagnose.data ? (
          <div className="rounded-lg bg-rose-500/10 p-3 text-sm text-rose-300">
            <div className="font-medium">❌ Token 无效（{diagnose.data.error || `HTTP ${diagnose.data.status_code}`}）</div>
            <div className="mt-2 whitespace-pre-wrap text-xs text-rose-200/80">{diagnose.data.guidance || diagnose.data.error_description}</div>
          </div>
        ) : (
          <div className="text-sm text-slate-500">输入 refresh_token 后点击「开始诊断」，系统会调用 Microsoft Token Endpoint 验证并给出解决方案。</div>
        )}
        {diagnose.isError && <div className="mt-2 text-xs text-rose-400">{(diagnose.error as Error).message}</div>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 临时邮箱 Provider */
function ProvidersTab() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["tempmail-providers"],
    queryFn: () => api<{ items: any[]; total: number }>("/tempmail-providers"),
    refetchInterval: 15000,
  });

  const update = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: any }) =>
      api(`/tempmail-providers/${name}`, { method: "PUT", body: payload }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tempmail-providers"] }),
  });

  const test = useMutation({
    mutationFn: ({ name }: { name: string }) => api(`/tempmail-providers/${name}/test`, { method: "POST", body: {} }),
  });

  return (
    <div className="panel p-4">
      <h3 className="mb-3 text-sm font-medium text-slate-300">
        已注册 Provider（{data?.total ?? 0}）
      </h3>
      <div className="space-y-3">
        {data?.items.map((p) => (
          <div key={p.name} className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm font-medium text-slate-100">{p.display_name}</span>
                <span className="ml-2 text-xs text-slate-500">{p.name}</span>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => test.mutate({ name: p.name })}
                  disabled={test.isPending}
                  className="rounded bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50"
                >
                  {test.isPending ? "测试中..." : "测试连接"}
                </button>
                <label className="flex items-center gap-1.5 text-xs text-slate-400">
                  优先级
                  <input
                    type="number"
                    defaultValue={p.priority}
                    onBlur={(e) => update.mutate({ name: p.name, payload: { enabled: p.enabled, priority: Number(e.target.value) || 10, config: p.config } })}
                    className="w-16 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-100"
                  />
                </label>
                <button
                  onClick={() => update.mutate({ name: p.name, payload: { enabled: !p.enabled, priority: p.priority, config: p.config } })}
                  className={clsx(
                    "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                    p.enabled ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-800 text-slate-500"
                  )}
                >
                  {p.enabled ? "已启用" : "已停用"}
                </button>
              </div>
            </div>
            {test.data?.ok && (
              <div className="mt-2 text-xs text-emerald-400">
                连接成功：{test.data.email || "已创建并释放"}
                {test.data.cleanup !== "ok" && test.data.cleanup ? `（释放：${test.data.cleanup}）` : ""}
              </div>
            )}
            {test.data && !test.data.ok && (
              <div className="mt-2 text-xs text-rose-400">连接失败：{test.data.error}</div>
            )}
            {p.configured ? (
              <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                <Badge tone="green">已配置</Badge>
                <span className="truncate">{JSON.stringify(p.config)}</span>
              </div>
            ) : (
              <div className="mt-2 text-xs text-amber-400">未配置参数（需通过 API 或后端配置）</div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        支持 GPTMail / Moemail / 自定义 HTTP 接口。配置项通过 <code className="text-slate-300">PUT /api/v1/tempmail-providers/&#123;name&#125;</code> 写入；敏感字段以 ****** 掩码回显。
      </p>
    </div>
  );
}
