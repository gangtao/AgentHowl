// @vitest-environment node
// 卡牌皮肤 CSS 守卫（评审 PR ⑤）：夜间牌背规则不得压过选中 / 本人的篝火边；卡牌模式下桌子区给阶段木牌让位并可滚动。
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const cards = readFileSync(new URL("./CardBoard.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../../pages/GamePage.module.css", import.meta.url), "utf8");

describe("CardBoard.module.css", () => {
  it("选中 / 本人 / 发言 / 领先的边框规则写在夜间牌背规则之后且特异性不低于它", () => {
    const night = cards.indexOf(".root[data-night] .piece[data-face='back']");
    expect(night).toBeGreaterThan(-1);
    for (const sel of [
      ".root .grid .piece[data-selected]",
      ".root .grid .piece[data-me]",
      ".root .grid .piece[data-speaking]",
      ".root .grid .piece[data-leader]",
    ]) {
      expect(cards.indexOf(sel), sel).toBeGreaterThan(night);
    }
    expect(cards).toMatch(/\.root \.grid \.piece\[data-selected\][^{]*{[^}]*opacity:\s*1/);
  });
  it("准星 / 水晶（data-orb）在卡牌模式下缩到 140px 以内（issue #176）", () => {
    expect(cards).toMatch(/\.center > \[data-orb\]\s*{[^}]*width:\s*1[0-4]\dpx/);
  });
  it("桌心容器不再固定 min-height，桌心内容改为跟随文档流", () => {
    expect(cards).not.toMatch(/\.center\s*{[^}]*min-height/);
    expect(cards).toMatch(/\.center > \*\s*{[^}]*position:\s*static/);
  });
});

describe("GamePage.module.css 卡牌模式", () => {
  it("tableArea[data-table='cards'] 顶部给阶段木牌让位并允许纵向滚动", () => {
    expect(page).toMatch(/\.tableArea\[data-table='cards'\]\s*{[^}]*padding-top:\s*7\dpx/);
    expect(page).toMatch(/\.tableArea\[data-table='cards'\]\s*{[^}]*overflow-y:\s*auto/);
  });
});
