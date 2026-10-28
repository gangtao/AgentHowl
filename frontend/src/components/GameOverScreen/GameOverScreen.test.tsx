import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import fixture from "../../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameState } from "../../engine/types";
import { fateOf } from "../../lib/village";
import GameOverScreen from "./GameOverScreen";

const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];
const last = states[states.length - 1] as GameState; // 狼胜，角色全知

describe("fateOf", () => {
  it("存活 → 存活；出局 → 墓地文案", () => {
    const alive = last.players.find((p) => p.alive)!.seat;
    expect(fateOf(alive, events, last)).toBe("存活");
    expect(fateOf(6, events, last)).toMatch(/^第 \d+ 天自爆$/);
    expect(fateOf(7, events, last)).toMatch(/^第 \d+ 夜死亡$/);
  });
});

describe("GameOverScreen（规格 §4.8，设计稿 1i）", () => {
  it("狼胜：文案、data-winner、揭晓网格、三个按钮", () => {
    const onReplay = vi.fn();
    render(<GameOverScreen state={last} events={events} total={129} onReplay={onReplay} />);
    const root = screen.getByRole("region", { name: "游戏结束" });
    expect(root).toHaveAttribute("data-winner", "WOLF");
    expect(screen.getByText("狼人阵营胜")).toBeInTheDocument();
    expect(screen.getByText(/WOLF · 屠边成功 · 129 条事件/)).toBeInTheDocument();
    expect(screen.getAllByRole("img").length).toBe(last.players.length);
    fireEvent.click(screen.getByRole("button", { name: "查看全局回放" }));
    expect(onReplay).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "再来一局" })).toHaveAttribute("href", "#/");
    expect(screen.getByRole("link", { name: "回到历史对局" })).toHaveAttribute("href", "#/history");
  });

  it("好人胜 / 平局文案；没有 onReplay 不渲染回放按钮", () => {
    const { unmount } = render(
      <GameOverScreen state={{ ...last, winner: "GOOD" }} events={events} total={10} />,
    );
    expect(screen.getByRole("region", { name: "游戏结束" })).toHaveAttribute("data-winner", "GOOD");
    expect(screen.getByText("好人阵营胜")).toBeInTheDocument();
    expect(screen.getByText(/GOOD · 狼人出清 · 10 条事件/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看全局回放" })).toBeNull();
    unmount();
    render(<GameOverScreen state={{ ...last, winner: null }} events={events} total={10} />);
    expect(screen.getByText("平局")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "游戏结束" })).toHaveAttribute("data-winner", "TIE");
  });

  it("角色未知显示「?」，knownRoles 可覆盖", () => {
    const unknown: GameState = {
      ...last,
      players: last.players.map((p) => ({
        ...p,
        role: "VILLAGER" as const,
        faction: "GOOD" as const,
      })),
    };
    render(
      <GameOverScreen state={unknown} events={events} total={10} knownRoles={{ 0: "SEER" }} />,
    );
    expect(screen.getAllByRole("img", { name: "身份未知" }).length).toBe(last.players.length - 1);
    expect(screen.getByRole("img", { name: "预言家" })).toBeInTheDocument();
  });
});
