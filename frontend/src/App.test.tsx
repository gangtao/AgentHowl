import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { useAuth } from "./store/auth";

describe("App 匿名首访（issue #114）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("/auth/me 恒 401：不递归重试，渲染登录表单，hash 不变", async () => {
    useAuth.setState({ user: null, status: "loading" });
    window.location.hash = "#/history";
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "未登录" }), { status: 401, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.getByLabelText("用户名或邮箱")).toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(2);
    expect(window.location.hash).toBe("#/history");
  });
});

describe("App 登录态下的认证路由（issue #120）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
    sessionStorage.removeItem("agenthowl.next");
  });

  it("已登录打开 #/login → 不显示表单，回跳到记下的目的地并清掉 agenthowl.next", async () => {
    const me = { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" };
    useAuth.setState({ user: me as never, status: "authed" });
    sessionStorage.setItem("agenthowl.next", "#/history");
    window.location.hash = "#/login";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const body = url.includes("/auth/me") ? me : []; // 回跳后的历史页会拉 /games 列表
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe("#/history"));
    expect(screen.queryByLabelText("用户名或邮箱")).toBeNull();
    expect(sessionStorage.getItem("agenthowl.next")).toBeNull();
  });
});

describe("App 导航（设计稿 1c 木栏）", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("登录态：当前路由高亮、右侧显示「用户名 · 离村」", async () => {
    const me = { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" };
    useAuth.setState({ user: me as never, status: "authed" });
    window.location.hash = "#/history";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(url.includes("/auth/me") ? me : []), { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    );
    render(<App />);
    expect(screen.getByRole("link", { name: "历史对局" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "新的一局" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "离村" })).toBeInTheDocument();
    await waitFor(() => expect(useAuth.getState().status).toBe("authed"));
  });
});
