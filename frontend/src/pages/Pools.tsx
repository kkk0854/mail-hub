import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Pool } from "../api/types";
import { Badge, Button, Empty, Field, Input, Modal, PageHeader, toast } from "../components/ui";

export default function Pools() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["pools-page"],
    queryFn: () => api<{ items: Pool[] }>("/pools"),
    refetchInterval: 8000,
  });

  const allocate = useMutation({
    mutationFn: (poolId: string) => api<{ email: string }>(`/pools/${poolId}/allocate`, { method: "POST", body: {} }),
    onSuccess: (mb) => {
      toast.success(`已分配：${mb.email}`);
      queryClient.invalidateQueries({ queryKey: ["pools-page"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader
        title="邮箱池"
        desc="调度资源层：分配 / 冷却 / 并发与每日限额 / 自动隔离（§9）"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <Plus size={14} /> 创建邮箱池
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(data?.items ?? []).map((p) => (
          <div key={p.id} className="panel p-4">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold text-slate-100">{p.name}</div>
                <div className="text-xs text-slate-500">{p.description || "无描述"}</div>
              </div>
              <Badge tone={p.status === "active" ? "green" : "slate"}>{p.status}</Badge>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
              {([["可用", p.stats?.available ?? 0, "text-emerald-400"], ["使用中", p.stats?.in_use ?? 0, "text-sky-400"], ["冷却", p.stats?.cooldown ?? 0, "text-amber-400"]] as const).map(([k, v, c]) => (
                <div key={k} className="rounded-lg border border-slate-800 bg-slate-900/50 py-2">
                  <div className={c}>{v}</div>
                  <div className="text-[10px] text-slate-600">{k}</div>
                </div>
              ))}
            </div>

            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-500">
              <span>并发上限 <b className="text-slate-300">{p.max_concurrent}</b></span>
              <span>冷却 <b className="text-slate-300">{p.cooldown_seconds}s</b></span>
              <span>每日限额 <b className="text-slate-300">{p.daily_limit}</b></span>
              <span>失败阈值 <b className="text-slate-300">{p.failure_threshold}</b></span>
              <span className="col-span-2">自动隔离 <Badge tone={p.auto_quarantine ? "green" : "slate"}>{p.auto_quarantine ? "开启" : "关闭"}</Badge></span>
            </div>

            <div className="mt-3 flex justify-end gap-2">
              <Button size="sm" variant="subtle" onClick={() => allocate.mutate(p.id)}>
                <ArrowRightLeft size={12} /> 测试分配
              </Button>
            </div>
          </div>
        ))}
        {(data?.items?.length ?? 0) === 0 && (
          <div className="panel md:col-span-2 xl:col-span-3"><Empty text="暂无邮箱池" /></div>
        )}
      </div>

      <CreatePoolModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function CreatePoolModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", description: "", max_concurrent: 1, cooldown_seconds: 300, daily_limit: 20, failure_threshold: 3, auto_quarantine: true });

  const create = useMutation({
    mutationFn: () => api("/pools", { method: "POST", body: form }),
    onSuccess: () => {
      toast.success("邮箱池已创建");
      queryClient.invalidateQueries({ queryKey: ["pools-page"] });
      onClose();
    },
    onError: (e: any) => toast.error(e.message),
  });

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="创建邮箱池"
      footer={
        <>
          <Button variant="subtle" onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={!form.name || create.isPending} onClick={() => create.mutate()}>创建</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="名称"><Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="pool-a" /></Field>
        <Field label="描述"><Input value={form.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="单邮箱最大并发"><Input type="number" value={form.max_concurrent} onChange={(e) => set("max_concurrent", Number(e.target.value))} /></Field>
          <Field label="冷却时间（秒）"><Input type="number" value={form.cooldown_seconds} onChange={(e) => set("cooldown_seconds", Number(e.target.value))} /></Field>
          <Field label="单邮箱每日任务上限"><Input type="number" value={form.daily_limit} onChange={(e) => set("daily_limit", Number(e.target.value))} /></Field>
          <Field label="连续失败隔离阈值"><Input type="number" value={form.failure_threshold} onChange={(e) => set("failure_threshold", Number(e.target.value))} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={form.auto_quarantine} onChange={(e) => set("auto_quarantine", e.target.checked)} className="accent-indigo-500" />
          达到失败阈值自动隔离
        </label>
      </div>
    </Modal>
  );
}
