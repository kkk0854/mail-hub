import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api } from "../api/client";

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  mustChangePassword: boolean;
  /** 登录成功；返回是否强制改密 */
  login: (username: string, password: string) => Promise<boolean>;
  /** 修改当前用户密码（成功后会解除强制标记） */
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
  clearMustChangePassword: () => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      role: null,
      mustChangePassword: false,
      login: async (username, password) => {
        const data = await api<{
          token: string;
          username: string;
          role: string;
          force_password_change: boolean;
        }>("/auth/login", {
          method: "POST",
          body: { username, password },
        });
        const forced = data.force_password_change === true;
        set({
          token: data.token,
          username: data.username,
          role: data.role,
          mustChangePassword: forced,
        });
        return forced;
      },
      changePassword: async (oldPassword, newPassword) => {
        const data = await api<{ ok: boolean }>("/auth/change-password", {
          method: "POST",
          body: { old_password: oldPassword, new_password: newPassword },
        });
        if (!data.ok) throw new Error("修改失败");
        set({ mustChangePassword: false });
      },
      clearMustChangePassword: () => set({ mustChangePassword: false }),
      logout: () =>
        set({ token: null, username: null, role: null, mustChangePassword: false }),
    }),
    { name: "mailhub-auth" }
  )
);
