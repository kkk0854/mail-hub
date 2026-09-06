import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { DashboardSummary } from "../api/types";
import { Badge, Empty, PageHeader, StatCard, dt } from "../components/ui";

const COLORS = ["#6366f1", "#10b981", "#f59e0b", "#f43f5e", "#8b5cf6", "#0ea5e9"];

export default function Dashboard() {
  const { data: summary } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api<DashboardSummary>("/dashboard/summary"),
    refetchInterval: 10000,
  });
  const { data: charts } = useQuery({
    queryKey: ["dashboard-charts"],
    queryFn: () => api<any>("/dashboard/charts"),
    refetchInterval: 30000,
  });

  const m = summary?.mailboxes;
  const successRate = summary?.tasks.success_rate;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        desc="邮箱基础设施总览 · 数据 10 秒自动刷新"
        actions={
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Badge tone={summary?.workers.embedded ? "green" : "amber"}>
              Worker {summary?.workers.embedded ? `×${summary.workers.count}` : "外部进程"}
            </Badge>
            <Badge tone="slate">队列深度 {summary?.workers.queue_depth ?? 0}</Badge>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatCard label="邮箱总数" value={m?.total ?? "-"} />
        <StatCard label="正常" value={m?.healthy ?? "-"} tone="green" />
        <StatCard label="异常" value={(m?.warning ?? 0) + (m?.error ?? 0)} tone="amber" />
        <StatCard label="隔离" value={m?.quarantine ?? "-"} tone="red" />
        <StatCard label="今日邮件" value={summary?.mail.today_received ?? "-"} tone="blue" />
        <StatCard label="今日解析" value={summary?.mail.today_parsed ?? "-"} tone="indigo" />
        <StatCard label="运行任务" value={summary?.tasks.running ?? "-"} tone="blue" />
        <StatCard label="任务成功率" value={successRate === null || successRate === undefined ? "-" : `${(successRate * 100).toFixed(1)}%`} tone="green" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">7 日邮件量</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={charts?.mail_7d ?? []}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="#475569" fontSize={11} />
              <YAxis stroke="#475569" fontSize={11} allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }} />
              <Line type="monotone" dataKey="count" name="邮件量" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">健康度趋势（平均分）</h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={charts?.health_trend ?? []}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="#475569" fontSize={11} />
              <YAxis domain={[0, 100]} stroke="#475569" fontSize={11} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }} />
              <Area type="monotone" dataKey="avg_score" name="平均健康分" stroke="#10b981" fill="#10b981" fillOpacity={0.15} strokeWidth={2} connectNulls />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">Provider 分布</h3>
          {(charts?.provider_distribution?.length ?? 0) === 0 ? (
            <Empty text="暂无邮箱" />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={charts?.provider_distribution ?? []} dataKey="value" nameKey="provider" innerRadius={50} outerRadius={80} paddingAngle={3}>
                  {(charts?.provider_distribution ?? []).map((_: any, i: number) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">注册任务结果分布</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={["completed", "failed", "cancelled"].map((k) => ({ name: { completed: "完成", failed: "失败", cancelled: "取消" }[k], value: charts?.task_success?.[k] ?? 0 }))}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="name" stroke="#475569" fontSize={11} />
              <YAxis allowDecimals={false} stroke="#475569" fontSize={11} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }} />
              <Bar dataKey="value" name="任务数" radius={[4, 4, 0, 0]} >
                {[0, 1, 2].map((i) => (
                  <Cell key={i} fill={COLORS[i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">邮箱池健康度</h3>
          <div className="space-y-2">
            {(summary?.pools ?? []).map((p) => (
              <div key={p.id} className="flex items-center gap-3 text-sm">
                <span className="w-28 truncate text-slate-300">{p.name}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-slate-800">
                  <div
                    className="h-full rounded bg-emerald-500"
                    style={{ width: `${p.health_rate === null ? 0 : Math.round(p.health_rate * 100)}%` }}
                  />
                </div>
                <span className="w-20 text-right text-xs text-slate-500 tabular-nums">
                  {p.available}/{p.total} 可用
                </span>
              </div>
            ))}
            {(summary?.pools?.length ?? 0) === 0 && <Empty text="暂无邮箱池" />}
          </div>
        </div>

        <div className="panel p-4">
          <h3 className="mb-3 text-sm font-medium text-slate-300">最近异常</h3>
          {(summary?.recent_errors?.length ?? 0) === 0 ? (
            <Empty text="一切正常" />
          ) : (
            <div className="space-y-2">
              {summary!.recent_errors.map((e) => (
                <div key={e.id} className="rounded-lg border border-rose-900/50 bg-rose-950/20 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <Badge tone="red">{e.task_type}</Badge>
                    <span className="text-slate-500">{dt(e.finished_at)}</span>
                  </div>
                  <div className="mt-1 truncate text-rose-300">{e.error_message}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
