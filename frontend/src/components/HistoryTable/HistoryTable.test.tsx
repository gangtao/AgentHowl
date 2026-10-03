import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HistoryTable from "./HistoryTable";

const base = {
  preset: "std_9_kill_side",
  num_players: 9,
  rounds: 2,
  seq: 50,
  seats: [
    { seat: 0, display_name: "夜枭", agent: true },
    { seat: 1, display_name: "Bot1", agent: false },
  ],
};

describe("HistoryTable", () => {
  it("三种状态的操作列", () => {
    render(
      <HistoryTable
        items={[
          {
            ...base,
            game_id: "g_f",
            status: "finished",
            started_at: "2026-10-02T03:00:00+00:00",
            ended_at: "2026-10-02T03:10:00+00:00",
            winner: "WOLF",
          },
          {
            ...base,
            game_id: "g_l",
            status: "live",
            started_at: "2026-10-02T02:00:00+00:00",
            ended_at: null,
            winner: null,
          },
          {
            ...base,
            game_id: "g_a",
            status: "aborted",
            started_at: "2026-10-02T01:00:00+00:00",
            ended_at: null,
            winner: null,
          },
        ]}
      />,
    );
    const replay = screen.getByRole("link", { name: /回放/ });
    expect(replay).toHaveAttribute("href", "#/g/g_f?replay=1");
    expect(screen.getByText(/狼人胜/)).toBeInTheDocument();
    expect(screen.getByText(/直播中/)).toBeInTheDocument();
    expect(screen.getByText(/中断/)).toBeInTheDocument();
    // 三行共用同一份 seats，座位列必然出现三次——用 getAllByText（brief 原文的 getByText
    // 会报 "Found multiple elements"，见 task-3-report.md）。
    expect(screen.getAllByText(/夜枭/)).toHaveLength(3);
  });
  it("删除按钮：已结束/中断可点并回调整行，直播中禁用（issue #100）", () => {
    const onDelete = vi.fn();
    const finished = {
      ...base,
      game_id: "g_f",
      status: "finished" as const,
      started_at: null,
      ended_at: null,
      winner: "GOOD",
    };
    render(
      <HistoryTable
        items={[
          finished,
          { ...base, game_id: "g_l", status: "live", started_at: null, ended_at: null, winner: null },
          {
            ...base,
            game_id: "g_a",
            status: "aborted",
            started_at: null,
            ended_at: null,
            winner: null,
          },
        ]}
        onDelete={onDelete}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: /删除/ });
    expect(buttons).toHaveLength(3);
    expect(buttons[1]).toBeDisabled();
    expect(buttons[0]).toBeEnabled();
    expect(buttons[2]).toBeEnabled();
    fireEvent.click(buttons[0]!);
    expect(onDelete).toHaveBeenCalledWith(finished);
  });
  it("不传 onDelete 则无删除按钮", () => {
    render(
      <HistoryTable
        items={[
          { ...base, game_id: "g_f", status: "finished", started_at: null, ended_at: null, winner: null },
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: /删除/ })).toBeNull();
  });
  it("空态", () => {
    render(<HistoryTable items={[]} />);
    expect(screen.getByText(/还没有对局/)).toBeInTheDocument();
  });
});
