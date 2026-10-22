// 登录态 store（issue #114）：启动 load() 一次；401 时 App 经 setUnauthorizedHandler 再调 load()。

import { create } from "zustand";
import * as api from "../api/auth";
import type { UserPublic } from "../api/auth";

export type AuthStatus = "loading" | "anon" | "authed";

interface AuthState {
  user: UserPublic | null;
  status: AuthStatus;
  load(): Promise<void>;
  login(identifier: string, password: string): Promise<void>;
  logout(): Promise<void>;
  markAnon(): void;
}

let inflight: Promise<void> | null = null;

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: "loading",

  load() {
    // 并发 load() 合并为同一个请求，避免 401 回调与启动加载互相放大。
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const user = await api.me();
        set({ user, status: "authed" });
      } catch {
        // 401 即匿名；网络 / 5xx 也按匿名处理（页面落到登录页，重试即可）
        set({ user: null, status: "anon" });
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  },

  async login(identifier, password) {
    const user = await api.login(identifier, password);
    set({ user, status: "authed" });
  },

  async logout() {
    try {
      await api.logout();
    } finally {
      set({ user: null, status: "anon" });
    }
  },

  markAnon() {
    set({ user: null, status: "anon" });
  },
}));
