import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import type { GameState } from "../../engine/types";
import PlayerStatusPanel from "./PlayerStatusPanel";

const states = fixture.states as unknown as GameState[];
const day = states.find((s) => s.phase === "DAY_SPEECH") as GameState;

/** 引擎已把发言权交给下一位（speech_idx 指向 5 号），但 2 号的配音还在播。 */
const state: GameState = { ...day, speech_order: [2, 5, 6], speech_idx: 1, sheriff_seat: null };

/** 「N号」在备注行 / 警徽流里也会出现：只取带状态签的那一行。 */
function statusOf(seat: number): string {
  const rows = screen
    .getAllByText(`${seat}号`)
    .map((el) => el.closest("div") as HTMLElement)
    .filter((row) => within(row).queryByText(/已发言|发言中|待发言/) !== null);
  expect(rows).toHaveLength(1);
  return within(rows[0] as HTMLElement).getByText(/已发言|发言中|待发言/).textContent ?? "";
}

describe("PlayerStatusPanel 发言顺序状态", () => {
  it("正在出声的座位标「发言中」，即使引擎已经轮到下一位（用户反馈：2 号正在说却显示已发言）", () => {
    render(<PlayerStatusPanel state={state} speakingSeat={2} />);
    expect(statusOf(2)).toBe("发言中");
    expect(statusOf(5)).toBe("待发言");
    expect(statusOf(6)).toBe("待发言");
  });

  it("配音跟上引擎后：前面的已发言、当前发言中、后面待发言", () => {
    render(<PlayerStatusPanel state={state} speakingSeat={5} />);
    expect(statusOf(2)).toBe("已发言");
    expect(statusOf(5)).toBe("发言中");
    expect(statusOf(6)).toBe("待发言");
  });
});
