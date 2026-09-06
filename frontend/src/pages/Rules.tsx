import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { ParserRule } from "../api/types";
import { Badge, Button, Empty, Field, Input, Modal, PageHeader, Select, statusTone, Textarea, toast } from "../components/ui";

const OUTPUT_TYPES = ["OTP", "URL", "SECURITY_EVENT", "ORDER_ID", "ACTIVATION_LINK", "CUSTOM"];

export default function Rules() {
  const queryClient = useQueryClient();
  const [editRule, setEditRule] = useState<ParserRule | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["rules"],
    queryFn: () => api<{ items: ParserRule[] }>("/parser-rules"),
  });

  const toggle = useMutation({
    mutationFn: (r: ParserRule) => api(`/parser-rules/${r.id}`, { method: "PATCH", body: { status: r.status === "active" ? "disabled" : "active" } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/parser-rules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("规则已删除");
      queryClient.invalidateQueries({ queryKey: ["rules"] });
    },
  });

  return (
    <div>
      <PageHeader
        title="解析规则"
        desc="Sender / Subject / Regex / 优先级 / 输出类型（§11）· 优先级数字越小越优先"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <Plus size={14} /> 新建规则
          </Button>
        }
      />
      <div className="panel overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>名称</th><th>发件人匹配</th><th>主题匹配</th><th>Body Regex</th><th>输出</th><th>优先级</th><th>状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((r) => (
              <tr key={r.id}>
                <td className="font-medium text-slate-200">
                  <button onClick={() => setEditRule(r)} className="hover:text-indigo-300">{r.name}</button>
                </td>
                <td className="font-mono text-xs text-slate-400">{r.sender_pattern || "*"}</td>
                <td className="font-mono text-xs text-slate-400">{r.subject_pattern || "-"}</td>
                <td className="max-w-56 truncate font-mono text-xs text-slate-400">{r.body_regex || "-"}</td>
                <td><Badge tone={r.output_type === "OTP" ? "green" : r.output_type === "SECURITY_EVENT" ? "red" : "indigo"}>{r.output_type}</Badge></td>
                <td className="tabular-nums text-slate-400">{r.priority}</td>
                <td>
                  <button onClick={() => toggle.mutate(r)}>
                    <Badge tone={statusTone(r.status === "active" ? "ACTIVE" : "DISABLED")}>{r.status}</Badge>
                  </button>
                </td>
                <td>
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(r.id)}>
                    <Trash2 size={12} />
                  </Button>
                </td>
              </tr>
            ))}
            {(data?.items?.length ?? 0) === 0 && (
              <tr><td colSpan={8}><Empty /></td></tr>
            )}
          </tbody>
        </table>
      </div>

      <RuleModal open={createOpen || !!editRule} rule={editRule} onClose={() => { setCreateOpen(false); setEditRule(null); }} />
    </div>
  );
}

function RuleModal({ open, rule, onClose }: { open: boolean; rule: ParserRule | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<any>(null);

  // 每次打开时同步表单
  if (open && rule && (!form || form.id !== rule.id)) {
    setForm({ ...rule });
  }
  if (open && !rule && form?.id) {
    setForm(null);
  }
  const value = form ?? (rule ? { ...rule } : { name: "", sender_pattern: "*", subject_pattern: "", body_regex: "", output_type: "OTP", priority: 50, provider_type: "", status: "active" });

  const save = useMutation({
    mutationFn: () => {
      const body = { ...value, provider_type: value.provider_type || null };
      if (rule) return api(`/parser-rules/${rule.id}`, { method: "PATCH", body });
      return api("/parser-rules", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(rule ? "规则已更新" : "规则已创建");
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      setForm(null);
      onClose();
    },
    onError: (e: any) => toast.error(e.message),
  });

  const set = (k: string, v: any) => setForm((f: any) => ({ ...(f ?? value), [k]: v }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={rule ? "编辑规则" : "新建规则"}
      footer={
        <>
          <Button variant="subtle" onClick={onClose}>取消</Button>
          <Button variant="primary" onClick={() => save.mutate()} disabled={!value.name}>保存</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="规则名称"><Input value={value.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="输出类型">
            <Select value={value.output_type} onChange={(e) => set("output_type", e.target.value)} className="w-full">
              {OUTPUT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="发件人匹配" hint="支持 glob，* 为任意"><Input value={value.sender_pattern} onChange={(e) => set("sender_pattern", e.target.value)} /></Field>
          <Field label="主题匹配（正则）"><Input value={value.subject_pattern} onChange={(e) => set("subject_pattern", e.target.value)} /></Field>
        </div>
        <Field label="Body 正则" hint="捕获组为提取值，如 \\b(\\d{6})\\b">
          <Textarea rows={2} value={value.body_regex} onChange={(e) => set("body_regex", e.target.value)} />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="优先级"><Input type="number" value={value.priority} onChange={(e) => set("priority", Number(e.target.value))} /></Field>
          <Field label="限定 Provider（可选）">
            <Select value={value.provider_type ?? ""} onChange={(e) => set("provider_type", e.target.value)} className="w-full">
              <option value="">全部</option>
              {["outlook", "cloudflare", "imap", "simulator"].map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>
          </Field>
          <Field label="状态">
            <Select value={value.status} onChange={(e) => set("status", e.target.value)} className="w-full">
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </Select>
          </Field>
        </div>
      </div>
    </Modal>
  );
}
