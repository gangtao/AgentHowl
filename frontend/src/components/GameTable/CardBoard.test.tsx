import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SeatModel } from "../../lib/seatModel";
import CardBoard from "./CardBoard";

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
const many = (n: number): SeatModel[] => Array.from({ length: n }, (_, i) => seat({ seat: i }));

const base = {
  night: false,
  center: { kind: "campfire", note: "x" } as const,
  speech: null,
  avatars: {},
};

describe("CardBoard（规格 §7 卡牌皮肤）", () => {
  it("12 座 / 9 座：每座一张 button[data-seat]；可选的可点并回调，其余 disabled", () => {
    const onSelect = vi.fn();
    const { unmount } = render(<CardBoard {...base} seats={many(12)} />);
    expect(document.querySelectorAll("button[data-seat]")).toHaveLength(12);
    unmount();
    render(
      <CardBoard
        {...base}
        seats={[seat({ seat: 0, selectable: true, selected: true }), ...many(9).slice(1)]}
        onSelectSeat={onSelect}
      />,
    );
    expect(document.querySelectorAll("button[data-seat]")).toHaveLength(9);
    fireEvent.click(screen.getByRole("button", { name: /^0号/ }));
    fireEvent.click(screen.getByRole("button", { name: /^1号/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(0);
    expect(screen.getByRole("button", { name: /^0号/ })).toHaveAttribute("data-selected", "true");
    expect(screen.getByRole("button", { name: /^1号/ })).toBeDisabled();
  });

  it("正面 / 牌背 / 出局：已知角色徽记 + 角色名；未知首字 + 「身份未翻」；出局未知「出局」；出局已知仍显角色 + ✕ 章", () => {
    render(
      <CardBoard
        {...base}
        seats={[
          seat({ seat: 0, role: "WEREWOLF" }),
          seat({ seat: 1, name: "Gang" }),
          seat({ seat: 2, alive: false }),
          seat({ seat: 3, role: "SEER", alive: false }),
        ]}
      />,
    );
    const b = (n: number): HTMLElement =>
      screen.getByRole("button", { name: new RegExp(`^${n}号`) });
    expect(b(0)).toHaveAttribute("data-face", "front");
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(b(1)).toHaveAttribute("data-face", "back");
    expect(b(1)).toHaveTextContent("G");
    expect(b(1)).toHaveTextContent("身份未翻");
    expect(b(2)).toHaveAttribute("data-face", "dead");
    expect(b(2)).toHaveTextContent("出局");
    expect(b(3)).toHaveAttribute("data-face", "dead");
    expect(b(3)).toHaveTextContent("预言家");
    expect(b(3).querySelector("[data-stamp]")).not.toBeNull();
    expect(b(3)).toHaveAttribute("aria-label", expect.stringContaining("出局"));
  });

  it("票数 2.5 原样；并列最高者都 data-leader；候选「警」；警长 ★；夜间目标红签 data-target；dim / me / speaking", () => {
    render(
      <CardBoard
        {...base}
        night
        seats={[
          seat({
            seat: 0,
            badges: { sheriff: false, candidate: true, votes: 2.5, mark: null, tag: null },
          }),
          seat({
            seat: 1,
            badges: { sheriff: true, candidate: false, votes: 2.5, mark: "狼人", tag: null },
          }),
          seat({
            seat: 2,
            badges: { sheriff: false, candidate: false, votes: 1, mark: null, tag: "被刀" },
          }),
          seat({ seat: 3, dim: true, me: true, speaking: true }),
        ]}
      />,
    );
    const b = (n: number): HTMLElement =>
      screen.getByRole("button", { name: new RegExp(`^${n}号`) });
    expect(screen.getAllByText("2.5")).toHaveLength(2);
    expect(b(0)).toHaveAttribute("data-leader", "true");
    expect(b(1)).toHaveAttribute("data-leader", "true");
    expect(b(2)).not.toHaveAttribute("data-leader");
    expect(screen.getByText("警")).toBeInTheDocument();
    expect(screen.getByText("★")).toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByText("被刀")).toBeInTheDocument();
    expect(b(2)).toHaveAttribute("data-target", "true");
    expect(b(3)).toHaveAttribute("data-dim", "true");
    expect(b(3)).toHaveAttribute("data-me", "true");
    expect(b(3)).toHaveAttribute("data-speaking", "true");
  });

  it("发言条在牌阵下方（role=status，不定位）；center 为 tally 时渲染桌心内容，campfire 不渲染", () => {
    const { rerender } = render(
      <CardBoard
        {...base}
        seats={many(4)}
        speech={{
          items: [],
          speaker: 1,
          kind: "speech",
          deadline: null,
          voicing: false,
          mine: false,
        }}
      />,
    );
    const status = screen.getByRole("status", { name: "1号 P1 发言中" });
    expect(status.style.left).toBe("");
    expect(screen.queryByText("x")).toBeNull();
    rerender(
      <CardBoard
        {...base}
        seats={many(4)}
        center={{
          kind: "tally",
          cast: 1,
          voters: 3,
          rows: [{ target: 2, name: "P2", votes: 1, from: [0] }],
          waiting: [1, 3],
          election: false,
        }}
      />,
    );
    expect(screen.getByText(/已投 1\/3|1\/3/)).toBeInTheDocument();
  });

  it("篝火不渲染桌心容器（空盒子会把下方内容挤出视口）；发言进度一行与月亮都渲染", () => {
    const { rerender } = render(
      <CardBoard {...base} seats={many(4)} center={{ kind: "campfire", note: "x" }} />,
    );
    expect(screen.queryByTestId("card-center")).toBeNull();
    rerender(
      <CardBoard
        {...base}
        seats={many(4)}
        center={{ kind: "speechProgress", lastNight: null, lastTally: null, done: 2, total: 4, next: 3 }}
      />,
    );
    expect(screen.getByTestId("card-center")).toHaveTextContent("发言进度 2 / 4 · 下一位 3号");
    rerender(<CardBoard {...base} seats={many(4)} center={{ kind: "moon", sub: "x" }} />);
    expect(screen.getByTestId("card-center")).toBeInTheDocument();
  });

  it("准星 / 水晶在卡牌模式下带 data-orb，供 CSS 缩成小圆（issue #176）", () => {
    const { rerender } = render(
      <CardBoard {...base} seats={many(4)} center={{ kind: "crosshair", seat: 2 }} />,
    );
    expect(screen.getByTestId("card-center").querySelector("[data-orb]")).not.toBeNull();
    rerender(<CardBoard {...base} seats={many(4)} center={{ kind: "crystal", seat: 2 }} />);
    expect(screen.getByTestId("card-center").querySelector("[data-orb]")).not.toBeNull();
  });
});

describe("CardBoard 座位状态行（规格 §4.1）", () => {
  it("名字下方有状态行，data-tone 与文案来自 SeatModel.status；空串也占位", () => {
    const seats = [
      seat({ seat: 0, status: { text: "发言中", tone: "now" } }),
      seat({ seat: 1, status: { text: "", tone: "none" } }),
      seat({ seat: 2, alive: false, status: { text: "出局", tone: "dead" } }),
    ];
    render(<CardBoard seats={seats} night={false} center={{ kind: "none" }} speech={null} avatars={{}} />);
    const first = document.querySelector('button[data-seat="0"] [data-tone]')!;
    expect(first).toHaveAttribute("data-tone", "now");
    expect(first).toHaveTextContent("发言中");
    expect(document.querySelector('button[data-seat="1"] [data-tone="none"]')).toBeInTheDocument();
    expect(document.querySelector('button[data-seat="2"] [data-tone="dead"]')).toHaveTextContent("出局");
    expect(document.querySelectorAll("button[data-seat] [data-tone]").length).toBe(3);
  });
});

