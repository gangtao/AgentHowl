import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../store/auth";
import LoginPage from "./LoginPage";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const userBody = { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" };

describe("LoginPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("登录成功后跳回 next", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(200, { user: userBody }))));
    render(<LoginPage mode="login" next="#/history" />);
    fireEvent.change(screen.getByLabelText("用户名或邮箱"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(useAuth.getState().status).toBe("authed"));
    expect(window.location.hash).toBe("#/history");
  });

  it("未验证 → 切到验证页", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(401, { detail: "邮箱未验证", reason: "unverified" }))));
    render(<LoginPage mode="login" />);
    fireEvent.change(screen.getByLabelText("用户名或邮箱"), { target: { value: "a@x" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(window.location.hash).toBe("#/verify"));
  });

  it("注册：auto 模式提示去登录", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(201, { user: userBody, verification: "auto" }))));
    render(<LoginPage mode="register" />);
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "a@x" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    await waitFor(() => expect(screen.getByText(/注册成功/)).toBeInTheDocument());
  });

  it("注册：email 模式跳验证页", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(201, { user: userBody, verification: "email" }))));
    render(<LoginPage mode="register" />);
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "a@x" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    await waitFor(() => expect(window.location.hash).toBe("#/verify"));
  });
});
