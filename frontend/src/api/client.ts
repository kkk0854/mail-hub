import { useAuthStore } from "../stores/auth";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface Opts {
  method?: string;
  body?: unknown;
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`/api/v1${path}`, {
    method: opts.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && token) {
    useAuthStore.getState().logout();
    window.location.href = "/login";
    throw new ApiError(401, "登录已过期");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}
