import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { Mailbox } from "../api/types";
import { Badge, Button, Empty, PageHeader, statusTone, toast, dt } from "../components/ui";
import { clsx } from "clsx";

const GROUPS = [
  { key: "HEALTHY", label: "Healthy", tone: "green" },
  { key: "WARNING", label: "Warning", tone: "amber" },
  { key: "TOKEN_EXPIRED", label: "Token 过期", tone: "red" },
  { key: "AUTH_FAILED", label: "Auth Failed", tone: "red" },
  { key: "SYNC_ERROR", label: "Sync Error", tone: "amber" },
  { key: "QUARANTINED", label: "Quarantine", tone: "purple" },
];

export default function Keepalive() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");

  const { data: all } = useQuery({
    queryKey: ["keepalive-mailboxes", "all"],
    queryFn: () => api<{ items: Mailbox[]; total: number }>("/mailboxes?page=1&page_size=200"),
    refetchInterval: 8000,
  });

  const items = (all?.items ?? []).filter((m) => !filter || m.health_status === filter);
  const counts: Record<string, number> = {};
  for (const m of all?.items ?? []) {
    const k = m.health_status ?? "未检测";
    counts[k] = (counts[k] ?? 0) + 1;
  }

  const batchCheck = useMutation({
    mutationFn: () => api("/mailboxes/batch-health-check", { method: "POST", body: { ids: items.map((m) => m.id) } }),
    onSuccess: (r: any) => {
      toast.success(`已入队 ${r.enqueued} 个健康检查任务`);
      queryClient.invalidateQueries({ queryKey: ["keepalive-mailboxes"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const checkOne = useMutation({
    mutationFn: (id: string) => api(`/mailboxes/${id}/health-check`, { method: "POST" }),
    onSuccess: (r: any) => {
      toast.success(`${r.health_status} · ${r.score} 分`);
      queryClient.invalidateQueries({ queryKey: ["keepalive-mailboxes"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader
        title="保活中心"
        desc="账号/授权 + 连接 + 同步 + 取件 四维健康监测（§3.6/§8）"
        actions={
          <Button variant="subtle" onClick={() => batchCheck.mutate()} disabled={items.length === 0}>
            <ShieldCheck size={14} /> 批量健康检查 ({items.length})
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          onClick={() => setFilter("")}
          className={clsx(
            "rounded-lg border px-3 py-2 text-sm transition-colors",
            !filter ? "border-indigo-500 bg-indigo-600/10 text-indigo-300" : "border-slate-800 bg-slate-900/60 text-slate-400"
          )}
        >
          全部 <span className="tabular-nums">({all?.total ?? 0})</span>
        </button>
        {GROUPS.map((g) => (
          <button
            key={g.key}
            onClick={() => setFilter(g.key)}
            className={clsx(
              "rounded-lg border px-3 py-2 text-sm transition-colors",
              filter === g.key ? "border-indigo-500 bg-indigo-600/10 text-indigo-300" : "border-slate-800 bg-slate-900/60 text-slate-400"
            )}
          >
            {g.label} <span className="tabular-nums">({counts[g.key] ?? 0})</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((m) => (
          <div key={m.id} className="panel p-4">
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <div className="truncate font-medium text-slate-200">{m.email}</div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <Badge tone="indigo">{m.provider_type}</Badge>
                  <Badge tone={statusTone(m.status)}>{m.status}</Badge>
                </div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => checkOne.mutate(m.id)}>
                <ShieldCheck size={13} />
              </Button>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded bg-slate-800">
                <div
                  className={clsx(
                    "h-full rounded",
                    m.health_score >= 90 ? "bg-emerald-500" : m.health_score >= 75 ? "bg-emerald-400" : m.health_score >= 50 ? "bg-amber-500" : "bg-rose-500"
                  )}
                  style={{ width: `${m.health_score}%` }}
                />
              </div>
              <span className="text-xs tabular-nums text-slate-400">{m.health_score}</span>
            </div>
            <div className="mt-2 flex justify-between text-xs text-slate-600">
              <span>最近检查 {dt(m.last_check_at)}</span>
              <span>失败 {m.failure_count} 次</span>
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <div className="panel md:col-span-2 xl:col-span-3">
            <Empty text="没有匹配的邮箱" />
          </div>
        )}
      </div>
    </div>
  );
}
