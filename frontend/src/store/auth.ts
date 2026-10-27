// 登录态 store（issue #114）：启动 load() 一次；401 时 App 经 setUnauthorizedHandler 再调 load()。

import { create } from "zustand";
import * as api from "../api/auth";
import { ApiError } from "../api/rest";
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
      } catch (e) {
        // 401 即匿名。网络 / 5xx（issue #120）：已登录态保持不动（一次抖动不该把人踢到登录页），
        // 启动加载期没有别的可展示才落到匿名
        const unauthorized = e instanceof ApiError && e.status === 401;
        set((s) => (unauthorized || s.status !== "authed" ? { user: null, status: "anon" } : {}));
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
