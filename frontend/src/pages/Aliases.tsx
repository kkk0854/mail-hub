import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Alias, Mailbox } from "../api/types";
import { Badge, Button, Empty, Input, PageHeader, toast, dt } from "../components/ui";
import { clsx } from "clsx";

export interface AliasT {}

interface AliasWithTime extends Alias {
  created_at: string;
}

export default function Aliases() {
  const queryClient = useQueryClient();
  const [masterId, setMasterId] = useState("");
  const [newAlias, setNewAlias] = useState("");

  const { data: mailboxes } = useQuery({
    queryKey: ["mailboxes", "alias-masters"],
    queryFn: () => api<{ items: Mailbox[] }>("/mailboxes?page=1&page_size=100"),
  });
  const { data: aliases } = useQuery({
    queryKey: ["aliases", masterId],
    queryFn: () => api<{ items: AliasWithTime[] }>(`/aliases?master_mailbox_id=${masterId}`),
  });

  const create = useMutation({
    mutationFn: () => api("/aliases", { method: "POST", body: { master_mailbox_id: masterId, alias_address: newAlias } }),
    onSuccess: () => {
      toast.success("别名已创建");
      setNewAlias("");
      queryClient.invalidateQueries({ queryKey: ["aliases"] });
    },
    onError: (e: any) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/aliases/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("别名已删除");
      queryClient.invalidateQueries({ queryKey: ["aliases"] });
    },
  });

  const masters = mailboxes?.items ?? [];
  const selectedMaster = masters.find((m) => m.id === masterId);
  const items = aliases?.items ?? [];

  return (
    <div>
      <PageHeader title="Alias 中心" desc="主邮箱与分裂别名一对多逻辑关系（§3.5）· 别名收件自动归档到主邮箱" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="panel p-3 lg:col-span-2">
          <h3 className="mb-2 px-1 text-xs font-medium uppercase tracking-wider text-slate-500">Master 邮箱</h3>
          <div className="max-h-[480px] space-y-1 overflow-y-auto">
            {masters.map((m) => (
              <button
                key={m.id}
                onClick={() => setMasterId(m.id)}
                className={clsx(
                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm",
                  masterId === m.id ? "bg-indigo-600/15 text-indigo-200" : "text-slate-300 hover:bg-slate-800/60"
                )}
              >
                <span className="truncate">{m.email}</span>
                <Badge tone="indigo">{m.provider_type}</Badge>
              </button>
            ))}
            {masters.length === 0 && <Empty text="请先添加邮箱" />}
          </div>
        </div>

        <div className="panel p-4 lg:col-span-3">
          {!masterId ? (
            <Empty text="从左侧选择主邮箱" />
          ) : (
            <>
              <div className="mb-4 flex gap-2">
                <Input
                  value={newAlias}
                  onChange={(e) => setNewAlias(e.target.value)}
                  placeholder={`如 ${selectedMaster?.email.split("@")[0]}+001@${selectedMaster?.email.split("@")[1]}`}
                />
                <Button variant="primary" disabled={!newAlias || create.isPending} onClick={() => create.mutate()}>
                  <Plus size={14} /> 添加别名
                </Button>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm text-slate-300">
                  <span className="rounded-lg bg-indigo-600/20 px-2 py-1 font-medium text-indigo-300">{selectedMaster?.email}</span>
                </div>
                <div className="ml-4 space-y-2 border-l-2 border-slate-800 pl-4">
                  {items.length === 0 && <span className="text-xs text-slate-600">暂无别名</span>}
                  {items.map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-lg bg-slate-900/70 px-3 py-2">
                      <span className="font-mono text-xs text-slate-300">├─ {a.alias_address}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-600">{dt(a.created_at)}</span>
                        <Button size="sm" variant="ghost" onClick={() => remove.mutate(a.id)}>
                          <Trash2 size={12} />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
