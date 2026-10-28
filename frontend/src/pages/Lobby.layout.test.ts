// @vitest-environment node
// 大厅布局守卫（评审 PR ③）：900–1440px 之间要有一档中间断点，否则第 2 步 360 + 300 + 间距把圆桌挤到 250px 以下。
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./Lobby.module.css", import.meta.url), "utf8");

describe("Lobby.module.css 中间断点", () => {
  it("有 900 < max-width < 1440 的媒体查询，且在其中改写第 2 步列与第 1 步剧本牌列", () => {
    const widths = [...css.matchAll(/@media \(max-width:\s*(\d+)px\)/g)].map((m) => Number(m[1]));
    const mid = widths.find((w) => w > 900 && w < 1440);
    expect(mid, `断点: ${widths.join(", ")}`).toBeDefined();
    const block = css.slice(css.indexOf(`@media (max-width: ${mid}px)`));
    expect(block).toMatch(/\.page\[data-step='2'\]\s*{[^}]*grid-template-columns/);
    expect(block).toMatch(/\.presets\s*{[^}]*grid-template-columns:\s*1fr/);
  });
});
