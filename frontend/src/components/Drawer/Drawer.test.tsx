import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

describe("Drawer 壳（设计稿 4e）", () => {
  it("缺省羊皮纸、渲染 kicker 与 idTag", () => {
    render(
      <Drawer title="编辑 Agent" kicker="招 募 告 示" idTag="a_1" onClose={vi.fn()} footer={<span>foot</span>}>
        body
      </Drawer>,
    );
    const dialog = screen.getByRole("dialog", { name: "编辑 Agent" });
    expect(dialog).toHaveAttribute("data-tone", "parch");
    expect(screen.getByText("招 募 告 示")).toBeInTheDocument();
    expect(screen.getByText("a_1")).toBeInTheDocument();
  });

  it("tone=wood 透传；Esc 关闭", () => {
    const onClose = vi.fn();
    render(
      <Drawer title="t" tone="wood" onClose={onClose} footer={null}>
        b
      </Drawer>,
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("data-tone", "wood");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
