// 冒烟测试：角色牌由数据决定（Ruling 10 / spec §1 零过滤）、出局 aria-label、当前发言标记。

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import type { GameState } from "../../engine/types";
import SeatCircle from "./SeatCircle";

const states = fixture.states as unknown as GameState[];
const preDealState = states[0] as GameState;
const finalState = states[states.length - 1] as GameState;

describe("SeatCircle", () => {
  it("发牌前（全员默认 VILLAGER/GOOD）角色牌为背面 ?，不冒充「民」", () => {
    render(<SeatCircle state={preDealState} speaking={null} votes={{}} nightLines={[]} />);
    expect(screen.getAllByText("?")).toHaveLength(preDealState.players.length);
    expect(screen.queryAllByText("民")).toHaveLength(0);
  });

  it("state 里已有角色时照实翻牌（零过滤：与 viewer 无关）", () => {
    render(<SeatCircle state={finalState} speaking={null} votes={{}} nightLines={[]} />);
    expect(screen.getAllByText("狼")).toHaveLength(3);
    expect(screen.queryAllByText("?")).toHaveLength(0);
  });

  it("出局座位的 aria-label 含「出局」", () => {
    render(<SeatCircle state={finalState} speaking={null} votes={{}} nightLines={[]} />);
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
      <SeatCircle state={finalState} speaking={speaking} votes={{}} nightLines={[]} />,
    );
    const marked = container.querySelectorAll("[data-speaking]");
    expect(marked).toHaveLength(1);
    expect(marked[0]!.getAttribute("aria-label")).toContain(`${speaking}号`);
  });
});
