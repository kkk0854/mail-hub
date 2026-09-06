import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Radio, RotateCcw } from "lucide-react";
import { api } from "../api/client";
import type { FetchTask, MailEvent } from "../api/types";
import { Badge, Button, Empty, PageHeader, statusTone, timeOnly, toast } from "../components/ui";
import { useEventStream } from "../hooks/useEvents";

const EVENT_META: Record<string, { label: string; tone: string }> = {
  "mail.received": { label: "邮件进入", tone: "blue" },
  "mail.parsed": { label: "解析完成", tone: "indigo" },
  "mail.result.ready": { label: "结果就绪", tone: "green" },
  "mailbox.status.changed": { label: "邮箱状态变更", tone: "amber" },
  "mailbox.health.changed": { label: "健康度变更", tone: "amber" },
  "task.started": { label: "任务启动", tone: "blue" },
  "task.retrying": { label: "任务重试", tone: "amber" },
  "task.completed": { label: "任务完成", tone: "green" },
  "task.failed": { label: "任务失败", tone: "red" },
  "import.completed": { label: "导入完成", tone: "green" },
};

function describe(e: MailEvent): string {
  const p = e.payload ?? {};
  switch (e.type) {
    case "mail.received":
      return `${p.mailbox ?? p.email ?? ""} ← ${p.sender ?? ""}「${p.subject ?? ""}」`;
    case "mail.parsed":
      return `消息 ${p.message_id} · ${p.parse_status} · ${(p.results ?? []).map((r: any) => `${r.type}=${r.value}`).join(", ") || "无匹配"}`;
    case "mail.result.ready":
      return `任务 ${p.task_id} → ${p.result?.type}=${p.result?.value}`;
    case "mailbox.status.changed":
      return `${p.email ?? ""} ${p.previous ?? "?"} → ${p.status}`;
    case "mailbox.health.changed":
      return `${p.email ?? p.domain ?? ""} ${p.previous ?? "?"} → ${p.health_status}（${p.score} 分）`;
    case "task.started":
      return `任务 ${p.task_id} · 状态 ${p.state}`;
    case "task.retrying":
      return `${p.kind ?? "任务"} 第 ${p.attempt} 次重试`;
    case "task.completed":
      return `任务 ${p.task_id} 已完成`;
    case "task.failed":
      return `任务 ${p.task_id} 失败（${p.reason ?? p.error ?? "unknown"}）`;
    case "import.completed":
      return `批次 ${p.batch_id} 导入 ${p.imported} 个邮箱`;
    default:
      return JSON.stringify(p).slice(0, 120);
  }
}

export default function FetchCenter() {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<MailEvent[]>([]);
  const [live, setLive] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEventStream((e) => {
    setEvents((prev) => [e, ...prev].slice(0, 200));
    if (["task.retrying"].includes(e.type)) {
      queryClient.invalidateQueries({ queryKey: ["fetch-tasks"] });
    }
  });

  useEffect(() => {
    // 判断 SSE 是否已连接：收到事件即 live
    if (events.length > 0) setLive(true);
  }, [events]);

  const { data: tasks } = useQuery({
    queryKey: ["fetch-tasks"],
    queryFn: () => api<{ items: FetchTask[]; total: number }>("/fetch-tasks?page=1&page_size=20"),
    refetchInterval: 6000,
  });
  const { data: summary } = useQuery({
    queryKey: ["dashboard-summary-fetch"],
    queryFn: () => api<any>("/dashboard/summary"),
    refetchInterval: 8000,
  });

  const retry = useMutation({
    mutationFn: (id: string) => api(`/fetch-tasks/${id}/retry`, { method: "POST" }),
    onSuccess: () => {
      toast.info("已重新入队");
      queryClient.invalidateQueries({ queryKey: ["fetch-tasks"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader
        title="取件中心"
        desc="事件驱动取件管道：邮件进入 → 解析 → 规则匹配 → 结果绑定（§10）"
        actions={
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Badge tone={live ? "green" : "amber"}>
              <Radio size={10} className="mr-1 inline" /> {live ? "实时推送中" : "等待事件…"}
            </Badge>
            <Badge tone="slate">Worker ×{summary?.workers?.count ?? 0}</Badge>
            <Badge tone="slate">队列 {summary?.workers?.queue_depth ?? 0}</Badge>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="panel flex flex-col p-4 lg:col-span-3">
          <h3 className="mb-3 text-sm font-medium text-slate-300">实时事件流</h3>
          <div ref={listRef} className="max-h-[440px] flex-1 space-y-1.5 overflow-y-auto font-mono text-xs">
            {events.length === 0 && <Empty text="等待新邮件事件…（注入或同步邮件后此处实时滚动）" />}
            {events.map((e) => {
              const meta = EVENT_META[e.type] ?? { label: e.type, tone: "slate" };
              return (
                <div key={e.event_id} className="flex items-start gap-2 rounded-lg border border-slate-800/70 bg-slate-950/60 px-3 py-2">
                  <span className="shrink-0 text-slate-600">{timeOnly(e.created_at)}</span>
                  <Badge tone={meta.tone} className="shrink-0">{meta.label}</Badge>
                  <span className="break-all text-slate-400">{describe(e)}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="panel p-4 lg:col-span-2">
          <h3 className="mb-3 text-sm font-medium text-slate-300">取件任务队列</h3>
          <div className="max-h-[440px] space-y-2 overflow-y-auto">
            {(tasks?.items ?? []).map((t) => (
              <div key={t.id} className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge tone={t.task_type === "MAIL_SYNC" ? "blue" : t.task_type === "HEALTH_CHECK" ? "green" : "indigo"}>{t.task_type}</Badge>
                    <Badge tone={statusTone(t.state)}>{t.state}</Badge>
                  </div>
                  {t.state === "FAILED" && (
                    <Button size="sm" variant="ghost" onClick={() => retry.mutate(t.id)}>
                      <RotateCcw size={11} /> 重试
                    </Button>
                  )}
                </div>
                <div className="mt-1 flex justify-between text-slate-500">
                  <span className="truncate">{t.mailbox ?? t.mailbox_id ?? "-"}</span>
                  <span>attempt {t.attempt}/{t.max_attempt}</span>
                </div>
                {t.error_message && <div className="mt-1 truncate text-rose-400">{t.error_message}</div>}
              </div>
            ))}
            {(tasks?.items?.length ?? 0) === 0 && <Empty text="队列为空" />}
          </div>
        </div>
      </div>
    </div>
  );
}
