import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Mailbox, Pool } from "../api/types";
import { Badge, Button, Empty, Field, Input, Modal, PageHeader, Pagination, Select, statusTone, Textarea, toast, dt } from "../components/ui";

const PROVIDERS = ["outlook", "cloudflare", "imap", "simulator"];
const STATUS_OPTIONS = ["IMPORTED", "READY", "IN_USE", "COOLDOWN", "AVAILABLE", "QUARANTINED", "DISABLED", "ARCHIVED"];

export default function Mailboxes() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [providerType, setProviderType] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["mailboxes", q, providerType, status, page],
    queryFn: () =>
      api<{ items: Mailbox[]; total: number }>(
        `/mailboxes?page=${page}&page_size=15&q=${encodeURIComponent(q)}&provider_type=${providerType}&status=${status}`
      ),
    refetchInterval: 8000,
  });

  const healthCheck = useMutation({
    mutationFn: (id: string) => api(`/mailboxes/${id}/health-check`, { method: "POST" }),
    onSuccess: (r: any) => {
      toast.success(`${r.health_status} · 评分 ${r.score}`);
      queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const sync = useMutation({
    mutationFn: (id: string) => api(`/mailboxes/${id}/sync`, { method: "POST" }),
    onSuccess: () => toast.info("同步任务已入队"),
    onError: (e: any) => toast.error(e.message),
  });

  const archive = useMutation({
    mutationFn: (id: string) => api(`/mailboxes/${id}?hard=false`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("已归档");
      queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
  });

  const batchCheck = useMutation({
    mutationFn: (ids: string[]) => api("/mailboxes/batch-health-check", { method: "POST", body: { ids } }),
    onSuccess: (r: any) => {
      toast.success(`已入队 ${r.enqueued} 个健康检查任务`);
      setSelected(new Set());
    },
    onError: (e: any) => toast.error(e.message),
  });

  const toggleSelect = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  return (
    <div>
      <PageHeader
        title="邮箱管理"
        desc="统一接入 Outlook / Cloudflare / IMAP / Simulator 邮箱"
        actions={
          <>
            <Button
              variant="subtle"
              disabled={selected.size === 0}
              onClick={() => batchCheck.mutate(Array.from(selected))}
            >
              <ShieldCheck size={14} /> 批量检测 ({selected.size})
            </Button>
            <Button variant="primary" onClick={() => setAddOpen(true)}>
              <Plus size={14} /> 添加邮箱
            </Button>
          </>
        }
      />

      <div className="mb-3 flex flex-wrap gap-2">
        <Input placeholder="搜索邮箱…" value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />
        <Select value={providerType} onChange={(e) => { setProviderType(e.target.value); setPage(1); }}>
          <option value="">全部 Provider</option>
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </Select>
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">全部状态</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
      </div>

      <div className="panel overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th className="w-8"></th>
              <th>邮箱</th>
              <th>Provider</th>
              <th>状态</th>
              <th>健康</th>
              <th>Pool</th>
              <th>最近检查</th>
              <th>最近同步</th>
              <th>今日邮件</th>
              <th className="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={10} className="py-8 text-center text-slate-500">加载中…</td></tr>
            )}
            {(data?.items ?? []).map((mb) => (
              <tr key={mb.id}>
                <td>
                  <input type="checkbox" checked={selected.has(mb.id)} onChange={() => toggleSelect(mb.id)} className="accent-indigo-500" />
                </td>
                <td>
                  <div className="font-medium text-slate-200">{mb.email}</div>
                  <div className="text-xs text-slate-600">{mb.display_name}</div>
                </td>
                <td><Badge tone="indigo">{mb.provider_type}</Badge></td>
                <td><Badge tone={statusTone(mb.status)}>{mb.status}</Badge></td>
                <td>
                  <div className="flex items-center gap-1.5">
                    <Badge tone={statusTone(mb.health_status)}>{mb.health_status ?? "未检测"}</Badge>
                    <span className="text-xs text-slate-500 tabular-nums">{mb.health_score}</span>
                  </div>
                </td>
                <td className="text-xs text-slate-400">{mb.pool_name ?? "-"}</td>
                <td className="text-xs text-slate-500">{dt(mb.last_check_at)}</td>
                <td className="text-xs text-slate-500">{dt(mb.last_sync_at)}</td>
                <td className="tabular-nums text-slate-300">{mb.today_mail_count ?? 0}</td>
                <td>
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" title="健康检查" onClick={() => healthCheck.mutate(mb.id)}>
                      <ShieldCheck size={13} />
                    </Button>
                    <Button size="sm" variant="ghost" title="立即同步" onClick={() => sync.mutate(mb.id)}>
                      <RefreshCw size={13} />
                    </Button>
                    <Button size="sm" variant="ghost" title="归档" onClick={() => archive.mutate(mb.id)}>
                      <Trash2 size={13} />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && (data?.items?.length ?? 0) === 0 && (
              <tr><td colSpan={10}><Empty text="还没有邮箱，试试右上角添加或使用 Outlook 导入" /></td></tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={15} total={data?.total ?? 0} onChange={setPage} />

      <AddMailboxModal open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}

function AddMailboxModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: pools } = useQuery({
    queryKey: ["pools"],
    queryFn: () => api<{ items: Pool[] }>("/pools"),
  });
  const [email, setEmail] = useState("");
  const [providerType, setProviderType] = useState("simulator");
  const [poolId, setPoolId] = useState("");
  const [password, setPassword] = useState("");
  const [extraCreds, setExtraCreds] = useState("");

  const create = useMutation({
    mutationFn: () => {
      let credentials: Record<string, string> = {};
      if (password) credentials["PASSWORD"] = password;
      if (extraCreds.trim()) {
        try {
          credentials = { ...credentials, ...JSON.parse(extraCreds) };
        } catch {
          throw new Error("凭据 JSON 格式错误");
        }
      }
      return api("/mailboxes", { method: "POST", body: { email, provider_type: providerType, pool_id: poolId || null, credentials } });
    },
    onSuccess: () => {
      toast.success("邮箱已添加（IMPORTED），建议立即执行健康检查");
      queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
      onClose();
      setEmail("");
      setPassword("");
      setExtraCreds("");
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="添加邮箱"
      footer={
        <>
          <Button variant="subtle" onClick={onClose}>取消</Button>
          <Button variant="primary" onClick={() => create.mutate()} disabled={!email || create.isPending}>
            添加
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="邮箱地址">
          <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@example.com" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Provider">
            <Select value={providerType} onChange={(e) => setProviderType(e.target.value)} className="w-full">
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </Select>
          </Field>
          <Field label="邮箱池（可选）">
            <Select value={poolId} onChange={(e) => setPoolId(e.target.value)} className="w-full">
              <option value="">不加入</option>
              {(pools?.items ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="密码凭据（可选，服务端加密存储）">
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••" />
        </Field>
        <Field label="其他凭据 JSON（可选）" hint='如 {"OAUTH_REFRESH_TOKEN": "...", "OAUTH_CLIENT_ID": "...", "IMAP_HOST": "imap.example.com", "IMAP_PORT": 993}'>
          <Textarea rows={3} value={extraCreds} onChange={(e) => setExtraCreds(e.target.value)} placeholder="{}" />
        </Field>
      </div>
    </Modal>
  );
}
