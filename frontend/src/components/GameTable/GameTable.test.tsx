import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SeatModel } from "../../lib/seatModel";
import GameTable from "./GameTable";

function seat(over: Partial<SeatModel> & { seat: number }): SeatModel {
  return {
    name: `P${over.seat}`,
    role: null,
    alive: true,
    me: false,
    speaking: false,
    dim: false,
    selectable: false,
    selected: false,
    x: 50,
    y: 9,
    badges: { sheriff: false, candidate: false, votes: null, mark: null, tag: null },
    status: { text: "", tone: "none" },
    ...over,
  };
}

const base = {
  night: false,
  center: { kind: "campfire", note: "x" } as const,
  speech: null,
  avatars: {},
};

describe("GameTable（规格 §4.2）", () => {
  it("渲染全部座位；selectable 的可点并回调，其余 disabled 不回调", () => {
    const onSelect = vi.fn();
    render(
      <GameTable
        {...base}
        seats={[
          seat({ seat: 0, selectable: true }),
          seat({ seat: 1 }),
          seat({ seat: 2, alive: false }),
        ]}
        onSelectSeat={onSelect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^0号/ }));
    fireEvent.click(screen.getByRole("button", { name: /^1号/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(0);
    expect(screen.getByRole("button", { name: /^1号/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^2号.*出局/ })).toBeDisabled();
  });

  it("徽章：票数 5.5 原样、候选「警」、已验「狼人」、警长", () => {
    render(
      <GameTable
        {...base}
        seats={[
          seat({
            seat: 0,
            badges: { sheriff: false, candidate: true, votes: 5.5, mark: null, tag: null },
          }),
          seat({
            seat: 1,
            badges: { sheriff: true, candidate: false, votes: null, mark: "狼人", tag: "被刀" },
          }),
        ]}
      />,
    );
    expect(screen.getByText("5.5")).toBeInTheDocument();
    expect(screen.getByText("警")).toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByText("被刀")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^1号.*警长/ })).toBeInTheDocument();
  });

  it("夜间 dim 座位带 data-dim；本人 data-me；发言者 data-speaking", () => {
    render(
      <GameTable
        {...base}
        night
        seats={[seat({ seat: 0, dim: true }), seat({ seat: 1, me: true, speaking: true })]}
      />,
    );
    expect(screen.getByRole("button", { name: /^0号/ })).toHaveAttribute("data-dim", "true");
    const me = screen.getByRole("button", { name: /^1号/ });
    expect(me).toHaveAttribute("data-me", "true");
    expect(me).toHaveAttribute("data-speaking", "true");
  });

  it("已知角色渲染徽记，未知渲染首字", () => {
    const { container } = render(
      <GameTable
        {...base}
        seats={[seat({ seat: 0, role: "SEER" }), seat({ seat: 1, name: "Gang" })]}
      />,
    );
    expect(container.querySelectorAll("svg path")).toHaveLength(1);
    expect(screen.getByRole("img", { name: "身份未知" })).toHaveTextContent("G");
  });
});

describe("GameTable 座位状态行（规格 §4.1）", () => {
  it("名字下方有状态行，data-tone 与文案来自 SeatModel.status；空串也占位", () => {
    const seats = [
      seat({ seat: 0, status: { text: "发言中", tone: "now" } }),
      seat({ seat: 1, status: { text: "", tone: "none" } }),
      seat({ seat: 2, alive: false, status: { text: "出局", tone: "dead" } }),
    ];
    render(<GameTable seats={seats} night={false} center={{ kind: "none" }} speech={null} avatars={{}} />);
    const first = document.querySelector('button[data-seat="0"] [data-tone]')!;
    expect(first).toHaveAttribute("data-tone", "now");
    expect(first).toHaveTextContent("发言中");
    expect(document.querySelector('button[data-seat="1"] [data-tone="none"]')).toBeInTheDocument();
    expect(document.querySelector('button[data-seat="2"] [data-tone="dead"]')).toHaveTextContent("出局");
    expect(document.querySelectorAll("button[data-seat] [data-tone]").length).toBe(3);
  });
});

