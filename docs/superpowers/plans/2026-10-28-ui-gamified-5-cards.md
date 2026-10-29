# UI 游戏化 PR ⑤ 圆桌 / 卡牌皮肤切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对局页桌子区可在「圆桌」与「卡牌」两种皮肤间切换并记忆（localStorage），卡牌皮肤用同一份 `seatModel` / `stageContent` 渲染牌阵、状态与横向发言条；大厅与结算页不受影响。

**Architecture:** 新增 zustand `usePrefs`（`tableStyle`，读写 `localStorage["agenthowl.tableStyle"]`，try/catch，缺省 `round`）；新组件 `CardBoard` 与 `GameTable` 同一份 props（`GameTableProps`），`GamePage` 按偏好二选一；`SpeechBubble` 加 `layout="strip"` 变体（牌阵下方横向羊皮纸）；顶栏 `PhaseBar.extra` 里加 `TableStyleToggle`（「桌面：圆桌 ▾」下拉）。座位按钮沿用 `data-seat / data-selectable / data-selected / aria-label` 契约，e2e 与 HUD 不变。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、zustand、Vitest + Testing Library；复用 `lib/seatModel`（`SeatModel`：seat / name / role / alive / me / speaking / dim / selectable / selected / badges）、`lib/roleIcons`（`ROLE_ICON_PATH`、`roleCamp`、`CAMP_VARS`）、`RoleToken`、`TableCenter`、`SpeechBubble`。

**Spec:** `docs/superpowers/specs/2026-10-28-ui-gamification-design.md` §7（卡牌皮肤）、§8（PR ⑤：分支 `feat/ui-gamified-5-cards`，验证 `npm run check` + `play.mjs` 切卡牌跑四种状态 + 截图）、§9（`prefs` store 测试）、§10（卡牌只做桌子区）；设计稿 `docs/design/gamified-2026-10-27/options/{6a,6b,7e}.html`。

## Global Constraints

- 分支 `feat/ui-gamified-5-cards`，从 `main`（c736c5f）切出；`cd frontend && npm run check` 必须绿，用 `$?` 判定。
- 零过滤：`CardBoard` 只收 `seats: SeatModel[]`、`center`、`speech`、`avatars`、`night`，不收 viewer；「上帝回放灰牌仍显身份」只因为 `SeatModel.role` 非 null，组件不判断谁在看。
- `lib/seatModel.ts`、`lib/stageContent.ts`、`GameTable` 的 DOM 契约（`button[data-seat]`、`[data-selectable]`、`[data-selected]`、`aria-label="{seat}号 {name} 存活|出局 …"`）不变；`CardBoard` 的座位按钮沿用同一契约，`frontend/e2e/play.mjs` 两种皮肤都能跑。
- 偏好键 `localStorage["agenthowl.tableStyle"]`，值 `"round" | "cards"`，读写都 try/catch，缺省与非法值 → `round`。
- 文案 / 尺寸（规格 §7 原文）：顶栏「桌面：圆桌 ▾」/「桌面：卡牌 ▾」；牌阵 `repeat(4, 116px)`、牌 140px 高 `radius 7`、内嵌 1px 浅边框（`inset 6px`、`rgba(255,255,255,.14)`）、左上羊皮纸座位号签；已知身份正面 = 阵营渐变 + 46px 徽记 + 角色名；未知牌背 = 木纹 + 44px 首字圆 + 「身份未翻」；出局灰牌 = `#141821` + ✕ + 「出局」，角色已知时仍显徽记 + 角色名 + 右上 ✕ 章；发言者 `translateY(-8px)` + 金边 + `0 0 28px rgba(240,192,96,.55)`；本人 `--ah-fire` 边；夜间 `dim` 牌 `opacity .55`，目标牌（`badges.tag`）抬起泛红 + 底部红签；票数挂牌底篝火签、票数最高者金边；候选人右上金签「警」；警长 ★。
- 发言条：牌阵下方横向羊皮纸 = 左 44px 徽记（`RoleToken` seat 变体，size 44）+ 头行「{seat}号 {name} · 发言中」+ 倒计时 + 正文 + 进度条；`SpeechBubble` 的计时 / 占位 / 配音逻辑不变。
- 大厅第 2 步（`SeatRing`）与结算页（`GameOverScreen`）不读偏好。
- 中文注释 / 英文标识符；纯函数放 `src/lib/`；CSS Module 组合器后的全局类必须 `:global()`。

## Review Focus

1. 9 人局（非 4 的倍数）：牌阵最后一行 1 张牌，不拉伸、不居中错位；12 人正好 3 行 —— Task 3 测试（渲染 9 / 12 张 `button[data-seat]`）。
2. 投票票数 2.5（警长 1.5 票）：篝火签原样显示「2.5」，且只有票数最高者金边，并列时都金边 —— Task 3 测试。
3. 上帝回放里的出局牌：`role` 非 null → 徽记 + 角色名 + ✕ 章；玩家视角 `role` null → 「出局」灰牌 —— Task 3 测试。
4. `localStorage` 里是坏值（`"triangle"`）或抛异常（隐私模式）：偏好回退 `round`，写入失败不崩 —— Task 1 测试。
5. 切皮肤时正在选目标（`selectedTarget` 非 null）：卡牌上该座位 `data-selected`、可选座位可点并回调同一 `onSelectSeat`；再切回圆桌仍保持 —— Task 4 GamePage 测试。

---

### Task 1: `usePrefs` 偏好 store

**Files:**
- Create: `frontend/src/store/prefs.ts`
- Test: `frontend/src/store/prefs.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type TableStyle = "round" | "cards";
  export const TABLE_STYLE_KEY = "agenthowl.tableStyle";
  export function readTableStyle(): TableStyle;        // 导出便于测试；非 "round"/"cards" → "round"
  interface PrefsState { tableStyle: TableStyle; setTableStyle(v: TableStyle): void }
  export const usePrefs: UseBoundStore<StoreApi<PrefsState>>;
  ```

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/store/prefs.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { TABLE_STYLE_KEY, readTableStyle, usePrefs } from "./prefs";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  usePrefs.setState({ tableStyle: "round" });
});

describe("prefs.tableStyle（规格 §7）", () => {
  it("缺省 round；写入后持久化到 localStorage", () => {
    expect(readTableStyle()).toBe("round");
    usePrefs.getState().setTableStyle("cards");
    expect(usePrefs.getState().tableStyle).toBe("cards");
    expect(localStorage.getItem(TABLE_STYLE_KEY)).toBe("cards");
    expect(readTableStyle()).toBe("cards");
  });
  it("坏值回退 round", () => {
    localStorage.setItem(TABLE_STYLE_KEY, "triangle");
    expect(readTableStyle()).toBe("round");
  });
  it("localStorage 抛异常：读回退 round，写不崩且内存态仍更新", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    expect(readTableStyle()).toBe("round");
    expect(() => usePrefs.getState().setTableStyle("cards")).not.toThrow();
    expect(usePrefs.getState().tableStyle).toBe("cards");
  });
});
```

- [ ] **Step 2: Run → FAIL（模块不存在）** — `cd frontend && npx vitest run src/store/prefs.test.ts`
- [ ] **Step 3: Implement** 按 `store/voice.ts` 的 `readEnabled / setEnabled` 模式。
- [ ] **Step 4: Run → PASS 3/3；Step 5: Commit**

```bash
git add frontend/src/store/prefs.ts frontend/src/store/prefs.test.ts
git commit -m "feat(frontend): usePrefs 桌面皮肤偏好（localStorage，缺省圆桌）"
```

---

### Task 2: `SpeechBubble` 横向发言条变体

**Files:**
- Modify: `frontend/src/components/GameTable/SpeechBubble.tsx`（加 `layout?: "bubble" | "strip"`、`role?: RoleType | null`、`avatar?: string | null`）
- Modify: `frontend/src/components/GameTable/GameTable.module.css`（`.strip*` 类）
- Test: `frontend/src/components/GameTable/SpeechBubble.test.tsx`（追加）

**Interfaces:**
- Produces: `SpeechBubbleProps` 新增 `layout?: "bubble" | "strip"`（缺省 `"bubble"`，行为不变）、`role?: RoleType | null`、`avatar?: string | null`（strip 左侧 44px `RoleToken`）。`layout="strip"` 时根 `<div class={styles.strip} data-kind role="status" aria-label 同前>`，不读 `anchor`、无箭头，不设 left/top；内部 `.stripToken`（`RoleToken role variant="seat" size={44} initial={name[0]} avatar`）+ `.stripMain`（头行 / 正文 / 配音 / 进度条复用现有类）。

- [ ] **Step 1: Write the failing test**

```tsx
it("layout=strip：横向羊皮纸，不定位、带 44px 徽记，头行与倒计时同前", () => {
  render(
    <SpeechBubble item={null} seat={3} name="狐语" kind="speech" deadline={100} limit={120}
      now={() => 71} voicing={false} mine anchor={{ x: 50, y: 9 }} layout="strip" role="WEREWOLF" />,
  );
  const el = screen.getByRole("status", { name: "3号 狐语 发言中" });
  expect(el.style.left).toBe("");
  expect(screen.getByRole("img", { name: "狼人" })).toBeInTheDocument();
  expect(screen.getByText("29s")).toBeInTheDocument();
  expect(screen.getByText("轮到你发言…")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS（含 GameTable.test）**

CSS：`.strip { display:flex; gap:14px; align-items:flex-start; padding:12px 16px; border-radius:8px; background:var(--ah-parch); color:var(--ah-parch-ink); box-shadow:0 10px 30px rgba(0,0,0,.5) }`，`.strip[data-kind='last_words']` 复用气泡的血色边。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GameTable/SpeechBubble.tsx frontend/src/components/GameTable/SpeechBubble.test.tsx frontend/src/components/GameTable/GameTable.module.css
git commit -m "feat(frontend): SpeechBubble 横向发言条变体（卡牌皮肤用）"
```

---

### Task 3: `CardBoard` 牌阵

**Files:**
- Create: `frontend/src/components/GameTable/CardBoard.tsx`
- Create: `frontend/src/components/GameTable/CardBoard.module.css`
- Test: `frontend/src/components/GameTable/CardBoard.test.tsx`

**Interfaces:**
- Consumes: `GameTableProps` / `TableSpeech`（export from `GameTable.tsx`）、`SeatModel`、`StageContent`、`TableCenter`、`SpeechBubble layout="strip"`（Task 2）、`ROLE_ICON_PATH`、`roleCamp`、`CAMP_VARS`、`ROLE_ZH`。
- Produces: `export default function CardBoard(props: GameTableProps): JSX.Element`。DOM：根 `<div class={styles.root} data-night data-testid="card-board">` → `.grid`（`repeat(4, 116px)`，gap 14）→ 每座 `<button type="button" class={styles.card} data-seat data-face="front|back|dead" data-me data-speaking data-dim data-selectable data-selected data-leader data-target aria-label={seatLabel(s)} aria-pressed disabled={!selectable} style={阵营 CSS 变量 --cb-hi/--cb-lo/--cb-fg/--cb-ring（已知时）}>`：`.inner`（1px 内框）、`.no`（羊皮纸座号签）、正面 = `<svg 46px>` + `.roleName`（`ROLE_ZH[role]`），牌背 = `.initial`（44px 圆 + 首字 / 头像）+ 「身份未翻」，出局 = `.dead`（✕ + 「出局」）或 已知角色 + 右上 `.stamp` ✕；右上 `.candidate`「警」、`.sheriff` ★；牌底 `.votes`（篝火签）/ `.tag`（红签）/ `.mark`；`.name` 底部居中。`leader` = `badges.votes` 等于全桌最大且 > 0。牌阵下 `.center`（`TableCenter content seats`，`kind !== "none" && kind !== "campfire"` 时渲染），再下 `speech !== null` 时 `SpeechBubble layout="strip"`。`seatLabel` 与 `currentItem` 从 `GameTable.tsx` 抽到 `frontend/src/lib/tableText.ts` 共用（export `seatLabel(s: SeatModel): string`、`currentSpeechItem(items, speaker)`）。

- [ ] **Step 1: Write the failing tests**

```tsx
// CardBoard.test.tsx（seat() 夹具同 GameTable.test）
it("12 座 3 行 / 9 座：每座一张 button[data-seat]；可选的可点并回调", ...)   // onSelect 只对 selectable 触发
it("正面 / 牌背 / 出局：已知角色显示徽记 + 角色名；未知显示首字 + 「身份未翻」；出局未知「出局」；出局已知仍显角色 + ✕ 章", () => {
  // seat 0 role WEREWOLF alive → getByText("狼人"), data-face front
  // seat 1 role null → getByText("P1"[0]) & 「身份未翻」, data-face back
  // seat 2 role null dead → 「出局」, data-face dead
  // seat 3 role SEER dead → 「预言家」 + data-face dead + stamp ✕
});
it("票数 2.5 原样；并列最高者都 data-leader；候选「警」；夜间目标红签", () => {
  // votes 2.5 / 2.5 / 1 → 两张 data-leader；tag "被刀" → getByText("被刀") & data-target
});
it("发言者 data-speaking，发言条在牌阵下方（role=status）", ...)
it("center 为 tally 时渲染桌心内容；campfire 不渲染", ...)
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement（先抽 `lib/tableText.ts` 并让 `GameTable` 改用，GameTable.test 仍绿）；Step 4: Run → PASS + `cssModules.test`**

CSS 关键：`.card { width:116px; height:140px; border-radius:7px; border:2px solid var(--ah-wood-edge); position:relative; transition: transform .15s, box-shadow .15s }`；`[data-face='front'] { background: radial-gradient(circle at 50% 30%, var(--cb-hi), var(--cb-lo)); color: var(--cb-fg); border-color: var(--cb-ring) }`；`[data-face='back'] { background: linear-gradient(180deg, var(--ah-wood-hi), var(--ah-wood-lo)) }`；`[data-face='dead'] { background:#141821; color:#5a5f6a; border-color:#2a3042 }`；`[data-speaking] { transform: translateY(-8px); border-color: var(--ah-gold); box-shadow: 0 0 28px rgba(240,192,96,.55) }`；`[data-me] { border-color: var(--ah-fire) }`；`[data-dim] { opacity:.55 }`；`[data-target] { transform: translateY(-6px); box-shadow: 0 0 24px rgba(201,70,61,.5) }`；`[data-leader] { border-color: var(--ah-gold) }`；`[data-selectable] { cursor:pointer }`、`[data-selected] { border-color: var(--ah-fire); box-shadow: 0 0 24px rgba(227,166,72,.6) }`。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GameTable/CardBoard.tsx frontend/src/components/GameTable/CardBoard.module.css frontend/src/components/GameTable/CardBoard.test.tsx frontend/src/lib/tableText.ts frontend/src/components/GameTable/GameTable.tsx
git commit -m "feat(frontend): CardBoard 卡牌皮肤牌阵（正面 / 牌背 / 出局 / 发言 / 投票 / 竞选 / 夜间）"
```

---

### Task 4: 顶栏切换 + `GamePage` 接入

**Files:**
- Create: `frontend/src/components/PhaseBar/TableStyleToggle.tsx`
- Modify: `frontend/src/pages/GamePage.tsx:626-640`（`headerExtra` 加 toggle）、`:723-733`（按偏好渲染 `CardBoard` / `GameTable`）
- Modify: `frontend/src/components/PhaseBar/PhaseBar.module.css`（toggle 样式）
- Test: `frontend/src/components/PhaseBar/TableStyleToggle.test.tsx`（新建）、`frontend/src/pages/GamePage.test.tsx`（追加 1 例）

**Interfaces:**
- Consumes: `usePrefs`（Task 1）、`CardBoard`（Task 3）。
- Produces: `TableStyleToggle(): JSX.Element` = `<label class={styles.toggle}>桌面：<select class={styles.select} aria-label="桌面皮肤" value={tableStyle}><option value="round">圆桌</option><option value="cards">卡牌</option></select></label>`（选项文案「圆桌 / 卡牌」，下拉自带 ▾）。`GamePage`：`const tableStyle = usePrefs((s) => s.tableStyle)`；`tableStyle === "cards" ? <CardBoard …同 props /> : <GameTable …/>`；toggle 放 `headerExtra` 最前（所有视角都显示）。

- [ ] **Step 1: Write failing tests**

```tsx
// TableStyleToggle.test.tsx
it("显示当前偏好并切换", () => {
  usePrefs.setState({ tableStyle: "round" });
  render(<TableStyleToggle />);
  const sel = screen.getByLabelText("桌面皮肤") as HTMLSelectElement;
  expect(sel.value).toBe("round");
  fireEvent.change(sel, { target: { value: "cards" } });
  expect(usePrefs.getState().tableStyle).toBe("cards");
  expect(localStorage.getItem("agenthowl.tableStyle")).toBe("cards");
});
// GamePage.test.tsx 追加（用文件里现成的 GM 回放夹具）
it("偏好 cards 时桌子区渲染 CardBoard，切回 round 渲染圆桌；座位契约不变", async () => {
  usePrefs.setState({ tableStyle: "cards" });
  ...render GM replay...
  expect(await screen.findByTestId("card-board")).toBeInTheDocument();
  expect(document.querySelectorAll("button[data-seat]").length).toBeGreaterThan(0);
  fireEvent.change(screen.getByLabelText("桌面皮肤"), { target: { value: "round" } });
  expect(screen.queryByTestId("card-board")).toBeNull();
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS + `npm run check` EXIT=0**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PhaseBar frontend/src/pages/GamePage.tsx frontend/src/pages/GamePage.test.tsx
git commit -m "feat(frontend): 顶栏「桌面：圆桌 / 卡牌」切换，GamePage 按偏好渲染 CardBoard"
```

---

### Task 5: e2e 切卡牌跑一遍、截图、文档、PR

**Files:**
- Modify: `frontend/e2e/play.mjs`（env `AH_TABLE=cards`：进对局页后 `selectOption('select[aria-label="桌面皮肤"]', "cards")`；截图文件名前缀用 `RUN`）
- Modify: `frontend/e2e/screens.mjs`（env `AH_TABLE=cards` 同上，输出前缀 `11-cards-gm-replay-*`）
- Modify: `frontend/e2e/README.md`、`docs/design/ui-gamified-2026-10-28/README.md`（PR ⑤ 段）
- Create: `docs/design/ui-gamified-2026-10-28/11-cards-*.png`（夜晚狼刀 / 投票 / 竞选 / 回放终局，1440；390 一张）

- [ ] **Step 1: play.mjs / screens.mjs 加 `AH_TABLE`**
- [ ] **Step 2: 起后端 + Vite；`AH_TABLE=cards RUN=cards-wolf AH_SEED=2 RUN_SHERIFF=1 SPEECH_SEC=5 ACTION_SEC=5 node play.mjs` → `finished: true / rejected: [] / mismatches: 0`**（狼视角：夜间目标红签 + 竞选金签 + 投票票数）
- [ ] **Step 3: `AH_TABLE=cards AH_GAME=<上一步 gameId> node screens.mjs` → 上帝回放的灰牌显身份 + ✕ 章**
- [ ] **Step 4: 复制截图、更新两份 README；`cd frontend && npm run check; echo EXIT=$?` → 0**
- [ ] **Step 5: Commit、push、`gh pr create`（用户在 GitHub 合并）**

```bash
git add frontend/e2e docs/design/ui-gamified-2026-10-28
git commit -m "test(e2e): 卡牌皮肤跑一遍四种状态 + PR ⑤ 截图基线"
```
