import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ErrorState from "./ErrorState";

describe("ErrorState（设计稿 4f）", () => {
  it("4404：这局已随风散去 → 回到村志", () => {
    render(<ErrorState kind="4404" />);
    expect(screen.getByRole("alert")).toHaveTextContent("这局已随风散去");
    expect(screen.getByRole("link", { name: "回到村志" })).toHaveAttribute("href", "#/history");
  });

  it("auth：村口有人守着 → 去登录", () => {
    render(<ErrorState kind="auth" />);
    expect(screen.getByText("村口有人守着")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去登录" })).toHaveAttribute("href", "#/login");
  });

  it("locked：以玩家身份进入链接", () => {
    render(<ErrorState kind="locked" playerHref="#/g/g_1?token=t" />);
    expect(screen.getByRole("link", { name: /以玩家身份进入/ })).toHaveAttribute(
      "href",
      "#/g/g_1?token=t",
    );
  });

  it("4409：status 角色与重试次数", () => {
    render(<ErrorState kind="4409" attempt={3} />);
    expect(screen.getByRole("status")).toHaveTextContent("第 3 次");
  });

  it("detail 原文照渲染（长文本）", () => {
    const long = "x".repeat(240);
    render(<ErrorState kind="error" detail={long} />);
    expect(screen.getByText(long)).toBeInTheDocument();
  });
});
