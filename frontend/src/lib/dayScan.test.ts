// dayScan（规格 R12 / §6.1）：日夜标签只从事件流推导，上帝全量流与玩家过滤流必须给出同样的标签。

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
    const fullMarks = dayMarks(events);
    const full = new Map(events.map((e, i) => [e.seq, fullMarks[i]]));
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
    // 天亮之前第一条 day 标记（可能是公开的 PHASE_CHANGED to DEATH_ANNOUNCE）也必须是第 1 天
    const firstDay = marks.findIndex((m) => m.kind === "day");
    expect(marks[firstDay]).toEqual({ kind: "day", n: 1 });
    expect(marks[firstDay - 1]?.kind).not.toBe("day");
  });

  it("dayLabel 文案", () => {
    expect(dayLabel({ kind: "start", n: 0 })).toBe("开局");
    expect(dayLabel({ kind: "night", n: 2 })).toBe("第 2 夜");
    expect(dayLabel({ kind: "day", n: 2 })).toBe("第 2 天");
  });

  it.each([
    ["观众（只剩 PUBLIC）", (v: string) => v === "PUBLIC"],
    ["村民 / 神职（PUBLIC ∪ ROLE_SELF）", (v: string) => v === "PUBLIC" || v === "ROLE_SELF"],
    ["狼人（PUBLIC ∪ WOLVES）", (v: string) => v === "PUBLIC" || v === "WOLVES"],
  ])("%s：每条可见事件的日夜与上帝流完全相同（评审 C1）", (_n, keep) => {
    const fullMarks = dayMarks(events);
    const full = new Map(events.map((e, i) => [e.seq, dayLabel(fullMarks[i]!)]));
    const visible = events.filter((e) => keep(e.visibility));
    const marks = dayMarks(visible);
    const mismatches = visible.filter((e, i) => dayLabel(marks[i]!) !== full.get(e.seq));
    expect(mismatches.map((e) => `${e.seq}:${e.type}`)).toEqual([]);
    // 六次天亮依次是第 1…6 天
    const dawns = visible
      .map((e, i) => (e.type === "DEATH_ANNOUNCED" ? dayLabel(marks[i]!) : null))
      .filter((x): x is string => x !== null);
    expect(dawns).toEqual(dawns.map((_, i) => `第 ${i + 1} 天`));
  });

  it("女巫只收到自己的 ROLE_SKIPPED：它也开夜", () => {
    const visible = events.filter(
      (e) => e.visibility === "PUBLIC" || (e.type === "ROLE_SKIPPED" && e.visibility === "ROLE_SELF"),
    );
    const marks = dayMarks(visible);
    const i = visible.findIndex((e) => e.type === "ROLE_SKIPPED");
    expect(i).toBeGreaterThan(-1);
    expect(marks[i]?.kind).toBe("night");
  });
});
