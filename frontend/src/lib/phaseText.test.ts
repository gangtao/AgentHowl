import { describe, expect, it } from "vitest";
import { statusText } from "./phaseText";

describe("statusText（顶栏居中状态）", () => {
  it("终局文案用传入的最终胜方，而不是回放游标处的 state", () => {
    expect(statusText("WOLF", "replay", "idle", 416, true)).toEqual({
      text: "游戏结束：狼人阵营胜",
      tone: "over",
    });
    expect(statusText(null, "replay", "idle", 416, true).text).toBe("游戏结束：平局");
  });
  it("直播 / 回放 / 连接态", () => {
    expect(statusText(null, "live", "open", 12, false)).toEqual({ text: "● 直播 · seq 12", tone: "live" });
    expect(statusText(null, "replay", "idle", 99, false)).toEqual({ text: "▶ 回放 · 99 条事件", tone: "replay" });
    expect(statusText(null, "live", "closed", 12, false).tone).toBe("warn");
  });
});
