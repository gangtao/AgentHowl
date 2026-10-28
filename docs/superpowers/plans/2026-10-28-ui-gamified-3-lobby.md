# UI 游戏化 PR ③ 大厅三步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把大厅三步（选剧本 → 分配座位 → 开局卷轴）换成暗夜村庄视觉：羊皮纸剧本牌、圆桌入座 `SeatRing`、右栏「开局卷轴」木牌卡、第 3 步 640px 羊皮纸卷轴，建局请求形状与 `lib/seats.ts` 不变。

**Architecture:** 新增零 IO 的文案 / 座位签选择器 `lib/lobbyText.ts`；新组件 `SeatRing`（复用 `seatPositions`）+ `AgentMiniList`（左栏迷你档案卡）+ `LobbyScrollCard`（右栏木牌卡）+ `LaunchScroll`（第 3 步卷轴）；`PresetCard` 重皮；`Lobby.tsx` 只负责状态与编排。`SeatAssignment` 原样保留为 <900px 列表回退（CSS 切换，两套同时渲染、aria 名字不同）。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、Vitest + Testing Library、`--ah-*` 令牌与全局 `.ah-wood/.ah-parch/.btn-*/.tag-*` 类（PR ①）、`RoleToken`（PR ①）、`seatPositions`（PR ②）。

**Spec:** `docs/superpowers/specs/2026-10-28-ui-gamification-design.md` §5（大厅）、§8（PR ③ 分支 / 验证）、§9（约束）；设计稿片段 `docs/design/gamified-2026-10-27/options/{1c,1d,4a}.html`。

## Global Constraints

- 分支 `feat/ui-gamified-3-lobby`，从 `main`（73fa9f8）切出；验证 `cd frontend && npm run check`（lint + tsc + vitest）必须绿，用 `$?` 判定。
- 零过滤：大厅没有 viewer 概念，所有数据来自 `/agents` `/presets` `/tts/status`，不新增任何隐藏逻辑。
- `SeatSlot`、`lib/seats.ts`、`POST /games` 请求形状（`preset / agents / agent_ids / voice / narration / config_override`）不变；`buildAgentsPayload` 对含 memory_id 的 fill 抛错的规则不变。
- 文案（规格 §5 原文）：左栏标题「建 局 三 步」；第 1 步标题「选择剧本」、按钮「下一步 · 分配座位 →」；第 2 步标题「分配座位」、说明「从档案库把 Agent 放到座位上；留空即随机 bot。选「我自己」即亲自入座。」、工具行「全部随机 bot」「随机打乱」「填满其余座位：{档案名 | 不填} ▾」；右栏卡标题「开局卷轴」、汇总「{n} 座位 · {agents} 个 Agent · 我在 N号 · {bots} 个随机 bot」、「{preset 中文} · seed {随机|值}」、按钮「点燃篝火 · 开局」；第 3 步顶部进度「① 选择剧本 ② 分配座位 ③ 点燃篝火」、标题「开 局 卷 轴」、副标「你将以 N号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角」/「全 AI 对局 · 创建后进入上帝视角」、表行 剧本 / 座位 / seed / 我的显示名 / 发言时限 / 行动时限 / 播报、「秒 · 一根蜡烛」、返回「← 上一步 · 分配座位」。
- 尺寸：外层 `grid-template-columns: 240px 1fr 300px; gap 40px; padding 40px 56px`，第 2 步左栏 360px；剧本牌 3px 描边（选中 `--ah-fire`，未选 `--ah-parch-edge`）、标题 20px、角色徽记 `RoleToken variant="parch" size={28}`；圆桌 480px、座位 56px；卷轴 640px、标题 32px、开局按钮 20px heading 字体。
- <900px：三栏折成单列；`SeatRing` + `AgentMiniList` 隐藏，`SeatAssignment` 显示（两者 aria 名不同：圆桌座位按钮 `aria-label="入座 {seat}号"`，列表 select 仍是 `"{seat}号 座位"`）。
- 现有 e2e 入口 `frontend/e2e/play.mjs` 的大厅选择器必须同步更新（Task 8）。
- 中文注释 / 英文标识符；纯函数放 `src/lib/`（eslint `react-refresh/only-export-components`）；CSS Module 里组合器后的全局类必须包 `:global()`（守卫测试 `cssModules.test.ts`）。

## Review Focus

1. 档案库为空时第 2 步：左栏应显示「档案库是空的；不分配也能开局（全随机 bot）。」且圆桌全部为虚线 bot 座位，开局按钮在第 3 步仍可用 —— Task 4 / Task 7 测试覆盖。
2. 切换 preset 后座位数变化（12 → 9）：已分配的 10、11 号应被丢弃，圆桌重新按 9 座布点，「我自己」若在 10 号则汇总不再显示「我在 10号」—— Task 7 测试。
3. 先在左栏点中档案 A、再点已经放了「我自己」的座位：应直接改成 A 且「我自己」从圆桌消失（可再分配）—— Task 3 测试。
4. 含 memory_id 的档案已占 2 号：点 5 号弹出木牌菜单里该档案禁用并写「记忆已在 2号 使用」；左栏点中它再点 5 号不生效 —— Task 3 测试。
5. 第 3 步 `createAndStart` 失败（join 409）：错误与「删除这局」出现在卷轴底部，「点燃篝火 · 开局」（卷轴底部与右栏卡两处）都禁用，删除后恢复 —— Task 7 测试（沿用现有 issue #115 用例改选择器）。

---

### Task 1: 大厅文案 / 座位签选择器 `lib/lobbyText.ts`

**Files:**
- Create: `frontend/src/lib/lobbyText.ts`
- Test: `frontend/src/lib/lobbyText.test.ts`

**Interfaces:**
- Consumes: `SeatSlot`, `ME`, `AssignmentSummary` from `lib/seats.ts`；`StoredAgent` from `api/agents.ts`。
- Produces:
  ```ts
  export type SeatTagKind = "me" | "agent" | "fill" | "bot";
  export interface SeatTag { seat: number; kind: SeatTagKind; text: string }
  /** 右栏卡汇总行一：`12 座位 · 3 个 Agent · 我在 0号 · 8 个随机 bot`；numPlayers null → `未选剧本 · …`；fill 时末段 `其余 8 座由「狐语」填满`。 */
  export function summaryMain(numPlayers: number | null, s: AssignmentSummary, fillName: string | null): string;
  /** 汇总行二：`12 人预女猎白 · seed 随机`；presetZh null → `seed 随机`。seed 两端去空白，空 → `随机`。 */
  export function summarySub(presetZh: string | null, seed: string): string;
  /** 卷轴副标。 */
  export function scrollSubtitle(me: number | null): string;
  /** 圆桌座位显示：我自己 → {text:"我", kind:"me"}；库内档案 → 名字首字；fill 生效的空位 → 档案首字 kind "fill"；其余 → {text:"bot", kind:"bot"}。库里查不到的 id 视为 bot。 */
  export function seatGlyph(agentId: string | null, library: StoredAgent[], fillName: string | null): { text: string; kind: SeatTagKind };
  /** 第 3 步「座位」行：已分配座位按座号升序的签 + 其余座位数（`rest`）。 */
  export function seatTags(assignment: SeatSlot[], library: StoredAgent[], fill: string | null): { tags: SeatTag[]; rest: number; fillName: string | null };
  /** 木签文案 `12 人 / 带警长`、`9 人`。 */
  export function presetTag(numPlayers: number, sheriff: boolean): string;
  ```

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/lobbyText.test.ts
import { describe, expect, it } from "vitest";
import type { StoredAgent } from "../api/agents";
import { EMPTY_RATING } from "../api/agents";
import { ME, assignmentSummary } from "./seats";
import { presetTag, scrollSubtitle, seatGlyph, seatTags, summaryMain, summarySub } from "./lobbyText";

const lib: StoredAgent[] = [
  { agent_id: "a_fox", profile: { name: "狐语", model: "m" }, created_at: "", updated_at: "", rating: EMPTY_RATING },
  { agent_id: "a_abacus", profile: { name: "算盘", model: "m", memory_id: "mem1" }, created_at: "", updated_at: "", rating: EMPTY_RATING },
];
const assignment = [
  { seat: 0, agentId: ME }, { seat: 1, agentId: null }, { seat: 2, agentId: "a_fox" },
  { seat: 3, agentId: "a_ghost" }, { seat: 4, agentId: null },
];

describe("summaryMain / summarySub", () => {
  it("有我自己与 bot", () => {
    expect(summaryMain(5, assignmentSummary(assignment, null), null)).toBe("5 座位 · 1 个 Agent · 我在 0号 · 3 个随机 bot");
  });
  it("无我自己、有 fill", () => {
    const a = assignment.map((s) => (s.agentId === ME ? { ...s, agentId: null } : s));
    expect(summaryMain(5, assignmentSummary(a, "a_fox"), "狐语")).toBe("5 座位 · 1 个 Agent · 其余 4 座由「狐语」填满");
  });
  it("未选剧本", () => {
    expect(summaryMain(null, assignmentSummary([], null), null)).toBe("未选剧本 · 0 个 Agent · 0 个随机 bot");
  });
  it("summarySub", () => {
    expect(summarySub("12 人预女猎白", " 42 ")).toBe("12 人预女猎白 · seed 42");
    expect(summarySub(null, "")).toBe("seed 随机");
  });
});

describe("scrollSubtitle", () => {
  it.each([
    [3, "你将以 3号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角"],
    [null, "全 AI 对局 · 创建后进入上帝视角"],
  ])("%s", (me, text) => expect(scrollSubtitle(me)).toBe(text));
});

describe("seatGlyph", () => {
  it.each([
    [ME, null, { text: "我", kind: "me" }],
    ["a_fox", null, { text: "狐", kind: "agent" }],
    ["a_ghost", null, { text: "bot", kind: "bot" }],
    [null, null, { text: "bot", kind: "bot" }],
    [null, "狐语", { text: "狐", kind: "fill" }],
  ])("%s / fill %s", (id, fillName, want) => expect(seatGlyph(id, lib, fillName)).toEqual(want));
});

describe("seatTags", () => {
  it("签按座号升序，库里查不到的 id 不算", () => {
    expect(seatTags(assignment, lib, null)).toEqual({
      tags: [{ seat: 0, kind: "me", text: "我自己" }, { seat: 2, kind: "agent", text: "狐语" }],
      rest: 3,
      fillName: null,
    });
  });
  it("fill 时 fillName 带出", () => {
    expect(seatTags(assignment, lib, "a_fox").fillName).toBe("狐语");
  });
});

describe("presetTag", () => {
  it.each([[12, true, "12 人 / 带警长"], [9, false, "9 人"]])("%s %s", (n, s, t) => expect(presetTag(n, s)).toBe(t));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/lobbyText.test.ts`
Expected: FAIL — `Failed to resolve import "./lobbyText"`

- [ ] **Step 3: Implement `frontend/src/lib/lobbyText.ts` with the Produces signatures**

`summaryMain` 的末段：`s.filled && fillName !== null` → `其余 ${s.restSeats} 座由「${fillName}」填满`，否则 `${s.restSeats} 个随机 bot`；「我在 N号」段只在 `humanSeat !== null` 时插入。`seatGlyph` 首字用 `Array.from(name.trim())[0]`，名字为空回退 `"bot"`。`seatTags.rest = assignment.length - tags.length`。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/lobbyText.test.ts`
Expected: PASS（6 个 describe 全绿）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/lobbyText.ts frontend/src/lib/lobbyText.test.ts
git commit -m "feat(frontend): 大厅文案 / 座位签纯函数 lobbyText（UI 改版 PR ③）"
```

---

### Task 2: `PresetCard` 羊皮纸剧本牌

**Files:**
- Modify: `frontend/src/components/PresetCard/PresetCard.tsx`（整体重写渲染，props 不变）
- Modify: `frontend/src/components/PresetCard/PresetCard.module.css`（重写）
- Test: `frontend/src/components/PresetCard/PresetCard.test.tsx`（新建）

**Interfaces:**
- Consumes: `presetTag` (Task 1)；`RoleToken` default export `{ role, variant: "parch", size: 28, state?: "known" }`；`ROLE_ZH` from `engine/phases`。
- Produces: `PresetCard({ preset, selected, onSelect })` 不变；根元素 `<button class="ah-parch …" aria-pressed>`，含 `data-selected` 属性供 CSS 与测试。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/PresetCard/PresetCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PresetCard from "./PresetCard";

const preset = {
  name: "std_12_yn_hunter_idiot", num_players: 12, sheriff: true, win_condition: "KILL_SIDE",
  description_zh: "12 人预女猎白",
  roles: [{ role: "WEREWOLF", count: 4 }, { role: "VILLAGER", count: 4 }, { role: "SEER", count: 1 }, { role: "WITCH", count: 1 }, { role: "HUNTER", count: 1 }, { role: "IDIOT", count: 1 }],
};

describe("PresetCard（羊皮纸剧本牌）", () => {
  it("标题 / 木签 / 12 枚角色徽记 / mono id，选中态 aria-pressed", () => {
    const onSelect = vi.fn();
    render(<PresetCard preset={preset} selected onSelect={onSelect} />);
    const btn = screen.getByRole("button", { pressed: true });
    expect(btn).toHaveAttribute("data-selected", "true");
    expect(screen.getByRole("heading", { name: "12 人预女猎白" })).toBeInTheDocument();
    expect(screen.getByText("12 人 / 带警长")).toBeInTheDocument();
    expect(screen.getAllByTitle(/狼人|平民|预言家|女巫|猎人|白痴/)).toHaveLength(12);
    expect(screen.getByText("std_12_yn_hunter_idiot")).toBeInTheDocument();
    btn.click();
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/PresetCard`
Expected: FAIL — 找不到 heading「12 人预女猎白」/「12 人 / 带警长」

- [ ] **Step 3: Rewrite `PresetCard.tsx`**

结构：`<button type="button" className={"ah-parch " + styles.card} aria-pressed data-selected={selected ? "true" : undefined}>` → `.head`（`<h4 className={styles.title}>` 20px heading + `<span className="tag tag-wood">{presetTag(...)}</span>`）→ `.sub`（`description_zh` 的补充：`{胜利条件中文}`，沿用 `WIN_ZH`）→ `.tokens`（每个展开角色 `<span title={ROLE_ZH[role]}><RoleToken role={role} variant="parch" size={28} /></span>`）→ `.id`（mono `preset.name`）。CSS：`border: 3px solid var(--ah-parch-edge)`，`[data-selected] { border-color: var(--ah-fire); box-shadow: 0 0 0 1px var(--ah-fire), 0 10px 30px rgba(0,0,0,.4) }`，`:hover` 边 `--ah-parch-muted`；去掉旧 `.dot`。

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/PresetCard src/pages/Lobby.test.tsx`
Expected: PASS（Lobby 现有用例靠 `findByText("标准 9 人局")`，heading 文本仍命中）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PresetCard
git commit -m "feat(frontend): PresetCard 改羊皮纸剧本牌（3px 描边 / 木签 / 角色徽记）"
```

---

### Task 3: `SeatRing` 圆桌入座

**Files:**
- Create: `frontend/src/components/SeatRing/SeatRing.tsx`
- Create: `frontend/src/components/SeatRing/SeatRing.module.css`
- Test: `frontend/src/components/SeatRing/SeatRing.test.tsx`

**Interfaces:**
- Consumes: `seatPositions` from `lib/seatModel.ts`；`seatGlyph` (Task 1)；`ME`, `memoryConflicts`, `SeatSlot` from `lib/seats.ts`；`RoleToken`（`role={null}` → unknown，`initial` 为显示字）。
- Produces:
  ```ts
  export interface SeatRingProps {
    assignment: SeatSlot[];
    library: StoredAgent[];
    fill: string | null;
    /** 左栏当前点中的档案；非 null 时点座位直接分配并由父级清空。 */
    pendingAgent: string | null;
    onAssign(seat: number, agentId: string | null): void;
  }
  export default function SeatRing(props: SeatRingProps): JSX.Element;
  ```
  DOM 约定：根 `data-testid="seat-ring"`；每座 `<button aria-label="入座 {seat}号" data-kind={me|agent|fill|bot}>`；木牌菜单 `<div role="menu" aria-label="{seat}号 座位菜单">`，项为 `<button role="menuitem">`：「我自己」（已占他座时 disabled，文案加「（已在 N号）」）、「随机 bot」、pendingAgent 非 null 时「放入 {名}」、已分配时「清空」（等价随机 bot，仅当 slot 非空显示）、以及库内每个档案一项（memory 冲突时 disabled 加「（记忆已在 N号 使用）」）。点座位时若 `pendingAgent !== null` 且该档案无冲突 → 直接 `onAssign(seat, pendingAgent)`，不开菜单；有冲突 → 开菜单（该项禁用）。Escape / 点其它座位关闭菜单。

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/SeatRing/SeatRing.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_RATING, type StoredAgent } from "../../api/agents";
import { ME } from "../../lib/seats";
import SeatRing from "./SeatRing";

const lib: StoredAgent[] = [
  { agent_id: "a_fox", profile: { name: "狐语", model: "m" }, created_at: "", updated_at: "", rating: EMPTY_RATING },
  { agent_id: "a_mem", profile: { name: "算盘", model: "m", memory_id: "mem1" }, created_at: "", updated_at: "", rating: EMPTY_RATING },
];
const four = (over: Record<number, string | null> = {}) =>
  [0, 1, 2, 3].map((seat) => ({ seat, agentId: over[seat] ?? null }));

describe("SeatRing（规格 §5 第 2 步）", () => {
  it("n 个座位按 seatPositions 布点，显示 我 / 首字 / bot", () => {
    render(<SeatRing assignment={four({ 0: ME, 1: "a_fox" })} library={lib} fill={null} pendingAgent={null} onAssign={vi.fn()} />);
    const seats = screen.getAllByRole("button", { name: /^入座 \d+号$/ });
    expect(seats).toHaveLength(4);
    expect(seats[0]).toHaveAttribute("data-kind", "me");
    expect(seats[0]).toHaveTextContent("我");
    expect(seats[1]).toHaveTextContent("狐");
    expect(seats[2]).toHaveAttribute("data-kind", "bot");
    expect((seats[0] as HTMLElement).style.left).toBe("50%");
    expect((seats[1] as HTMLElement).style.left).toBe("91%");
  });

  it("点座位开木牌菜单，选「我自己」回调 onAssign(seat, ME)", () => {
    const onAssign = vi.fn();
    render(<SeatRing assignment={four()} library={lib} fill={null} pendingAgent={null} onAssign={onAssign} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 2号" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "我自己" }));
    expect(onAssign).toHaveBeenCalledWith(2, ME);
  });

  it("「我自己」已在 0 号：其它座位菜单里禁用并标注", () => {
    render(<SeatRing assignment={four({ 0: ME })} library={lib} fill={null} pendingAgent={null} onAssign={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 3号" }));
    expect(screen.getByRole("menuitem", { name: /我自己（已在 0号）/ })).toBeDisabled();
  });

  it("左栏点中档案后点座位 → 直接分配，即使该座是「我自己」", () => {
    const onAssign = vi.fn();
    render(<SeatRing assignment={four({ 0: ME })} library={lib} fill={null} pendingAgent="a_fox" onAssign={onAssign} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 0号" }));
    expect(onAssign).toHaveBeenCalledWith(0, "a_fox");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("memory_id 已占 2 号：5 号菜单里该档案禁用；pending 它再点 5 号不分配", () => {
    const onAssign = vi.fn();
    const six = [0, 1, 2, 3, 4, 5].map((seat) => ({ seat, agentId: seat === 2 ? "a_mem" : null }));
    const { rerender } = render(<SeatRing assignment={six} library={lib} fill={null} pendingAgent={null} onAssign={onAssign} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 5号" }));
    expect(screen.getByRole("menuitem", { name: /算盘（记忆已在 2号 使用）/ })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    rerender(<SeatRing assignment={six} library={lib} fill={null} pendingAgent="a_mem" onAssign={onAssign} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 5号" }));
    expect(onAssign).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("「清空」只在已分配座位出现，回调 null", () => {
    const onAssign = vi.fn();
    render(<SeatRing assignment={four({ 1: "a_fox" })} library={lib} fill={null} pendingAgent={null} onAssign={onAssign} />);
    fireEvent.click(screen.getByRole("button", { name: "入座 0号" }));
    expect(screen.queryByRole("menuitem", { name: "清空" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "入座 1号" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "清空" }));
    expect(onAssign).toHaveBeenCalledWith(1, null);
  });

  it("fill 生效时空位显示档案首字、data-kind=fill", () => {
    render(<SeatRing assignment={four()} library={lib} fill="a_fox" pendingAgent={null} onAssign={vi.fn()} />);
    expect(screen.getByRole("button", { name: "入座 0号" })).toHaveAttribute("data-kind", "fill");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/SeatRing`
Expected: FAIL — 找不到模块 `./SeatRing`

- [ ] **Step 3: Implement `SeatRing.tsx` + CSS**

内部状态 `openSeat: number | null`；`useMemo(memoryConflicts)`；`useEffect` 监听 `keydown` Escape 关闭。座位 `style={{ left: x + "%", top: y + "%" }}`，`transform: translate(-50%,-50%)`。渲染：`.root`（`position: relative; width: 480px; aspect-ratio: 1; margin: 0 auto`）→ `.disc`（复用 GameTable 的木桌渐变、`border: 6px solid var(--ah-wood-edge)`）→ `.fire`（84px 篝火径向渐变）→ 座位按钮：内含 `<RoleToken role={null} variant="seat" size={56} initial={glyph.text} />`，`data-kind="bot"` 时 `.token > :first-child` 边框改 `2px dashed var(--ah-wood-edge)`（用 `:global` 不需要——RoleToken 根在按钮内，用 `[data-kind="bot"] > *` 选中），`me` 边 `--ah-fire`，`agent/fill` 实线 `--ah-gold`；座位下 11px 座号。菜单 `.menu`：`position:absolute; left/top 同座位，transform: translate(-50%, 36px); z-index: 2`，类 `ah-wood` + `styles.menu`，项 `btn btn-ghost` 全宽左对齐。

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/SeatRing src/styles/cssModules.test.ts`
Expected: PASS 7/7 + 守卫绿

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SeatRing
git commit -m "feat(frontend): SeatRing 圆桌入座（木牌菜单 / 预选档案直接分配 / memory 冲突禁用）"
```

---

### Task 4: `AgentMiniList` 左栏迷你档案卡

**Files:**
- Create: `frontend/src/components/SeatRing/AgentMiniList.tsx`
- Create: `frontend/src/components/SeatRing/AgentMiniList.module.css`
- Test: `frontend/src/components/SeatRing/AgentMiniList.test.tsx`

**Interfaces:**
- Consumes: `ratingLine` from `lib/rating.ts`；`Avatar`（`size={40}`）。
- Produces:
  ```ts
  export interface AgentMiniListProps {
    library: StoredAgent[];
    selected: string | null;
    onSelect(agentId: string | null): void;   // 再点同一张 → null
    onNewAgent(): void;
  }
  export default function AgentMiniList(props: AgentMiniListProps): JSX.Element;
  ```
  DOM：搜索框 `aria-label="搜索档案"`（class `input`）；卡 `<button aria-pressed data-agent-id>` 两列网格，内容 40px `Avatar` + 名字 + 模型简称（`model.split("/").pop()`）+ `ratingLine(rating)`；空库提示「档案库是空的；不分配也能开局（全随机 bot）。」；无匹配「没有匹配的档案。」；底部「+ 新建 Agent」（`btn btn-secondary`）。搜索匹配 `name / model / memory_id`（与 SeatAssignment 一致）。

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/SeatRing/AgentMiniList.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_RATING, type StoredAgent } from "../../api/agents";
import AgentMiniList from "./AgentMiniList";

const lib: StoredAgent[] = [
  { agent_id: "a_fox", profile: { name: "狐语", model: "openai/gpt-5" }, created_at: "", updated_at: "", rating: { rating: 1024, games: 12, wins: 7, losses: 5, draws: 0 } },
  { agent_id: "a_owl", profile: { name: "夜枭", model: "m" }, created_at: "", updated_at: "", rating: EMPTY_RATING },
];

describe("AgentMiniList", () => {
  it("卡片含首字 / 名字 / 模型简称 / 战绩；点选 aria-pressed，再点取消", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<AgentMiniList library={lib} selected={null} onSelect={onSelect} onNewAgent={vi.fn()} />);
    const fox = screen.getByRole("button", { name: /狐语/ });
    expect(fox).toHaveTextContent("gpt-5");
    expect(fox).toHaveTextContent("1024 分 · 12 局 · 胜率 58%");
    fireEvent.click(fox);
    expect(onSelect).toHaveBeenCalledWith("a_fox");
    rerender(<AgentMiniList library={lib} selected="a_fox" onSelect={onSelect} onNewAgent={vi.fn()} />);
    expect(screen.getByRole("button", { name: /狐语/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /狐语/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("搜索过滤与空态文案", () => {
    const { rerender } = render(<AgentMiniList library={lib} selected={null} onSelect={vi.fn()} onNewAgent={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("搜索档案"), { target: { value: "zzz" } });
    expect(screen.getByText("没有匹配的档案。")).toBeInTheDocument();
    rerender(<AgentMiniList library={[]} selected={null} onSelect={vi.fn()} onNewAgent={vi.fn()} />);
    expect(screen.getByText(/档案库是空的/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ 新建 Agent" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/SeatRing/AgentMiniList.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: Implement**

CSS：`.grid { display:grid; grid-template-columns: 1fr 1fr; gap:10px }`；卡 `.card`（`ah-wood` 外观但 `padding:12px; border:2px solid var(--ah-wood-edge); text-align:left`），`[aria-pressed="true"] { border-color: var(--ah-fire); box-shadow: 0 0 16px rgba(227,166,72,.35) }`。

- [ ] **Step 4: Run test → PASS；Step 5: Commit**

```bash
git add frontend/src/components/SeatRing/AgentMiniList*
git commit -m "feat(frontend): AgentMiniList 左栏迷你档案卡（搜索 / 点选预分配）"
```

---

### Task 5: `LobbyScrollCard` 右栏「开局卷轴」木牌卡

**Files:**
- Create: `frontend/src/components/LobbyScrollCard/LobbyScrollCard.tsx`
- Create: `frontend/src/components/LobbyScrollCard/LobbyScrollCard.module.css`
- Test: `frontend/src/components/LobbyScrollCard/LobbyScrollCard.test.tsx`

**Interfaces:**
- Consumes: `summaryMain / summarySub` (Task 1)；`TtsStatus` from `api/rest`。
- Produces:
  ```ts
  export interface LobbyScrollCardProps {
    numPlayers: number | null;
    presetZh: string | null;
    summary: AssignmentSummary;
    fillName: string | null;
    seed: string;
    tts: TtsStatus;
    voice: boolean; narration: boolean;
    onVoice(v: boolean): void; onNarration(v: boolean): void;
    /** 第 2 步为 true：多一段 12px 规则说明。 */
    showNotes: boolean;
    canLaunch: boolean; creating: boolean;
    onLaunch(): void;
  }
  ```
  DOM：`<aside class="ah-wood">`，`card-kicker`「开局卷轴」，汇总两行，复选框 label 文案「语音播报」「旁白（GM 播报阶段 / 结算 / 投票结果）」（沿用 Lobby 现有联动：取消语音时父级清旁白），按钮 `btn btn-primary` 文案 `creating ? "创建中…" : "点燃篝火 · 开局"`，`disabled={!canLaunch || creating}`；`showNotes` 时两行 `.note`：「同一档案可放多个座位；配置了 memory_id 的档案只能占一个座位。」「「我自己」只能占一个座位；建局后你以该座位入座并直接进入玩家页。」。

- [ ] **Step 1: Write the failing test**

```tsx
// LobbyScrollCard.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LobbyScrollCard from "./LobbyScrollCard";

const base = {
  numPlayers: 12, presetZh: "12 人预女猎白", fillName: null, seed: "",
  summary: { agentSeats: 3, restSeats: 8, filled: false, humanSeat: 0 },
  tts: { enabled: true, ok: true, url: null, detail: null, supports_style: false },
  voice: false, narration: false, onVoice: vi.fn(), onNarration: vi.fn(),
  showNotes: false, canLaunch: false, creating: false, onLaunch: vi.fn(),
};

describe("LobbyScrollCard", () => {
  it("汇总两行 + 开局按钮禁用态", () => {
    render(<LobbyScrollCard {...base} />);
    expect(screen.getByText("12 座位 · 3 个 Agent · 我在 0号 · 8 个随机 bot")).toBeInTheDocument();
    expect(screen.getByText("12 人预女猎白 · seed 随机")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "点燃篝火 · 开局" })).toBeDisabled();
    expect(screen.queryByText(/同一档案可放多个座位/)).toBeNull();
  });
  it("可开局时按钮可用并回调；第 2 步显示说明", () => {
    const onLaunch = vi.fn();
    render(<LobbyScrollCard {...base} canLaunch showNotes onLaunch={onLaunch} />);
    fireEvent.click(screen.getByRole("button", { name: "点燃篝火 · 开局" }));
    expect(onLaunch).toHaveBeenCalled();
    expect(screen.getByText(/「我自己」只能占一个座位/)).toBeInTheDocument();
  });
  it("tts 未开启时不渲染复选框", () => {
    render(<LobbyScrollCard {...base} tts={{ ...base.tts, enabled: false }} />);
    expect(screen.queryByLabelText(/语音播报/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run → FAIL（模块不存在）；Step 3: Implement；Step 4: Run → PASS 3/3**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LobbyScrollCard
git commit -m "feat(frontend): LobbyScrollCard 右栏「开局卷轴」木牌卡"
```

---

### Task 6: `LaunchScroll` 第 3 步羊皮纸卷轴

**Files:**
- Create: `frontend/src/components/LaunchScroll/LaunchScroll.tsx`
- Create: `frontend/src/components/LaunchScroll/LaunchScroll.module.css`
- Test: `frontend/src/components/LaunchScroll/LaunchScroll.test.tsx`

**Interfaces:**
- Consumes: `scrollSubtitle`, `SeatTag` (Task 1)；`PresetInfo`。
- Produces:
  ```ts
  export interface LaunchScrollProps {
    preset: PresetInfo;
    me: number | null;
    seatTags: SeatTag[]; rest: number; fillName: string | null;
    seed: string;
    displayName: string; displayNamePlaceholder: string; onDisplayName(v: string): void;
    speechTimeout: string; onSpeechTimeout(v: string): void;
    actionTimeout: string; onActionTimeout(v: string): void;
    voice: boolean; narration: boolean; ttsEnabled: boolean;
    error: string | null;             // createError 或 fillBlocked 文案
    canDiscard: boolean; onDiscard(): void;
    canLaunch: boolean; creating: boolean;
    onBack(): void; onLaunch(): void;
  }
  ```
  DOM：`<section class="ah-parch">` 640px，顶部 `.roller`（28px 木轴条，`top:-14px`），`<h2>`「开 局 卷 轴」32px，副标 `scrollSubtitle(me)`；`<dl>` 两列（110px / 1fr）：`剧本`（`description_zh` + mono `name`）、`座位`（签：`me` → `tag tag-gold`「0号 我自己」、`agent` → `tag tag-parch`「2号 狐语」，再加 muted「· 其余 {rest} 座随机 bot」或「· 其余 {rest} 座由「{fillName}」填满」）、`seed`（空 → 随机）、仅 `me !== null` 时 `我的显示名`（`input aria-label="我的显示名"` placeholder = `displayNamePlaceholder`）、`发言时限`（`input aria-label="发言时限" inputMode="numeric"` + 「秒 · 一根蜡烛」）、`行动时限`（`input aria-label="行动时限"` + 「秒」）、`ttsEnabled` 时 `播报`（`☑/☐ 语音播报 · ☑/☐ 旁白`，只读文本）。底部 `.foot`：`btn btn-ghost`「← 上一步 · 分配座位」+ `btn btn-primary` 20px heading「点燃篝火 · 开局」(`disabled={!canLaunch || creating}`，creating → 「创建中…」)。`error` 非 null → `.error` 块在 foot 之上，`canDiscard` 时附 `btn btn-ghost`「删除这局」。

- [ ] **Step 1: Write the failing test**

```tsx
// LaunchScroll.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LaunchScroll from "./LaunchScroll";

const preset = { name: "std_9_kill_side", num_players: 9, roles: [], sheriff: true, win_condition: "KILL_SIDE", description_zh: "标准 9 人局" };
const base = {
  preset, me: 3, seatTags: [{ seat: 3, kind: "me" as const, text: "我自己" }, { seat: 5, kind: "agent" as const, text: "狐语" }], rest: 7, fillName: null,
  seed: "", displayName: "", displayNamePlaceholder: "alice", onDisplayName: vi.fn(),
  speechTimeout: "120", onSpeechTimeout: vi.fn(), actionTimeout: "60", onActionTimeout: vi.fn(),
  voice: true, narration: false, ttsEnabled: true,
  error: null, canDiscard: false, onDiscard: vi.fn(), canLaunch: true, creating: false, onBack: vi.fn(), onLaunch: vi.fn(),
};

describe("LaunchScroll（规格 §5 第 3 步）", () => {
  it("我自己入座：副标 / 座位签 / 时限输入 / 开局按钮", () => {
    render(<LaunchScroll {...base} />);
    expect(screen.getByRole("heading", { name: "开 局 卷 轴" })).toBeInTheDocument();
    expect(screen.getByText("你将以 3号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角")).toBeInTheDocument();
    expect(screen.getByText("3号 我自己")).toBeInTheDocument();
    expect(screen.getByText("5号 狐语")).toBeInTheDocument();
    expect(screen.getByText(/其余 7 座随机 bot/)).toBeInTheDocument();
    expect(screen.getByLabelText("我的显示名")).toHaveAttribute("placeholder", "alice");
    expect(screen.getByLabelText("发言时限")).toHaveValue("120");
    expect(screen.getByText(/秒 · 一根蜡烛/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "点燃篝火 · 开局" }));
    expect(base.onLaunch).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "← 上一步 · 分配座位" }));
    expect(base.onBack).toHaveBeenCalled();
  });
  it("全 AI：副标改写，没有显示名输入；错误 + 删除这局", () => {
    render(<LaunchScroll {...base} me={null} seatTags={[]} rest={9} error="409 · 座位被占" canDiscard canLaunch={false} />);
    expect(screen.getByText("全 AI 对局 · 创建后进入上帝视角")).toBeInTheDocument();
    expect(screen.queryByLabelText("我的显示名")).toBeNull();
    expect(screen.getByText("409 · 座位被占")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    expect(base.onDiscard).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "点燃篝火 · 开局" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run → FAIL；Step 3: Implement；Step 4: Run → PASS 2/2 + `cssModules.test.ts` 绿**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LaunchScroll
git commit -m "feat(frontend): LaunchScroll 第 3 步羊皮纸开局卷轴"
```

---

### Task 7: `Lobby.tsx` 编排与布局接入

**Files:**
- Modify: `frontend/src/pages/Lobby.tsx`（STEPS 文案、布局、三步内容替换；状态与 `createAndStart / discardFailedGame / saveNewAgent / shuffle / assign` 逻辑不动）
- Modify: `frontend/src/pages/Lobby.module.css`（重写布局）
- Modify: `frontend/src/pages/Lobby.test.tsx`（选择器与文案跟进 + 新用例）

**Interfaces:**
- Consumes: Task 1–6 全部。
- Produces: 页面 DOM 契约（供 Task 8 e2e）：第 1 步 `#lobby-seed`、`button:has-text("下一步 · 分配座位 →")`；第 2 步 `button[aria-label="入座 0号"]` → `[role=menuitem]:has-text("我自己")`、`button:has-text("下一步 · 开局卷轴 →")`；第 3 步 `input[aria-label="我的显示名" | "发言时限" | "行动时限"]`、`section.ah-parch button:has-text("点燃篝火 · 开局")`。

- [ ] **Step 1: Update existing tests + add new ones (RED)**

在 `Lobby.test.tsx`：
- `pickMeOnSeat3` 改为：点 `/下一步 · 分配座位/` → `fireEvent.click(await screen.findByRole("button", { name: "入座 3号" }))` → 点 `menuitem` 「我自己」 → 点 `/下一步 · 开局卷轴/`。
- 所有 `getAllByRole("button", { name: "创建并开始" })[0]` 改为 `screen.getAllByRole("button", { name: "点燃篝火 · 开局" })[0]`（卷轴内的那颗在前；右栏卡那颗在后）；「禁用」断言改为 `getAllByRole(...).every(b => b.disabled)`。
- issue #123 用例：座位用圆桌菜单选「狐语」（menuitem 名 `/夜枭|狐语/` 按 LIBRARY_ROWS 实际名），fill 用隐藏回退 `getByLabelText("填满其余座位")` **改为** 工具行 `getByLabelText("填满其余座位")`（Lobby 工具行的 `<select aria-label="填满其余座位">`，SeatAssignment 回退里的同名 select 改成 `aria-label="填满其余座位（列表）"` 以免重名）；删掉 `agent_ids: {…}` 文本断言（UI 不再显示 payload 调试行，请求体断言保留）。
- 新增：
  ```tsx
  it("换 preset 座位数变少：越界的「我自己」被丢弃，汇总不再显示我在 N号", async () => { /* presets [12 人, 9 人]；第 2 步把我放 10 号 → 回第 1 步选 9 人 → 汇总文本不含「我在」 */ });
  it("档案库为空：第 2 步显示空库提示，圆桌 9 个 bot 座位，第 3 步仍可开局", async () => { /* 入座按钮 data-kind 全 bot；卷轴按钮 enabled */ });
  it("第 3 步顶部进度条高亮「③ 点燃篝火」，左栏步骤隐藏", ...);
  ```

- [ ] **Step 2: Run → FAIL**

Run: `cd frontend && npx vitest run src/pages/Lobby.test.tsx`
Expected: FAIL（找不到「入座 3号」等）

- [ ] **Step 3: Rewrite Lobby render**

- `STEPS = [{n:1,title:"选择剧本",sub:"板子 preset 与 seed"},{n:2,title:"分配座位",sub:"从档案库挑 Agent"},{n:3,title:"点燃篝火",sub:"开局卷轴与时限"}]`。
- 新状态 `pendingAgent: string | null`（左栏点中档案；`assign` 成功后与换步时清空）。
- 布局：`<div className={styles.page} data-step={step}>`；`step !== 3` 渲染 `<aside className={styles.steps}>`（标题「建 局 三 步」+ 三行按钮，`data-state="current|done|todo"`）；`step === 3` 渲染 `<nav className={styles.progress} aria-label="建局进度">` 三个 span，当前 `aria-current="step"`；`<main className={styles.main}>`；`<LobbyScrollCard … showNotes={step===2} canLaunch={step===3 && preset!==null && !fillBlocked && failedGame===null} />`。
- 第 1 步：`<h2>`「选择剧本」+ 说明「全 AI 对局；未分配档案的座位是随机 bot（零 LLM）。」；`PresetCard` 两列网格；seed 字段（`#lobby-seed`，`input` 类 + label「seed」）；`btn btn-secondary`「下一步 · 分配座位 →」。
- 第 2 步：`<h2>`「分配座位」+ 规格说明；`.assignGrid`（`360px 1fr`）：`AgentMiniList`（`selected={pendingAgent}`）| `SeatRing`（`onAssign={(s,id)=>{assign(s,id); setPendingAgent(null);}}`）+ `.tools` 行（「全部随机 bot」「随机打乱」`btn btn-ghost`，`<label>填满其余座位：<select aria-label="填满其余座位" className="input">`，选项同 SeatAssignment，含 memory 的 disabled）+ `fillBlocked` 警示；`<div className={styles.fallback}><SeatAssignment … /></div>`（CSS `display:none`，<900px 显示；同时 `.assignGrid` 隐藏）。底部 `btn btn-ghost`「← 上一步」+ `btn btn-secondary`「下一步 · 开局卷轴 →」。
- 第 3 步：`<LaunchScroll … error={fillBlocked ? 「{name}」配置了 memory_id… : createError} canDiscard={failedGame!==null} canLaunch={…同上} />`。
- 去掉 `payloadKeys / idKeys` 与 `styles.payload / .review / .json / .navHint`。
- CSS：`.page { display:grid; grid-template-columns: 240px minmax(0,1fr) 300px; gap:40px; padding:40px 56px; overflow-y:auto }`，`[data-step="2"] { grid-template-columns: minmax(0,1fr) 300px }`（左栏并入 main 的 `.assignGrid`），`[data-step="3"] { grid-template-columns: minmax(0,1fr) 300px; grid-template-rows: auto 1fr }`（进度条跨两列）；步骤圆 34px：current 篝火渐变 / done 木牌 / todo `2px dashed var(--ah-wood-edge)` + `opacity:.55`；`@media (max-width:900px)`：单列、`.assignGrid{display:none}`、`.fallback{display:block}`、`.page{padding:24px 16px}`。

- [ ] **Step 4: Run tests + full check**

Run: `cd frontend && npx vitest run src/pages/Lobby.test.tsx && npm run check; echo EXIT=$?`
Expected: Lobby 用例全绿；`EXIT=0`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Lobby.tsx frontend/src/pages/Lobby.module.css frontend/src/pages/Lobby.test.tsx frontend/src/components/SeatAssignment/SeatAssignment.tsx
git commit -m "feat(frontend): 大厅三步接入新视觉（步骤栏 / 圆桌入座 / 开局卷轴，SeatAssignment 作 <900px 回退）"
```

---

### Task 8: e2e 选择器、全流程手测、截图与 PR

**Files:**
- Modify: `frontend/e2e/play.mjs:101-115`（大厅段）
- Modify: `frontend/e2e/screens.mjs`（新增 `02-lobby-1-preset.png` / `02-lobby-2-seats.png`（含打开的木牌菜单）/ `02-lobby-3-scroll.png`；1440×900 与 390 宽回退 `02-lobby-2-seats-390.png`）
- Modify: `frontend/e2e/README.md`、`docs/design/ui-gamified-2026-10-28/README.md`（PR ③ 行）
- Create: `docs/design/ui-gamified-2026-10-28/02-lobby-*.png`

- [ ] **Step 1: Update `play.mjs` lobby section to the Task 7 DOM contract**

```js
await page.locator('button:has-text("下一步 · 分配座位 →")').click();   // 在选 preset 之后
await page.locator('button[aria-label="入座 0号"]').click();
await page.locator('[role="menuitem"]:has-text("我自己")').click();
await page.locator('button:has-text("下一步 · 开局卷轴 →")').click();
await page.fill('input[aria-label="我的显示名"]', "E2E");
… 发言 / 行动时限同前 …
await page.locator('section.ah-parch button:has-text("点燃篝火 · 开局")').click();
```

- [ ] **Step 2: Start backend + Vite, run one full game as villager (seed 3) to prove the lobby path**

Run: `cd frontend/e2e && AH_SEED=3 SPEECH_SEC=5 ACTION_SEC=5 node play.mjs 2>&1 | tail -3`
Expected: 末行 `SUMMARY {…"rejected":0,"mismatches":0,"stalls":0…}` 且 `finished:true`

- [ ] **Step 3: Capture screenshots, copy to docs, update both READMEs**

Run: `cd frontend/e2e && SHOT_DIR=shots node screens.mjs --lobby` 然后 `cp` 到 `docs/design/ui-gamified-2026-10-28/`；肉眼核对三张图与 1c / 1d / 4a 的布局对应。

- [ ] **Step 4: Final gate**

Run: `cd frontend && npm run check; echo EXIT=$?`
Expected: `EXIT=0`

- [ ] **Step 5: Commit, push, open PR (user merges on GitHub)**

```bash
git add frontend/e2e docs/design/ui-gamified-2026-10-28
git commit -m "test(e2e): 大厅选择器跟进新视觉 + PR ③ 截图基线"
git push -u origin feat/ui-gamified-3-lobby
gh pr create --title "feat(frontend): UI 游戏化 PR ③ 大厅三步" --body-file <(…规格 §5 对照、截图、Deferred minors…)
```
