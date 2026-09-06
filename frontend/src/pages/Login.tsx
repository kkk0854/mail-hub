import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/auth";
import { Button, Input, toast } from "../components/ui";

export default function Login() {
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err: any) {
      toast.error(err.message ?? "登录失败");
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
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1">
            <span className="text-xs font-medium text-slate-400">用户名</span>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1">
            <span className="text-xs font-medium text-slate-400">密码</span>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="默认 admin123" />
          </div>
          <Button type="submit" variant="primary" disabled={loading} className="w-full py-2">
            {loading ? "登录中…" : "登录控制台"}
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-slate-600">首次启动默认账号 admin / admin123，请及时修改</p>
      </div>
    </div>
  );
}
