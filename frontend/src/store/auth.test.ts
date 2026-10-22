import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/rest";
import { useAuth } from "./auth";

const user = {
  user_id: "u_1",
  username: "alice",
  email: "a@x",
  role: "user" as const,
  status: "active" as const,
  email_verified: true,
  created_at: "t",
};

function mockFetch(handler: (url: string, init?: RequestInit) => Response): void {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(handler(url, init))));
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("useAuth", () => {
  beforeEach(() => {
    useAuth.setState({ user: null, status: "loading" });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("load：me 200 → authed；401 → anon", async () => {
    mockFetch(() => json(200, user));
    await useAuth.getState().load();
    expect(useAuth.getState()).toMatchObject({ status: "authed", user });
    mockFetch(() => json(401, { detail: "未登录" }));
    await useAuth.getState().load();
    expect(useAuth.getState()).toMatchObject({ status: "anon", user: null });
  });

  it("login 成功写入 user；失败抛 ApiError 带 reason", async () => {
    mockFetch(() => json(200, { user }));
    await useAuth.getState().login("alice", "password1");
    expect(useAuth.getState().user?.username).toBe("alice");
    mockFetch(() => json(401, { detail: "邮箱未验证", reason: "unverified" }));
    await expect(useAuth.getState().login("alice", "x")).rejects.toMatchObject({ reason: "unverified" });
  });

  it("logout 清空并置 anon", async () => {
    useAuth.setState({ user, status: "authed" });
    mockFetch(() => new Response(null, { status: 204 }));
    await useAuth.getState().logout();
    expect(useAuth.getState()).toMatchObject({ status: "anon", user: null });
  });

  it("fetch 带 credentials same-origin", async () => {
    mockFetch(() => json(200, user));
    await useAuth.getState().load();
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(call[1].credentials).toBe("same-origin");
    expect(new ApiError(401, "x")).toBeInstanceOf(Error);
  });
});
