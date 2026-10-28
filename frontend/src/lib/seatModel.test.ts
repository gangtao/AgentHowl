import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import { initialState } from "../engine/reduce";
import type { GameMeta, GameState } from "../engine/types";
import { seatModel, seatPositions } from "./seatModel";

const meta = fixture.meta as unknown as GameMeta;
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1] as GameState; // GAME_OVER，角色全知
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
    const m = seatModel({
      state: { ...blank, phase: "NIGHT_WEREWOLF" },
      me: 0,
      knownRoles: { 0: "WEREWOLF", 3: "WEREWOLF" },
    });
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
    expect(m.filter((s) => s.alive).every((s) => s.selectable)).toBe(true);
  });

  it("徽章：警长 / 候选 / 票数 / 已验签 / 夜间红签", () => {
    const st: GameState = {
      ...last,
      phase: "SHERIFF_ELECTION",
      sheriff_seat: 2,
      sheriff_candidates: [1, 5],
      sheriff_withdrawn: [5],
    };
    const m = seatModel({
      state: st,
      votes: { 1: 2.5 },
      marks: { 4: "狼人" },
      tags: { 7: "被刀" },
      selected: 1,
      selectable: [1],
    });
    expect(m[2]?.badges.sheriff).toBe(true);
    expect(m[1]?.badges.candidate).toBe(true);
    expect(m[5]?.badges.candidate).toBe(false);
    expect(m[1]?.badges.votes).toBe(2.5);
    expect(m[0]?.badges.votes).toBeNull();
    expect(m[4]?.badges.mark).toBe("狼人");
    expect(m[7]?.badges.tag).toBe("被刀");
    expect(m[1]?.selected).toBe(true);
    expect(m[1]?.speaking).toBe(false);
  });

  it("speaking 标在指定座位", () => {
    const m = seatModel({ state: last, speaking: 4 });
    expect(m[4]?.speaking).toBe(true);
    expect(m.filter((s) => s.speaking)).toHaveLength(1);
  });
});
