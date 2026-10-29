// readingDwellMs（规格 R9 / §7）：回放静音时按字数折算的阅读停留。

import { describe, expect, it } from "vitest";
import type { Event } from "../engine/types";
import { readingDwellMs } from "./readingDwell";

const spoke = (content: string): Event =>
  ({
    seq: 1,
    game_id: "g",
    ts: 0,
    type: "PLAYER_SPOKE",
    actor_seat: 2,
    visibility: "PUBLIC",
    meta: {},
    payload: { content, claim_role: null, badge_flow: [] },
  }) as unknown as Event;

describe("readingDwellMs（规格 R9）", () => {
  it("空正文 1.5 s；每字 150 ms；200 字封顶 30 s；倍速除", () => {
    expect(readingDwellMs(spoke(""), 1)).toBe(1500);
    expect(readingDwellMs(spoke("十个字十个字十个字十"), 1)).toBe(3000);
    expect(readingDwellMs(spoke("字".repeat(200)), 1)).toBe(30000);
    expect(readingDwellMs(spoke("字".repeat(200)), 2)).toBe(15000);
  });

  it("遗言同发言；其它事件与 undefined 为 0", () => {
    const lw = {
      ...spoke("走了"),
      type: "LAST_WORDS",
      payload: { seat: 2, content: "走了" },
    } as unknown as Event;
    expect(readingDwellMs(lw, 1)).toBe(1800);
    expect(readingDwellMs({ ...spoke("x"), type: "VOTE_CAST" } as Event, 1)).toBe(0);
    expect(readingDwellMs(undefined, 1)).toBe(0);
  });
});
