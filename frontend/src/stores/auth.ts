import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api } from "../api/client";

interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      role: null,
      login: async (username, password) => {
        const data = await api<{ token: string; username: string; role: string }>("/auth/login", {
          method: "POST",
          body: { username, password },
        });
        set({ token: data.token, username: data.username, role: data.role });
      },
      logout: () => set({ token: null, username: null, role: null }),
    }),
    { name: "mailhub-auth" }
  )
);
