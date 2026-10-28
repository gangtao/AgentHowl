import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ROLE_ICON_PATH } from "../../lib/roleIcons";
import RoleToken from "./RoleToken";

describe("RoleToken（规格 §2.4）", () => {
  it("known：渲染阵营徽记与角色名", () => {
    const { container } = render(<RoleToken role="SEER" size={64} />);
    const root = screen.getByRole("img", { name: "预言家" });
    expect(root).toHaveAttribute("data-state", "known");
    expect(root).toHaveAttribute("data-camp", "god");
    expect(container.querySelector("path")).toHaveAttribute("d", ROLE_ICON_PATH.SEER);
    expect(root.style.width).toBe("64px");
  });

  it("unknown：显示首字，无徽记", () => {
    const { container } = render(<RoleToken role={null} initial="G" size={56} />);
    expect(screen.getByRole("img", { name: "身份未知" })).toHaveTextContent("G");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("unknown 且无 initial → ?", () => {
    render(<RoleToken role={null} size={56} />);
    expect(screen.getByRole("img", { name: "身份未知" })).toHaveTextContent("?");
  });

  it("dead：✕ 且忽略 role", () => {
    const { container } = render(<RoleToken role="WEREWOLF" state="dead" size={64} />);
    expect(screen.getByRole("img", { name: "已出局" })).toHaveTextContent("✕");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("card 变体高度是宽的 4/3", () => {
    render(<RoleToken role="HUNTER" variant="card" size={84} />);
    const root = screen.getByRole("img", { name: "猎人" });
    expect(root).toHaveAttribute("data-variant", "card");
    expect(root.style.height).toBe("112px");
  });

  it("avatar：渲染图片 + 小章；图片失败后退回徽记", () => {
    const { container } = render(<RoleToken role="WITCH" size={64} avatar="av_1" />);
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img.src).toContain("av_1");
    expect(container.querySelectorAll("svg")).toHaveLength(1); // 右下角小章
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelectorAll("svg")).toHaveLength(1); // 退回居中徽记
  });
});
