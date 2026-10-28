import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../store/auth";
import AdminUsers from "./AdminUsers";

const me = {
  user_id: "u_me",
  username: "root",
  email: "r@x",
  role: "admin" as const,
  status: "active" as const,
  email_verified: true,
  created_at: "t",
};
const bob = {
  user_id: "u_bob",
  username: "bob",
  email: "b@x",
  role: "user" as const,
  status: "active" as const,
  email_verified: false,
  created_at: "t",
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("AdminUsers", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("列出用户，自己那行按钮禁用，禁用他人后刷新", async () => {
    useAuth.setState({ user: me, status: "authed" });
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return Promise.resolve(json(200, { ...bob, status: "disabled" }));
      if (init?.method === "POST")
        return Promise.resolve(json(200, { ...bob, email_verified: true }));
      return Promise.resolve(json(200, [me, bob]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminUsers />);
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    // 长老名册：标题 / 羊皮纸表 / 身份着色标记
    expect(screen.getByRole("heading", { name: "长老名册 · 用户管理" })).toBeInTheDocument();
    expect(document.querySelector("table")).toHaveClass("table-parch");
    expect(screen.getByText("管理员")).toHaveAttribute("data-role", "admin");
    expect(screen.getByText("普通用户")).toHaveAttribute("data-role", "user");
    expect(screen.getByRole("button", { name: "禁用 bob" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "禁用 root" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "禁用 bob" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/admin/users/u_bob",
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "标记已验证 bob" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/admin/users/u_bob/verify",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("请求在途时该行按钮禁用，返回后更新为「启用」", async () => {
    useAuth.setState({ user: me, status: "authed" });
    let resolvePatch: (r: Response) => void = () => {};
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return new Promise<Response>((res) => (resolvePatch = res));
      return Promise.resolve(json(200, [me, bob]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminUsers />);
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "禁用 bob" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "禁用 bob" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "设为管理员 bob" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "标记已验证 bob" })).toBeDisabled();
    resolvePatch(json(200, { ...bob, status: "disabled" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "启用 bob" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "设为管理员 bob" })).toBeEnabled();
  });

  it("PATCH 失败时行不变并在错误条显示 detail", async () => {
    useAuth.setState({ user: me, status: "authed" });
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return Promise.resolve(json(400, { detail: "至少保留一个可用的管理员" }));
      return Promise.resolve(json(200, [me, bob]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminUsers />);
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "禁用 bob" }));
    await waitFor(() => expect(screen.getByText("至少保留一个可用的管理员")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "禁用 bob" })).toBeEnabled();
  });

  it("两行并发失败各自显示错误、互不覆盖；注册时间按本地格式显示（issue #120）", async () => {
    useAuth.setState({ user: me, status: "authed" });
    const carol = {
      ...bob,
      user_id: "u_carol",
      username: "carol",
      email: "c@x",
      created_at: "2026-10-02T03:00:00+00:00",
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const who = url.endsWith("/u_bob") ? "bob 不能改" : "carol 不能改";
        return Promise.resolve(json(400, { detail: who }));
      }
      return Promise.resolve(json(200, [me, bob, carol]));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminUsers />);
    await waitFor(() => expect(screen.getByText("carol")).toBeInTheDocument());
    const cell = screen.getByText("carol").closest("tr") as HTMLElement;
    expect(cell.textContent).toContain("2026");
    expect(cell.textContent).not.toContain("T03:00:00");
    fireEvent.click(screen.getByRole("button", { name: "禁用 bob" }));
    fireEvent.click(screen.getByRole("button", { name: "禁用 carol" }));
    await waitFor(() => expect(screen.getByText("bob 不能改")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("carol 不能改")).toBeInTheDocument());
    expect(screen.getByText("bob 不能改")).toBeInTheDocument(); // 没被后到的 carol 错误覆盖
  });
});
