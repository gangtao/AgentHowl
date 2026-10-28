import { describe, expect, it } from "vitest";
import { nameGradient, nameGradientCss, potionColors, winnerColorVar } from "./pagesLook";

describe("nameGradient", () => {
  it("同名同色、不同名大概率不同色、空名缺省", () => {
    expect(nameGradient("狐语")).toEqual(nameGradient("狐语"));
    // 六对色按哈希取：一组不同名字至少散到 3 种颜色（单对比较会撞桶）
    const his = new Set(
      ["狐语", "算盘", "夜枭", "老好人", "巧舌", "村长", "铁匠"].map((n) => nameGradient(n).hi),
    );
    expect(his.size).toBeGreaterThanOrEqual(3);
    expect(nameGradient("")).toEqual({ hi: "#5a4330", lo: "#3a2a1e" });
    expect(nameGradient("   ")).toEqual(nameGradient(null));
  });
  it("css 形状", () => {
    expect(nameGradientCss("狐语")).toMatch(
      /^radial-gradient\(circle at 35% 30%, #[0-9a-f]{6}, #[0-9a-f]{6}\)$/,
    );
  });
});

describe("potionColors / winnerColorVar", () => {
  it("六种 kind 各有颜色，未知 kind 缺省", () => {
    expect(potionColors("ollama")).toEqual({ hi: "#f0b85a", lo: "#8a5a1e" });
    expect(potionColors("mystery")).toEqual({ hi: "#a79f8c", lo: "#4a4238" });
  });
  it.each([
    ["GOOD", "--ah-god"],
    ["WOLF", "--ah-wolf"],
    ["DRAW", null],
    [null, null],
  ])("%s → %s", (w, v) => expect(winnerColorVar(w)).toBe(v));
});
