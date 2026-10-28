import { describe, expect, it } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameState } from "../engine/types";
import { graveyard, townNews } from "./village";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1] as GameState;
const upTo = (seq: number): Event[] => events.filter((e) => e.seq <= seq);
/** states[i] 是 events[i] 应用之后的状态。 */
const stateAfter = (seq: number): GameState => states[events.findIndex((e) => e.seq === seq)] as GameState;

describe("graveyard（规格 §4.5）", () => {
  it("按出局顺序列出自爆 / 夜死 / 被带走 / 放逐，角色全知时带 role", () => {
    const rows = graveyard(events, last);
    expect(rows.slice(0, 4).map((r) => [r.seat, r.cause])).toEqual([
      [6, "self_destruct"],
      [7, "night"],
      [4, "shot"],
      [3, "exiled"],
    ]);
    expect(rows[0]?.when).toMatch(/^第 \d+ 天自爆$/);
    expect(rows[1]?.when).toMatch(/^第 \d+ 夜死亡$/);
    expect(rows[2]?.when).toMatch(/^第 \d+ 天被带走$/);
    expect(rows[3]?.when).toMatch(/^第 \d+ 天放逐$/);
    expect(rows.every((r) => r.role !== null)).toBe(true);
    expect(rows.every((r) => r.name !== "")).toBe(true);
  });

  it("角色未知时 role 为 null，knownRoles 可覆盖", () => {
    const blank: GameState = {
      ...last,
      players: last.players.map((p) => ({ ...p, role: "VILLAGER" as const, faction: "GOOD" as const })),
    };
    const rows = graveyard(events, blank, { 6: "WEREWOLF" });
    expect(rows[0]?.role).toBe("WEREWOLF");
    expect(rows[1]?.role).toBeNull();
  });

  it("没有死亡事件 → 空", () => {
    expect(graveyard(upTo(5), stateAfter(5))).toEqual([]);
  });
});

describe("townNews", () => {
  it("有死讯的白天：昨夜 / 今日 / 警长 / 存活 / 阵营", () => {
    // seq 62 是 HUNTER_SHOT（第 2 天），其后白天发言
    const i = events.findIndex((e) => e.seq > 62 && e.type === "PHASE_CHANGED" && (e.payload as { to: string }).to === "DAY_SPEECH");
    const e = events[i] as Event;
    const rows = townNews(upTo(e.seq), states[i] as GameState);
    expect(rows.map((r) => r.k)).toEqual(["昨夜", "今日", "警长", "存活", "阵营"]);
    expect(rows[0]?.v).toBe("7号 死亡");
    expect(rows[1]?.v).toContain("4号 被带走");
    expect(rows[3]?.v).toMatch(/^\d+\/9$/);
    expect(rows[4]).toMatchObject({ tone: "wolf" });
  });

  it("开局前：只有警长与存活", () => {
    expect(townNews(upTo(1), states[0] as GameState).map((r) => r.k)).toEqual(["警长", "存活"]);
  });

  it("平安夜写「平安夜」", () => {
    const i = events.findIndex(
      (e) => e.type === "DEATH_ANNOUNCED" && (e.payload as { seats: number[] }).seats.length === 0,
    );
    const e = events[i] as Event;
    expect(townNews(upTo(e.seq), states[i] as GameState)[0]).toMatchObject({ k: "昨夜", v: "平安夜" });
  });
});
