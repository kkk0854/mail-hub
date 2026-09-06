import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, XCircle } from "lucide-react";
import { clsx } from "clsx";
import { api } from "../api/client";
import type { Pool, RegistrationTask } from "../api/types";
import { Badge, Button, Empty, Field, Input, Modal, PageHeader, Pagination, Select, statusTone, toast, dt } from "../components/ui";

const FLOW = ["CREATED", "WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED", "RESULT_READY", "WAITING_CALLBACK", "COMPLETED"];

function stateProgress(state: string): number {
  const abnormal = ["TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR", "CANCELLED"];
  if (abnormal.includes(state)) return -1;
  const idx = FLOW.indexOf(state);
  if (state === "EMAIL_RECEIVED") return 3.5;
  return idx;
}

export default function Tasks() {
  const queryClient = useQueryClient();
  const [state, setState] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["tasks", state, page],
    queryFn: () => api<{ items: RegistrationTask[]; total: number }>(`/registration-tasks?state=${state}&page=${page}&page_size=15`),
    refetchInterval: 5000,
  });
  const { data: detail } = useQuery({
    queryKey: ["tasks", detailId],
    queryFn: () => api<RegistrationTask>(`/registration-tasks/${detailId}`),
    enabled: !!detailId,
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api(`/registration-tasks/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      toast.success("任务已取消");
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const elapsed = (t: RegistrationTask) => {
    const start = new Date(t.created_at.endsWith("Z") ? t.created_at : t.created_at + "Z").getTime();
    const end = t.updated_at ? new Date(t.updated_at.endsWith("Z") ? t.updated_at : t.updated_at + "Z").getTime() : Date.now();
    const s = Math.max(0, Math.round((end - start) / 1000));
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
  };

  return (
    <div>
      <PageHeader
        title="注册任务中心"
        desc="申请邮箱 → 等待邮件 → 匹配 → 提取 → 回调（§12）"
        actions={
          <>
            <Select value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
              <option value="">全部状态</option>
              {[...FLOW, "TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR", "CANCELLED"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </Select>
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus size={14} /> 创建测试任务
            </Button>
          </>
        }
      />

      <div className="panel overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Task ID</th><th>Target Ref</th><th>Mailbox</th><th>状态</th><th>耗时</th><th>结果</th><th>回调</th><th>创建时间</th><th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((t) => (
              <tr key={t.id}>
                <td>
                  <button onClick={() => setDetailId(t.id)} className="font-mono text-xs text-indigo-300 hover:underline">
                    {t.id.slice(0, 18)}…
                  </button>
                  <div className="text-[10px] text-slate-600">{t.external_ref}</div>
                </td>
                <td className="text-xs text-slate-400">{t.external_ref || "-"}</td>
                <td className="max-w-44 truncate text-xs text-slate-300">{t.mailbox ?? <span className="text-slate-600">待分配</span>}</td>
                <td><Badge tone={statusTone(t.state)}>{t.state}</Badge></td>
                <td className="text-xs tabular-nums text-slate-500">{elapsed(t)}</td>
                <td>
                  {t.result ? (
                    <span className="font-mono text-xs text-emerald-300">{t.result.type}={t.result.value}</span>
                  ) : (
                    <span className="text-xs text-slate-600">-</span>
                  )}
                </td>
                <td>
                  {t.callback_url ? (
                    <Badge tone={statusTone(t.callback_state)}>{t.callback_state ?? "PENDING"}</Badge>
                  ) : (
                    <span className="text-xs text-slate-600">无</span>
                  )}
                </td>
                <td className="text-xs text-slate-500">{dt(t.created_at)}</td>
                <td>
                  {["CREATED", "WAITING_MAILBOX", "WAITING_EMAIL", "EMAIL_RECEIVED"].includes(t.state) && (
                    <Button size="sm" variant="ghost" title="取消" onClick={() => cancel.mutate(t.id)}>
                      <XCircle size={13} />
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {(data?.items?.length ?? 0) === 0 && (
              <tr><td colSpan={9}><Empty text="暂无任务" /></td></tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pageSize={15} total={data?.total ?? 0} onChange={setPage} />

      <CreateTaskModal open={createOpen} onClose={() => setCreateOpen(false)} />

      <Modal open={!!detailId} onClose={() => setDetailId(null)} title={`任务详情 ${detailId ?? ""}`} wide>
        {detail && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Badge tone={statusTone(detail.state)}>{detail.state}</Badge>
              {detail.result && <span className="font-mono text-sm text-emerald-300">{detail.result.type} = {detail.result.value}</span>}
            </div>
            {stateProgress(detail.state) >= 0 && (
              <div className="flex items-center">
                {FLOW.map((s, i) => {
                  const cur = stateProgress(detail.state);
                  return (
                    <div key={s} className="flex flex-1 items-center last:flex-none">
                      <div className="flex flex-col items-center gap-1">
                        <div className={clsx("h-2.5 w-2.5 rounded-full", i <= cur ? "bg-indigo-500" : "bg-slate-700")} />
                        <span className="max-w-16 text-center text-[9px] text-slate-500">{s}</span>
                      </div>
                      {i < FLOW.length - 1 && <div className={clsx("mx-1 mb-4 h-0.5 flex-1", i < cur ? "bg-indigo-500" : "bg-slate-800")} />}
                    </div>
                  );
                })}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Info label="External Ref" value={detail.external_ref || "-"} />
              <Info label="Mailbox" value={detail.mailbox ?? "-"} />
              <Info label="Sender 匹配" value={detail.match?.sender || "*"} />
              <Info label="Subject 包含" value={detail.match?.subject_contains || "*"} />
              <Info label="超时" value={`${detail.timeout_seconds}s`} />
              <Info label="Callback" value={detail.callback_url || "无"} mono />
              <Info label="Callback 状态" value={detail.callback_state ?? "-"} />
              <Info label="幂等键" value={detail.idempotency_key ?? "-"} mono />
            </div>
            {detail.matched_message && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs">
                <div className="mb-1 font-medium text-slate-400">匹配到的邮件</div>
                <div className="text-slate-300">{detail.matched_message.sender}</div>
                <div className="text-slate-400">{detail.matched_message.subject}</div>
                <div className="text-slate-600">{dt(detail.matched_message.received_at)}</div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-600">{label}</div>
      <div className={`truncate text-slate-300 ${mono ? "font-mono text-xs" : "text-xs"}`}>{value}</div>
    </div>
  );
}

function CreateTaskModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: pools } = useQuery({ queryKey: ["pools"], queryFn: () => api<{ items: Pool[] }>("/pools") });
  const [poolId, setPoolId] = useState("");
  const [targetRef, setTargetRef] = useState("");
  const [sender, setSender] = useState("");
  const [subjectContains, setSubjectContains] = useState("verification");
  const [timeout, setTimeoutSec] = useState(300);
  const [callbackUrl, setCallbackUrl] = useState("");
  const [idemKey, setIdemKey] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api("/registration-tasks", {
        method: "POST",
        body: {
          pool_id: poolId || null,
          target_ref: targetRef,
          match: { sender, subject_contains: subjectContains },
          timeout_seconds: timeout,
          callback_url: callbackUrl || null,
          idempotency_key: idemKey || null,
        },
      }),
    onSuccess: (t: any) => {
      toast.success(`任务已创建：${t.state}`);
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onClose();
    },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="创建注册任务"
      footer={
        <>
          <Button variant="subtle" onClick={onClose}>取消</Button>
          <Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending}>创建</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="邮箱池">
            <Select value={poolId} onChange={(e) => setPoolId(e.target.value)} className="w-full">
              <option value="">default</option>
              {(pools?.items ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Target Ref">
            <Input value={targetRef} onChange={(e) => setTargetRef(e.target.value)} placeholder="external-job-123" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Sender 匹配" hint="支持 glob，如 *@example.com">
            <Input value={sender} onChange={(e) => setSender(e.target.value)} placeholder="留空不限定" />
          </Field>
          <Field label="主题包含">
            <Input value={subjectContains} onChange={(e) => setSubjectContains(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="超时（秒）">
            <Input type="number" value={timeout} onChange={(e) => setTimeoutSec(Number(e.target.value))} />
          </Field>
          <Field label="幂等键（可选）">
            <Input value={idemKey} onChange={(e) => setIdemKey(e.target.value)} placeholder="ext-idempotency-key" />
          </Field>
        </div>
        <Field label="Callback URL（可选）" hint="留空则通过 API 轮询结果">
          <Input value={callbackUrl} onChange={(e) => setCallbackUrl(e.target.value)} placeholder="https://client.example/callback" />
        </Field>
      </div>
    </Modal>
  );
}
