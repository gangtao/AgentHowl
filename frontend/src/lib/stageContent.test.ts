import { describe, expect, it } from "vitest";
import type { YourTurn } from "../api/player";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../engine/reduce";
import type { Event, GameMeta, GameState } from "../engine/types";
import { stageContent } from "./stageContent";

const meta = fixture.meta as unknown as GameMeta;
const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const blank = initialState(meta);
const upTo = (seq: number): Event[] => events.filter((e) => e.seq <= seq);
const at = (pick: (s: GameState) => boolean): { state: GameState; events: Event[] } => {
  const i = states.findIndex(pick);
  if (i < 0) throw new Error("fixture 里没有这样的状态");
  return { state: states[i] as GameState, events: upTo((events[i] as Event).seq) };
};

function promptWith(priv: Record<string, unknown>, extra: Record<string, unknown> = {}): YourTurn {
  return {
    available_tools: ["night_action"],
    deadline_ts: 0,
    observation: {
      game_id: "g",
      state_version: 1,
      my_seat: 0,
      my_role: "WITCH",
      my_status: "ALIVE",
      phase: "NIGHT_WITCH",
      round: 1,
      seats: [],
      sheriff_seat: null,
      badge_flow_claims: {},
      private: priv,
      election_stage: "",
      sheriff_candidates: [],
      vote_candidates: [],
      pk_speech_pending: false,
      badge_only: false,
      sheriff_options: [],
      available_actions: [],
      ...extra,
    },
  };
}

describe("stageContent（规格 §4.4）", () => {
  it.each([
    [
      "NIGHT_WEREWOLF 有提案 → wolfCouncil",
      (s: GameState) => s.phase === "NIGHT_WEREWOLF" && Object.keys(s.wolf_proposals).length > 0,
      "wolfCouncil",
    ],
    ["VOTE → tally", (s: GameState) => s.phase === "VOTE", "tally"],
    [
      "DAY_SPEECH 有发言者 → speechProgress",
      (s: GameState) => s.phase === "DAY_SPEECH" && s.speech_order.length > 0,
      "speechProgress",
    ],
    ["GAME_OVER → none", (s: GameState) => s.phase === "GAME_OVER", "none"],
    [
      "SHERIFF_ELECTION 报名 → campfire",
      (s: GameState) => s.phase === "SHERIFF_ELECTION" && s.election_stage === "candidacy",
      "campfire",
    ],
  ])("%s", (_n, pick, kind) => {
    const { state, events: ev } = at(pick);
    expect(stageContent({ state, events: ev, mode: "live" }).kind).toBe(kind);
  });

  it("折叠夜晚 NIGHT（观众）→ moon", () => {
    expect(stageContent({ state: { ...blank, phase: "NIGHT" }, events: [], mode: "live" })).toEqual({
      kind: "moon",
      sub: "请闭眼，等待其他角色行动",
    });
  });

  it("回放游标 0（LOBBY）→ campfire 等待开局", () => {
    expect(stageContent({ state: blank, events: [], mode: "replay" })).toEqual({
      kind: "campfire",
      note: "等待开局",
    });
  });

  it("GM 回放夜间有本夜行动 → gmNotes 优先于 moon", () => {
    const { state, events: ev } = at((s) => s.phase === "NIGHT_HUNTER_CONFIRM" && s.round === 2);
    const c = stageContent({ state, events: ev, mode: "replay" });
    expect(c.kind).toBe("gmNotes");
    if (c.kind === "gmNotes") {
      expect(c.round).toBe(2);
      expect(c.rows.length).toBeGreaterThan(0);
    }
    // 直播（非回放）同一状态：没有狼提案时走 moon
    const live = stageContent({ state: { ...state, wolf_proposals: {} }, events: ev, mode: "live" });
    expect(live.kind).toBe("moon");
  });

  it("女巫夜 + 刀口 + 观察里的药瓶 → witchTarget", () => {
    const st: GameState = {
      ...states[states.length - 1]!,
      phase: "NIGHT_WITCH",
      wolf_proposals: {},
      pending_night: { ...blank.pending_night, wolf_target: 5 },
    };
    const c = stageContent({
      state: st,
      events: [],
      mode: "live",
      prompt: promptWith({ antidote_available: true, poison_available: false }),
      myRole: "WITCH",
    });
    expect(c).toMatchObject({ kind: "witchTarget", seat: 5, antidote: true, poison: false });
    if (c.kind === "witchTarget") expect(c.name).not.toBe("");
    // 没有观察 → 药瓶为 null
    const c2 = stageContent({ state: st, events: [], mode: "live" });
    expect(c2).toMatchObject({ kind: "witchTarget", antidote: null, poison: null });
  });

  it("预言家选中目标 → crystal；非预言家不出现", () => {
    const st: GameState = { ...blank, phase: "NIGHT_SEER" };
    expect(
      stageContent({ state: st, events: [], mode: "live", selectedTarget: 8, myRole: "SEER" }),
    ).toEqual({ kind: "crystal", seat: 8 });
    expect(
      stageContent({ state: st, events: [], mode: "live", selectedTarget: 8, myRole: "VILLAGER" }).kind,
    ).toBe("moon");
  });

  it("猎人确认 + 选中目标 → crosshair", () => {
    const st: GameState = { ...blank, phase: "HUNTER_SHOOT", pending_hunter: 0 };
    expect(
      stageContent({ state: st, events: [], mode: "live", selectedTarget: 9, myRole: "HUNTER" }),
    ).toEqual({ kind: "crosshair", seat: 9 });
  });

  it("VOTE_PK 两人 → pkStage，票数带小数", () => {
    const base = states[states.length - 1]!;
    const sheriff = base.players[1]!.seat;
    const st: GameState = {
      ...base,
      phase: "VOTE_PK",
      tie_round: 1,
      vote_candidates: [0, 8],
      sheriff_seat: sheriff,
      players: base.players.map((p) => ({ ...p, alive: true, can_vote: true, is_sheriff: p.seat === sheriff })),
    };
    const mk = (seq: number, type: string, payload: unknown): Event =>
      ({ seq, game_id: "g", ts: 0, type, actor_seat: null, payload, visibility: "PUBLIC", meta: {} }) as Event;
    const ev: Event[] = [
      mk(1, "VOTE_STARTED", { candidates: [0, 8], tie_round: 1 }),
      mk(2, "VOTE_CAST", { voter: sheriff, target: 0 }),
      mk(3, "VOTE_CAST", { voter: 2, target: 0 }),
      mk(4, "VOTE_CAST", { voter: 3, target: 8 }),
    ];
    const c = stageContent({ state: st, events: ev, mode: "live" });
    expect(c.kind).toBe("pkStage");
    if (c.kind === "pkStage") {
      expect(c.a).toMatchObject({ seat: 0, votes: 2.5 });
      expect(c.b).toMatchObject({ seat: 8, votes: 1 });
      expect(c.cast).toBe(3);
      expect(c.voters).toBe(7); // 9 人全活，PK 双方不投
    }
  });

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

  it("speechProgress：第一次发言阶段还没有票型时 lastTally 为 null", () => {
    const { state, events: ev } = at((s) => s.phase === "DAY_SPEECH");
    expect(ev.some((e) => e.type === "VOTE_RESULT")).toBe(false);
    const c = stageContent({ state, events: ev, mode: "live" });
    expect(c.kind).toBe("speechProgress");
    expect(c.kind === "speechProgress" && c.lastTally).toBeNull();
  });

  it("tally 行按被投者分组并带投票人", () => {
    const { state, events: ev } = at((s) => s.phase === "VOTE" && s.round === 2);
    const c = stageContent({ state, events: ev, mode: "live" });
    if (c.kind !== "tally") throw new Error("expected tally");
    expect(c.election).toBe(false);
    expect(c.voters).toBeGreaterThan(0);
    for (const r of c.rows) {
      expect(r.from.length).toBeGreaterThan(0);
      expect(r.name).not.toBe("");
    }
  });
});
