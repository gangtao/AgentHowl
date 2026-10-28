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

  it("未验证且 identifier 是用户名 → 验证页邮箱不预填（issue #120）", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(401, { detail: "邮箱未验证", reason: "unverified" }))));
    const { unmount } = render(<LoginPage mode="login" />);
    fireEvent.change(screen.getByLabelText("用户名或邮箱"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(window.location.hash).toBe("#/verify"));
    unmount();
    render(<LoginPage mode="verify" />);
    expect((screen.getByLabelText("邮箱") as HTMLInputElement).value).toBe("");
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

describe("LoginPage 村口木牌（设计稿 1b）", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it.each([
    ["login", "入村", "登录"],
    ["register", "落户", "注册"],
    ["verify", "对暗号", "验证"],
  ] as const)("%s 模式：木牌标题「%s」，主按钮「%s」", (mode, heading, button) => {
    render(<LoginPage mode={mode} />);
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: button })).toBeInTheDocument();
    expect(screen.getByText("AgentHowl")).toBeInTheDocument();
  });
});
