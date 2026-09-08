import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/auth";
import { Button, Input, toast } from "../components/ui";

export default function Login() {
  const login = useAuthStore((s) => s.login);
  const changePassword = useAuthStore((s) => s.changePassword);
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "change">("login");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mode === "change" && newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setLoading(true);
    try {
      if (mode === "login") {
        const forced = await login(username, password);
        if (forced) {
          setMode("change");
        } else {
          navigate("/");
        }
      } else {
        await changePassword(password, newPassword);
        toast.success("密码已修改，请使用新密码重新登录");
        setMode("login");
        setPassword("");
        setNewPassword("");
        setConfirmPassword("");
      }
    } catch (err: any) {
      toast.error(err.message ?? "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-slate-950">
      <div className="w-96 panel p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white">M</div>
          <div>
            <div className="text-lg font-bold text-slate-100">MAIL HUB</div>
            <div className="text-xs text-slate-500">多邮箱接入 · 注册任务编排 · 自动取件回填</div>
          </div>
        </div>

        {mode === "change" && (
          <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            出于安全考虑，首次登录必须修改初始密码后才能进入控制台。
          </div>
        )}

        <form onSubmit={submit} className="space-y-4">
          {mode === "login" ? (
            <>
              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-400">用户名</span>
                <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-400">密码</span>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-400">当前密码</span>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-400">新密码（至少 8 位，含字母和数字）</span>
                <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div className="space-y-1">
                <span className="text-xs font-medium text-slate-400">确认新密码</span>
                <Input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
              </div>
            </>
          )}
          <Button type="submit" variant="primary" disabled={loading} className="w-full py-2">
            {loading ? "处理中…" : mode === "login" ? "登录控制台" : "确认修改密码"}
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-600">
          {mode === "login" ? "首次启动默认账号 admin，请登录后立即修改密码" : "修改成功后需使用新密码重新登录"}
        </p>
      </div>
    </div>
  );
}
