import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_RATING, type StoredAgent } from "../../api/agents";
import { ME } from "../../lib/seats";
import SeatRing from "./SeatRing";

const lib: StoredAgent[] = [
  {
    agent_id: "a_fox",
    profile: { name: "狐语", model: "m" },
    created_at: "",
    updated_at: "",
    rating: EMPTY_RATING,
  },
  {
    agent_id: "a_mem",
    profile: { name: "算盘", model: "m", memory_id: "mem1" },
    created_at: "",
    updated_at: "",
    rating: EMPTY_RATING,
  },
];
const four = (over: Record<number, string | null> = {}) =>
  [0, 1, 2, 3].map((seat) => ({ seat, agentId: over[seat] ?? null }));

describe("SeatRing（规格 §5 第 2 步）", () => {
  it("n 个座位按 seatPositions 布点，显示 我 / 首字 / bot", () => {
    render(
      <SeatRing
        assignment={four({ 0: ME, 1: "a_fox" })}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={vi.fn()}
      />,
    );
    const seats = screen.getAllByRole("button", { name: /^入座 \d+号$/ });
    expect(seats).toHaveLength(4);
    expect(seats[0]).toHaveAttribute("data-kind", "me");
    expect(seats[0]).toHaveTextContent("我");
    expect(seats[1]).toHaveTextContent("狐");
    expect(seats[2]).toHaveAttribute("data-kind", "bot");
    expect((seats[0] as HTMLElement).style.left).toBe("50%");
    expect((seats[1] as HTMLElement).style.left).toBe("91%");
  });

  it("点座位开木牌菜单，选「我自己」回调 onAssign(seat, ME)", () => {
    const onAssign = vi.fn();
    render(
      <SeatRing
        assignment={four()}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={onAssign}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 2号" }));
    expect(screen.getByRole("menu", { name: "2号 座位菜单" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "我自己" }));
    expect(onAssign).toHaveBeenCalledWith(2, ME);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("「我自己」已在 0 号：其它座位菜单里禁用并标注", () => {
    render(
      <SeatRing
        assignment={four({ 0: ME })}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 3号" }));
    expect(screen.getByRole("menuitem", { name: /我自己（已在 0号）/ })).toBeDisabled();
  });

  it("左栏点中档案后点座位 → 直接分配，即使该座是「我自己」", () => {
    const onAssign = vi.fn();
    render(
      <SeatRing
        assignment={four({ 0: ME })}
        library={lib}
        fill={null}
        pendingAgent="a_fox"
        onAssign={onAssign}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 0号" }));
    expect(onAssign).toHaveBeenCalledWith(0, "a_fox");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("memory_id 已占 2 号：5 号菜单里该档案禁用；pending 它再点 5 号不分配", () => {
    const onAssign = vi.fn();
    const six = [0, 1, 2, 3, 4, 5].map((seat) => ({ seat, agentId: seat === 2 ? "a_mem" : null }));
    const { rerender } = render(
      <SeatRing
        assignment={six}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={onAssign}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 5号" }));
    expect(screen.getByRole("menuitem", { name: /算盘（记忆已在 2号 使用）/ })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    rerender(
      <SeatRing
        assignment={six}
        library={lib}
        fill={null}
        pendingAgent="a_mem"
        onAssign={onAssign}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 5号" }));
    expect(onAssign).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("「清空」只在已分配座位出现，回调 null", () => {
    const onAssign = vi.fn();
    render(
      <SeatRing
        assignment={four({ 1: "a_fox" })}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={onAssign}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 0号" }));
    expect(screen.queryByRole("menuitem", { name: "清空" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "入座 1号" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "清空" }));
    expect(onAssign).toHaveBeenCalledWith(1, null);
  });

  it("fill 生效时空位显示档案首字、data-kind=fill", () => {
    render(
      <SeatRing
        assignment={four()}
        library={lib}
        fill="a_fox"
        pendingAgent={null}
        onAssign={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "入座 0号" })).toHaveAttribute("data-kind", "fill");
  });

  it("点菜单外部关闭；打开时焦点进第一项，Escape 把焦点还给座位按钮", () => {
    render(
      <SeatRing
        assignment={four({ 0: ME })}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={vi.fn()}
      />,
    );
    const seat = screen.getByRole("button", { name: "入座 2号" });
    fireEvent.click(seat);
    // 「我自己」已在 0 号被禁用 → 焦点落在第一个可用项「随机 bot」
    expect(screen.getByRole("menuitem", { name: "随机 bot" })).toHaveFocus();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(seat);
    fireEvent.mouseDown(screen.getByRole("menu"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(seat).toHaveFocus();
  });

  it("菜单内 ↑ ↓ 在可用项之间移动焦点并循环", () => {
    render(
      <SeatRing
        assignment={four({ 0: ME })}
        library={lib}
        fill={null}
        pendingAgent={null}
        onAssign={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "入座 2号" }));
    const bot = screen.getByRole("menuitem", { name: "随机 bot" });
    expect(bot).toHaveFocus();
    fireEvent.keyDown(bot, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "狐语" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: "狐语" }), { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "算盘" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: "算盘" }), { key: "ArrowDown" });
    expect(bot).toHaveFocus();
    fireEvent.keyDown(bot, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: "算盘" })).toHaveFocus();
  });
});
