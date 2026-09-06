import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import type { ImportPreview, Pool } from "../api/types";
import { Badge, Button, Field, Input, PageHeader, Select, Textarea, statusTone, toast } from "../components/ui";
import { clsx } from "clsx";

const FIELD_TARGETS = ["email", "password", "refresh_token", "client_id", "client_secret", "tenant_id", "imap_host", "imap_port", "imap_user", "display_name", "ignore"];

const SAMPLE = `alice01@outlook.com:Passw0rd!:RT-A1B2C3D4:936da51f-c
alice02@outlook.com:Passw0rd!:RT-E5F6G7H8:936da51f-c
alice03@outlook.com:Passw0rd!:RT-I9J0K1L2:936da51f-c`;

export default function ImportWizard() {
  const [step, setStep] = useState(1);
  const [sourceType, setSourceType] = useState("PASTE");
  const [delimiter, setDelimiter] = useState(":");
  const [providerType, setProviderType] = useState("outlook");
  const [mapping, setMapping] = useState<string[]>(["email", "password", "refresh_token", "client_id"]);
  const [text, setText] = useState(SAMPLE);
  const [poolId, setPoolId] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [commitResult, setCommitResult] = useState<any>(null);

  const { data: pools } = useQuery({ queryKey: ["pools"], queryFn: () => api<{ items: Pool[] }>("/pools") });

  const doPreview = async () => {
    try {
      const data = await api<ImportPreview>("/imports/preview", {
        method: "POST",
        body: { provider_type: providerType, source_type: sourceType, delimiter, field_mapping: mapping, source_text: text, pool_id: poolId || null },
      });
      setPreview(data);
      setStep(3);
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const doCommit = async () => {
    if (!preview) return;
    try {
      const result = await api("/imports/commit", { method: "POST", body: { batch_id: preview.id } });
      setCommitResult(result);
      setStep(4);
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const steps = ["① 粘贴", "② 映射", "③ 预览", "④ 导入"];
  return (
    <div>
      <PageHeader title="Outlook 四段式导入" desc="Segment→字段可配置映射 · 校验 · 去重 · 敏感字段加密（§7）" />
      <div className="mb-5 flex items-center gap-2">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={clsx(
                "flex h-8 items-center rounded-full px-4 text-xs font-medium",
                step === i + 1 ? "bg-indigo-600 text-white" : step > i + 1 ? "bg-emerald-600/20 text-emerald-300" : "bg-slate-800 text-slate-500"
              )}
            >
              {step > i + 1 && <Check size={12} className="mr-1" />}
              {s}
            </div>
            {i < 3 && <ChevronRight size={14} className="text-slate-700" />}
          </div>
        ))}
      </div>

      {step === 1 && (
        <div className="panel space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="来源格式">
              <Select value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="w-full">
                <option value="PASTE">四段式文本</option>
                <option value="CSV">CSV</option>
                <option value="JSON">JSON</option>
              </Select>
            </Field>
            <Field label="分隔符（四段式）">
              <Input value={delimiter} onChange={(e) => setDelimiter(e.target.value)} maxLength={3} />
            </Field>
            <Field label="目标 Provider">
              <Select value={providerType} onChange={(e) => setProviderType(e.target.value)} className="w-full">
                <option value="outlook">outlook</option>
                <option value="imap">imap</option>
                <option value="simulator">simulator</option>
              </Select>
            </Field>
            <Field label="导入后加入邮箱池">
              <Select value={poolId} onChange={(e) => setPoolId(e.target.value)} className="w-full">
                <option value="">不加入</option>
                {(pools?.items ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="邮箱数据" hint={sourceType === "PASTE" ? "每行一条，段与段之间用分隔符隔开" : sourceType === "CSV" ? "首行为表头（支持 email/password/refresh_token/...）" : "JSON 对象数组"}>
            <Textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="flex justify-end">
            <Button variant="primary" onClick={() => setStep(2)} disabled={!text.trim()}>
              下一步：字段映射
            </Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="panel space-y-4 p-5">
          <p className="text-sm text-slate-400">将每个 Segment 映射到业务字段（四段式不固定绑定机密字段，§3.3）。敏感字段将加密存储。</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {mapping.map((target, i) => (
              <Field key={i} label={`Segment ${i + 1}`}>
                <Select
                  value={target}
                  onChange={(e) => setMapping(mapping.map((m, j) => (j === i ? e.target.value : m)))}
                  className="w-full"
                >
                  {FIELD_TARGETS.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </Select>
              </Field>
            ))}
          </div>
          <div className="flex justify-between">
            <Button variant="subtle" onClick={() => setStep(1)}><ChevronLeft size={14} /> 上一步</Button>
            <Button variant="primary" onClick={doPreview}>解析并预览</Button>
          </div>
        </div>
      )}

      {step === 3 && preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <CountCard label="总记录" value={preview.total_rows} tone="slate" />
            <CountCard label="有效" value={preview.valid_rows} tone="green" />
            <CountCard label="重复" value={preview.duplicate_rows} tone="amber" />
            <CountCard label="字段错误" value={preview.error_rows} tone="red" />
            <CountCard label="缺失" value={preview.missing_rows} tone="purple" />
          </div>
          <div className="panel max-h-96 overflow-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>行</th><th>内容</th><th>解析结果</th><th>状态</th><th>说明</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 200).map((r) => (
                  <tr key={r.line_no}>
                    <td className="text-slate-500 tabular-nums">{r.line_no}</td>
                    <td className="max-w-72 truncate font-mono text-xs text-slate-400">{r.raw_line}</td>
                    <td className="font-mono text-xs text-slate-400">{r.parsed?.email ?? "-"}</td>
                    <td><Badge tone={statusTone(r.status)}>{r.status}</Badge></td>
                    <td className="text-xs text-rose-400">{r.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-between">
            <Button variant="subtle" onClick={() => setStep(2)}><ChevronLeft size={14} /> 上一步</Button>
            <Button variant="primary" onClick={doCommit} disabled={preview.valid_rows === 0}>
              导入 {preview.valid_rows} 条有效记录
            </Button>
          </div>
        </div>
      )}

      {step === 4 && commitResult && (
        <div className="panel p-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-600/20 text-emerald-400">
            <Check size={24} />
          </div>
          <h3 className="text-lg font-semibold text-slate-100">导入完成</h3>
          <p className="mt-1 text-sm text-slate-400">
            成功导入 <span className="font-semibold text-emerald-400">{commitResult.imported}</span> 个邮箱
            {commitResult.skipped > 0 && <>，跳过重复 <span className="text-amber-400">{commitResult.skipped}</span></>}。
            每个邮箱已建立凭据（加密）、同步游标与健康检查任务。
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <Button variant="subtle" onClick={() => { setStep(1); setPreview(null); setCommitResult(null); }}>
              继续导入
            </Button>
            <Button variant="primary" onClick={() => (window.location.href = "/mailboxes")}>前往邮箱管理</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function CountCard({ label, value, tone }: { label: string; value: number; tone: string }) {
  const colors: Record<string, string> = { slate: "text-slate-200", green: "text-emerald-400", amber: "text-amber-400", red: "text-rose-400", purple: "text-purple-400" };
  return (
    <div className="panel p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", colors[tone])}>{value}</div>
    </div>
  );
}
