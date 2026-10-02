import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
  it("空态", () => {
    render(<HistoryTable items={[]} />);
    expect(screen.getByText(/还没有对局/)).toBeInTheDocument();
  });
});
