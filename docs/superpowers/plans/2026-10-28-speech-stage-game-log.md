# 发言台 / 对局记录（发言阶段重排）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对局页去掉座位气泡，座位加状态行；右栏改成「发言台」（当前发言人 + 正文）在上、「对局记录」（全部可见事件倒序、按日夜分隔、可过滤）在下；桌心一行发言进度；回放静音时按阅读时长停留。

**Architecture:** 三个新纯选择器进 `src/lib/`：`dayScan`（日夜标签，只从事件流推导）、`gameLog.logEntries`（事件 → 记录条目）、`seatStatus`（座位状态行）；`stageContent` 的 `bubble` 分支换成 `speechProgress`。两个新组件 `SpeakerStand`、`GameLog` 只收 state / events / avatars / knownRoles / meta.agents 派生数据，不收 viewer。`GamePage` 右栏改两段 grid，宽屏删抽屉页签，窄屏抽屉复用同一右栏。回放门控扩成「有配音播配音，否则按字数 sleep」，暂停 / 拖动取消 sleep。

**Tech Stack:** React 18 + TypeScript strict、CSS Modules、zustand、Vitest + Testing Library；复用 `RoleToken`、`InfoRail`、`EventDrawer`、`seatModel`、`speechItems` / `currentSpeechItem`、`townNews`、`voteTally` / `sheriffVoteTally`、`useVoice`、`useGameStore.setReplayGate`。

**Spec:** `docs/superpowers/specs/2026-10-28-speech-stage-game-log-design.md`（R1–R12 为已确认裁定；§13 四项用户已确认「照规格做」）。设计稿 `docs/design/gamified-2026-10-27/options/{8a,8b,8c}.html`。

## Global Constraints

- 分支 `feat/ui-speech-stage-log`（已存在，含设计导入与规格两个提交，草稿 PR #190）；每个任务结束 `cd frontend && npm run check` 必须绿，用 `$?` 判定（`echo "exit=$?"`）。
- 零过滤：`SpeakerStand` / `GameLog` / `lib/gameLog.ts` / `lib/seatStatus.ts` / `lib/dayScan.ts` 的参数与 props 里没有 `viewer`；检查项 `grep -rn "viewer" src/components/SpeakerStand src/components/GameLog src/lib/gameLog.ts src/lib/seatStatus.ts src/lib/dayScan.ts` 为空。`mine` 由 GamePage 推出后作为 boolean 传入。
- 日夜标签只从事件流推导（R12），`logEntries(events, state)` 对同一份事件流给同一份结果；不读 `state.round`。
- 时间列显示 `#seq` mono，不显示钟点（R4）。
- 过滤页签文案：全部 / 发言 / 投票 / 夜晚 / 验人（仅当有 `SEER_CHECKED` 条目）（R5）。
- 发言台文案：胶囊「发言中 / 竞选发言 / 遗言」「轮到你」；占位「正在组织语言…」；本人占位沿用 `SpeechBubble.PLACEHOLDER` 三句；底行「之后 {a}号 → {b}号」/「最后一位 · 发完即进入投票」（kind=speech）/「最后一位 · 发完即进入下一阶段」；8b 提示「本轮自称：5号 警长、2号 预言家」/「本轮尚无人声明身份」（R6）。
- 模型行「{model} · 声线：{voice}」只在 `meta.agents[String(seat)]` 存在时渲染；model 去掉 `provider/` 前缀；voice：`preset` → `speaker`，`design` → 「定制」，无 voice → 「不配音」（R7）。
- 座位状态行文案（R11）：出局 / 发言中 / 已发言 / 待发言 / 已投 {t}号 / 弃票 / 未投 / PK 中 / 无票 / 上警 / 退水 / 空串；`data-tone` ∈ now / done / wait / dead / none。
- 桌心两行：「昨夜 {lastNight} · 昨日票型 {lastTally}」「发言进度 {done} / {total} · 下一位 {next}号 | · 最后一位」。
- 阅读停留：`clamp(1500 + content.length * 150, 1500, 30000) / speed` 毫秒，仅 `PLAYER_SPOKE` / `LAST_WORDS`（R9）。
- 布局：`.stage` 列 `minmax(0,1fr) minmax(400px, 42%)`（1100–1199px：`minmax(360px, 40%)`；<1100px：`minmax(0,1fr) 28px` + 抽屉）；`.rail` `grid-template-rows: auto minmax(0,1fr); gap 12px; padding-top 0`；`.railTop` `max-height: 48%`（R10）。
- `railCards` 删 `"order"`，`MAX_CARDS = 2`；删除 `SpeechBubble`、`SpeechFeed`、`PlayerStatusPanel`（含测试与 CSS）。
- 中文注释 / 英文标识符；纯函数进 `src/lib/`；CSS Module 组合全局类用 `:global()`（`src/styles/cssModules.test.ts` 守卫）。
- 提交信息用中文，结尾 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`；不本地合并 main，不 push 到 main。

## Review Focus

1. 直播玩家视角（事件流无 `ROUND_STARTED` / 夜间 `PHASE_CHANGED`）：预言家的 `SEER_CHECKED` 必须落在「第 N 夜」而不是「开局」，且与上帝流同一标签 —— Task 1 测试（过滤 GM_ONLY 后逐条比对）。
2. 配音正在读上一位（`voicingSeq` 指向上一位的 seq）而 `speech_idx` 已到下一位：发言台显示上一位 + 正文 + 音柱，座位状态行上一位「发言中」、下一位「待发言」—— Task 3 测试（`speaking` 与 `speech_idx` 不一致时的状态）与 Task 9 GamePage 测试。
3. 回放暂停 / 拖动时正在阅读等待：等待必须立即结束，否则恢复播放后时钟卡住到 30 s —— Task 5 测试（`onPause` 后 gate promise 立即 resolve）。
4. 观众 / 玩家的 `meta.agents` 为 `{}`、GM 的档案没有 `voice`：模型行不渲染 / 写「不配音」，不抛错 —— Task 6 测试。
5. 卡牌皮肤 + 发言阶段：牌底状态行与牌阵下一行进度同时出现，不再有横向发言条；9 人局最后一行 1 张牌不错位 —— Task 8 测试。

---

### Task 1: 日夜扫描 `dayScan`

**Files:**
- Create: `frontend/src/lib/dayScan.ts`
- Test: `frontend/src/lib/dayScan.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type DayKind = "start" | "night" | "day";
  export interface DayMark { kind: DayKind; n: number }
  /** 夜间组事件类型（也是 gameLog 的 night 分组）。 */
  export const NIGHT_EVENT_TYPES: ReadonlySet<EventType>; // GUARD_PROTECTED WOLF_KILL_PROPOSED WOLF_KILL_DECIDED WOLF_KILL_REVOTE WITCH_SAVED WITCH_POISONED WITCH_POTION_CONSUMED NIGHT_RESOLVED SEER_CHECKED
  export function dayLabel(m: DayMark): string; // start→「开局」 night→「第 N 夜」 day→「第 N 天」
  /** 与 events 等长：第 i 项是「应用了 events[i] 之后」生效的日夜。 */
  export function dayMarks(events: readonly Event[]): DayMark[];
  ```
  规则（规格 §6.1）：初值 `{start,0}`；`ROUND_STARTED` → `{night, payload.round}`；`PHASE_CHANGED` 且 `isNight(to)` 且 `cur.kind!=="night"` → `{night, cur.n+1}`；`NIGHT_EVENT_TYPES` 且 `cur.kind!=="night"` → `{night, cur.n+1}`；`DEATH_ANNOUNCED` 或 `PHASE_CHANGED` 且 `!isNight(to)` → night→`{day, n}`，start→`{day, 1}`，day 不变。

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/dayScan.test.ts
import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event, RoundStartedPayload } from "../engine/types";
import { dayLabel, dayMarks } from "./dayScan";

const events = fixture.events as unknown as Event[];

describe("dayScan（规格 R12 / §6.1）", () => {
  it("上帝全量流：ROUND_STARTED 开夜、DEATH_ANNOUNCED 开天、开局前为 start", () => {
    const marks = dayMarks(events);
    expect(marks).toHaveLength(events.length);
    expect(marks[0]).toEqual({ kind: "start", n: 0 });
    events.forEach((e, i) => {
      if (e.type === "ROUND_STARTED") {
        expect(marks[i]).toEqual({ kind: "night", n: (e.payload as RoundStartedPayload).round });
      }
      if (e.type === "DEATH_ANNOUNCED") expect(marks[i]?.kind).toBe("day");
    });
    const rounds = events.filter((e) => e.type === "ROUND_STARTED").length;
    expect(marks.filter((m) => m.kind === "day").map((m) => m.n)).toContain(rounds);
  });

  it("玩家直播流（无 GM_ONLY）：非 GM_ONLY 事件的日夜与全量流逐条相同，SEER_CHECKED 在夜里", () => {
    const full = new Map(events.map((e, i) => [e.seq, dayMarks(events)[i]]));
    const visible = events.filter((e) => e.visibility !== "GM_ONLY");
    const marks = dayMarks(visible);
    visible.forEach((e, i) => expect(marks[i]).toEqual(full.get(e.seq)));
    const seer = visible.findIndex((e) => e.type === "SEER_CHECKED");
    expect(seer).toBeGreaterThan(-1);
    expect(marks[seer]?.kind).toBe("night");
  });

  it("观众流（只剩 PUBLIC）：第一夜无可见事件，天亮直接开第 1 天", () => {
    const pub = events.filter((e) => e.visibility === "PUBLIC");
    const marks = dayMarks(pub);
    const firstDawn = pub.findIndex((e) => e.type === "DEATH_ANNOUNCED");
    expect(marks[firstDawn]).toEqual({ kind: "day", n: 1 });
    expect(marks[firstDawn - 1]?.kind).not.toBe("day");
  });

  it("dayLabel 文案", () => {
    expect(dayLabel({ kind: "start", n: 0 })).toBe("开局");
    expect(dayLabel({ kind: "night", n: 2 })).toBe("第 2 夜");
    expect(dayLabel({ kind: "day", n: 2 })).toBe("第 2 天");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/dayScan.test.ts`
Expected: FAIL — `Cannot find module './dayScan'`

- [ ] **Step 3: Implement `dayScan.ts`** per the Interfaces block（`isNight` 来自 `../engine/phases`）。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/dayScan.test.ts`
Expected: PASS 4/4。若第三条在观众流里 `marks[firstDawn-1]` 已是 day（公开的 `PHASE_CHANGED to DEATH_ANNOUNCE` 先到），把断言改成「`firstDawn` 之前第一条 kind 为 day 的 mark 的 n 为 1」——两者都符合规格。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/dayScan.ts frontend/src/lib/dayScan.test.ts
git commit -m "feat(frontend): dayScan——只从事件流推导第 N 天 / 第 N 夜（规格 R12）"
```

---

### Task 2: 记录条目选择器 `logEntries`

**Files:**
- Create: `frontend/src/lib/gameLog.ts`
- Modify: `frontend/src/engine/select.ts:365`（`function renderEventText` → `export function renderEventText`）
- Test: `frontend/src/lib/gameLog.test.ts`

**Interfaces:**
- Consumes: Task 1 `dayMarks`、`dayLabel`、`NIGHT_EVENT_TYPES`；`select.renderEventText(e: Event): string`；`select.speechItems`（取 `claim` / `badgeFlow` / `content` 的同一套 payload 读法）。
- Produces:
  ```ts
  export type LogGroup = "speech" | "vote" | "night" | "seer" | "flow";
  export interface LogSpeech { content: string; claim: RoleType | null; badgeFlow: number[]; kind: "speech" | "last_words" }
  export interface LogEntry {
    seq: number; type: EventType; group: LogGroup; label: string; color: string; text: string;
    actor_seat: number | null; visibility: Visibility; speech?: LogSpeech; day: string;
  }
  /** 倒序（最新在上）；跳过 ROUND_STARTED / PHASE_CHANGED / VOTE_STARTED。 */
  export function logEntries(events: readonly Event[]): LogEntry[];
  /** 与 entries[0] 同一 day 的发言条目的自称，按座位去重保留最新，按座位升序。 */
  export function currentClaims(entries: readonly LogEntry[]): [number, RoleType][];
  ```
  （`state` 参数在规格里保留给未来；本任务不需要，签名只收 `events`。）
  `label` / `group` / `color` 表与 `text` 清洗规则按规格 §6.1：`text = renderEventText(e).replace(/^(【[^】]*】|\[GM\] |\s+|💥 )+/, "")`；`VOTE_RESULT` 的 `text` 自己拼：`tally.map(([t,n]) => `${t}号 ·${n}`).join(" ｜ ") + (exiled !== null ? ` → ${exiled}号 出局` : ` → 平票 ${tie_seats.map(s=>`${s}号`).join("、")}`)`；`SHERIFF_CANDIDACY` 且 `running === false` 的 label 为「不上警」。

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/gameLog.test.ts
import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event } from "../engine/types";
import { currentClaims, logEntries } from "./gameLog";

const events = fixture.events as unknown as Event[];

describe("logEntries（规格 §6.1）", () => {
  const entries = logEntries(events);

  it("倒序、跳过 ROUND_STARTED / PHASE_CHANGED / VOTE_STARTED，其余事件一条不少", () => {
    const kept = events.filter(
      (e) => !["ROUND_STARTED", "PHASE_CHANGED", "VOTE_STARTED"].includes(e.type),
    );
    expect(entries.map((x) => x.seq)).toEqual(kept.map((e) => e.seq).reverse());
  });

  it.each<[string, string, string]>([
    ["PLAYER_SPOKE", "发言", "speech"],
    ["LAST_WORDS", "遗言", "speech"],
    ["VOTE_CAST", "投票", "vote"],
    ["VOTE_RESULT", "票型", "vote"],
    ["PLAYER_EXILED", "放逐", "vote"],
    ["SHERIFF_CANDIDACY", "上警", "vote"],
    ["ELECTION_STAGE_CHANGED", "竞选", "vote"],
    ["SHERIFF_BADGE_LOST", "警徽", "vote"],
    ["DEATH_ANNOUNCED", "天亮", "flow"],
    ["HUNTER_SHOT", "开枪", "flow"],
    ["WOLF_SELF_DESTRUCT", "自爆", "flow"],
    ["WOLF_KILL_PROPOSED", "刀口", "night"],
    ["NIGHT_RESOLVED", "结算", "night"],
    ["SEER_CHECKED", "验人", "seer"],
    ["ROLES_ASSIGNED", "发牌", "flow"],
    ["GAME_OVER", "终局", "flow"],
  ])("%s → 签「%s」分组 %s", (type, label, group) => {
    const x = entries.find((e) => e.type === type && !(type === "SHERIFF_CANDIDACY" && label === "上警" && e.label === "不上警"));
    expect(x).toBeDefined();
    expect(x!.label).toBe(label);
    expect(x!.group).toBe(group);
  });

  it("正文去掉【…】/ [GM] / 缩进前缀；发言条目带 speech 字段", () => {
    for (const x of entries) {
      expect(x.text).not.toMatch(/^(【|\[GM\]|\s|💥)/);
    }
    const sp = entries.find((e) => e.type === "PLAYER_SPOKE")!;
    expect(sp.speech?.kind).toBe("speech");
    expect(sp.speech?.content.length).toBeGreaterThan(0);
    const vr = entries.find((e) => e.type === "VOTE_RESULT")!;
    expect(vr.text).toMatch(/^\d+号 ·[\d.]+/);
    expect(vr.text).toMatch(/→ (\d+号 出局|平票)/);
  });

  it("day 标签：SEER_CHECKED 在「第 N 夜」，PLAYER_SPOKE 在「第 N 天」，开局事件在「开局」", () => {
    expect(entries.find((e) => e.type === "SEER_CHECKED")!.day).toMatch(/^第 \d+ 夜$/);
    expect(entries.find((e) => e.type === "PLAYER_SPOKE")!.day).toMatch(/^第 \d+ 天$/);
    expect(entries.find((e) => e.type === "GAME_CREATED")!.day).toBe("开局");
  });

  it("过滤掉 GM_ONLY 的流：公开条目的 day 与全量流相同", () => {
    const full = new Map(entries.map((x) => [x.seq, x.day]));
    for (const x of logEntries(events.filter((e) => e.visibility !== "GM_ONLY"))) {
      expect(x.day).toBe(full.get(x.seq));
    }
  });

  it("currentClaims：只取最新一天的发言自称，按座位去重", () => {
    const claims = currentClaims(entries);
    const day = entries[0]!.day;
    const expected = new Map<number, string>();
    for (const x of [...entries].reverse()) {
      if (x.day === day && x.speech?.kind === "speech" && x.speech.claim && x.actor_seat !== null) {
        expected.set(x.actor_seat, x.speech.claim);
      }
    }
    expect(claims).toEqual([...expected.entries()].sort((a, b) => a[0] - b[0]));
    expect(currentClaims([])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/gameLog.test.ts`
Expected: FAIL — `Cannot find module './gameLog'`

- [ ] **Step 3: Export `renderEventText` from `select.ts`; implement `gameLog.ts`** with a `const LABELS: Record<EventType, {label, group, color}>`-style table（未列入规格的类型落 flow / `--ah-text-muted`）。若 fixture 里某个 `it.each` 行的事件类型不存在（如 `SHERIFF_BADGE_LOST`），先用 `grep -c` 核对 `std_9_kill_all-3.json`，确实没有则换 `std_9_kill_side-3.json` 里有的类型或删掉该行，并在提交信息里说明。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/gameLog.test.ts src/engine`
Expected: 全部 PASS（`select.ts` 只是导出，engine 测试不变）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/gameLog.ts frontend/src/lib/gameLog.test.ts frontend/src/engine/select.ts
git commit -m "feat(frontend): logEntries——对局记录条目（分组 / 签 / 日夜 / 自称）"
```

---

### Task 3: 座位状态行 `seatStatus` + `SeatModel.status`

**Files:**
- Create: `frontend/src/lib/seatStatus.ts`
- Modify: `frontend/src/lib/seatModel.ts`（`SeatModel.status`、`SeatModelInput.voteTargets`）、`frontend/src/lib/tableText.ts:8-13`（`seatLabel` 用 `status.text`）
- Test: `frontend/src/lib/seatStatus.test.ts`；更新 `frontend/src/lib/seatModel.test.ts`、`frontend/src/lib/tableText.test.ts`（若存在）

**Interfaces:**
- Produces:
  ```ts
  export type SeatStatusTone = "now" | "done" | "wait" | "dead" | "none";
  export interface SeatStatus { text: string; tone: SeatStatusTone }
  export interface SeatStatusInput {
    speaking: number | null;
    /** voter → target（null = 弃票）；非投票阶段传 {}。 */
    voteTargets: Record<number, number | null>;
  }
  export function seatStatus(state: GameState, seat: number, input: SeatStatusInput): SeatStatus;
  ```
  `SeatModel` 增加 `status: SeatStatus`；`SeatModelInput` 增加 `voteTargets?: Record<number, number | null>`（缺省 `{}`），`seatModel` 内部调 `seatStatus`。`seatLabel`：`发言中` 一项改为 `status.text` 非空时追加。
  规则见规格 §4.1（发言类 / 投票类 / 报名 / 其它 / 出局）。SHERIFF_PK：`election_stage === "speech"` 走发言类，`"vote"` 走投票类。

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/seatStatus.test.ts
import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_all-3.json";
import type { GameState } from "../engine/types";
import { seatStatus } from "./seatStatus";

const states = fixture.states as unknown as GameState[];
const pick = (f: (s: GameState) => boolean): GameState => {
  const s = states.find(f);
  if (!s) throw new Error("fixture 里没有这样的状态");
  return s;
};

describe("seatStatus（规格 §4.1 / R11）", () => {
  it("发言阶段：speaking 优先；speech_idx 之前已发言、之后待发言；不在顺序里为空", () => {
    const s = pick((x) => x.phase === "DAY_SPEECH" && x.speech_idx >= 1 && x.speech_order.length > 2);
    const prev = s.speech_order[s.speech_idx - 1]!;
    const cur = s.speech_order[s.speech_idx]!;
    const later = s.speech_order[s.speech_order.length - 1]!;
    // 配音还在读上一位：上一位「发言中」、轮到的那位「待发言」
    expect(seatStatus(s, prev, { speaking: prev, voteTargets: {} })).toEqual({ text: "发言中", tone: "now" });
    expect(seatStatus(s, cur, { speaking: prev, voteTargets: {} })).toEqual({ text: "待发言", tone: "wait" });
    // 静音：轮到谁谁「发言中」，上一位「已发言」
    expect(seatStatus(s, cur, { speaking: cur, voteTargets: {} })).toEqual({ text: "发言中", tone: "now" });
    expect(seatStatus(s, prev, { speaking: cur, voteTargets: {} })).toEqual({ text: "已发言", tone: "done" });
    expect(seatStatus(s, later, { speaking: cur, voteTargets: {} }).text).toBe("待发言");
    const outside = s.players.find((p) => p.alive && !s.speech_order.includes(p.seat));
    if (outside) expect(seatStatus(s, outside.seat, { speaking: cur, voteTargets: {} })).toEqual({ text: "", tone: "none" });
  });

  it("出局永远「出局」", () => {
    const s = pick((x) => x.players.some((p) => !p.alive) && x.phase === "DAY_SPEECH");
    const dead = s.players.find((p) => !p.alive)!;
    expect(seatStatus(s, dead.seat, { speaking: dead.seat, voteTargets: {} })).toEqual({ text: "出局", tone: "dead" });
  });

  it("投票阶段：已投 / 弃票 / 未投 / 无票", () => {
    const s = pick((x) => x.phase === "VOTE");
    const voters = s.players.filter((p) => p.alive && p.can_vote).map((p) => p.seat);
    const [a, b, c] = voters;
    expect(seatStatus(s, a!, { speaking: null, voteTargets: { [a!]: c! } })).toEqual({ text: `已投 ${c}号`, tone: "done" });
    expect(seatStatus(s, b!, { speaking: null, voteTargets: { [b!]: null } })).toEqual({ text: "弃票", tone: "done" });
    expect(seatStatus(s, c!, { speaking: null, voteTargets: {} })).toEqual({ text: "未投", tone: "wait" });
    const noVote = { ...s, players: s.players.map((p) => (p.seat === a ? { ...p, can_vote: false } : p)) };
    expect(seatStatus(noVote, a!, { speaking: null, voteTargets: {} })).toEqual({ text: "无票", tone: "none" });
  });

  it("PK 投票：候选人「PK 中」", () => {
    const s = pick((x) => x.phase === "VOTE_PK" && x.vote_candidates.length === 2);
    expect(seatStatus(s, s.vote_candidates[0]!, { speaking: null, voteTargets: {} })).toEqual({ text: "PK 中", tone: "now" });
  });

  it("竞选报名：上警 / 退水 / 空", () => {
    const s = pick((x) => x.phase === "SHERIFF_ELECTION" && x.election_stage === "candidacy" && x.sheriff_declared.length > 0);
    const up = s.sheriff_declared.find((d) => !s.sheriff_withdrawn.includes(d))!;
    expect(seatStatus(s, up, { speaking: null, voteTargets: {} })).toEqual({ text: "上警", tone: "now" });
    const withdrawn = { ...s, sheriff_withdrawn: [up] };
    expect(seatStatus(withdrawn, up, { speaking: null, voteTargets: {} })).toEqual({ text: "退水", tone: "done" });
  });

  it("夜间与公布死讯：空", () => {
    const n = pick((x) => x.phase === "NIGHT_WEREWOLF");
    expect(seatStatus(n, n.players[0]!.seat, { speaking: null, voteTargets: {} })).toEqual({ text: "", tone: "none" });
  });
});
```

若 fixture 里没有 `VOTE_PK` 状态，改用 `std_9_kill_side-3.json` 或构造 `{ ...s, phase: "VOTE_PK", vote_candidates: [a, b] }`。

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/seatStatus.test.ts`
Expected: FAIL — `Cannot find module './seatStatus'`

- [ ] **Step 3: Implement `seatStatus.ts`; wire into `seatModel` and `seatLabel`.** 在 `seatModel.test.ts` 加一条：发言阶段 `speaking` 座位的 `status.text === "发言中"`，出局座位 `"出局"`；`tableText` 的 `seatLabel` 测试（若有）里 `发言中` 来自 `status`。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/seatStatus.ts frontend/src/lib/seatStatus.test.ts frontend/src/lib/seatModel.ts frontend/src/lib/seatModel.test.ts frontend/src/lib/tableText.ts
git commit -m "feat(frontend): seatStatus——座位状态行（发言 / 投票 / 竞选 / 出局）进 SeatModel"
```

---

### Task 4: 桌心 `speechProgress`（替代 `bubble`）

**Files:**
- Modify: `frontend/src/lib/stageContent.ts`（`StageContent` 联合、`lastVoteSummary` 拆成 `lastVoteTally`、发言类分支）、`frontend/src/components/GameTable/TableCenter.tsx:24-31`、`frontend/src/components/GameTable/CardBoard.tsx:44-47`（`showCenter`）
- Test: `frontend/src/lib/stageContent.test.ts`（`bubble` 两处用例改写）、`frontend/src/components/GameTable/TableCenter.test.tsx`（加一条）

**Interfaces:**
- Produces:
  ```ts
  | { kind: "speechProgress"; lastNight: string | null; lastTally: string | null;
      done: number; total: number; next: number | null }
  ```
  `lastNight`：`townNews(events, state)` 里 `k === "昨夜"` 的 `v`；`lastTally`：上一轮 `VOTE_RESULT.tally` → `4号 ·4 ｜ 8号 ·2`（无投票人）；`done = state.speech_idx`、`total = state.speech_order.length`、`next = state.speech_order[state.speech_idx + 1] ?? null`。`speaker` 字段删除（发言台由 GamePage 的 `speaking` 决定）。
  `TableCenter` 的 `speechProgress` 分支：`.center.centerLow` 容器，两行 `.progressLine`（11px/1.7 `--ah-text-dim`），第一行在 `lastNight`、`lastTally` 都为 null 时不渲染；`lastNight === "平安夜"` 用 `--ah-ok`，否则 `--ah-wolf`；第二行 `done` 用 `<b>` 金色。`CardBoard.showCenter`：`speechProgress` 永远 true，一行用 ` · ` 连接。

- [ ] **Step 1: Write the failing tests**

在 `stageContent.test.ts`：把 `"DAY_SPEECH 有发言者 → bubble"` 的期望改为 `"speechProgress"`；把 `bubble.lastTally` 用例改为：

```ts
  it("speechProgress：昨夜 / 上一轮票型 / 发言进度", () => {
    const { state, events: ev } = at((s) => s.phase === "DAY_SPEECH" && s.round === 3);
    const c = stageContent({ state, events: ev, mode: "live" });
    expect(c.kind).toBe("speechProgress");
    if (c.kind === "speechProgress") {
      expect(c.lastTally).toMatch(/^\d+号 ·[\d.]+( ｜ \d+号 ·[\d.]+)*$/);
      expect(c.lastNight === "平安夜" || /死亡$/.test(c.lastNight ?? "")).toBe(true);
      expect(c.done).toBe(state.speech_idx);
      expect(c.total).toBe(state.speech_order.length);
      expect(c.next).toBe(state.speech_order[state.speech_idx + 1] ?? null);
    }
  });
  it("speechProgress：第 1 轮没有票型时 lastTally 为 null", () => {
    const { state, events: ev } = at((s) => s.phase === "DAY_SPEECH" && s.round === 1);
    const c = stageContent({ state, events: ev, mode: "live" });
    expect(c.kind === "speechProgress" && c.lastTally).toBeNull();
  });
```

在 `TableCenter.test.tsx` 加：

```ts
  it("speechProgress 渲染两行；无昨夜与票型时只剩进度行", () => {
    render(<TableCenter content={{ kind: "speechProgress", lastNight: "平安夜", lastTally: "4号 ·4 ｜ 8号 ·2", done: 6, total: 9, next: 8 }} seats={[]} />);
    expect(screen.getByText(/昨夜/)).toHaveTextContent("昨夜 平安夜 · 昨日票型 4号 ·4 ｜ 8号 ·2");
    expect(screen.getByText(/发言进度/)).toHaveTextContent("发言进度 6 / 9 · 下一位 8号");
    cleanup();
    render(<TableCenter content={{ kind: "speechProgress", lastNight: null, lastTally: null, done: 9, total: 9, next: null }} seats={[]} />);
    expect(screen.queryByText(/昨夜/)).toBeNull();
    expect(screen.getByText(/发言进度/)).toHaveTextContent("发言进度 9 / 9 · 最后一位");
  });
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/stageContent.test.ts src/components/GameTable/TableCenter.test.tsx`
Expected: FAIL（kind 仍为 `bubble`；TableCenter 没有 speechProgress 文案）。tsc 也会报 `speechProgress` 不在联合里。

- [ ] **Step 3: Implement**（`stageContent.ts`、`TableCenter.tsx`、`GameTable.module.css` 加 `.progressLine`、`CardBoard.tsx` 的 `showCenter`）。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/stageContent.test.ts src/components/GameTable && npx tsc --noEmit -p .`
Expected: PASS；tsc 0 errors（`GamePage.tsx` 里 `center.kind === "bubble"` 的引用这一步会报错——同一步里把 `GamePage.tsx:595` 的 `bubbleSpeaker` 暂改为 `speaking`，保持可编译；气泡在 Task 9 整体删除）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/stageContent.ts frontend/src/lib/stageContent.test.ts frontend/src/components/GameTable frontend/src/pages/GamePage.tsx
git commit -m "feat(frontend): 桌心 speechProgress——昨夜 / 昨日票型 / 发言进度一行，替代 bubble"
```

---

### Task 5: 回放阅读停留 `readingDwell` + 可取消 `dwell`

**Files:**
- Create: `frontend/src/lib/readingDwell.ts`、`frontend/src/lib/dwell.ts`
- Modify: `frontend/src/pages/GamePage.tsx:323-333`（门控）、`:578`（`replayControls(store, …)` 的第二个参数）
- Test: `frontend/src/lib/readingDwell.test.ts`、`frontend/src/lib/dwell.test.ts`、`frontend/src/pages/GamePage.test.tsx`（加一条）

**Interfaces:**
- Produces:
  ```ts
  // readingDwell.ts
  export function readingDwellMs(event: Event | undefined, speed: number): number; // 非发言 / undefined → 0
  // dwell.ts
  export interface Dwell { sleep(ms: number): Promise<void>; cancel(): void }
  export function createDwell(): Dwell; // cancel() 让所有挂起的 sleep 立即 resolve 并 clearTimeout
  ```
  GamePage：模块级 `const dwell = createDwell();`；门控 `(seq) => parts && voice.enabled ? playSeq(...) : (ms = readingDwellMs(events.find(e => e.seq === seq), speed)) > 0 ? dwell.sleep(ms) : null`（`events` / `speed` 从 `useGameStore.getState()` 读，不进依赖数组）；`replayControls(store, { clear: () => { useVoice.getState().clear(); dwell.cancel(); } })`；门控卸载时也 `dwell.cancel()`。

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/lib/readingDwell.test.ts
import { describe, expect, it } from "vitest";
import type { Event } from "../engine/types";
import { readingDwellMs } from "./readingDwell";

const spoke = (content: string): Event =>
  ({ seq: 1, game_id: "g", ts: 0, type: "PLAYER_SPOKE", actor_seat: 2, visibility: "PUBLIC", meta: {},
     payload: { content, claim_role: null, badge_flow: [] } }) as unknown as Event;

describe("readingDwellMs（规格 R9）", () => {
  it("空正文 1.5 s；每字 150 ms；200 字封顶 30 s；倍速除", () => {
    expect(readingDwellMs(spoke(""), 1)).toBe(1500);
    expect(readingDwellMs(spoke("十个字十个字十个字十"), 1)).toBe(3000);
    expect(readingDwellMs(spoke("字".repeat(200)), 1)).toBe(30000);
    expect(readingDwellMs(spoke("字".repeat(200)), 2)).toBe(15000);
  });
  it("遗言同发言；其它事件与 undefined 为 0", () => {
    const lw = { ...spoke("走了"), type: "LAST_WORDS", payload: { seat: 2, content: "走了" } } as unknown as Event;
    expect(readingDwellMs(lw, 1)).toBe(1800);
    expect(readingDwellMs({ ...spoke("x"), type: "VOTE_CAST" } as Event, 1)).toBe(0);
    expect(readingDwellMs(undefined, 1)).toBe(0);
  });
});
```

```ts
// frontend/src/lib/dwell.test.ts
import { describe, expect, it, vi } from "vitest";
import { createDwell } from "./dwell";

describe("createDwell", () => {
  it("sleep 到点 resolve；cancel 让挂起的 sleep 立即 resolve", async () => {
    vi.useFakeTimers();
    const d = createDwell();
    let a = false; let b = false;
    void d.sleep(1000).then(() => { a = true; });
    vi.advanceTimersByTime(1000);
    await Promise.resolve();
    expect(a).toBe(true);
    void d.sleep(5000).then(() => { b = true; });
    d.cancel();
    await Promise.resolve();
    expect(b).toBe(true);
    vi.useRealTimers();
  });
});
```

GamePage 测试（放进「终审修复」describe 之后，新 describe「回放阅读停留（规格 §7）」）：

```ts
  it("语音关：发言 seq 的门控返回阅读等待，onPause 后立即 resolve；非发言 seq 为 null", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    useVoice.setState({ enabled: false });
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const gate = useGameStore.getState().replayGate!;
    const spoke = events.find((e) => e.type === "PLAYER_SPOKE")!;
    const vote = events.find((e) => e.type === "VOTE_CAST")!;
    expect(gate(vote.seq)).toBeNull();
    const p = gate(spoke.seq);
    expect(p).not.toBeNull();
    let done = false;
    void p!.then(() => { done = true; });
    await Promise.resolve();
    expect(done).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /暂停|播放/ })); // 绳索条的播放 / 暂停键：先点一次进入播放再点暂停亦可
    fireEvent.click(screen.getByRole("button", { name: /暂停/ }));
    await Promise.resolve();
    expect(done).toBe(true);
  });
```

（先读 `ReplayBar.tsx` 确认播放 / 暂停按钮的 `aria-label`，按实际文案改两处 name。）

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/readingDwell.test.ts src/lib/dwell.test.ts src/pages/GamePage.test.tsx -t "阅读"`
Expected: FAIL — 模块不存在；GamePage 用例里 `gate(spoke.seq)` 为 null。

- [ ] **Step 3: Implement** `readingDwell.ts`、`dwell.ts`，改 GamePage 门控与 `replayControls` 第二参数。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/readingDwell.test.ts src/lib/dwell.test.ts src/lib/replayControls.test.ts src/pages/GamePage.test.tsx`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/readingDwell.ts frontend/src/lib/readingDwell.test.ts frontend/src/lib/dwell.ts frontend/src/lib/dwell.test.ts frontend/src/pages/GamePage.tsx frontend/src/pages/GamePage.test.tsx
git commit -m "feat(frontend): 回放静音时按阅读时长停留，暂停 / 拖动即取消等待（issue #189）"
```

---

### Task 6: 发言台 `SpeakerStand`

**Files:**
- Create: `frontend/src/lib/useCountdown.ts`（从 `SpeechBubble.useLeft` 搬出：`useCountdown(deadline: number | null, now: () => number): number | null`）、`frontend/src/components/SpeakerStand/SpeakerStand.tsx`、`SpeakerStand.module.css`
- Modify: `frontend/src/components/GameTable/SpeechBubble.tsx`（改 import `useCountdown`；本任务不删它）
- Test: `frontend/src/components/SpeakerStand/SpeakerStand.test.tsx`

**Interfaces:**
- Consumes: `select.SpeechItem`、`RoleToken`、`ROLE_ZH`。
- Produces:
  ```ts
  export type StandKind = "speech" | "campaign" | "last_words";
  export interface SpeakerStandProps {
    seat: number; name: string; role: RoleType | null; avatar: string | null;
    kind: StandKind; item: SpeechItem | null; mine: boolean;
    deadline: number | null; limit: number | null; now?: () => number;
    voicing: boolean; agent?: { model: string; voice: string } | null;
    queue: number[]; claims: [number, RoleType][];
  }
  export default function SpeakerStand(props: SpeakerStandProps): JSX.Element;
  ```
  DOM 契约：根 `<section role="status" aria-label="{seat}号 {name} {发言中|竞选发言|遗言|轮到你}" data-layout="full|compact">`；正文 `<p data-testid="stand-text">`；音柱 `[data-testid="stand-bars"]`；模型行 `[data-testid="stand-agent"]`；底行 `[data-testid="stand-queue"]`；提示行 `[data-testid="stand-hint"]`；计时 `[data-testid="stand-timer"]`；环 `style={{ "--ring": `${pct}%` }}`。文案与尺寸按规格 §5；`compact` 当且仅当 `mine && item === null`。

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/SpeakerStand/SpeakerStand.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SpeechItem } from "../../engine/select";
import SpeakerStand from "./SpeakerStand";

const item: SpeechItem = { seq: 9, type: "PLAYER_SPOKE", kind: "speech", actor_seat: 5, text: "5号发言：我是警长", content: "我是警长", claim: "SEER", badgeFlow: [2, 7] };
const base = { seat: 5, name: "火药桶", role: null, avatar: null, kind: "speech" as const, mine: false, deadline: null, limit: null, voicing: false, queue: [8, 9, 0], claims: [] as [number, "SEER"][] };

describe("SpeakerStand（规格 §5）", () => {
  it("他人发言：正文、自称签、警徽流签、队列；无 agent 不渲染模型行", () => {
    render(<SpeakerStand {...base} item={item} />);
    expect(screen.getByRole("status", { name: "5号 火药桶 发言中" })).toHaveAttribute("data-layout", "full");
    expect(screen.getByTestId("stand-text")).toHaveTextContent("我是警长");
    expect(screen.getByText("自称 预言家")).toBeInTheDocument();
    expect(screen.getByText("警徽流 2 → 7")).toBeInTheDocument();
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("之后 8号 → 9号 → 0号");
    expect(screen.queryByTestId("stand-agent")).toBeNull();
    expect(screen.queryByTestId("stand-bars")).toBeNull();
  });
  it("未开口：占位「正在组织语言…」；本人未开口切紧凑版「轮到你」+ 提示", () => {
    const { rerender } = render(<SpeakerStand {...base} item={null} />);
    expect(screen.getByTestId("stand-text")).toHaveTextContent("正在组织语言…");
    rerender(<SpeakerStand {...base} item={null} mine queue={[]} claims={[[5, "SEER"], [2, "WITCH"]]} />);
    expect(screen.getByRole("status", { name: "5号 火药桶 轮到你" })).toHaveAttribute("data-layout", "compact");
    expect(screen.getByTestId("stand-hint")).toHaveTextContent("本轮自称：5号 预言家、2号 女巫");
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("最后一位 · 发完即进入投票");
    rerender(<SpeakerStand {...base} item={null} mine queue={[]} claims={[]} kind="campaign" />);
    expect(screen.getByTestId("stand-hint")).toHaveTextContent("本轮尚无人声明身份");
    expect(screen.getByTestId("stand-queue")).toHaveTextContent("最后一位 · 发完即进入下一阶段");
  });
  it("配音中：音柱 + 光标；遗言 / 竞选胶囊文案", () => {
    render(<SpeakerStand {...base} item={item} voicing kind="last_words" />);
    expect(screen.getByTestId("stand-bars")).toBeInTheDocument();
    expect(screen.getByTestId("stand-text")).toHaveTextContent("▍");
    expect(screen.getByRole("status", { name: /遗言$/ })).toBeInTheDocument();
  });
  it("agent 行与声线文案；倒计时与进度环", () => {
    render(<SpeakerStand {...base} item={item} agent={{ model: "claude-sonnet", voice: "低沉" }} deadline={1030} limit={60} now={() => 1000} />);
    expect(screen.getByTestId("stand-agent")).toHaveTextContent("claude-sonnet · 声线：低沉");
    expect(screen.getByTestId("stand-timer")).toHaveTextContent("30s");
    expect(screen.getByRole("status").querySelector("[style*='--ring']")?.getAttribute("style")).toContain("50%");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/SpeakerStand`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Implement** `useCountdown.ts`（`SpeechBubble` 改用它，自身测试仍绿）、`SpeakerStand.tsx` + CSS（木牌面板、环、羊皮纸正文、音柱动画从 `GameTable.module.css` 复制 `.bars` / `@keyframes ah-bars` 到本模块）。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/SpeakerStand src/components/GameTable/SpeechBubble.test.tsx && npm run lint`
Expected: PASS；lint 0 errors。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useCountdown.ts frontend/src/components/SpeakerStand frontend/src/components/GameTable/SpeechBubble.tsx
git commit -m "feat(frontend): SpeakerStand 发言台——当前发言人 / 正文 / 计时环 / 队列（设计稿 8a / 8b）"
```

---

### Task 7: 对局记录 `GameLog`

**Files:**
- Create: `frontend/src/components/GameLog/GameLog.tsx`、`GameLog.module.css`
- Test: `frontend/src/components/GameLog/GameLog.test.tsx`

**Interfaces:**
- Consumes: Task 2 `LogEntry`、`LogGroup`；`RoleToken`；`rolesKnown`。
- Produces:
  ```ts
  export interface GameLogProps {
    entries: LogEntry[]; state: GameState; cursor: number | null;
    avatars?: Record<number, string>; knownRoles?: Record<number, RoleType>;
  }
  export default function GameLog(props: GameLogProps): JSX.Element;
  ```
  DOM 契约：根 `<section aria-label="对局记录">`；过滤 `role="tablist"` 内 `role="tab"` 按钮，`aria-selected`；每条 `<article data-seq data-group data-current? data-private?>`；分隔 `[data-testid="log-day"]`；空态文本「尚无记录」；未读胶囊按钮「↑ 有 N 条新记录」。图标字形表与颜色按规格 §6.2。

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/GameLog/GameLog.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_all-3.json";
import type { Event, GameState } from "../../engine/types";
import { logEntries } from "../../lib/gameLog";
import GameLog from "./GameLog";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1]!;

describe("GameLog（规格 §6.2）", () => {
  const entries = logEntries(events);

  it("最新在上、日夜分隔、验人页签按数据出现", () => {
    render(<GameLog entries={entries} state={last} cursor={null} />);
    const arts = document.querySelectorAll("article[data-seq]");
    expect(Number(arts[0]!.getAttribute("data-seq"))).toBe(entries[0]!.seq);
    expect(screen.getAllByTestId("log-day").length).toBeGreaterThan(2);
    expect(screen.getByRole("tab", { name: "验人" })).toBeInTheDocument();
  });

  it("过滤：发言页签只剩 speech 组；无验人条目时没有验人页签", () => {
    render(<GameLog entries={entries} state={last} cursor={null} />);
    fireEvent.click(screen.getByRole("tab", { name: "发言" }));
    const groups = new Set([...document.querySelectorAll("article[data-group]")].map((a) => a.getAttribute("data-group")));
    expect(groups).toEqual(new Set(["speech"]));
    cleanupAndRender(entries.filter((e) => e.group !== "seer"));
    expect(screen.queryByRole("tab", { name: "验人" })).toBeNull();
  });

  it("回放游标处的条目 data-current；私有行 data-private；空态", () => {
    const seer = entries.find((e) => e.type === "SEER_CHECKED")!;
    render(<GameLog entries={entries} state={last} cursor={seer.seq} />);
    const art = document.querySelector(`article[data-seq="${seer.seq}"]`)!;
    expect(art).toHaveAttribute("data-current", "true");
    expect(art).toHaveAttribute("data-private", "true");
    expect(document.querySelector('article[data-group="speech"]')).not.toHaveAttribute("data-private");
    cleanupAndRender([]);
    expect(screen.getByText("尚无记录")).toBeInTheDocument();
  });
});

function cleanupAndRender(entries: ReturnType<typeof logEntries>): void {
  document.body.innerHTML = "";
  render(<GameLog entries={entries} state={last} cursor={null} />);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/GameLog`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Implement** `GameLog.tsx` + CSS（面板、页签、分隔线、事件行 / 发言行、`data-current` 金线、`data-private` 左边线用 `style={{ borderLeftColor: `var(${color})` }}`、`scrollIntoView` 在 `cursor` 变化的 effect 里且 `typeof el.scrollIntoView === "function"` 时调用、未读胶囊）。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/GameLog && npm run lint`
Expected: PASS；lint 0 errors。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GameLog
git commit -m "feat(frontend): GameLog 对局记录——倒序 / 日夜分隔 / 分组过滤 / 回放游标高亮"
```

---

### Task 8: 桌面只留状态（圆桌 + 卡牌状态行）

**Files:**
- Modify: `frontend/src/components/GameTable/GameTable.tsx`（名字下加状态行；`speech` prop 本任务保留）、`GameTable.module.css`（`.status`）、`CardBoard.tsx`、`CardBoard.module.css`（`.name` → `bottom: 18px`，新 `.status` `bottom: 5px`）
- Test: `GameTable.test.tsx`、`CardBoard.test.tsx` 各加一条

**Interfaces:**
- Consumes: Task 3 `SeatModel.status`。
- Produces: 座位按钮内 `<span class={status} data-tone="…">{text}</span>`（空串也渲染，占 10px 行高）。

- [ ] **Step 1: Write the failing tests**

`GameTable.test.tsx`：

```tsx
  it("座位名字下方有状态行，data-tone 与文案来自 SeatModel.status（规格 §4.1）", () => {
    const seats = baseSeats(); // 复用文件里已有的座位构造，若无则按 SeatModel 手写 2 个座位
    seats[0]!.status = { text: "发言中", tone: "now" };
    seats[1]!.status = { text: "", tone: "none" };
    render(<GameTable seats={seats} night={false} center={{ kind: "none" }} speech={null} avatars={{}} />);
    const first = document.querySelector('button[data-seat="0"] [data-tone]')!;
    expect(first).toHaveAttribute("data-tone", "now");
    expect(first).toHaveTextContent("发言中");
    expect(document.querySelector('button[data-seat="1"] [data-tone="none"]')).toBeInTheDocument();
  });
```

`CardBoard.test.tsx` 同样一条（9 张牌时 `button[data-seat]` 仍为 9，且每张牌都有 `[data-tone]`）。

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/GameTable/GameTable.test.tsx src/components/GameTable/CardBoard.test.tsx`
Expected: FAIL — 找不到 `[data-tone]`。

- [ ] **Step 3: Implement** 两个组件的状态行与 CSS（`.status` 10px、`white-space: nowrap`、颜色按 tone：now `--ah-gold`、done `--ah-text-muted`、wait `--ah-text-dim`、dead `--ah-dead-fg`）。

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/GameTable`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GameTable
git commit -m "feat(frontend): 圆桌 / 卡牌座位加状态行（发言中 / 已发言 / 待发言 / 出局…）"
```

---

### Task 9: GamePage 装配：右栏两段、删气泡 / 抽屉页签 / 发言流 / 发言顺序卡

**Files:**
- Modify: `frontend/src/pages/GamePage.tsx`、`GamePage.module.css`、`frontend/src/lib/railCards.ts`（删 `"order"`、`MAX_CARDS = 2`）、`frontend/src/components/InfoRail/InfoRail.tsx`（删 `order` case 与 import）、`frontend/src/components/EventDrawer/EventDrawer.tsx`（删 `top` 插槽；页签文案由调用方传）、`frontend/src/components/GameTable/GameTable.tsx` / `CardBoard.tsx`（删 `speech` prop 与 `SpeechBubble` 渲染）、`frontend/src/lib/tableText.ts`（`currentSpeechItem` 保留）
- Delete: `frontend/src/components/GameTable/SpeechBubble.tsx`、`SpeechBubble.test.tsx`、`GameTable.module.css` 的「发言气泡」「横向发言条」两节；`frontend/src/components/SpeechFeed/`；`frontend/src/components/PlayerStatusPanel/`
- Test: `GamePage.test.tsx`（改 3 条、加 3 条）、`railCards.test.ts`、`InfoRail.test.tsx`、`EventDrawer.test.tsx`

**Interfaces:**
- Consumes: Task 2 `logEntries` / `currentClaims`；Task 4 `speechProgress`；Task 6 `SpeakerStand`；Task 7 `GameLog`；`useGameStore((s) => s.meta)`。
- GamePage 新派生值：
  ```ts
  const entries = useMemo(() => logEntries(visibleEvents), [visibleEvents]);
  const standItem = speaking === null ? null : currentSpeechItem(speechItems(visibleEvents), speaking);
  const queue = speaking === null ? [] : view.speech_order.slice(view.speech_order.indexOf(speaking) + 1);
  const claims = useMemo(() => currentClaims(entries), [entries]);
  const agent = agentLine(meta?.agents, speaking);   // src/lib/agentLine.ts：{ model, voice } | null（R7）
  const voteTargets = (VOTE 类阶段) ? tally.votes : {};  // 传给 seatModel
  const showStand = speaking !== null && SPEAKING_PHASES.has(view.phase) && !(view.phase === "SHERIFF_ELECTION" && view.election_stage !== "speech");
  ```
  `agentLine(agents: Record<string, unknown> | undefined, seat: number | null): { model: string; voice: string } | null` 放 `src/lib/agentLine.ts`，有 3 条单测（无档案 null；`model: "openai/gpt-4o"` → `gpt-4o`；voice preset / design / 无）。
  右栏 JSX 与 CSS 按规格 §3 / §8；窄屏 `EventDrawer tabLabel="发言台 · 对局记录"`，children 为同一段 `.rail` 内容；`.drawerRail` 删除。
  `SPEAKING_PHASES` 保留；`bubbleKind` 改名 `standKind`（同三值映射）。

- [ ] **Step 1: Write / update the failing tests**

`GamePage.test.tsx`：
- 第 566 行用例「配音正在读第一轮某句时，气泡显示的是游标处那句」改为查 `screen.findByRole("status", { name: new RegExp(`^${first.actor_seat}号 .* (发言中|竞选发言|遗言)$`) })` 的 `[data-testid="stand-text"]` 含正文前 20 字（断言语义不变，DOM 换成发言台）。
- 新增 describe「GamePage 右栏（规格 §3 / §8）」：
  ```tsx
  it("回放到发言阶段：右栏上半是发言台、下半是对局记录；不再有气泡与事件流页签", async () => {
    stubFetch(() => jsonResponse(200, meta)); vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const spoke = events.find((e) => e.type === "PLAYER_SPOKE")!;
    act(() => useGameStore.getState().setCursor(spoke.seq));
    expect(await screen.findByRole("status", { name: /(发言中|竞选发言)$/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "对局记录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /事件流/ })).toBeNull();
    expect(document.querySelector(`article[data-seq="${spoke.seq}"]`)).toHaveAttribute("data-current", "true");
  });
  it("回放到投票阶段：右栏上半是信息卡（票型），记录仍在", async () => {
    …setCursor 到第一条 VOTE_CAST…
    expect(screen.queryByRole("status", { name: /发言中$/ })).toBeNull();
    expect(screen.getByLabelText("信息栏")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "对局记录" })).toBeInTheDocument();
  });
  it("配音读上一位时发言台显示上一位，座位状态行上一位「发言中」下一位「待发言」", async () => {
    …找到第二条 PLAYER_SPOKE 的 seq=s2，前一条 s1；setCursor(s2)；act(() => useVoice.setState({ voicingSeq: s1, playing: { seq: s1, part: 0 } }))…
    expect(screen.getByRole("status", { name: new RegExp(`^${e1.actor_seat}号`) })).toBeInTheDocument();
    expect(document.querySelector(`button[data-seat="${e1.actor_seat}"] [data-tone="now"]`)).toHaveTextContent("发言中");
    useVoice.getState().clear();
  });
  ```
  （`GameLog` 根 `<section aria-label="对局记录">` 的隐式 role 是 `region`。）
- `railCards.test.ts`：`DAY_SPEECH` 期望不再含 `order`，任何阶段长度 ≤ 2。
- `InfoRail.test.tsx`：删 `order` 用例。`EventDrawer.test.tsx`：删 `top` 相关断言。

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/pages/GamePage.test.tsx src/lib/railCards.test.ts`
Expected: 新用例 FAIL（没有「对局记录」region；仍有「事件流」页签；`order` 仍在）。

- [ ] **Step 3: Implement** GamePage 装配 + CSS + `agentLine.ts`（含测试）+ railCards / InfoRail / EventDrawer 修改 + 删除清单文件。`git rm` 删除的文件；`grep -rn "SpeechBubble\|SpeechFeed\|PlayerStatusPanel\|drawerRail\|\"order\"" frontend/src` 为空。

- [ ] **Step 4: Run to verify everything passes**

Run: `cd frontend && npm run check; echo "exit=$?"`
Expected: `exit=0`；再跑 `grep -rn "viewer" frontend/src/components/SpeakerStand frontend/src/components/GameLog frontend/src/lib/gameLog.ts frontend/src/lib/seatStatus.ts frontend/src/lib/dayScan.ts` 无输出。

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "feat(frontend): 对局页右栏改发言台 + 对局记录；删座位气泡 / 事件流抽屉页签 / 发言顺序卡（设计稿 8a–8c）"
```

---

### Task 10: 端到端验收、截图与文档

**Files:**
- Modify: `frontend/e2e/screens.mjs`（抽屉截图改在 1100 宽以下；上帝回放多截一张发言阶段右栏）、`frontend/e2e/README.md`（一行：抽屉只在 <1100px）、`docs/superpowers/specs/2026-10-28-ui-gamification-design.md`（§4.3 / §4.6 开头加一句「已被 `2026-10-28-speech-stage-game-log-design.md` 取代」）
- Create: `docs/design/ui-speech-stage-2026-10-28/*.png`

- [ ] **Step 1: 跑 e2e（后端 `:8000` 与 `npm run dev :5173` 须在跑；按 `frontend/e2e/README.md` 取账号）**

Run: `cd frontend/e2e && AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… AH_SEED=5 RUN=wolf SPEECH_SEC=15 ACTION_SEC=15 node play.mjs 2>&1 | tail -3`
Expected: 最后一行 `SUMMARY` JSON 含 `"finished": true` 且 `"rejected": []`。再以 `AH_SEED=2 RUN=seer` 跑一次（验人页签），同样通过。

- [ ] **Step 2: 截图**

Run: `cd frontend/e2e && AH_BASE_URL=http://localhost:5173 AH_USER=e2e_player AH_PASS=… AH_GAME=<上一步的 game_id> SHOT_DIR=../../docs/design/ui-speech-stage-2026-10-28 node screens.mjs 2>&1 | tail -5`，再加 `AH_TABLE=cards` 跑一次。
Expected: 目录里出现上帝回放发言 / 投票 / 夜晚、观众发言、卡牌发言、1100 宽抽屉的 png；人工打开 `*-speech.png` 对照 8a：右栏上发言台、下记录，桌面无气泡，座位有状态行。

- [ ] **Step 3: 文档**

更新上述三处文档；`git add docs frontend/e2e`。

- [ ] **Step 4: 全量验证**

Run: `cd frontend && npm run check; echo "exit=$?"`
Expected: `exit=0`。

- [ ] **Step 5: Commit 并 push，更新 PR #190 正文（去掉「草稿」说明，列出截图目录），`gh pr ready 190`**

```bash
git add -A docs frontend/e2e
git commit -m "docs: 发言台 / 对局记录截图与 e2e 说明；旧规格 §4.3 / §4.6 标记为已取代"
git push
```
