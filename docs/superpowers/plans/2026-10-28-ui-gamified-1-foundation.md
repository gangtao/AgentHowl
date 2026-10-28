# 游戏化改版 PR ① · 视觉基础 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端的 token / 字体 / 全局组件类换成「暗夜村庄」风格，落地 `RoleToken` 徽记组件，并按设计稿重做导航、登录页、错误态、分享 / 确认对话框与抽屉壳。

**Architecture:** 只动渲染层：`src/styles/` 两个 CSS、`index.html` 字体 link、五个组件 / 页面的 TSX + CSS Module。旧的 `--color-*` token 名保留并映射到新值，所以本 PR 没碰的页面只是换色，不会破版。新增的纯函数（`roleIcons.ts`）与组件（`RoleToken`）给 PR ②–⑤ 复用。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、Vitest + Testing Library（jsdom）、Google Fonts。

**Spec:** `docs/superpowers/specs/2026-10-28-ui-gamification-design.md` §2、§3、§8（PR ①）、§9

## Global Constraints

- 代码注释与文档用中文，标识符英文；Prettier `printWidth: 100`；TS strict + `noUncheckedIndexedAccess`。
- 不新增 npm 依赖；字体只走 Google Fonts link（`display=swap`），不自托管。
- 旧 token 名 `--color-bg / --color-surface / --color-text / --color-accent / --color-accent-2 / --color-divider / --color-neutral-{100..900} / --color-accent-{100..900}` 与 `--ah-wolf / --ah-god / --ah-villager / --ah-line-* / --ah-ok / --ah-warn / --ah-err / --ah-tick-*` 全部保留（值可变）。
- 现有 277 个 vitest 全部保持通过；每个任务结束跑 `npm run check`（lint + tsc + vitest，在 `frontend/` 下）。
- 测试里依赖的可访问名不变：输入框 label「用户名或邮箱 / 用户名 / 邮箱 / 密码 / 验证码」、按钮「登录 / 注册 / 重发验证码」、链接「去登录」「以玩家身份进入」、ShareDialog 的 label 正则 `/观众链接/`、`/上帝视角链接/` 与按钮「进入对局 →」「进入上帝视角 →」。
- 零过滤不变量与本 PR 无关（不碰对局数据），但 `RoleToken` 不得自己判断「该不该显示角色」：传什么渲染什么。

## Review Focus

1. **离线 / 内网打不开 Google Fonts**：三条字体栈都必须以通用族（`serif` / `monospace`）收尾，否则回退成浏览器默认无衬线。→ Task 1 的 `tokens.test.ts` 断言。
2. **头像图片 404**：`RoleToken` 带 `avatar` 时图片加载失败要退回徽记 / 首字，不能留空圆。→ Task 3 测试 `onError` 分支。
3. **ErrorState 的 `detail` 是后端原文，可能很长**：羊皮纸条要 `word-break: break-word`，并且 detail 仍渲染在 DOM 里。→ Task 6 测试传 240 字符 detail。
4. **`Drawer` 新增 `tone` 默认 `parch`**：AgentEditor / ProviderEditor 没改内部，羊皮纸上原来的深色输入框要靠 `.ah-parch .input` 规则换成浅底，否则不可读。→ Task 7 跑两个编辑器的现有测试 + 截图核对。
5. **390px 宽的登录页**：木牌 `width: min(400px, calc(100% - 32px))`，剪影不得撑出横向滚动。→ Task 8 的 390 宽截图。

---

### Task 1: 暗夜村庄 token、字体与全局组件类

**Files:**
- Modify: `frontend/index.html`（`<head>` 加 preconnect + 字体 link）
- Modify: `frontend/src/styles/tokens.css`（整体重写）
- Modify: `frontend/src/styles/global.css`（追加 / 替换组件类）
- Test: `frontend/src/styles/tokens.test.ts`

**Interfaces:**
- Produces: CSS 自定义属性（规格 §2.1 表格里的全部 `--ah-*`，名字逐字一致）；`--font-heading / --font-body / --font-mono`；全局类 `.btn-primary .btn-secondary .btn-ghost .btn-danger .btn-ok .btn-icon .btn-block .input .field .ah-wood .ah-parch .ah-panel .ah-panel-head .ah-plaque .ah-plaque-sub .tag-parch .tag-wood .tag-gold .seg .seg-opt .nav .nav-brand .nav-links .nav-user .table-parch .dialog-backdrop .dialog .dialog-title .dialog-body .dialog-actions .text-muted .ah-rule-x .ah-rule-y`。

- [ ] **Step 1: 写失败的 token 守卫测试**

```ts
// frontend/src/styles/tokens.test.ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const tokens = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const global = readFileSync(new URL("./global.css", import.meta.url), "utf8");

const REQUIRED = [
  "--ah-night", "--ah-night-deep", "--ah-panel", "--ah-panel-edge", "--ah-panel-glass",
  "--ah-wood-hi", "--ah-wood-lo", "--ah-wood-edge", "--ah-wood-shadow",
  "--ah-wood-btn-hi", "--ah-wood-btn-lo", "--ah-wood-btn-edge",
  "--ah-parch", "--ah-parch-hi", "--ah-parch-edge", "--ah-parch-shade", "--ah-parch-ink",
  "--ah-parch-ink-2", "--ah-parch-muted", "--ah-parch-link", "--ah-parch-danger",
  "--ah-fire", "--ah-fire-hi", "--ah-fire-lo", "--ah-fire-edge", "--ah-fire-shadow", "--ah-gold",
  "--ah-text", "--ah-text-bright", "--ah-text-dim", "--ah-text-muted",
  "--ah-wolf", "--ah-wolf-hi", "--ah-wolf-lo", "--ah-wolf-fg", "--ah-wolf-btn-hi", "--ah-wolf-btn-lo",
  "--ah-god", "--ah-god-hi", "--ah-god-lo", "--ah-god-fg",
  "--ah-villager", "--ah-villager-hi", "--ah-villager-lo", "--ah-villager-fg",
  "--ah-dead-bg", "--ah-dead-edge", "--ah-dead-fg", "--ah-ok", "--ah-ok-hi", "--ah-ok-lo",
  "--ah-moon", "--ah-sky-night", "--ah-table-night", "--ah-table-night-edge",
  "--ah-night-text", "--ah-night-muted", "--ah-night-panel", "--ah-night-panel-edge",
  "--ah-night-wood-edge", "--ah-blood-sky",
];
const LEGACY = ["--color-bg", "--color-surface", "--color-text", "--color-accent", "--color-accent-2",
  "--color-divider", "--color-neutral-500", "--color-accent-800", "--ah-line-guard", "--ah-err", "--ah-tick-night"];
const CLASSES = [".btn-primary", ".btn-secondary", ".btn-ghost", ".btn-danger", ".btn-ok", ".input",
  ".ah-wood", ".ah-parch", ".ah-panel", ".ah-panel-head", ".ah-plaque", ".tag-parch", ".tag-wood",
  ".tag-gold", ".seg", ".nav", ".nav-links", ".table-parch", ".dialog"];

describe("tokens.css / global.css（规格 §2）", () => {
  it.each(REQUIRED)("定义了 %s", (name) => expect(tokens).toMatch(new RegExp(`${name}\\s*:`)));
  it.each(LEGACY)("旧名 %s 仍然存在", (name) => expect(tokens).toMatch(new RegExp(`${name}\\s*:`)));
  it("字体栈以通用族收尾", () => {
    expect(tokens).toMatch(/--font-heading:\s*'ZCOOL XiaoWei'[^;]*serif;/);
    expect(tokens).toMatch(/--font-body:\s*'Noto Serif SC'[^;]*serif;/);
    expect(tokens).toMatch(/--font-mono:\s*'IBM Plex Mono'[^;]*monospace;/);
  });
  it.each(CLASSES)("全局类 %s 存在", (cls) => expect(`${tokens}\n${global}`).toContain(cls));
  it("羊皮纸容器内的输入框换浅底", () => expect(global).toMatch(/\.ah-parch \.input\s*\{[^}]*--ah-parch-hi/));
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/styles/tokens.test.ts`
Expected: FAIL，缺 `--ah-night` 等 token。

- [ ] **Step 3: 重写 `tokens.css`**

按规格 §2.1 的表逐行定义 `--ah-*`（值逐字复制）；旧名按 §2.1「旧名映射」指向新值（`--color-neutral-900..100` 取 `#161b28 #1f2434 #2a3042 #3b4257 #5a6276 #8a92a8 #a79f8c #c9bca0 #f1ead6`，`--color-accent-900..100` 取 `#2b1a08 #4a2f10 #6b4a1e #8a5a1e #c9842c #e3a648 #f0b85a #f6d9a6 #fbe7b5`）；`--font-*` 三条按 §2.2；`--space-*`、`--radius-*` 保留，`--shadow-sm/md/lg` 改成 `0 0 0 1px var(--ah-panel-edge)` / `0 10px 30px rgba(0,0,0,.5)` / `0 20px 50px rgba(0,0,0,.6)`。文件顶部注释改为「暗夜村庄 token（来自 Claude Design 项目 AgentHowl 游戏化，见 docs/design/gamified-2026-10-27）」。`body` 背景 `--ah-night`、字色 `--ah-text`、字体 `--font-body`、15px/1.6；`h1–h6` 用 `--font-heading`、`letter-spacing: 0.04em`、`font-weight: 400`。

- [ ] **Step 4: 重写全局组件类**

把原 `tokens.css` 里 `.btn … .dialog-actions` 一段搬到 `global.css` 并按规格 §2.3 表改写（每个类的颜色 / 阴影值逐字取自表格）。新增 `.btn-danger .btn-ok .ah-wood .ah-parch .ah-panel .ah-panel-head .ah-plaque .ah-plaque-sub .tag-parch .tag-wood .tag-gold .table-parch .nav-links .nav-user`；`.nav` 改 56px 木栏；`.btn-primary:disabled` 的虚线态；`.ah-parch .input { background: var(--ah-parch-hi); }`；`.ah-rule-x/-y` 颜色换 `rgba(232,223,202,.16)`。`.radio / .seg` 的描边换 `--ah-wood-edge`，选中换 `--ah-fire`。保留 `ah-pulse / ah-spin` 动画。

- [ ] **Step 5: `index.html` 加字体**

`<head>` 内 `<title>` 之前加：
```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=ZCOOL+XiaoWei&family=Noto+Serif+SC:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

- [ ] **Step 6: 跑测试与全量检查**

Run: `cd frontend && npx vitest run src/styles/tokens.test.ts && npm run check`
Expected: 全部 PASS（旧页面只换色，不改 DOM）。

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/src/styles frontend/src/styles/tokens.test.ts
git commit -m "feat(frontend): 暗夜村庄 token、字体与全局组件类（UI 改版 PR ① / 1）"
```

---

### Task 2: 角色徽记数据 `roleIcons.ts`

**Files:**
- Create: `frontend/src/lib/roleIcons.ts`
- Test: `frontend/src/lib/roleIcons.test.ts`

**Interfaces:**
- Produces:
  - `export type Camp = "wolf" | "god" | "villager"`
  - `export const ROLE_ICON_PATH: Record<RoleType, string>` — 24×24 SVG `d`，七条路径逐字取自 `docs/design/gamified-2026-10-27/AgentHowl-gamified.dc.html` 末尾脚本的 `ICON` 表（狼 `M4 3l5 5h6l5-5…`、预 `M12 5C6.5 5 2 12…`、巫 `M9 2h6v2h-1v5…`、猎 `M12 2a10 10…`、守 `M12 1.5l8.5 3.2…`、痴 `M3 5l5 4 4-6…`、民 `M12 2.5l9.5 8.5…`）。
  - `export function roleCamp(role: RoleType): Camp` — WEREWOLF → wolf；SEER / WITCH / HUNTER / GUARD / IDIOT → god；VILLAGER → villager。
  - `export const CAMP_VARS: Record<Camp, { ring: string; hi: string; lo: string; fg: string }>` — 值是 CSS 变量引用字符串，如 `{ ring: "var(--ah-wolf)", hi: "var(--ah-wolf-hi)", lo: "var(--ah-wolf-lo)", fg: "var(--ah-wolf-fg)" }`。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/lib/roleIcons.test.ts
import { describe, expect, it } from "vitest";
import { CAMP_VARS, ROLE_ICON_PATH, roleCamp } from "./roleIcons";
import type { RoleType } from "../engine/types";

const ROLES: RoleType[] = ["WEREWOLF", "VILLAGER", "SEER", "WITCH", "HUNTER", "GUARD", "IDIOT"];

describe("roleIcons（设计稿 2a）", () => {
  it.each(ROLES)("%s 有以 M 开头的路径", (r) => expect(ROLE_ICON_PATH[r]).toMatch(/^M[\d.]/));
  it("七条路径互不相同", () => expect(new Set(Object.values(ROLE_ICON_PATH)).size).toBe(7));
  it("阵营映射", () => {
    expect(roleCamp("WEREWOLF")).toBe("wolf");
    expect(roleCamp("VILLAGER")).toBe("villager");
    for (const r of ["SEER", "WITCH", "HUNTER", "GUARD", "IDIOT"] as const) expect(roleCamp(r)).toBe("god");
  });
  it("阵营色是 CSS 变量引用", () => {
    expect(CAMP_VARS.wolf.ring).toBe("var(--ah-wolf)");
    expect(CAMP_VARS.god.fg).toBe("var(--ah-god-fg)");
    expect(CAMP_VARS.villager.lo).toBe("var(--ah-villager-lo)");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/roleIcons.test.ts`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `roleIcons.ts`**

按 Interfaces 定义三个导出；文件头注释说明路径来源与 24 网格。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/lib/roleIcons.test.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/roleIcons.ts frontend/src/lib/roleIcons.test.ts
git commit -m "feat(frontend): 七枚角色徽记路径与阵营映射 roleIcons（UI 改版 PR ① / 2）"
```

---

### Task 3: `RoleToken` 组件

**Files:**
- Create: `frontend/src/components/RoleToken/RoleToken.tsx`
- Create: `frontend/src/components/RoleToken/RoleToken.module.css`
- Test: `frontend/src/components/RoleToken/RoleToken.test.tsx`

**Interfaces:**
- Consumes: Task 2 的 `ROLE_ICON_PATH / roleCamp / CAMP_VARS`；`ROLE_ZH`（`src/engine/phases.ts`）；`avatarUrl`（`src/api/avatars.ts`）。
- Produces:
  ```ts
  export type RoleTokenState = "known" | "unknown" | "dead";
  export type RoleTokenVariant = "seat" | "card" | "parch" | "outline";
  export interface RoleTokenProps {
    role: RoleType | null;        // known 时必有；null 一律按 unknown 渲染
    state?: RoleTokenState;       // 缺省 role === null ? "unknown" : "known"
    variant?: RoleTokenVariant;   // 缺省 "seat"
    size: number;                 // seat/parch/outline 为直径；card 为宽，高 = size * 4 / 3
    initial?: string;             // unknown 时显示的首字；缺省「?」
    avatar?: string | null;       // 头像 id；known/unknown 且非 dead 时圆内渲染 <img>，徽记缩成右下角 size*0.3 的小章
    className?: string;
    style?: CSSProperties;
  }
  export default function RoleToken(props: RoleTokenProps): JSX.Element;
  ```
  - 根节点 `<span role="img" aria-label>`：known → `ROLE_ZH[role]`；unknown → `身份未知`；dead → `已出局`。
  - 根节点 `data-variant` / `data-state` / `data-camp`（known 时）属性，CSS 以此选择。
  - 颜色全部通过内联 CSS 变量 `--rt-ring / --rt-hi / --rt-lo / --rt-fg` 注入（来自 `CAMP_VARS`），模块 CSS 只引用这四个变量；`parch` 变体底 `--ah-parch`、环 `--ah-parch-edge`、徽记色 `--rt-ring`；`outline` 透明底、`1.5px` `--rt-ring` 环；unknown 底 `linear-gradient(180deg, var(--ah-wood-hi), var(--ah-wood-lo))`、环 `--ah-wood-btn-edge`、字 `--ah-text-dim`、`--font-heading`；dead 底 `--ah-dead-bg`、`2px dashed var(--ah-dead-edge)`、字 `--ah-dead-fg`。
  - 徽记 `<svg viewBox="0 0 24 24" aria-hidden>` 宽高 = `size * 0.5`（card 为 `size * 0.48`），`<path d fill="currentColor" fill-rule="evenodd">`。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/RoleToken/RoleToken.test.tsx
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
    expect(container.querySelectorAll("svg")).toHaveLength(1); // 小章
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelectorAll("svg")).toHaveLength(1); // 退回居中徽记
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/RoleToken`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `RoleToken.tsx` 与 `RoleToken.module.css`**

`useState(broken)` 处理 `onError`（同 `Avatar.tsx` 的做法）；`avatar` 存在且未 broken 且 state !== "dead" 时渲染 `<img className={styles.avatar} src={avatarUrl(avatar)} alt="">` + 右下角 `<span className={styles.stamp}>` 包小 svg；否则按 state 渲染居中内容。CSS 用 `display:grid; place-items:center; position:relative; border-radius:50%`（card 变体 `border-radius: 6px`），背景 `radial-gradient(circle at 35% 30%, var(--rt-hi), var(--rt-lo))`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/RoleToken && npm run check`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RoleToken
git commit -m "feat(frontend): RoleToken 角色徽记组件（UI 改版 PR ① / 3）"
```

---

### Task 4: 木栏导航

**Files:**
- Modify: `frontend/src/App.tsx:138-175`（`<nav>` 段）
- Test: `frontend/src/App.test.tsx`（追加一组用例）

**Interfaces:**
- Consumes: Task 1 的 `.nav .nav-brand .nav-links .nav-user .btn-ghost`。

- [ ] **Step 1: 写失败测试**

在 `App.test.tsx` 追加：

```tsx
describe("App 导航（设计稿 1c 木栏）", () => {
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = ""; });
  it("登录态：当前路由高亮、右侧显示「用户名 · 离村」", async () => {
    const me = { user_id: "u", username: "alice", email: "a@x", role: "user", status: "active", email_verified: true, created_at: "t" };
    useAuth.setState({ user: me as never, status: "authed" });
    window.location.hash = "#/history";
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/auth/me") ? me : []), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<App />);
    expect(screen.getByRole("link", { name: "历史对局" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "新的一局" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "离村" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL，找不到按钮「离村」。

- [ ] **Step 3: 改写 `<nav>` 段**

结构：`<nav className="nav"><span className="nav-brand">AgentHowl</span><div className="nav-links">{NAV 链接…}{admin 时追加 <a href="#/admin">用户</a>}</div><div className="nav-user">{user ? <><span>{user.username}</span><span aria-hidden>·</span><button className="btn btn-ghost">离村</button></> : <a href="#/login">登录</a>}</div></nav>`。去掉现有的内联 `style`；admin 不再显示 `· admin` 后缀（身份在「用户」链接的出现与否上体现）。外层 grid 行高改 `56px minmax(0,1fr)`。

- [ ] **Step 4: 跑测试与检查**

Run: `cd frontend && npx vitest run src/App.test.tsx && npm run check`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): 木栏导航与「离村」（UI 改版 PR ① / 4）"
```

---

### Task 5: 登录页「村口木牌」

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx:98-150`（render 段）
- Modify: `frontend/src/pages/LoginPage.module.css`（重写）
- Test: `frontend/src/pages/LoginPage.test.tsx`（追加）

**Interfaces:**
- Consumes: Task 1 的 `.input .btn-primary .btn-ghost .field`、`--ah-moon` 等 token。
- Produces: 页面结构 `.page > .sky(.moon) + .scene(.hills .ground .houseL .houseR .lamp) + .hero(.brand .tagline .posts) + form.plaque`。

- [ ] **Step 1: 写失败测试**

```tsx
it.each([
  ["login", "入村", "登录"],
  ["register", "落户", "注册"],
  ["verify", "对暗号", "验证"],
] as const)("%s 模式：木牌标题「%s」，主按钮「%s」", (mode, heading, button) => {
  render(<LoginPage mode={mode} />);
  expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: button })).toBeInTheDocument();
  expect(screen.getByText("AgentHowl")).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx`
Expected: FAIL，heading「入村」不存在。

- [ ] **Step 3: 改写 render 与 CSS**

- `title` 改为 heading 文案映射 `{login:"入村", register:"落户", verify:"对暗号"}`，按钮文案映射 `{login:"登录", register:"注册", verify:"验证"}`，`<h2 className={styles.title}>` 渲染 heading（视觉上字间距 `0.4em`，用 CSS `letter-spacing` 而不是在字符串里插空格，这样可访问名保持「入村」）。
- 布局：`.page` 全屏 `radial-gradient(ellipse at 50% 0%, #1c2440 0%, var(--ah-night) 60%)`、`overflow:auto`、`display:grid; place-items:start center; padding-top: 72px`；`.moon` 160px 圆（`--ah-moon`，`0 0 80px 30px rgba(241,234,214,.18)`，`position:absolute; top:90px`）；`.scene` 绝对定位在底部 260px：两片 `radial-gradient` 黑山丘、120px `--ah-night-deep` 地面、左右两组 `#0a0d14` 方块房子（尺寸按设计稿 1b：左 40×70 / 60×110 / 30×50，右 50×60 / 36×140 / 70×90）、10px 篝火色窗灯带光晕；`.brand` heading 54px 字距 4px `--ah-text-bright` + `text-shadow: 0 0 30px rgba(241,234,214,.3)`；`.tagline`「狼 人 嚎 叫 · AI 狼 人 杀」13px 字距 6px `--ah-text-muted`；`.posts` 两根 2px×28px `--ah-wood-edge` 木柱间距 40px；`.plaque` = 木牌（`.ah-wood` 的样式内联到模块：木纹渐变、`2px solid var(--ah-wood-edge)`、radius 8、`0 20px 50px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,220,160,.15)`），`width: min(400px, calc(100% - 32px))`，`padding: 26px 30px 24px`；label 12px `--ah-text-dim`；`.error` 羊皮纸底 `--ah-parch` 字 `--ah-parch-danger`；`.notice` 羊皮纸底字 `--ah-parch-ink`；`.links` 两端对齐、12px、`--ah-fire`。
- 页面所有元素 `z-index` 保证表单在剪影之上。

- [ ] **Step 4: 跑测试与检查**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx src/App.test.tsx && npm run check`
Expected: PASS（原有 5 个用例靠 label 与按钮名不变而继续通过）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.module.css frontend/src/pages/LoginPage.test.tsx
git commit -m "feat(frontend): 登录页「村口木牌」（UI 改版 PR ① / 5）"
```

---

### Task 6: 错误态「这局已随风散去 / 村口有人守着」

**Files:**
- Modify: `frontend/src/components/ErrorState/ErrorState.tsx`（重写 render）
- Modify: `frontend/src/components/ErrorState/ErrorState.module.css`（重写）
- Test: `frontend/src/components/ErrorState/ErrorState.test.tsx`（新建）

**Interfaces:**
- Consumes: `ErrorKind`（不变）、Task 1 的按钮类与 token。
- Produces: 每种 kind 的文案（下表），`role` 属性不变（4409 / reconnecting 为 `status`，其余 `alert`）。

| kind | 插画 | code | title | desc | 按钮 |
|---|---|---|---|---|---|
| `4404` | 月亮 70px | `4404` | 这局已随风散去 | 对局不存在，或已被建局者删除。检查链接，或回村志看看别的局。 | `.btn-secondary`「回到村志」`#/history` |
| `auth` | 木牌「?」64×84 | `4401 / 4403` | 村口有人守着 | 这局不对外公开。请登录，或使用建局者给你的分享链接。 | `.btn-primary`「去登录」`#/login` |
| `locked` | 木牌「?」 | `403` | 你还坐在桌上 | 你已入座这局，对局结束前不能查看全局；终局后自动恢复。 | `playerHref` 时 `.btn-primary`「以玩家身份进入」 |
| `4409` | 篝火光球 + 脉冲 | `4409` | 篝火未燃 · 等待开局 | 对局尚未开始 · 每 2 秒重试{ · 第 N 次} | 无 |
| `reconnecting` | 篝火光球 + 脉冲 | — | 重连中 | 连接已断开，正在补发事件{（第 N 次）}。指数退避 1s → 8s。 | 无 |
| `error` | 木牌「!」 | — | 载入对局失败 | 请稍后重试；若持续失败请检查服务端状态。 | `.btn-secondary`「回到村志」`#/history` |

`detail` 有则渲染为羊皮纸条 `.detail`（mono 11.5px、`word-break: break-word`、`max-width: 420px`）。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/ErrorState/ErrorState.test.tsx
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
    expect(screen.getByRole("link", { name: /以玩家身份进入/ })).toHaveAttribute("href", "#/g/g_1?token=t");
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/ErrorState`
Expected: FAIL，「这局已随风散去」不存在。

- [ ] **Step 3: 重写组件与 CSS**

抽一个内部 `Shell({ role, art, code, title, desc, detail, action })` 渲染统一结构 `.root > .box > (.art, .code, .title, .desc, .detail?, action?)`，六个 kind 各填一组值。`.root` 背景 `radial-gradient(ellipse at 50% 30%, #1a1f30, var(--ah-night) 70%)`；`.title` `--font-heading` 30px `--ah-text-bright`；`.code` `--font-mono` 12px `--ah-parch-muted`；`.desc` 13px/1.7 `--ah-text-muted`；`.artMoon` 70px `--ah-moon` 光晕 `0 0 40px 14px rgba(241,234,214,.15)`；`.artCard` 64×84 木牌 radius 5 heading 30px `--ah-parch-muted`；`.artFire` 48px 篝火径向渐变 + `ah-pulse` 动画。

- [ ] **Step 4: 跑测试与检查**

Run: `cd frontend && npx vitest run src/components/ErrorState src/pages/GamePage.test.tsx && npm run check`
Expected: PASS（GamePage.test 用到的「去登录」「以玩家身份进入」不变）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ErrorState
git commit -m "feat(frontend): 错误态改为村口木牌文案（UI 改版 PR ① / 6）"
```

---

### Task 7: 对话框与抽屉壳

**Files:**
- Modify: `frontend/src/components/ShareDialog/ShareDialog.tsx`、`ShareDialog.module.css`
- Modify: `frontend/src/components/ConfirmDialog/ConfirmDialog.tsx`、`ConfirmDialog.module.css`
- Modify: `frontend/src/components/Drawer/Drawer.tsx`、`Drawer.module.css`
- Modify: `frontend/src/components/AgentEditor/AgentEditor.tsx:231-235`、`frontend/src/components/ProviderEditor/ProviderEditor.tsx:149-152`（只加 `kicker`）
- Test: `frontend/src/components/Drawer/Drawer.test.tsx`（新建）、`ShareDialog.test.tsx`（追加一条）

**Interfaces:**
- Produces: `DrawerProps` 新增 `tone?: "wood" | "parch"`（缺省 `"parch"`）与 `kicker?: string`；根面板带 `data-tone`。
- ShareDialog 标题统一为「传 · 分享对局」（`aria-label` 同），说明行「观众链接 · 仅公开信息，可匿名打开 · 不含任何身份」放在 `.dialog-body` 顶部；其余 label / 按钮文案不变。

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/Drawer/Drawer.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

describe("Drawer 壳（设计稿 4e）", () => {
  it("缺省羊皮纸、渲染 kicker 与 idTag", () => {
    render(<Drawer title="编辑 Agent" kicker="招 募 告 示" idTag="a_1" onClose={vi.fn()} footer={<span>foot</span>}>body</Drawer>);
    const dialog = screen.getByRole("dialog", { name: "编辑 Agent" });
    expect(dialog).toHaveAttribute("data-tone", "parch");
    expect(screen.getByText("招 募 告 示")).toBeInTheDocument();
    expect(screen.getByText("a_1")).toBeInTheDocument();
  });
  it("tone=wood 透传；Esc 关闭", () => {
    const onClose = vi.fn();
    render(<Drawer title="t" tone="wood" onClose={onClose} footer={null}>b</Drawer>);
    expect(screen.getByRole("dialog")).toHaveAttribute("data-tone", "wood");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

`ShareDialog.test.tsx` 追加：
```tsx
it("标题统一为「传 · 分享对局」", () => {
  render(<ShareDialog gameId="g_1" gmToken="G" shareToken="S" onEnter={vi.fn()} onLater={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "传 · 分享对局" })).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Drawer src/components/ShareDialog`
Expected: FAIL（`data-tone` 缺失；标题不符）。

- [ ] **Step 3: 实现**

- `Drawer.tsx`：解构 `tone = "parch"`, `kicker`；面板加 `data-tone={tone}`、`className={`${styles.panel} ${tone === "parch" ? "ah-parch" : ""}`}`（这样内部 `.input` 自动换浅底）；头部在标题上方渲染 `{kicker && <span className={styles.kicker}>{kicker}</span>}`；左侧 `<span className={styles.spine} aria-hidden />`。CSS：`.panel[data-tone="parch"]` 底 `--ah-parch` 字 `--ah-parch-ink`、`box-shadow: -30px 0 80px rgba(0,0,0,.7)`；`.spine` 14px 宽 `linear-gradient(90deg, var(--ah-wood-btn-hi), var(--ah-wood-hi))`；`.head` `padding: 26px 32px 14px 40px; border-bottom: 2px solid var(--ah-wood-hi)`；`.kicker` 11px 字距 3px `--ah-parch-muted`；`.title` `--font-heading` 30px；`.foot` 底 `#e2d4b6`、`border-top: 2px solid var(--ah-wood-hi)`；`.panel[data-tone="wood"]` 木纹渐变、字 `--ah-text`、头尾分隔线 `--ah-wood-edge`；`.close` 20px `--ah-parch-muted`；`.backdrop` `rgba(6,8,13,.55)`。idTag 的 `tag-neutral` 换 `tag-wood`。
- `AgentEditor.tsx` 的 `<Drawer` 加 `kicker="招 募 告 示"`；`ProviderEditor.tsx` 加 `kicker="配 方"`。
- `ShareDialog.tsx`：标题与 `aria-label` 改「传 · 分享对局」；body 顶部加 `<p className={styles.lead}>观众链接 · 仅公开信息，可匿名打开 · 不含任何身份</p>`；`.warn` 改羊皮纸条（`--ah-parch` 底、`--ah-parch-ink-2` 字、⚠ 用 `--ah-parch-danger`）；`.mono` 用 `--font-mono`。
- `ConfirmDialog.tsx`：`danger` 时按钮类改 `btn btn-danger`（删除 `styles.danger`，`ConfirmDialog.module.css` 删空后移除该文件与 import）。

- [ ] **Step 4: 跑测试与检查**

Run: `cd frontend && npx vitest run src/components/Drawer src/components/ShareDialog src/components/AgentEditor src/components/ProviderEditor && npm run check`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ShareDialog frontend/src/components/ConfirmDialog frontend/src/components/Drawer frontend/src/components/AgentEditor/AgentEditor.tsx frontend/src/components/ProviderEditor/ProviderEditor.tsx
git commit -m "feat(frontend): 木牌对话框与羊皮纸抽屉壳（UI 改版 PR ① / 7）"
```

---

### Task 8: 视觉核对、截图与 PR

**Files:**
- Create: `docs/design/ui-gamified-2026-10-28/01-auth-login.png`、`01-auth-register.png`、`01-auth-verify.png`、`01-auth-login-390.png`、`09-error-not-found.png`、`09-error-forbidden.png`、`06-history-share-dialog.png`、`07-agents-editor.png`、`README.md`

- [ ] **Step 1: 全量检查**

Run: `cd frontend && npm run check`
Expected: lint 0 warning、tsc 无错、vitest 全绿（应为 277 + 本 PR 新增约 25 条）。

- [ ] **Step 2: 起开发服务并截图**

Run: `cd frontend && npm run dev -- --port 5173`（后台），用 Playwright 1440×900 打开 `http://localhost:5173/#/login`、`#/register`、`#/verify`、`#/g/g_nonexistent`（匿名 → 4404 或 auth，取决于后端是否在跑；两者都截）；390×844 截 `#/login`；若本地后端在跑且有 `e2e_player` 账号，再登录后截 `#/history` 的分享对话框与 `#/agents` 的编辑器抽屉。文件按上表命名存入 `docs/design/ui-gamified-2026-10-28/`，README 一张表列出文件与对应设计稿编号（1b / 4f / 4e）。
Expected: 登录页木牌、月亮、剪影与设计稿 1b 一致；390 宽无横向滚动（`document.documentElement.scrollWidth === 390`）；羊皮纸抽屉里的输入框是浅底。

- [ ] **Step 3: 对照修正**

截图与 `docs/design/gamified-2026-10-27/options/{1b,4f,4e}.html` 并排看；颜色 / 间距偏差就地改 CSS，再跑 `npm run check`。

- [ ] **Step 4: Commit 并开 PR**

```bash
git add docs/design/ui-gamified-2026-10-28
git commit -m "docs(design): UI 改版 PR ① 截图基线"
git push -u origin feat/ui-gamified-1-foundation
gh pr create --title "feat(frontend): 游戏化改版 PR ① · 视觉基础 / 登录 / 错误态 / 对话框" --body "<按模板：改动范围、截图、规格章节、验收命令>"
```

Expected: PR 打开；描述末尾带 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`。
