import { type ReactNode } from "react";
import { clsx } from "clsx";
import { X } from "lucide-react";
import { create } from "zustand";

/* ------------------------------------------------ Toast */
interface Toast {
  id: number;
  type: "success" | "error" | "info";
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push: (type: Toast["type"], message: string) => void;
  remove: (id: number) => void;
}

let nextId = 1;
export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (type, message) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, type, message }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 4200);
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  success: (m: string) => useToastStore.getState().push("success", m),
  error: (m: string) => useToastStore.getState().push("error", m),
  info: (m: string) => useToastStore.getState().push("info", m),
};

export function Toasts() {
  const { toasts, remove } = useToastStore();
  return (
    <div className="fixed bottom-4 right-4 z-[100] space-y-2 w-80">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-lg backdrop-blur",
            t.type === "success" && "border-emerald-800 bg-emerald-950/80 text-emerald-200",
            t.type === "error" && "border-rose-800 bg-rose-950/80 text-rose-200",
            t.type === "info" && "border-slate-700 bg-slate-900/90 text-slate-200"
          )}
        >
          <span className="flex-1 break-all">{t.message}</span>
          <button onClick={() => remove(t.id)} className="opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------ 基础组件 */
export function Button({
  children,
  onClick,
  variant = "default",
  size = "md",
  disabled,
  className,
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "danger" | "ghost" | "subtle";
  size?: "sm" | "md";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
        variant === "default" && "border border-slate-700 bg-slate-800/70 hover:bg-slate-700/70 text-slate-200",
        variant === "primary" && "bg-indigo-600 hover:bg-indigo-500 text-white",
        variant === "danger" && "bg-rose-600/90 hover:bg-rose-500 text-white",
        variant === "ghost" && "hover:bg-slate-800 text-slate-300",
        variant === "subtle" && "bg-slate-800/50 hover:bg-slate-800 text-slate-300 border border-slate-800",
        className
      )}
    >
      {children}
    </button>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("panel p-4", className)}>{children}</div>;
}

const badgeTones: Record<string, string> = {
  slate: "bg-slate-800 text-slate-300 border-slate-700",
  green: "bg-emerald-950 text-emerald-300 border-emerald-800",
  amber: "bg-amber-950 text-amber-300 border-amber-800",
  red: "bg-rose-950 text-rose-300 border-rose-800",
  blue: "bg-sky-950 text-sky-300 border-sky-800",
  indigo: "bg-indigo-950 text-indigo-300 border-indigo-800",
  purple: "bg-purple-950 text-purple-300 border-purple-800",
};

export function Badge({ children, tone = "slate", className }: { children: ReactNode; tone?: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap", badgeTones[tone] ?? badgeTones.slate, className)}>
      {children}
    </span>
  );
}

export function statusTone(status: string | null | undefined): string {
  const s = (status ?? "").toUpperCase();
  if (["HEALTHY", "COMPLETED", "SUCCESS", "AVAILABLE", "READY", "ACTIVE", "PARSED", "DELIVERED"].includes(s)) return "green";
  if (["WARNING", "SYNC_ERROR", "RATE_LIMITED", "RETRYING", "PENDING", "COOLDOWN", "VALIDATING", "UNKNOWN"].includes(s)) return "amber";
  if (["AUTH_FAILED", "TOKEN_EXPIRED", "NETWORK_ERROR", "MAILBOX_UNAVAILABLE", "FAILED", "ERROR", "TIMEOUT", "PARSING_FAILED", "MAILBOX_ERROR", "EXHAUSTED", "PARSE_FAILED", "MISSING"].includes(s)) return "red";
  if (["QUARANTINED", "DISABLED", "ARCHIVED", "CANCELLED"].includes(s)) return "purple";
  if (["IN_USE", "RUNNING", "EMAIL_RECEIVED", "PARSING", "RESULT_READY"].includes(s)) return "blue";
  return "slate";
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={clsx(
        "w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500",
        props.className
      )}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={clsx(
        "w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 font-mono",
        props.className
      )}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={clsx(
        "rounded-lg border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-sm text-slate-200 outline-none focus:border-indigo-500",
        props.className
      )}
    >
      {props.children}
    </select>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-600">{hint}</span>}
    </label>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className={clsx("panel w-full p-5 max-h-[85vh] overflow-y-auto", wide ? "max-w-3xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-100">{title}</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X size={16} />
          </button>
        </div>
        {children}
        {footer && <div className="mt-4 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <div className={clsx("h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400", className)} />
  );
}

export function Empty({ text = "暂无数据" }: { text?: string }) {
  return <div className="py-10 text-center text-sm text-slate-600">{text}</div>;
}

export function StatCard({ label, value, sub, tone = "slate" }: { label: string; value: ReactNode; sub?: string; tone?: string }) {
  const colors: Record<string, string> = {
    slate: "text-slate-100",
    green: "text-emerald-400",
    amber: "text-amber-400",
    red: "text-rose-400",
    blue: "text-sky-400",
    indigo: "text-indigo-400",
  };
  return (
    <div className="panel p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", colors[tone] ?? colors.slate)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-600">{sub}</div>}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between pt-3 text-xs text-slate-500">
      <span>
        共 {total} 条 · 第 {page}/{pages} 页
      </span>
      <div className="flex gap-1.5">
        <Button size="sm" variant="subtle" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          上一页
        </Button>
        <Button size="sm" variant="subtle" disabled={page >= pages} onClick={() => onChange(page + 1)}>
          下一页
        </Button>
      </div>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { key: string; label: string; count?: number }[]; active: string; onChange: (k: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-slate-800 bg-slate-900/70 p-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={clsx(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            active === t.key ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
          )}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1 opacity-70">({t.count})</span>}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
        {desc && <p className="mt-0.5 text-sm text-slate-500">{desc}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function dt(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}
