// 积分展示纯函数（issue #123）：只排版服务端数字，不在前端算 Elo。

import { describe, expect, it } from "vitest";
import { EMPTY_RATING } from "../api/agents";
import { ratingLine } from "./rating";

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
