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
