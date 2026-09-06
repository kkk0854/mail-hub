import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  Gauge,
  Globe,
  Inbox,
  Layers,
  ListChecks,
  LogOut,
  Mail,
  Radio,
  Settings2,
  Upload,
  Users,
} from "lucide-react";
import { clsx } from "clsx";
import { useAuthStore } from "../stores/auth";
import { Badge, Toasts } from "./ui";
import { useEventStream } from "../hooks/useEvents";
import { useQueryClient } from "@tanstack/react-query";

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/mailboxes", label: "邮箱管理", icon: Inbox },
  { to: "/import", label: "Outlook 导入", icon: Upload },
  { to: "/domains", label: "CF 域名", icon: Globe },
  { to: "/aliases", label: "Alias 中心", icon: Users },
  { to: "/keepalive", label: "保活中心", icon: Activity },
  { to: "/fetch", label: "取件中心", icon: Radio },
  { to: "/mails", label: "邮件中心", icon: Mail },
  { to: "/tasks", label: "注册任务", icon: ListChecks },
  { to: "/pools", label: "邮箱池", icon: Layers },
  { to: "/rules", label: "解析规则", icon: Settings2 },
];

export default function Layout() {
  const { username, logout } = useAuthStore();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEventStream((e) => {
    // 关键页面数据自动刷新（无需手动刷新页面，§18）
    const refreshMap: Record<string, string[]> = {
      "mail.received": ["messages", "mailboxes", "dashboard"],
      "mail.parsed": ["messages", "dashboard"],
      "mail.result.ready": ["tasks", "dashboard"],
      "mailbox.health.changed": ["mailboxes", "dashboard", "keepalive"],
      "mailbox.status.changed": ["mailboxes", "dashboard", "keepalive", "pools"],
      "task.started": ["tasks", "dashboard"],
      "task.completed": ["tasks", "dashboard", "pools"],
      "task.failed": ["tasks", "dashboard", "pools"],
      "task.retrying": ["fetch-tasks"],
      "import.completed": ["mailboxes", "imports"],
    };
    for (const key of refreshMap[e.type] ?? []) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  });

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">M</div>
          <div>
            <div className="text-sm font-bold tracking-wide text-slate-100">MAIL HUB</div>
            <div className="text-[10px] text-slate-500">邮箱基础设施平台</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  isActive ? "bg-indigo-600/15 text-indigo-300 font-medium" : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                )
              }
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800 px-4 py-3 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            <Badge tone="indigo">{username ?? "-"}</Badge>
          </span>
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="text-slate-500 hover:text-rose-400"
            title="退出登录"
          >
            <LogOut size={15} />
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6">
          <Outlet />
        </div>
      </main>
      <Toasts />
    </div>
  );
}
