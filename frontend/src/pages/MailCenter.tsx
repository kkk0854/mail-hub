import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Eye } from "lucide-react";
import { api } from "../api/client";
import type { MessageDetail, MessageSummary } from "../api/types";
import { Badge, Button, Empty, PageHeader, Pagination, Tabs, statusTone, toast, dt } from "../components/ui";
import { clsx } from "clsx";

const TABS = [
  { key: "all", label: "全部" },
  { key: "unread", label: "未读" },
  { key: "verification", label: "验证类" },
  { key: "security", label: "安全" },
  { key: "link", label: "链接" },
  { key: "failed", label: "解析失败" },
  { key: "archived", label: "已归档" },
];

export default function MailCenter() {
  const queryClient = useQueryClient();
  const [view, setView] = useState("all");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["messages", view, page],
    queryFn: () => api<{ items: MessageSummary[]; total: number }>(`/messages?view=${view}&page=${page}&page_size=15`),
    refetchInterval: 8000,
  });
  const { data: detail } = useQuery({
    queryKey: ["messages", selectedId],
    queryFn: () => api<MessageDetail>(`/messages/${selectedId}`),
    enabled: !!selectedId,
  });

  const reparse = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}/reparse`, { method: "POST" }),
    onSuccess: (r: any) => {
      toast.success(`重新解析完成：${r.results.length} 个结果`);
      queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const markRead = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}/read`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages"] }),
  });
  const archive = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}/archive`, { method: "POST" }),
    onSuccess: () => {
      toast.success("已归档");
      queryClient.invalidateQueries({ queryKey: ["messages"] });
      setSelectedId(null);
    },
  });

  return (
    <div>
      <PageHeader title="邮件中心" desc="统一邮件视图 · 解析结果与原始邮件留档（§3.8）" />
      <div className="mb-3">
        <Tabs tabs={TABS} active={view} onChange={(k) => { setView(k); setPage(1); }} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <div className="panel overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>发件人</th><th>主题</th><th>邮箱</th><th>状态</th><th>时间</th><th></th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((m) => (
                  <tr key={m.id} className={clsx(!m.is_read && "font-medium")}>
                    <td className="max-w-40 truncate text-slate-300">{m.sender}</td>
                    <td className="max-w-52">
                      <button onClick={() => { setSelectedId(m.id); if (!m.is_read) markRead.mutate(m.id); }} className="truncate text-left text-slate-200 hover:text-indigo-300">
                        {m.subject || "(无主题)"}
                      </button>
                    </td>
                    <td className="max-w-40 truncate text-xs text-slate-500">{m.mailbox}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={statusTone(m.parse_status)}>{m.parse_status}</Badge>
                        {m.category !== "normal" && <Badge tone={m.category === "security" ? "red" : "indigo"}>{m.category}</Badge>}
                      </div>
                    </td>
                    <td className="text-xs text-slate-500">{dt(m.received_at)}</td>
                    <td>
                      <Button size="sm" variant="ghost" onClick={() => { setSelectedId(m.id); if (!m.is_read) markRead.mutate(m.id); }}>
                        <Eye size={13} />
                      </Button>
                    </td>
                  </tr>
                ))}
                {(data?.items?.length ?? 0) === 0 && (
                  <tr><td colSpan={6}><Empty /></td></tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={15} total={data?.total ?? 0} onChange={setPage} />
        </div>

        <div className="lg:col-span-2">
          {detail ? (
            <div className="panel p-4">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-slate-100">{detail.subject || "(无主题)"}</h3>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {detail.sender} → {detail.recipient} · {dt(detail.received_at)}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="subtle" onClick={() => reparse.mutate(detail.id)}>重解析</Button>
                  <Button size="sm" variant="ghost" onClick={() => archive.mutate(detail.id)}>
                    <Archive size={12} />
                  </Button>
                </div>
              </div>

              {detail.results.length > 0 && (
                <div className="mb-3 space-y-1.5">
                  {detail.results.map((r) => (
                    <div key={r.id} className="flex items-center justify-between rounded-lg border border-emerald-900/50 bg-emerald-950/20 px-3 py-2">
                      <Badge tone="green">{r.type}</Badge>
                      <span className="font-mono text-sm font-semibold text-emerald-300">{r.value}</span>
                      <span className="text-xs text-slate-600">{r.rule_name} · {(r.confidence * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              )}

              {detail.body_html ? (
                <iframe
                  title="mail-html"
                  sandbox=""
                  srcDoc={detail.body_html}
                  className="h-72 w-full rounded-lg border border-slate-800 bg-white"
                />
              ) : (
                <pre className="h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300">
                  {detail.body_text || "(空正文)"}
                </pre>
              )}

              <div className="mt-2 text-[10px] text-slate-600">原始邮件：{detail.raw_storage_ref || "-"}</div>
            </div>
          ) : (
            <div className="panel">
              <Empty text="选择一封邮件查看详情与解析结果" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
