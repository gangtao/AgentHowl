// 积分展示纯函数（issue #123）：只排版服务端数字，不在前端算 Elo。

import { describe, expect, it } from "vitest";
import { EMPTY_RATING } from "../api/agents";
import type { StoredAgent } from "../api/agents";
import { ratingLine, sortAgents } from "./rating";

describe("ratingLine", () => {
  it("取整积分、四舍五入胜率；0 局为「尚无战绩」", () => {
    expect(ratingLine({ rating: 1015.6, games: 12, wins: 7, losses: 4, draws: 1 })).toBe(
      "1016 分 · 12 局 · 胜率 58%",
    );
    expect(ratingLine({ rating: 1024, games: 12, wins: 7, losses: 5, draws: 0 })).toBe(
      "1024 分 · 12 局 · 胜率 58%",
    );
    expect(ratingLine(EMPTY_RATING)).toBe("尚无战绩");
  });
});

function agent(id: string, name: string, rating: number, games: number, updated: string): StoredAgent {
  return {
    agent_id: id,
    profile: { name, model: "m", skills: [] },
    created_at: updated,
    updated_at: updated,
    rating: { rating, games, wins: games, losses: 0, draws: 0 },
  };
}

// 服务端按 updated_at 倒序返回
const ITEMS: StoredAgent[] = [
  agent("a_new", "新人", 1000, 0, "2026-10-26T00:00:00+00:00"),
  agent("a_mid", "中坚", 1016, 1, "2026-10-25T00:00:00+00:00"),
  agent("a_vet", "老将", 1016, 5, "2026-10-24T00:00:00+00:00"),
  agent("a_top", "顶尖", 1100, 3, "2026-10-23T00:00:00+00:00"),
];

describe("sortAgents", () => {
  it("积分降序 → 场次降序 → 名字；最近更新保持服务端顺序且不改入参", () => {
    const before = ITEMS.map((a) => a.agent_id);
    expect(sortAgents(ITEMS, "rating").map((a) => a.agent_id)).toEqual(["a_top", "a_vet", "a_mid", "a_new"]);
    expect(sortAgents(ITEMS, "updated").map((a) => a.agent_id)).toEqual(before);
    expect(ITEMS.map((a) => a.agent_id)).toEqual(before);
  });
});
