import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../engine/reduce";
import type { Event, GameMeta, GameState } from "../engine/types";
import { railCards } from "./railCards";

const meta = fixture.meta as unknown as GameMeta;
const blank = initialState(meta);
const base = { events: [], mode: "live" as const, hasPotions: false, hasDeaths: true };
const withPhase = (phase: GameState["phase"], extra: Partial<GameState> = {}): GameState => ({
  ...blank,
  phase,
  ...extra,
});

describe("railCards（规格 §4.5）", () => {
  it.each([
    ["DAY_SPEECH", withPhase("DAY_SPEECH"), ["order", "news", "graveyard"]],
    ["LAST_WORDS", withPhase("LAST_WORDS"), ["votes", "news", "graveyard"]],
    ["VOTE", withPhase("VOTE"), ["votes", "news", "graveyard"]],
    ["VOTE_PK", withPhase("VOTE_PK"), ["votes", "pkRecap", "news"]],
    ["EXILE", withPhase("EXILE"), ["votes", "news", "graveyard"]],
    [
      "SHERIFF_ELECTION 报名",
      withPhase("SHERIFF_ELECTION", { election_stage: "candidacy" }),
      ["election", "news", "graveyard"],
    ],
    [
      "SHERIFF_ELECTION 发言",
      withPhase("SHERIFF_ELECTION", { election_stage: "speech" }),
      ["election", "order", "news"],
    ],
    ["SHERIFF_PK", withPhase("SHERIFF_PK"), ["election", "pkRecap", "news"]],
    ["NIGHT_WEREWOLF 无夜间行动", withPhase("NIGHT_WEREWOLF"), ["nightFlow", "news", "graveyard"]],
    ["NIGHT 折叠", withPhase("NIGHT"), ["nightFlow", "news", "graveyard"]],
    ["DEATH_ANNOUNCE", withPhase("DEATH_ANNOUNCE"), ["news", "graveyard"]],
    ["GAME_OVER", withPhase("GAME_OVER"), ["news", "graveyard"]],
  ])("%s", (_n, state, expected) => {
    expect(railCards({ ...base, state })).toEqual(expected);
  });

  it("LOBBY 无死亡 → 只有公告", () => {
    expect(railCards({ ...base, state: blank, hasDeaths: false })).toEqual(["news"]);
  });

  it("夜间：女巫有药瓶 → potions 在 nightFlow 之前", () => {
    expect(railCards({ ...base, state: withPhase("NIGHT_WITCH"), hasPotions: true })).toEqual([
      "potions",
      "nightFlow",
      "news",
    ]);
  });

  it("夜间：回放有本夜行动 → nightActs 排第一", () => {
    const states = fixture.states as unknown as GameState[];
    const events = fixture.events as unknown as Event[];
    const i = states.findIndex((s) => s.phase === "NIGHT_HUNTER_CONFIRM" && s.round === 2);
    const input = {
      ...base,
      state: states[i] as GameState,
      events: events.slice(0, i + 1),
      mode: "replay" as const,
    };
    expect(railCards(input)[0]).toBe("nightActs");
  });

  it("预言家有验人记录：任何阶段 seerLog 排在 news 之前", () => {
    const st = withPhase("DAY_SPEECH", {
      seer_log: { "0": [{ round: 1, seat: 3, result: "WOLF" }] },
    });
    expect(railCards({ ...base, state: st })).toEqual(["order", "seerLog", "news"]);
  });

  it("永远不超过 3 张", () => {
    const st = withPhase("NIGHT_WITCH", {
      seer_log: { "0": [{ round: 1, seat: 3, result: "GOOD" }] },
    });
    expect(railCards({ ...base, state: st, hasPotions: true })).toHaveLength(3);
  });
});
