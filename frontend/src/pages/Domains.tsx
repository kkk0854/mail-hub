import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { CfDomain } from "../api/types";
import { Badge, Button, Empty, Field, Input, Modal, PageHeader, Select, statusTone, Textarea, toast, dt } from "../components/ui";

export default function Domains() {
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [secretShown, setSecretShown] = useState<CfDomain | null>(null);

  const { data } = useQuery({
    queryKey: ["domains"],
    queryFn: () => api<{ items: CfDomain[]; total: number }>("/cf-domains"),
    refetchInterval: 10000,
  });

  const checkDns = useMutation({
    mutationFn: (id: string) => api(`/cf-domains/${id}/check-dns`, { method: "POST" }),
    onSuccess: (r: any) => {
      toast.success(`DNS 检查完成：${r.dns_status}`);
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/cf-domains/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("域名已删除");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
  });

  return (
    <div>
      <PageHeader
        title="CF Domains"
        desc="Cloudflare Email Routing 域名接入 · Email Worker 推送模式"
        actions={
          <Button variant="primary" onClick={() => setAddOpen(true)}>
            <Globe size={14} /> 添加域名
          </Button>
        }
      />

      {(data?.items?.length ?? 0) === 0 ? (
        <div className="panel">
          <Empty text="还没有注册域名。添加后即可通过 Email Worker 把收件推送到 MAIL HUB" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(data?.items ?? []).map((d) => (
            <div key={d.id} className="panel p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-slate-100">{d.domain}</div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <Badge tone={statusTone(d.status)}>{d.status}</Badge>
                    <Badge tone="indigo">{d.mode}</Badge>
                  </div>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" title="检查 DNS" onClick={() => checkDns.mutate(d.id)}>
                    <RefreshCw size={13} />
                  </Button>
                  <Button size="sm" variant="ghost" title="删除" onClick={() => remove.mutate(d.id)}>
                    <Trash2 size={13} />
                  </Button>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-4 gap-2 text-center">
                {([["DNS", d.dns_status], ["MX", d.mx_status], ["SPF", d.spf_status], ["DKIM", d.dkim_status]] as const).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-slate-800 bg-slate-900/50 py-2">
                    <div className="text-[10px] text-slate-600">{k}</div>
                    <Badge tone={statusTone(v === "missing" ? "ERROR" : v)} className="mt-1">{v}</Badge>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                <span>今日收件 {d.today_messages ?? 0} 封</span>
                <span>最近收件 {dt(d.last_mail_at)}</span>
              </div>
              <div className="mt-2 rounded-lg border border-slate-800 bg-slate-950/60 p-2 font-mono text-[10px] leading-relaxed text-slate-600">
                POST /api/v1/inbound/cloudflare
                <br />
                X-Inbound-Token: {d.has_inbound_secret ? "••••••（已配置）" : "未配置"}
              </div>
            </div>
          ))}
        </div>
      )}

      <AddDomainModal open={addOpen} onClose={() => setAddOpen(false)} onCreated={setSecretShown} />
      <Modal open={!!secretShown} onClose={() => setSecretShown(null)} title="入站 Token（仅显示一次）">
        <p className="mb-3 text-sm text-slate-400">
          请将此 Token 配置到 Cloudflare Email Worker 的请求头 <code className="text-indigo-300">X-Inbound-Token</code>。关闭后不再显示，请妥善保存。
        </p>
        <div className="rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-sm text-emerald-300 break-all">
          {secretShown?.inbound_secret}
        </div>
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 font-mono text-[11px] text-slate-500">
          {`POST https://<your-host>/api/v1/inbound/cloudflare`}
          <br />
          {`Content-Type: application/json`}
          <br />
          {`X-Inbound-Token: <token>`}
          <br />
          {`{"to": "...", "from": "...", "subject": "...", "text": "...", "messageId": "..."}`}
        </div>
      </Modal>
    </div>
  );
}

function AddDomainModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (d: CfDomain) => void }) {
  const queryClient = useQueryClient();
  const [domain, setDomain] = useState("");
  const [mode, setMode] = useState("WORKER");
  const [notes, setNotes] = useState("");

  const create = useMutation({
    mutationFn: () => api<CfDomain>("/cf-domains", { method: "POST", body: { domain, mode, notes } }),
    onSuccess: (d) => {
      queryClient.invalidateQueries({ queryKey: ["domains"] });
      onClose();
      onCreated(d);
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="添加 CF 域名"
      footer={
        <>
          <Button variant="subtle" onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={!domain || create.isPending} onClick={() => create.mutate()}>创建</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="域名">
          <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="mail.example.com" />
        </Field>
        <Field label="接入模式" hint="WORKER：Email Worker 推送到 MAIL HUB；DESTINATION：转发到目标地址">
          <Select value={mode} onChange={(e) => setMode(e.target.value)} className="w-full">
            <option value="WORKER">WORKER（推荐）</option>
            <option value="DESTINATION">DESTINATION</option>
          </Select>
        </Field>
        <Field label="备注">
          <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
