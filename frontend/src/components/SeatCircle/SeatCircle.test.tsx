// 冒烟测试：座位环的角色牌（GM 缩写 / 观众背面）、出局 aria-label、当前发言标记。

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import type { GameState } from "../../engine/types";
import SeatCircle from "./SeatCircle";

const states = fixture.states as unknown as GameState[];
const finalState = states[states.length - 1] as GameState;

describe("SeatCircle", () => {
  it("GM 视角渲染角色缩写：9 人局 3 匹狼", () => {
    render(
      <SeatCircle state={finalState} viewer="GM" speaking={null} votes={{}} nightLines={[]} />,
    );
    expect(screen.getAllByText("狼")).toHaveLength(3);
  });

  it("观众视角角色牌为背面 ?（与 state 是否带角色无关）", () => {
    render(
      <SeatCircle
        state={finalState}
        viewer="SPECTATOR"
        speaking={null}
        votes={{}}
        nightLines={[]}
      />,
    );
    expect(screen.getAllByText("?")).toHaveLength(finalState.players.length);
  });

  it("出局座位的 aria-label 含「出局」", () => {
    render(
      <SeatCircle state={finalState} viewer="GM" speaking={null} votes={{}} nightLines={[]} />,
    );
    const dead = finalState.players.filter((p) => !p.alive);
    expect(dead.length).toBeGreaterThan(0);
    for (const p of dead) {
      const el = screen.getByLabelText(new RegExp(`^${p.seat}号 .*出局`));
      expect(el).toBeInTheDocument();
    }
  });

  it("当前发言座位带 data-speaking", () => {
    const speaking = finalState.players[2]!.seat;
    const { container } = render(
      <SeatCircle state={finalState} viewer="GM" speaking={speaking} votes={{}} nightLines={[]} />,
    );
    const marked = container.querySelectorAll("[data-speaking]");
    expect(marked).toHaveLength(1);
    expect(marked[0]!.getAttribute("aria-label")).toContain(`${speaking}号`);
  });
});
