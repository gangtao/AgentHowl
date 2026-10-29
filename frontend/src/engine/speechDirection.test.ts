import { describe, expect, it } from "vitest";
import { initialState } from "./reduce";
import { effectiveSpeechDirection } from "./select";
import type { GameMeta, GameState } from "./types";
import fx from "./__fixtures__/std_9_kill_all-3.json";

const META = (fx as unknown as { meta: GameMeta }).meta;

/** 按引擎 _speech_order 的规则造 state：rule / 警长 / 基准方向 / 轮次。 */
function make(
  rule: string,
  over: Partial<Pick<GameState, "sheriff_seat" | "sheriff_speech_direction" | "round">>,
): GameState {
  const base = initialState({ ...META, config: { ...META.config, speech_order_rule: rule } });
  return { ...base, sheriff_seat: null, sheriff_speech_direction: null, round: 1, ...over };
}

describe("effectiveSpeechDirection（本轮实际发言方向，与 engine._speech_order 同规则）", () => {
  it("SHERIFF_DECIDES：奇数轮用警长定的基准方向", () => {
    const s = make("SHERIFF_DECIDES", { sheriff_seat: 3, sheriff_speech_direction: "RIGHT" });
    expect(effectiveSpeechDirection(s)).toBe("RIGHT");
  });

  it("SHERIFF_DECIDES：偶数轮换手——基准 RIGHT 的第 2 轮实际是 LEFT（g_065945f9 第 2 轮 [2,1,0,8,7,6,3]）", () => {
    const s = make("SHERIFF_DECIDES", {
      sheriff_seat: 3,
      sheriff_speech_direction: "RIGHT",
      round: 2,
    });
    expect(effectiveSpeechDirection(s)).toBe("LEFT");
  });

  it("SHERIFF_DECIDES：基准 LEFT 的偶数轮实际是 RIGHT", () => {
    const s = make("SHERIFF_DECIDES", {
      sheriff_seat: 0,
      sheriff_speech_direction: "LEFT",
      round: 4,
    });
    expect(effectiveSpeechDirection(s)).toBe("RIGHT");
  });

  it("SHERIFF_DECIDES：无警长 / 未定向时退回 death-next（顺时针）", () => {
    expect(effectiveSpeechDirection(make("SHERIFF_DECIDES", { round: 2 }))).toBe("RIGHT");
    expect(
      effectiveSpeechDirection(make("SHERIFF_DECIDES", { sheriff_seat: 2, round: 2 })),
    ).toBe("RIGHT");
  });

  it("ODD_EVEN_CLOCK：奇数轮顺时针、偶数轮逆时针", () => {
    expect(effectiveSpeechDirection(make("ODD_EVEN_CLOCK", { round: 1 }))).toBe("RIGHT");
    expect(effectiveSpeechDirection(make("ODD_EVEN_CLOCK", { round: 2 }))).toBe("LEFT");
  });

  it("FIXED_CLOCKWISE / DEATH_NEXT 恒为顺时针；BIDDING 没有方向", () => {
    expect(effectiveSpeechDirection(make("FIXED_CLOCKWISE", { round: 2 }))).toBe("RIGHT");
    expect(effectiveSpeechDirection(make("DEATH_NEXT", { round: 2 }))).toBe("RIGHT");
    expect(effectiveSpeechDirection(make("BIDDING", {}))).toBeNull();
  });
});
