import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PresetCard from "./PresetCard";

const preset = {
  name: "std_12_yn_hunter_idiot",
  num_players: 12,
  sheriff: true,
  win_condition: "KILL_SIDE",
  description_zh: "12 人预女猎白",
  roles: [
    { role: "WEREWOLF", count: 4 },
    { role: "VILLAGER", count: 4 },
    { role: "SEER", count: 1 },
    { role: "WITCH", count: 1 },
    { role: "HUNTER", count: 1 },
    { role: "IDIOT", count: 1 },
  ],
};

describe("PresetCard（羊皮纸剧本牌）", () => {
  it("标题 / 木签 / 12 枚角色徽记 / mono id，选中态 aria-pressed", () => {
    const onSelect = vi.fn();
    render(<PresetCard preset={preset} selected onSelect={onSelect} />);
    const btn = screen.getByRole("button", { pressed: true });
    expect(btn).toHaveAttribute("data-selected", "true");
    expect(screen.getByRole("heading", { name: "12 人预女猎白" })).toBeInTheDocument();
    expect(screen.getByText("12 人 / 带警长")).toBeInTheDocument();
    expect(screen.getAllByTitle(/狼人|村民|预言家|女巫|猎人|白痴/)).toHaveLength(12);
    expect(screen.getByText("std_12_yn_hunter_idiot")).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("未选中：无 data-selected，aria-pressed=false", () => {
    render(
      <PresetCard
        preset={{ ...preset, sheriff: false, num_players: 9 }}
        selected={false}
        onSelect={vi.fn()}
      />,
    );
    const btn = screen.getByRole("button", { pressed: false });
    expect(btn).not.toHaveAttribute("data-selected");
    expect(screen.getByText("9 人")).toBeInTheDocument();
  });
});
