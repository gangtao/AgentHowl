// @vitest-environment node
// token / 全局类守卫（规格 §2）：防止后续 PR 改名时悄悄丢掉设计系统约定的变量与类。
// 用 node:fs 直接读源文件：vitest 默认把 .css（含 ?raw）处理成空模块，import 拿不到文本。
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const tokens = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const global = readFileSync(new URL("./global.css", import.meta.url), "utf8");

const REQUIRED = [
  "--ah-night",
  "--ah-night-deep",
  "--ah-panel",
  "--ah-panel-edge",
  "--ah-panel-glass",
  "--ah-wood-hi",
  "--ah-wood-lo",
  "--ah-wood-edge",
  "--ah-wood-shadow",
  "--ah-wood-btn-hi",
  "--ah-wood-btn-lo",
  "--ah-wood-btn-edge",
  "--ah-parch",
  "--ah-parch-hi",
  "--ah-parch-edge",
  "--ah-parch-shade",
  "--ah-parch-ink",
  "--ah-parch-ink-2",
  "--ah-parch-muted",
  "--ah-parch-link",
  "--ah-parch-danger",
  "--ah-fire",
  "--ah-fire-hi",
  "--ah-fire-lo",
  "--ah-fire-edge",
  "--ah-fire-shadow",
  "--ah-gold",
  "--ah-text",
  "--ah-text-bright",
  "--ah-text-dim",
  "--ah-text-muted",
  "--ah-wolf",
  "--ah-wolf-hi",
  "--ah-wolf-lo",
  "--ah-wolf-fg",
  "--ah-wolf-btn-hi",
  "--ah-wolf-btn-lo",
  "--ah-god",
  "--ah-god-hi",
  "--ah-god-lo",
  "--ah-god-fg",
  "--ah-villager",
  "--ah-villager-hi",
  "--ah-villager-lo",
  "--ah-villager-fg",
  "--ah-dead-bg",
  "--ah-dead-edge",
  "--ah-dead-fg",
  "--ah-ok",
  "--ah-ok-hi",
  "--ah-ok-lo",
  "--ah-moon",
  "--ah-sky-night",
  "--ah-table-night",
  "--ah-table-night-edge",
  "--ah-night-text",
  "--ah-night-muted",
  "--ah-night-panel",
  "--ah-night-panel-edge",
  "--ah-night-wood-edge",
  "--ah-blood-sky",
];
const LEGACY = [
  "--color-bg",
  "--color-surface",
  "--color-text",
  "--color-accent",
  "--color-accent-2",
  "--color-divider",
  "--color-neutral-500",
  "--color-accent-800",
  "--ah-line-guard",
  "--ah-err",
  "--ah-tick-night",
];
const CLASSES = [
  ".btn-primary",
  ".btn-secondary",
  ".btn-ghost",
  ".btn-danger",
  ".btn-ok",
  ".input",
  ".ah-wood",
  ".ah-parch",
  ".ah-panel",
  ".ah-panel-head",
  ".ah-plaque",
  ".tag-parch",
  ".tag-wood",
  ".tag-gold",
  ".seg",
  ".nav",
  ".nav-links",
  ".table-parch",
  ".dialog",
];

describe("tokens.css / global.css（规格 §2）", () => {
  it.each(REQUIRED)("定义了 %s", (name) => expect(tokens).toMatch(new RegExp(`${name}\\s*:`)));
  it.each(LEGACY)("旧名 %s 仍然存在", (name) => expect(tokens).toMatch(new RegExp(`${name}\\s*:`)));
  it("字体栈以通用族收尾", () => {
    expect(tokens).toMatch(/--font-heading:\s*'ZCOOL XiaoWei'[^;]*serif;/);
    expect(tokens).toMatch(/--font-body:\s*'Noto Serif SC'[^;]*serif;/);
    expect(tokens).toMatch(/--font-mono:\s*'IBM Plex Mono'[^;]*monospace;/);
  });
  it.each(CLASSES)("全局类 %s 存在", (cls) => expect(`${tokens}\n${global}`).toContain(cls));
  it("羊皮纸容器内的输入框换浅底", () =>
    expect(global).toMatch(/\.ah-parch \.input\s*\{[^}]*--ah-parch-hi/));
  it.each([
    ".ah-parch .card-kicker",
    ".ah-parch .seg-opt",
    ".ah-parch .seg",
    ".ah-parch .btn-ghost",
  ])("羊皮纸容器内覆盖全局类前景色：%s", (sel) => expect(global).toContain(`${sel} {`));
});
