import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HistoryTable from "./HistoryTable";

const base = {
  preset: "std_9_kill_side",
  num_players: 9,
  rounds: 2,
  seq: 50,
  owner_id: "u_1",
  owner_name: "alice",
  share_token: "S" as string | null,
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
    expect(replay).toHaveAttribute("href", "#/g/g_f");
    expect(screen.getByRole("link", { name: /观看/ })).toHaveAttribute("href", "#/g/g_l");
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
          {
            ...base,
            game_id: "g_l",
            status: "live",
            started_at: null,
            ended_at: null,
            winner: null,
          },
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
          {
            ...base,
            game_id: "g_f",
            status: "finished",
            started_at: null,
            ended_at: null,
            winner: null,
          },
        ]}
      />,
    );
    expect(screen.queryByRole("button", { name: /删除/ })).toBeNull();
  });
  it("空态", () => {
    render(<HistoryTable items={[]} />);
    expect(screen.getByText(/还没有对局/)).toBeInTheDocument();
  });
  it("onShare：有「分享」按钮，share_token 为 null 时禁用；showOwner 多一列创建者", () => {
    const onShare = vi.fn();
    const row = {
      ...base,
      game_id: "g_f",
      status: "finished" as const,
      started_at: null,
      ended_at: null,
      winner: "GOOD",
    };
    render(
      <HistoryTable
        items={[row, { ...row, game_id: "g_n", share_token: null, owner_name: null }]}
        onShare={onShare}
        showOwner
      />,
    );
    expect(screen.getByRole("columnheader", { name: "创建者" })).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    const btns = screen.getAllByRole("button", { name: "分享" });
    expect(btns[0]).toBeEnabled();
    expect(btns[1]).toBeDisabled();
    fireEvent.click(btns[0]!);
    expect(onShare).toHaveBeenCalledWith(expect.objectContaining({ game_id: "g_f" }));
  });

  it("羊皮纸账本：table-parch；胜方按阵营着色，null 胜方「—」不着色；时间 null「—」", () => {
    render(
      <HistoryTable
        items={[
          {
            ...base,
            game_id: "g_g",
            status: "finished",
            started_at: "2026-10-02T03:00:00+00:00",
            ended_at: null,
            winner: "GOOD",
          },
          {
            ...base,
            game_id: "g_w",
            status: "finished",
            started_at: null,
            ended_at: null,
            winner: "WOLF",
          },
          {
            ...base,
            game_id: "g_n",
            status: "aborted",
            started_at: null,
            ended_at: null,
            winner: null,
          },
        ]}
      />,
    );
    expect(document.querySelector("table")).toHaveClass("table-parch");
    // 羊皮纸上用深金 --ah-god-hi（浅金 --ah-god 对比度只有 1.6:1）
    expect(screen.getByText("好人胜")).toHaveStyle({ color: "var(--ah-god-hi)" });
    expect(screen.getByText("狼人胜")).toHaveStyle({ color: "var(--ah-wolf)" });
    // 两行 started_at null + 一行 winner null → 至少 3 个「—」
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("直播中的状态签不用夜色用的 tag-accent-2（羊皮纸上不可读）；未知胜方原样不着色", () => {
    render(
      <HistoryTable
        items={[
          { ...base, game_id: "g_l", status: "live", started_at: null, ended_at: null, winner: null },
          { ...base, game_id: "g_d", status: "finished", started_at: null, ended_at: null, winner: "DRAW" },
        ]}
      />,
    );
    const live = screen.getByText("直播中");
    expect(live).toHaveClass("tag");
    expect(live).not.toHaveClass("tag-accent-2");
    const draw = screen.getByText("DRAW");
    expect(draw.getAttribute("style")).toBeNull();
  });
});
