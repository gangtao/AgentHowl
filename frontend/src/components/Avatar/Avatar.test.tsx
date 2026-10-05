// Avatar：有 id 渲染 img（内容寻址 URL）；无 id 或加载失败退回「名字首字 + 座位色」占位。

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Avatar from "./Avatar";

describe("Avatar", () => {
  it("有 id 渲染 img，指向 /api/v1/avatars/{id}", () => {
    render(<Avatar avatar="3f9a1c0b7e2d4a66.png" name="夜枭" seat={3} size={40} />);
    const img = screen.getByRole("img", { name: /夜枭/ });
    expect(img).toHaveAttribute("src", "/api/v1/avatars/3f9a1c0b7e2d4a66.png");
  });
  it("无 id 渲染名字首字占位；空名用座位号", () => {
    render(<Avatar avatar={null} name="夜枭" seat={3} size={40} />);
    expect(screen.getByText("夜")).toBeInTheDocument();
    render(<Avatar avatar={null} name="" seat={5} size={40} />);
    expect(screen.getByText("5")).toBeInTheDocument();
  });
  it("img 加载失败退回占位", () => {
    render(<Avatar avatar="3f9a1c0b7e2d4a66.png" name="夜枭" seat={3} size={40} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("夜")).toBeInTheDocument();
  });
});
