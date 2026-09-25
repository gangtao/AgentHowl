import { describe, expect, it } from "vitest";
import { initialState, reduceAll } from "./reduce";
import {
  aliveSeats,
  nightSummary,
  roundSegments,
  rolesKnown,
  speechItems,
  voteTally,
  wolfSeats,
} from "./select";
import type { Event, GameMeta, GameState, VoteResultPayload } from "./types";
import fx from "./__fixtures__/std_9_kill_side-3.json";
import fx9a from "./__fixtures__/std_9_kill_all-3.json";
import fx12i from "./__fixtures__/std_12_yn_hunter_idiot-3.json";
import fx12g from "./__fixtures__/std_12_yn_hunter_guard-3.json";

interface Fixture {
  preset: string;
  seed: number;
  meta: GameMeta;
  events: Event[];
  states: GameState[];
}
const FX = fx as unknown as Fixture;
const ALL_FIXTURES = [fx, fx9a, fx12i, fx12g] as unknown as Fixture[];

describe("select 选择器（std_9_kill_side-3 金样）", () => {
  const finalState = FX.states.at(-1)!;

  it("aliveSeats 与 players.alive 一致", () => {
    expect(aliveSeats(finalState).length).toBe(finalState.players.filter((p) => p.alive).length);
  });

  it("wolfSeats 为 3 个（该 preset 3 狼）", () => {
    expect(wolfSeats(finalState).length).toBe(3);
  });

  it("rolesKnown：发牌后为 true，发牌前（全员默认 VILLAGER/GOOD）为 false", () => {
    expect(rolesKnown(finalState)).toBe(true);
    expect(rolesKnown(FX.states[0]!)).toBe(false);
  });

  it("voteTally 与首个 VOTE_RESULT 的 tally 一致", () => {
    const idx = FX.events.findIndex((e) => e.type === "VOTE_RESULT");
    expect(idx).toBeGreaterThanOrEqual(0);
    const prefix = FX.events.slice(0, idx + 1);
    const stateAt = reduceAll(initialState(FX.meta), prefix);
    const { tally } = voteTally(stateAt, prefix);
    const want = (FX.events[idx]!.payload as VoteResultPayload).tally;
    expect(tally).toEqual(want);
  });

  it("speechItems 中发言项数 = PLAYER_SPOKE 数", () => {
    const items = speechItems(FX.events);
    const spokeCount = FX.events.filter((e) => e.type === "PLAYER_SPOKE").length;
    expect(items.filter((it) => it.kind === "speech").length).toBe(spokeCount);
    expect(items.length).toBe(FX.events.length);
  });

  it("nightSummary(events, 1) 至少含狼队决定行", () => {
    const rows = nightSummary(FX.events, 1);
    expect(rows.some((r) => r.text.includes("狼队决定刀") || r.text.includes("狼队空刀"))).toBe(
      true,
    );
  });
});

describe("roundSegments 连续覆盖 events[0].seq..events.at(-1).seq（4 份金样）", () => {
  for (const fixture of ALL_FIXTURES) {
    it(`${fixture.preset} seed=${fixture.seed}`, () => {
      const segs = roundSegments(fixture.events);
      expect(segs.length).toBeGreaterThan(0);
      expect(segs[0]!.fromSeq).toBe(fixture.events[0]!.seq);
      expect(segs.at(-1)!.toSeq).toBe(fixture.events.at(-1)!.seq);
      segs.forEach((seg, i) => {
        expect(seg.fromSeq).toBeLessThanOrEqual(seg.toSeq);
        if (i > 0) {
          expect(seg.fromSeq).toBe(segs[i - 1]!.toSeq + 1);
        }
      });
    });
  }
});
