# 游戏化改版 PR ② · 对局页全景圆桌 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把对局页从「三栏 + 发言流」改成设计稿 3a 的「全景圆桌 + 底部 HUD / 回放绳索 + 右栏信息卡 + 事件流抽屉」，覆盖直播 / 回放 × 上帝 / 观众 / 座位三种视角的全部阶段，并加上终局结算页。

**Architecture:** 先写四个纯函数（`seatModel` 座位模型、`stageContent` 桌心内容、`railCards` 右栏卡片选择、`townNews` / `graveyard` 村镇选择器），全部只收 `GameState` / `Event[]` / `YourTurn`，用金样 fixture 测试；再写渲染它们的组件（`GameTable` / `TableCenter` / `SpeechBubble` / `InfoRail` / `EventDrawer` / `IdentityCard` / `GameOverScreen`），复用 PR ① 的 `RoleToken` 与全局类；最后 `GamePage` 换布局接线，删除 `SeatCircle` / `SpeakerSpotlight` / `NightOverlay`。目标座位由 `GamePage` 持有（`selectedTarget`），`ActionBar` 改成受控，桌上点座位与胶囊等价。store / API / engine reducer 不动。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、Zustand（只读现有 store）、Vitest + Testing Library、Playwright（e2e 脚本 + 截图）。

**Spec:** `docs/superpowers/specs/2026-10-28-ui-gamification-design.md` §4（4.1–4.10）、§8（PR ②）、§9、§10（规格在 PR #169 分支 `feat/ui-gamified-spec` 上，合并前用 `git show feat/ui-gamified-spec:<path>` 读）。设计稿片段：`docs/design/gamified-2026-10-27/options/{3a,3d,4b,4c,4d,5a,5b,5c,7a,7b,7c,7d,1i}.html`（同一分支）。

## Global Constraints

- 中文注释 / 英文标识符；Prettier `printWidth: 100`；TS strict + `noUncheckedIndexedAccess`；不新增 npm 依赖（e2e 脚本用 `playwright-core`，已在旧 scratchpad 的 `package.json` 里，复制进 `frontend/e2e/package.json` 单独安装，不进主 `package.json`）。
- **零过滤**（规格 §4.10）：`GameTable` / `TableCenter` / `InfoRail` / `SpeechBubble` / `GameOverScreen` / 四个纯函数的 props 与参数里没有 `viewer`；视角只在 `GamePage` 决定「渲染 HUD 还是绳索条」与顶栏标签。本人角色与狼队友来自服务端的 `PlayerObservation`（`my_role` / `private.teammates`），作为 `knownRoles` 覆盖层传入，不是前端推断。PR 验收项：`grep -rn "viewer" frontend/src/components/{GameTable,TableCenter,InfoRail,SpeechBubble,GameOverScreen} frontend/src/lib/{seatModel,stageContent,railCards,village}.ts` 为空。
- 现有行为不变：引导流程（/meta → /state → 409 轮询）、直播收尾自动切回放、回放配音门控、WS 发送、倒计时到 0 不锁提交、`useTurn` 语义、键盘快捷键（空格 / ←→）。`GamePage.test.tsx` 现有 17 条用例语义不变，只改查询。
- `npm run check` 每任务全绿；基线 440 条测试。
- 文案逐字按规格 §4 与设计稿；阶段中文沿用 `PHASE_ZH` / `ELECTION_STAGE_ZH` / `ROLE_ZH` / `WINNER_ZH`。
- `GameConfigLite` 只有 `num_players / sheriff / roles / win_condition` 强类型；`night_order`、`speech_time_limit`、`witch_self_save` 通过索引签名读，缺失时相应文案省略。

## Review Focus

1. **观众 / 玩家的折叠夜晚阶段 `"NIGHT"`**（`store.applyPhase` 写入，事件流里没有）：`isNight` 为真，但没有 `NIGHT_*` 子阶段。木牌要写「第 N 夜 · 夜晚」，桌心走 `moon`，右栏夜晚流程卡不能因为找不到当前子阶段而崩。→ Task 3 `stageContent` 与 Task 5 `PhasePlaque` 各一条用例。
2. **回放游标拖到 seq 0**：`viewState()` 是 `initialState`（`LOBBY`、`players` 来自 roster、无角色）。座位全部 unknown、桌心 `campfire`、右栏只剩公告（存活 n/n）、不能出现结算页。→ Task 3 / Task 4 / Task 10 各一条用例。
3. **玩家已出局（`my_status === "DEAD"`）还在收 `your_turn`**（猎人开枪 / 遗言）：身份牌显示 ✕ + 「已出局」，HUD 仍渲染行动区；没有 prompt 时中间显示「旁听中」而不是「天黑请闭眼」（白天）。→ Task 9 两条用例。
4. **警长 1.5 票**：桌心票型与座位角标显示 `5.5`，不能四舍五入成 6，也不能显示 `5.5.0`。→ Task 6 `TableCenter` tally 用例。
5. **座位点击在不需要目标时必须无效**：发言阶段点座位既不改 `selectedTarget` 也不显示指针；需要目标时只有 `selectable` 里的座位可点，已出局座位永远不可点。→ Task 6 `GameTable` 两条用例。

---

### Task 1: 座位模型 `seatModel`

**Files:**
- Create: `frontend/src/lib/seatModel.ts`
- Test: `frontend/src/lib/seatModel.test.ts`

**Interfaces:**
- Consumes: `rolesKnown`、`currentSpeaker`（`src/engine/select.ts`）；`positions()` 的坐标公式从 `SeatCircle.tsx:28-39` 搬过来（0 号顶部顺时针，半径 41%，保留两位小数）。
- Produces:
  ```ts
  export interface SeatBadges {
    sheriff: boolean;            // state.sheriff_seat === seat
    candidate: boolean;          // SHERIFF_ELECTION/SHERIFF_PK 且 seat ∈ sheriff_candidates 且 ∉ sheriff_withdrawn
    votes: number | null;        // input.votes[seat] > 0 时的票数，否则 null
    mark: "好人" | "狼人" | null; // input.marks[seat]（预言家已验签），缺省 null
    tag: string | null;          // input.tags[seat]（夜间「目标 · 2 票」/「被刀」红签），缺省 null
  }
  export interface SeatModel {
    seat: number; name: string;
    role: RoleType | null;       // 见下方 roleOf
    alive: boolean; me: boolean; speaking: boolean;
    dim: boolean;                // isNight(state.phase) && alive && role === null
    selectable: boolean;         // alive && input.selectable.includes(seat)
    selected: boolean;           // input.selected === seat
    x: number; y: number;        // 百分比坐标
    badges: SeatBadges;
  }
  export interface SeatModelInput {
    state: GameState;
    me?: number | null;
    /** 服务端观察给出的角色覆盖层：{ [seat]: role }。由 GamePage 从 my_role + private.teammates 组装。 */
    knownRoles?: Record<number, RoleType>;
    speaking?: number | null;
    votes?: Record<number, number>;
    marks?: Record<number, "好人" | "狼人">;
    tags?: Record<number, string>;
    selectable?: readonly number[];
    selected?: number | null;
  }
  export function seatPositions(seats: readonly number[]): { seat: number; x: number; y: number }[];
  export function seatModel(input: SeatModelInput): SeatModel[];   // 按 seat 升序
  ```
  - `roleOf(seat)`：`rolesKnown(state)` → `player.role`；否则 `knownRoles[seat] ?? null`。
  - 这是圆桌与 PR ⑤ 卡牌皮肤共用的唯一座位模型。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/lib/seatModel.test.ts
import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../engine/reduce";
import type { GameMeta, GameState } from "../engine/types";
import { seatModel, seatPositions } from "./seatModel";

const meta = fixture.meta as unknown as GameMeta;
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1] as GameState;        // GAME_OVER，角色全知
const night = states.find((s) => s.phase === "NIGHT_WEREWOLF") as GameState;

describe("seatPositions", () => {
  it("0 号在顶部，顺时针等分", () => {
    const p = seatPositions([0, 1, 2, 3]);
    expect(p[0]).toEqual({ seat: 0, x: 50, y: 9 });
    expect(p[1]).toEqual({ seat: 1, x: 91, y: 50 });
  });
});

describe("seatModel（规格 §4.2）", () => {
  it("角色全知：每个座位都有 role，夜间不暗化", () => {
    const m = seatModel({ state: { ...night, players: last.players } });
    expect(m).toHaveLength(9);
    expect(m.every((s) => s.role !== null)).toBe(true);
    expect(m.every((s) => !s.dim)).toBe(true);
  });
  it("角色未知 + knownRoles 覆盖层：只有本人与狼队友亮，其余夜间暗化", () => {
    const blank = initialState(meta);
    const m = seatModel({ state: { ...blank, phase: "NIGHT_WEREWOLF" }, me: 0, knownRoles: { 0: "WEREWOLF", 3: "WEREWOLF" } });
    expect(m[0]?.role).toBe("WEREWOLF");
    expect(m[3]?.role).toBe("WEREWOLF");
    expect(m[1]?.role).toBeNull();
    expect(m[1]?.dim).toBe(true);
    expect(m[0]?.dim).toBe(false);
    expect(m[0]?.me).toBe(true);
  });
  it("白天不暗化；出局座位 alive=false 且永不可选", () => {
    const m = seatModel({ state: last, selectable: last.players.map((p) => p.seat) });
    expect(m.every((s) => !s.dim)).toBe(true);
    const dead = m.filter((s) => !s.alive);
    expect(dead.length).toBeGreaterThan(0);
    expect(dead.every((s) => !s.selectable)).toBe(true);
  });
  it("徽章：警长 / 候选 / 票数 / 已验签 / 夜间红签", () => {
    const st: GameState = { ...last, phase: "SHERIFF_ELECTION", sheriff_seat: 2, sheriff_candidates: [1, 5], sheriff_withdrawn: [5] };
    const m = seatModel({ state: st, votes: { 1: 2.5 }, marks: { 4: "狼人" }, tags: { 7: "被刀" }, selected: 1, selectable: [1] });
    expect(m[2]?.badges.sheriff).toBe(true);
    expect(m[1]?.badges.candidate).toBe(true);
    expect(m[5]?.badges.candidate).toBe(false);
    expect(m[1]?.badges.votes).toBe(2.5);
    expect(m[4]?.badges.mark).toBe("狼人");
    expect(m[7]?.badges.tag).toBe("被刀");
    expect(m[1]?.selected).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Run: `cd frontend && npx vitest run src/lib/seatModel.test.ts` — Expected: FAIL，模块不存在。
- [ ] **Step 3: 实现 `seatModel.ts`**（文件头注释写明零过滤：`knownRoles` 是服务端观察给的数据，不是推断）。
- [ ] **Step 4: 跑测试确认通过** — 同命令 — Expected: PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): seatModel 座位模型（UI 改版 PR ② / 1）"`

---

### Task 2: 村镇选择器 `townNews` / `graveyard`

**Files:**
- Create: `frontend/src/lib/village.ts`
- Test: `frontend/src/lib/village.test.ts`

**Interfaces:**
- Consumes: `Event` 负载类型（`DEATH_ANNOUNCED.seats`、`PLAYER_EXILED.seat`、`HUNTER_SHOT.victim`、`WOLF_SELF_DESTRUCT.seat`、`ROUND_STARTED.round`、`SHERIFF_ELECTED.seat`、`WITCH_POISONED`、`NIGHT_RESOLVED.deaths`）、`rolesKnown`、`aliveSeats`、`wolfSeats`。
- Produces:
  ```ts
  export type DeathCause = "night" | "exiled" | "shot" | "self_destruct";
  export interface GraveRow { seat: number; name: string; role: RoleType | null; round: number; cause: DeathCause; when: string; }
  /** when 文案：night → `第 ${round} 夜死亡`；exiled → `第 ${round} 天放逐`；shot → `第 ${round} 天被带走`；self_destruct → `第 ${round} 天自爆`。 */
  export function graveyard(events: readonly Event[], state: GameState, knownRoles?: Record<number, RoleType>): GraveRow[];  // 按出局事件顺序

  export interface NewsRow { k: string; v: string; tone: "normal" | "wolf" | "gold" | "muted"; }
  /** 行序固定：昨夜（最近一次 DEATH_ANNOUNCED：`平安夜` 或 `N号、M号 死亡`，无则省略）→ 今日（最近一次 PLAYER_EXILED / HUNTER_SHOT / WOLF_SELF_DESTRUCT 且在最近一次 ROUND_STARTED 之后：`N号 被放逐`…，无则省略）→ 警长（`N号` / `无`）→ 存活（`a/n`）→ 阵营（仅 rolesKnown：`狼 k / 好人 m`，tone wolf）。 */
  export function townNews(events: readonly Event[], state: GameState): NewsRow[];
  ```
  - 死亡轮次用事件之前最近一次 `ROUND_STARTED.round`；round 为 0（开局前）按 1。

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/lib/village.test.ts
import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameState } from "../engine/types";
import { graveyard, townNews } from "./village";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1] as GameState;
const upTo = (seq: number): Event[] => events.filter((e) => e.seq <= seq);

describe("graveyard（规格 §4.5）", () => {
  it("按出局顺序列出自爆 / 夜死 / 被带走 / 放逐，角色全知时带 role", () => {
    const rows = graveyard(events, last);
    expect(rows.slice(0, 4).map((r) => [r.seat, r.cause])).toEqual([[6, "self_destruct"], [7, "night"], [4, "shot"], [3, "exiled"]]);
    expect(rows[0]?.when).toMatch(/^第 \d+ 天自爆$/);
    expect(rows[1]?.when).toMatch(/^第 \d+ 夜死亡$/);
    expect(rows.every((r) => r.role !== null)).toBe(true);
  });
  it("角色未知时 role 为 null，knownRoles 可覆盖", () => {
    const blank = { ...last, players: last.players.map((p) => ({ ...p, role: "VILLAGER" as const, faction: "GOOD" as const })) };
    const rows = graveyard(events, blank, { 6: "WEREWOLF" });
    expect(rows[0]?.role).toBe("WEREWOLF");
    expect(rows[1]?.role).toBeNull();
  });
});

describe("townNews", () => {
  it("有死讯的白天：昨夜 / 今日 / 警长 / 存活 / 阵营", () => {
    const st = states.find((s) => s.phase === "DAY_SPEECH" && s.round === 2) as GameState;
    const rows = townNews(upTo(70), st);
    expect(rows.map((r) => r.k)).toEqual(["昨夜", "今日", "警长", "存活", "阵营"]);
    expect(rows[0]?.v).toBe("7号 死亡");
  });
  it("开局前：只有警长与存活", () => {
    const first = states[0] as GameState;
    expect(townNews(upTo(1), first).map((r) => r.k)).toEqual(["警长", "存活"]);
  });
  it("平安夜写「平安夜」", () => {
    const i = events.findIndex((e) => e.type === "DEATH_ANNOUNCED" && (e.payload as { seats: number[] }).seats.length === 0);
    const st = states[i] as GameState;
    expect(townNews(upTo((events[i] as Event).seq), st)[0]).toMatchObject({ k: "昨夜", v: "平安夜" });
  });
});
```

- [ ] **Step 2: 跑测试确认失败** — Run: `cd frontend && npx vitest run src/lib/village.test.ts` — Expected: FAIL。
- [ ] **Step 3: 实现 `village.ts`**（先跑一遍 fixture 核对 seq 45 / 60 / 62 / 80 的 round；若 `states[i]` 与 `events[i]` 不对齐——fixture 的 `states` 是每条事件之后的状态，`states[i]` 对应 `events[i]`——按实际对齐改测试索引，不改语义）。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: Commit** — `"feat(frontend): 村镇公告与墓地选择器（UI 改版 PR ② / 2）"`

---

### Task 3: 桌心内容 `stageContent`

**Files:**
- Create: `frontend/src/lib/stageContent.ts`
- Test: `frontend/src/lib/stageContent.test.ts`

**Interfaces:**
- Consumes: `voteTally` / `sheriffVoteTally` / `nightSummary` / `speechItems` / `currentSpeaker`、`isNight`、`YourTurn`。
- Produces（规格 §4.4 的判别联合，按表格顺序匹配）：
  ```ts
  export interface StageInput {
    state: GameState; events: readonly Event[];       // events 已按回放游标截断
    prompt?: YourTurn | null; selectedTarget?: number | null;
    mode: "live" | "replay"; myRole?: RoleType | null;
  }
  export type StageContent =
    | { kind: "none" }
    | { kind: "wolfCouncil"; proposals: { seat: number; target: number | null }[]; round: number; hint: string }
    | { kind: "witchTarget"; seat: number; name: string; antidote: boolean | null; poison: boolean | null }
    | { kind: "crystal"; seat: number }
    | { kind: "crosshair"; seat: number }
    | { kind: "moon"; sub: string }
    | { kind: "tally"; cast: number; voters: number; rows: { target: number; name: string; votes: number; from: number[] }[]; waiting: number[]; election: boolean }
    | { kind: "pkStage"; a: { seat: number; name: string; votes: number }; b: { seat: number; name: string; votes: number }; cast: number; voters: number }
    | { kind: "bubble"; speaker: number; lastTally: string | null }
    | { kind: "gmNotes"; round: number; rows: NightSummaryRow[] }
    | { kind: "campfire"; note: string };
  export function stageContent(input: StageInput): StageContent;
  ```
  - `wolfCouncil`：夜间且 `Object.keys(state.wolf_proposals).length > 0`；`hint` = `意见不一致会重新提案；第 2 轮仍不一致则空刀。`；
  - `witchTarget`：`phase === "NIGHT_WITCH" && pending_night.wolf_target !== null`，`antidote/poison` 取 `prompt.observation.private.antidote_available / poison_available`（布尔才算，否则 null）；
  - `crystal`：`phase === "NIGHT_SEER" && selectedTarget !== null && myRole === "SEER"`；`crosshair`：`(phase === "NIGHT_HUNTER_CONFIRM" || state.pending_hunter !== null) && selectedTarget !== null && myRole === "HUNTER"`；
  - `gmNotes`：`mode === "replay" && isNight(phase) && nightSummary(events, round).length > 0`（排在 `moon` 之前）；
  - `moon.sub`：`"请闭眼，等待其他角色行动"`；
  - `tally`：`VOTE` / `VOTE_PK`（`tie_round === 0` 或 `vote_candidates.length !== 2` 时）/ `SHERIFF_ELECTION` 且 `election_stage === "vote"`；`pkStage`：`VOTE_PK` 且 `vote_candidates.length === 2`，或 `SHERIFF_PK` 且 `sheriff_candidates.length === 2`（票数取对应 tally）；`voters` = 存活且 `can_vote` 且不在 PK 台上的人数；
  - `bubble`：`DAY_SPEECH` / `LAST_WORDS` / `SHERIFF_PK`（非 vote）/ `SHERIFF_ELECTION` 且 `election_stage === "speech"`，且 `currentSpeaker !== null`；`lastTally` = 上一轮 `VOTE_RESULT` 摘要 `4号 ·4 ← 2 5 9 7 ｜ 8号 ·2 ← 1 3`（没有则 null）；没有发言者则落到 `campfire`；
  - `campfire.note`：`SHERIFF_ELECTION/candidacy` → `上警报名中 · 已上警 ${sheriff_declared.length} 人`；`DEATH_ANNOUNCE` → `公布死讯`；`LOBBY` → `等待开局`；其余 `PHASE_ZH[phase]`。

- [ ] **Step 1: 写失败测试**（用 fixture 的 `states[i]` / `events` 前缀；每个 kind 至少一条，另加 Review Focus 1 / 2）

```ts
it.each([
  ["NIGHT_WEREWOLF 有提案 → wolfCouncil", (s: GameState) => s.phase === "NIGHT_WEREWOLF" && Object.keys(s.wolf_proposals).length > 0, "wolfCouncil"],
  ["VOTE → tally", (s: GameState) => s.phase === "VOTE", "tally"],
  ["DAY_SPEECH 有发言者 → bubble", (s: GameState) => s.phase === "DAY_SPEECH" && s.speech_order.length > 0, "bubble"],
  ["GAME_OVER → none", (s: GameState) => s.phase === "GAME_OVER", "none"],
])("%s", (_n, pick, kind) => { const i = states.findIndex(pick); expect(stageContent({ state: states[i]!, events: upTo(events[i]!.seq), mode: "live" }).kind).toBe(kind); });
it("折叠夜晚 NIGHT（观众）→ moon", () => expect(stageContent({ state: { ...blank, phase: "NIGHT" }, events: [], mode: "live" })).toEqual({ kind: "moon", sub: "请闭眼，等待其他角色行动" }));
it("回放游标 0（LOBBY）→ campfire 等待开局", () => expect(stageContent({ state: blank, events: [], mode: "replay" })).toEqual({ kind: "campfire", note: "等待开局" }));
it("GM 回放夜间有本夜行动 → gmNotes 优先于 moon", …);
it("女巫夜 + 刀口 + 观察里的药瓶 → witchTarget", …);   // 自造 state：phase NIGHT_WITCH, pending_night.wolf_target=5, prompt.private {antidote_available:true, poison_available:false}
it("预言家选中目标 → crystal；非预言家不出现", …);
it("VOTE_PK 两人 → pkStage，票数带小数", …);           // 自造 votes 含警长 1.5
it("bubble.lastTally 取上一轮 VOTE_RESULT", …);
```

- [ ] **Step 2: RED** — `npx vitest run src/lib/stageContent.test.ts`。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: GREEN**。
- [ ] **Step 5: Commit** — `"feat(frontend): stageContent 桌心内容选择器（UI 改版 PR ② / 3）"`

---

### Task 4: 右栏卡片选择 `railCards`

**Files:**
- Create: `frontend/src/lib/railCards.ts`
- Test: `frontend/src/lib/railCards.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type RailCardId = "news" | "graveyard" | "order" | "election" | "votes" | "nightFlow" | "seerLog" | "potions" | "nightActs" | "pkRecap";
  export interface RailInput { state: GameState; events: readonly Event[]; mode: "live" | "replay"; hasPotions: boolean; hasDeaths: boolean; }
  /** 最多 3 张，按规格 §4.5 表格顺序。 */
  export function railCards(input: RailInput): RailCardId[];
  ```
  - 夜间：`["nightActs"（nightSummary 非空）, "potions"（hasPotions && NIGHT_WITCH）, "seerLog"（seer_log 非空）, "nightFlow", "news", "graveyard"]` 取前 3；
  - 竞选 / 警 PK：`["election", "pkRecap"（SHERIFF_PK）, "order"（speech 子阶段）, "news", "graveyard"]`；
  - 投票 / PK / 放逐 / 遗言：`["votes", "pkRecap"（VOTE_PK）, "news", "graveyard"]`；
  - 发言类：`["order", "news", "graveyard"]`；
  - 其它（LOBBY / DEATH_ANNOUNCE / GAME_OVER）：`["news", "graveyard"]`；
  - `graveyard` 只在 `hasDeaths` 时保留；`seerLog` 在任意阶段只要 `seer_log` 非空都排在 `news` 之前。

- [ ] **Step 1: 写失败测试**（每个阶段一条 `it.each`，断言数组；LOBBY 无死亡 → `["news"]`；夜间女巫有药瓶 → 含 `"potions"`；长度 ≤ 3）。
- [ ] **Step 2–5**：RED → 实现 → GREEN → Commit `"feat(frontend): railCards 右栏卡片选择（UI 改版 PR ② / 4）"`。

---

### Task 5: 顶栏 `PhaseBar` 与阶段木牌 `PhasePlaque`

**Files:**
- Create: `frontend/src/components/PhasePlaque/PhasePlaque.tsx`、`PhasePlaque.module.css`、`PhasePlaque.test.tsx`
- Modify: `frontend/src/components/PhaseBar/PhaseBar.tsx`、`PhaseBar.module.css`

**Interfaces:**
- `PhasePlaque`：
  ```ts
  export interface PhasePlaqueProps { state: GameState; events: readonly Event[]; cursor: number | null; total: number; }
  /** 纯函数，导出供测试：第一行 + 第二行文案。 */
  export function plaqueLines(state: GameState, events: readonly Event[], cursor: number | null, total: number): { title: string; sub: string };
  ```
  - `title`：夜间 `第 ${round} 夜 · ${夜间子阶段名}`（`NIGHT_WEREWOLF` → 狼人行动，`NIGHT` → 夜晚，取 `PHASE_ZH` 去掉「夜晚 · 」前缀）；白天 `第 ${round} 轮 · ${PHASE_ZH}`（`DAY_SPEECH` → 白天 · 发言 保持）；`GAME_OVER` → `第 ${round} 轮 · 游戏结束`。
  - `sub` 按规格 §4.1 的阶段表；回放时追加 ` · 回放到 seq ${cursor} / ${total}`（`cursor !== null` 且 `cursor !== total`）。
- `PhaseBar` 新 props：`extra?: ReactNode`（右侧插槽：匿名观众「登录」/ PR ⑤ 皮肤切换）；去掉 `reconnectHint` 单独元素，并入居中状态区文案；居中状态：直播 `● 直播 · seq N`（`.live` 红）/ 回放 `▶ 回放 · N 条事件` / 终局 `— 游戏结束：{WINNER_ZH}胜 —`（`over` 时优先）；连接中 / 断开时居中区写 `连接中…` / `连接已断开 · 重连中`。视角分段沿用 `.seg`，当前项篝火底。

- [ ] **Step 1: 写失败测试**

```ts
// PhasePlaque.test.tsx（只测 plaqueLines）
it("白天发言：标题与副标", () => expect(plaqueLines(daySpeech, [], null, 100)).toEqual({ title: "第 2 轮 · 白天 · 发言", sub: expect.stringMatching(/^(警长 \d+号|无警长) · (顺时针|逆时针) · \d+\/9 存活$/) }));
it("狼人夜：第 N 夜 · 狼人行动，副标「天黑请闭眼 · 狼人请睁眼」", …);
it("折叠夜晚 NIGHT：第 N 夜 · 夜晚", () => expect(plaqueLines({ ...blank, phase: "NIGHT", round: 3 }, [], null, 10).title).toBe("第 3 夜 · 夜晚"));
it("回放时追加 回放到 seq", () => expect(plaqueLines(daySpeech, [], 40, 100).sub).toMatch(/ · 回放到 seq 40 \/ 100$/));
// PhaseBar：现有无测试文件；在 GamePage.test 里靠 `已结束 · N 条事件` 文案匹配 —— 该文案改为 `▶ 回放 · N 条事件`，Task 11 同步更新查询。
```

- [ ] **Step 2–5**：RED → 实现（`PhaseBar.module.css` 改木纹 48px 顶栏，品牌 heading 20px，`game_id` mono） → GREEN → Commit `"feat(frontend): 阶段木牌与木纹顶栏（UI 改版 PR ② / 5）"`。

---

### Task 6: 桌子 `GameTable` + 桌心 `TableCenter` + 气泡 `SpeechBubble`

**Files:**
- Create: `frontend/src/components/GameTable/GameTable.tsx`、`GameTable.module.css`、`GameTable.test.tsx`
- Create: `frontend/src/components/GameTable/TableCenter.tsx`、`TableCenter.test.tsx`（同目录，共用 CSS）
- Create: `frontend/src/components/GameTable/SpeechBubble.tsx`、`SpeechBubble.test.tsx`

**Interfaces:**
- Consumes: Task 1 `SeatModel`、Task 3 `StageContent`、`RoleToken`、`SpeechItem`、`useVoice`（只读 `playing`）。
- Produces:
  ```ts
  export interface GameTableProps {
    seats: SeatModel[];
    night: boolean;                          // 月光调色板
    center: StageContent;
    speech: { items: SpeechItem[]; speaker: number | null; deadline: number | null; now?: () => number } | null;  // bubble 内容
    avatars: Record<number, string>;
    onSelectSeat?(seat: number): void;       // 只对 selectable 座位触发
  }
  export default function GameTable(props: GameTableProps): JSX.Element;
  export function TableCenter({ content, seats }: { content: StageContent; seats: SeatModel[] }): JSX.Element | null;
  export function SpeechBubble({ item, seat, name, kind, deadline, now, voicing, anchor }: { item: SpeechItem | null; seat: number; name: string; kind: "speech" | "last_words" | "campaign"; deadline: number | null; now?: () => number; voicing: boolean; anchor: { x: number; y: number } }): JSX.Element;
  ```
  - 座位 DOM：`<button type="button" class={seat} data-seat data-state … aria-label="N号 name 存活|出局[ 警长][ 发言中]" aria-pressed={selected} disabled={!selectable}>`，内含 `RoleToken size 64 variant="seat"` + 座位号角标 + 名字 + 徽章（候选金签「警」、警长签、票数角标、已验签、红签）；不可选时 `tabIndex=-1` 且 `cursor:default`。
  - 桌子容器 `aspect-ratio: 1`，`width: min(100%, var(--table-max, 560px))`，座位 `left/top` 用百分比。
  - `SpeechBubble` 锚点：`anchor.y < 50` → 气泡在座位下方、箭头朝上；否则在上方箭头朝下；`anchor.x` 决定左右偏移（限制在桌面 8%–92% 内）。正文 = `item.content ?? item.text`，`item === null` 时斜体占位「轮到你发言… / 轮到你时在此陈述竞选理由… / 写下遗言…」按 kind；流式光标 `▍` 只在 `voicing` 时显示；进度条宽度 = 剩余 / 总时限（`deadline` 为空不渲染）。

- [ ] **Step 1: 写失败测试**

```tsx
// GameTable.test.tsx
it("渲染全部座位，selectable 的可点并回调，其余 disabled 不回调", () => {
  const onSelect = vi.fn();
  render(<GameTable seats={seats(/* 0 selectable, 1 not, 2 dead */)} night={false} center={{ kind: "campfire", note: "x" }} speech={null} avatars={{}} onSelectSeat={onSelect} />);
  fireEvent.click(screen.getByRole("button", { name: /^0号/ }));
  fireEvent.click(screen.getByRole("button", { name: /^1号/ }));
  expect(onSelect).toHaveBeenCalledTimes(1);
  expect(onSelect).toHaveBeenCalledWith(0);
  expect(screen.getByRole("button", { name: /^2号.*出局/ })).toBeDisabled();
});
it("徽章：票数 5.5 原样、候选「警」、已验「狼人」", …);
it("夜间 dim 座位带 data-dim", …);
// TableCenter.test.tsx：每个 kind 渲染关键文案（wolfCouncil「狼 队 密 议 · 仅狼可见」/ witchTarget「今 夜 被 刀」/ crystal「查 验」/ crosshair「准 星」/ moon「天黑请闭眼」/ tally「实时票型 · 按被投者分组」+「5.5 票」/ pkStage「VS」/ gmNotes「GM 手记 · 第 N 夜」/ campfire note / none → null）。
// SpeechBubble.test.tsx：无 item 时占位文案按 kind；voicing 时有「正在朗读」；deadline 给进度条 width；anchor.y<50 时 data-side="below"。
```

- [ ] **Step 2–5**：RED → 实现（CSS 按设计稿 3a：桌面径向渐变 `#4a3524 → #2a1d14 70% → #1a110a`、`6px solid var(--ah-wood-edge)`；夜间 `data-night` 换 `--ah-table-night`；篝火 / 月亮装饰层；羊皮纸气泡 `--ah-parch`）→ GREEN → Commit `"feat(frontend): GameTable 全景圆桌、桌心与发言气泡（UI 改版 PR ② / 6）"`。

---

### Task 7: 右栏 `InfoRail` 与六张新卡 + 四张旧卡换皮

**Files:**
- Create: `frontend/src/components/InfoRail/InfoRail.tsx`、`InfoRail.module.css`、`InfoRail.test.tsx`
- Create（同目录）: `TownNews.tsx`、`Graveyard.tsx`、`NightFlow.tsx`、`SeerLog.tsx`、`Potions.tsx`、`PkRecap.tsx`
- Modify: `PlayerStatusPanel.module.css`、`ElectionPanel.module.css`、`VotePanel.module.css`、`NightSummary.module.css`（换成 `.ah-panel` 配色：底 `--ah-panel-glass`、边 `--ah-panel-edge`、标题 11px `--ah-text-muted`、正文 `--ah-text`、签用 `.tag-parch`）；`NightSummary.tsx` 去掉 `viewer` prop（空态副句改为固定「夜间行动仅上帝与行动者可见」）。

**Interfaces:**
```ts
export interface InfoRailProps {
  cards: RailCardId[]; state: GameState; events: readonly Event[];
  speakingSeat: number | null; nightRows: NightSummaryRow[];
  potions?: { antidote: boolean; poison: boolean } | null;
  knownRoles?: Record<number, RoleType>;
}
export default function InfoRail(props: InfoRailProps): JSX.Element;   // <aside aria-label="信息栏">，按 cards 顺序渲染
```
- `TownNews`：`townNews(events, state)` 行，`tone` 映射颜色；标题「村镇公告」+ 右上 `第 ${round} 天`。
- `Graveyard`：`graveyard(events, state, knownRoles)`，每行 `RoleToken size 26`（role 为 null 时 `state="dead"`）+ `{seat} {name} {ROLE_ZH}` + `when`；标题「墓地 · 按出局顺序」。
- `NightFlow`：`config.night_order`（数组才用，否则 `["WEREWOLF","WITCH","SEER","HUNTER"]` 里出现在 `config.roles` 的）→ 行「{ROLE_ZH} · 行动中 / 已行动 / 待行动」，依据当前 `phase` 的 `NIGHT_<ROLE>` 位置；`phase === "NIGHT"` 时全部「进行中」。
- `SeerLog`：`state.seer_log` 全部条目「第 N 夜 · M号 → 好人 / 狼人」（`result === "WOLF"` → 狼人红，否则好人绿）。
- `Potions`：两格「解药 / 毒药」+「未使用 / 已使用」。
- `PkRecap`：PK 双方（`vote_candidates` 或 `sheriff_candidates`）各自最近一条 `SpeechItem`（`kind === "speech"`）正文前 60 字。

- [ ] **Step 1: 写失败测试**（`InfoRail` 按 `cards` 顺序渲染对应标题；`NightFlow` 在 `NIGHT_WITCH` 标狼人已行动 / 女巫行动中；`NIGHT` 折叠不崩；`Graveyard` 未知角色渲染 ✕；`Potions` 已用 / 未用文案；`SeerLog` 颜色 data 属性）。
- [ ] **Step 2–5**：RED → 实现 → GREEN（并跑 `src/components/{PlayerStatusPanel,ElectionPanel,VotePanel,NightSummary}` 现有测试）→ Commit `"feat(frontend): InfoRail 右栏信息卡（UI 改版 PR ② / 7）"`。

---

### Task 8: 事件流抽屉 `EventDrawer`

**Files:**
- Create: `frontend/src/components/EventDrawer/EventDrawer.tsx`、`EventDrawer.module.css`、`EventDrawer.test.tsx`
- Modify: `frontend/src/components/SpeechFeed/SpeechFeed.module.css`（深色行：卡底 `rgba(22,27,40,.6)`、座位徽记 26px 用 `RoleToken`、GM / 系统行 `--ah-text-muted` 斜体、非 PUBLIC 行左边线阵营色）；`SpeechFeed.tsx` 把 `Avatar` 换成 `RoleToken`（role 来自 `state.players` 的 `rolesKnown` 或 `knownRoles` prop，新增可选 prop `knownRoles`）。

**Interfaces:**
```ts
export interface EventDrawerProps { open: boolean; onToggle(): void; tabLabel: string; children: ReactNode; /** <1100px 时并入的上半部分 */ top?: ReactNode; }
export default function EventDrawer(props: EventDrawerProps): JSX.Element;
```
- 28px 竖向页签 `<button aria-expanded={open} aria-controls="event-drawer">{tabLabel} ▸</button>`；打开时 400px 面板 `role="complementary" id="event-drawer"`，Esc 关闭（`onToggle`）。

- [ ] **Step 1: 写失败测试**（页签点击切换 `aria-expanded`；open 时渲染 children；Esc 触发 `onToggle`；`SpeechFeed` 现有 3 条测试仍过）。
- [ ] **Step 2–5**：RED → 实现 → GREEN → Commit `"feat(frontend): 事件流抽屉（UI 改版 PR ② / 8）"`。

---

### Task 9: 底部 HUD（`IdentityCard` + `ActionBar` 受控换皮）与回放绳索（`ReplayBar`）

**Files:**
- Create: `frontend/src/components/IdentityCard/IdentityCard.tsx`、`IdentityCard.module.css`、`IdentityCard.test.tsx`
- Modify: `frontend/src/components/ActionBar/ActionBar.tsx`、`ActionBar.module.css`、`ActionBar.test.tsx`（追加）
- Modify: `frontend/src/components/ReplayBar/ReplayBar.tsx`、`ReplayBar.module.css`、`ReplayBar.test.tsx`（追加）
- Modify: `frontend/src/components/VoiceToggle/VoiceToggle.module.css`（描边胶囊）

**Interfaces:**
```ts
// IdentityCard
export interface IdentityCardProps { seat: number; name: string; role: RoleType | null; alive: boolean; avatar?: string | null; lines: string[]; }
/** 纯函数，导出供测试：按角色与观察生成两行说明（规格 §4.7 左栏）。 */
export function identityLines(role: RoleType | null, obs: PlayerObservation | null, state: GameState): string[];
// ActionBar 新 props（都可选，缺省保持现有内部状态行为，现有 19 条测试不改）
selectedTarget?: number | null; onSelectTarget?(seat: number | null): void;
onSelectableChange?(seats: number[] | null): void;   // 当前分组需要目标时上报可选座位，否则 null
layout?: "panel" | "hud";                              // hud：标题 heading 18px 金 +「点圆桌上的座位选择 · 当前 N号」+ 48px 胶囊；缺省 panel 不变
idleText?: string;                                     // 无 prompt 时的文案（缺省「等待其他玩家…」）；GamePage 传「旁听中」/「天黑请闭眼」
// ReplayBar 新 props
leading?: ReactNode;    // 左侧插槽（观众：语音播报胶囊）
trailing?: ReactNode;   // 右侧插槽（观众：复制分享链接）
```
- `identityLines`：狼 `["队友 3号 · 9号", "目标：屠边" | "目标：屠城"]`（`config.win_condition === "kill_side"` → 屠边，`"kill_all"` → 屠城，其它 → 省略第二行）；预言家 `["已验 N 人 · K 狼", "警徽流 a → b"（本人 `badge_flow_claims` 有才加）]`；女巫 `["解药 n · 毒药 m", "不能自救"]`（`config.witch_self_save === false` 才加第二行；n/m 来自 `private.antidote_available/poison_available`，布尔 → 1/0，缺失省略整行）；猎人 `["可开枪"]`（`private.can_shoot !== false`）；守卫 / 民 / 白痴 `[]`；出局时第一行换「身份不公开」（role null）或保持角色，追加「已出局」由组件标题处理；竞选中 `sheriff_candidates` 含本人追加「已上警 · 可退水」。
- `ActionBar` 受控：`selectedTarget !== undefined` 时目标读写走 props；`useEffect` 在 `[active, night, obs]` 变化时调用 `onSelectableChange(needsTarget ? aliveTargets(...) : null)`。HUD 布局下主按钮文案：`发送发言` / `确认投票 · N号` / `刀 · N号` + `空刀` / `查验 · N号` + `跳过` / `开枪 · N号` + `不开枪` / `留下遗言`（`LAST_WORDS` 用 `.btn-danger`）/ `确认行动`；倒计时条 + mono 秒数放右栏。
- `ReplayBar` 绳索样式：轨道 `repeating-linear-gradient(135deg, var(--ah-wood-edge) 0 6px, var(--ah-wood-hi) 6px 12px)`，已播部分篝火纹理，游标 24px 火把光球；行为与键盘不变。

- [ ] **Step 1: 写失败测试**

```ts
// IdentityCard.test.tsx
it("狼：队友与屠边", () => expect(identityLines("WEREWOLF", obsWith({ teammates: [3, 9] }), stateWith({ win_condition: "kill_side" }))).toEqual(["队友 3号 · 9号", "目标：屠边"]));
it("女巫：药瓶 + 不能自救", …); it("预言家：已验 2 人 · 1 狼", …); it("出局：标题「已出局」+ RoleToken dead", …);
// ActionBar.test.tsx 追加
it("受控目标：点胶囊调用 onSelectTarget，不改内部状态；onSelectableChange 上报可选座位", …);
it("layout=hud：投票主按钮文案「确认投票 · 2号」，无 prompt 时显示 idleText", …);
it("已出局玩家收到 shoot prompt 仍渲染行动区", …);   // Review Focus 3
// ReplayBar.test.tsx 追加
it("leading / trailing 插槽渲染", …);
```

- [ ] **Step 2–5**：RED → 实现 → GREEN（`ActionBar` 全部 22 条 + `ReplayBar` 全部）→ Commit `"feat(frontend): 身份牌、受控 ActionBar 与回放绳索（UI 改版 PR ② / 9）"`。

---

### Task 10: 终局结算 `GameOverScreen`

**Files:**
- Create: `frontend/src/components/GameOverScreen/GameOverScreen.tsx`、`GameOverScreen.module.css`、`GameOverScreen.test.tsx`

**Interfaces:**
```ts
export interface GameOverScreenProps {
  state: GameState; events: readonly Event[]; total: number;
  knownRoles?: Record<number, RoleType>;
  onReplay?(): void;            // 「查看全局回放」；缺省不渲染该按钮
}
export function fateOf(seat: number, events: readonly Event[], state: GameState): string;  // 复用 graveyard：存活 → "存活"，否则 GraveRow.when
export default function GameOverScreen(props: GameOverScreenProps): JSX.Element;
```
- 文案：`第 ${round} 轮 · 游 戏 结 束` / heading 84px `${WINNER_ZH[winner]}胜`（`winner === null` → `平局`）/ `${winner} · ${kill_side ? "屠边成功" : "狼人出清" | 好人胜 → "狼人出清"} · ${total} 条事件`；`data-winner="WOLF|GOOD|TIE"` 切血月 / 金月。
- 揭晓网格：每座位 `RoleToken size 52`（role null → unknown 带首字）+ `{seat} {name}` + `ROLE_ZH`（阵营色）+ `fateOf`。
- 按钮：`.btn-primary`「查看全局回放」（`onReplay` 有时）、`.btn-secondary`「再来一局」`href="#/"`、`.btn-ghost`「回到历史对局」`href="#/history"`。

- [ ] **Step 1: 写失败测试**（狼胜文案与 `data-winner`；角色未知显示「?」；`onReplay` 缺省无按钮；链接 href）。
- [ ] **Step 2–5**：RED → 实现 → GREEN → Commit `"feat(frontend): 终局结算页（UI 改版 PR ② / 10）"`。

---

### Task 11: `GamePage` 换布局接线，删除旧组件

**Files:**
- Modify: `frontend/src/pages/GamePage.tsx`、`GamePage.module.css`、`GamePage.test.tsx`
- Delete: `frontend/src/components/SeatCircle/*`、`SpeakerSpotlight/*`、`NightOverlay/*`（含测试）
- Modify: `frontend/src/components/VoiceToggle/VoiceToggle.tsx`（无改动则略）

**Interfaces（接线决定，全部在 GamePage 内）：**
- 新 state：`selectedTarget: number | null`、`selectable: number[] | null`、`drawerOpen: boolean`。
- `knownRoles`：`useMemo`：`{}` + `myRole && isPlayer ? { [resolvedViewer]: myRole } : {}` + `teammates`（`turnPrompt.observation.private.teammates` 为数组时每个 → `"WEREWOLF"`）。
- `seats = seatModel({ state: view, me, knownRoles, speaking, votes, marks, tags, selectable, selected: selectedTarget })`，其中 `marks` 来自 `view.seer_log` 里本人条目（`result === "WOLF"` → 狼人），`tags`：`NIGHT_WITCH && pending_night.wolf_target !== null` → `{ [target]: "被刀" }`；狼刀阶段 `wolf_proposals` 的多数目标 → `目标 · N 票`。
- `center = stageContent({ state: view, events: visibleEvents, prompt: turnPrompt, selectedTarget, mode, myRole })`；`cards = railCards({...})`；`potions` 从 `turnPrompt.observation.private` 取。
- 布局 `GamePage.module.css`：`grid-template-rows: 48px minmax(0,1fr) auto`；舞台 `grid-template-columns: minmax(0,1fr) 340px 28px`；`data-night` / `data-blood`（`LAST_WORDS` / `VOTE_PK` / 狼胜终局）/ `data-amber`（`HUNTER_SHOOT`）切背景；≥1200 / 1100–1199（右栏 300）/ <1100（右栏隐藏，`InfoRail` 进抽屉 `top`）/ <900（纵向堆叠，HUD 与绳索条 `position: sticky; bottom: 0`）。
- 底部：`isPlayer && !over` → HUD（`IdentityCard` + `ActionBar layout="hud"` + 计时区）；否则绳索条 `ReplayBar`（观众 `leading={<VoiceToggle />}`，分享链接视角 `trailing={复制分享链接按钮}`）。玩家视角的 `VoiceToggle` 放顶栏 `extra`。
- 结算：`over && (mode === "live" || cursor === null || cursor === totalSeq)` 时在舞台上覆盖 `GameOverScreen`（玩家视角传 `onReplay`=现有「查看全局回放」逻辑）；回放游标在中途不覆盖。
- `ActionBar` 的 `idleText`：夜间 `天黑请闭眼`，PK 本人在台上 `等待裁决`，其余 `旁听中`。
- 移除 `NightOverlay`、`SeatCircle`、`SpeakerSpotlight` 的 import 与渲染；`spotlight` 逻辑保留为 `speaking` / `voicing` 传给 `SpeechBubble.voicing`。

- [ ] **Step 1: 更新 `GamePage.test.tsx` 的查询并写新用例（先跑确认 RED）**
  - `已结束 · N 条事件` → `▶ 回放 · N 条事件`；「旁白中 🔊」改为断言 `SpeechBubble` 不渲染且顶栏状态含「旁白」→ 简化为：`voicingActor === "GM"` 时 `screen.queryByRole("status", { name: /发言中/ })` 为空；`我是 2号` → 身份牌 `screen.findByText("2号 · P2")`；`请闭眼，等待其他角色行动` → 桌心 `moon` 文案不变；「查看全局回放」按钮不变。
  - 新增：`桌上点可选座位 → ActionBar 胶囊同步选中（aria-pressed）`；`回放游标拖到中段不显示结算页，拖到末尾显示`；`<1100px 不断言布局`（jsdom 不测媒体查询）；`零过滤 grep` 作为 Step 4 的 shell 断言。
- [ ] **Step 2: 实现接线与 CSS；删除旧组件。**
- [ ] **Step 3: 跑** `npx vitest run src/pages/GamePage.test.tsx` → PASS；
- [ ] **Step 4: 全量** `npm run check` → PASS；`grep -rn "viewer" frontend/src/components/{GameTable,InfoRail,GameOverScreen} frontend/src/lib/{seatModel,stageContent,railCards,village}.ts` → 无输出；`grep -rn "SeatCircle\|SpeakerSpotlight\|NightOverlay" frontend/src` → 无输出。
- [ ] **Step 5: Commit** — `"feat(frontend): 对局页换成全景圆桌布局，删除 SeatCircle / SpeakerSpotlight / NightOverlay（UI 改版 PR ② / 11）"`

---

### Task 12: e2e 回归脚本、截图与 PR

**Files:**
- Create: `frontend/e2e/README.md`、`frontend/e2e/package.json`、`frontend/e2e/play.mjs`（从旧 scratchpad `scratchpad/e2e/play2.mjs` 整理：去掉绝对路径与账号硬编码，改成环境变量 `AH_BASE_URL` / `AH_USER` / `AH_PASS` / `AH_SEED` / `AH_PRESET`；角色感知逻辑保留；选择器改成本 PR 的 DOM：座位 `button[data-seat]`、HUD 主按钮按文案）、`frontend/e2e/screens.mjs`（按视角 × 阶段截图）
- Create: `docs/design/ui-gamified-2026-10-28/03-*.png`、`04-*.png`、`05-*.png`（命名沿用 `docs/design/ui-baseline-2026-10-27/README.md` 的编号）+ README 追加表格行
- `.gitignore`：`frontend/e2e/node_modules/`

- [ ] **Step 1:** 复制并改造 `play2.mjs` → `frontend/e2e/play.mjs`；`cd frontend/e2e && npm i`；后端与 `npm run dev` 在跑的前提下，按 memory 里的 seed 表（`std_12_yn_hunter_idiot`：IDIOT 1 / WEREWOLF 2 / VILLAGER 3 / WITCH 4 / HUNTER 9 / SEER 22）跑狼 / 预言家 / 女巫 / 猎人 / 民五局，每局输出 `SUMMARY` JSON；Expected: 五局全部 `"finished": true` 且无 `WRONG_PHASE` 类拒绝。
- [ ] **Step 2:** `screens.mjs` 截：玩家视角（白天发言轮到我 / 旁听 / 投票 / PK / 遗言 / 狼刀 / 预言家 / 女巫 / 猎人 / 结算）、上帝直播（夜晚 / 发言 / 投票 / 竞选）、观众直播（同四张）、回放中段与终局；并排对照 `options/3a 3d 4b 4c 4d 5a 5b 5c 7a 7b 7c 7d 1i.html`，偏差就地改 CSS，再跑 `npm run check`。
- [ ] **Step 3:** 1100px 与 390px 各截一张对局页，确认右栏入抽屉、HUD sticky、无横向滚动（`document.documentElement.scrollWidth === 390`）。
- [ ] **Step 4:** 提交截图与 README；`git push -u origin feat/ui-gamified-2-game`；`gh pr create`（描述：范围、截图、规格章节、验收命令、依赖 #169 的说明、执行中的裁定），末尾 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`。
