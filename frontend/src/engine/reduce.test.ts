import { describe, expect, it } from "vitest";
import { initialState, reduce, reduceAll } from "./reduce";
import { normalizeState } from "./normalize";
import type { Event, GameMeta, GameState } from "./types";
import f9s from "./__fixtures__/std_9_kill_side-3.json";
import f9a from "./__fixtures__/std_9_kill_all-3.json";
import f12i from "./__fixtures__/std_12_yn_hunter_idiot-3.json";
import f12g from "./__fixtures__/std_12_yn_hunter_guard-3.json";

interface Fixture {
  preset: string;
  seed: number;
  meta: GameMeta;
  events: Event[];
  states: GameState[];
}
const FIXTURES = [f9s, f9a, f12i, f12g] as unknown as Fixture[];

describe("reduce 与后端逐事件等价（金样）", () => {
  for (const fx of FIXTURES) {
    it(`${fx.preset} seed=${fx.seed}`, () => {
      let s = initialState(fx.meta);
      fx.events.forEach((e, i) => {
        s = reduce(s, e);
        const got = normalizeState(s);
        const want = normalizeState(fx.states[i]!);
        if (JSON.stringify(got) !== JSON.stringify(want)) {
          const diff = Object.keys(want).filter(
            (k) =>
              JSON.stringify((got as unknown as Record<string, unknown>)[k]) !==
              JSON.stringify((want as unknown as Record<string, unknown>)[k]),
          );
          throw new Error(`seq=${e.seq} type=${e.type} 不一致字段：${diff.join(",")}`);
        }
      });
      expect(s.phase).toBe("GAME_OVER");
      expect(normalizeState(reduceAll(initialState(fx.meta), fx.events))).toEqual(
        normalizeState(fx.states.at(-1)!),
      );
    });
  }
  it("未知事件类型抛错", () => {
    const fx = FIXTURES[0]!;
    const bad = { ...fx.events[0]!, type: "NOPE" } as unknown as Event;
    expect(() => reduce(initialState(fx.meta), bad)).toThrow(/未知事件类型/);
  });
  it("ROLES_ASSIGNED 缺座位时抛错", () => {
    const fx = FIXTURES[0]!;
    const rolesEvent = fx.events[2]!;
    expect(rolesEvent.type).toBe("ROLES_ASSIGNED");
    const payload = rolesEvent.payload as unknown as { assignments: [number, string][] };
    const truncated = {
      ...rolesEvent,
      payload: { assignments: payload.assignments.slice(1) },
    } as unknown as Event;
    expect(() => reduce(initialState(fx.meta), truncated)).toThrow(/缺少座位/);
  });
  it("SHERIFF_VOTE_STARTED 收窄候选集合时记录旁观候选人（issue #50）", () => {
    const fx = FIXTURES[0]!;
    const base = { ...fx.events[0]!, type: "SHERIFF_VOTE_STARTED", visibility: "PUBLIC" } as Event;
    let s = { ...initialState(fx.meta), sheriff_candidates: [1, 2, 5] };
    // 首轮开票：候选集合不变，不记旁观者
    s = reduce(s, { ...base, payload: { candidates: [1, 2, 5] } } as Event);
    expect(s.sheriff_pk_bystanders).toEqual([]);
    // 进 PK：收窄为平票者，5 号落选成旁观候选人
    s = reduce(s, { ...base, payload: { candidates: [2, 1] } } as Event);
    expect(s.sheriff_candidates).toEqual([2, 1]);
    expect(s.sheriff_pk_bystanders).toEqual([5]);
    expect(s.sheriff_votes).toEqual({});
  });
  it("normalizeState 幂等", () => {
    const st = FIXTURES[0]!.states[10]!;
    expect(normalizeState(normalizeState(st))).toEqual(normalizeState(st));
  });
});
