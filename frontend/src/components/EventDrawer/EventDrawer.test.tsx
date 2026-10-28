import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EventDrawer from "./EventDrawer";

describe("EventDrawer（规格 §4.6）", () => {
  it("关闭时只有页签；点击页签回调；aria-expanded 跟随 open", () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <EventDrawer open={false} onToggle={onToggle} tabLabel="事件流 · 发言回顾">
        <p>feed</p>
      </EventDrawer>,
    );
    const tab = screen.getByRole("button", { name: /事件流 · 发言回顾/ });
    expect(tab).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("complementary")).toBeNull();
    fireEvent.click(tab);
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <EventDrawer open onToggle={onToggle} tabLabel="事件流 · 发言回顾">
        <p>feed</p>
      </EventDrawer>,
    );
    expect(screen.getByRole("button", { name: /事件流 · 发言回顾/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("complementary", { name: "事件流" })).toHaveTextContent("feed");
  });

  it("打开时 Esc 触发 onToggle；关闭时不触发", () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <EventDrawer open onToggle={onToggle} tabLabel="t">
        x
      </EventDrawer>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <EventDrawer open={false} onToggle={onToggle} tabLabel="t">
        x
      </EventDrawer>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("top 插槽渲染在 children 之上", () => {
    render(
      <EventDrawer open onToggle={vi.fn()} tabLabel="t" top={<div>rail</div>}>
        <div>feed</div>
      </EventDrawer>,
    );
    const panel = screen.getByRole("complementary");
    expect(panel.textContent?.indexOf("rail")).toBeLessThan(panel.textContent?.indexOf("feed") ?? -1);
  });
});
