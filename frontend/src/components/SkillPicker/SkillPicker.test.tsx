import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SkillPicker from "./SkillPicker";

const skills = [
  { name: "bluff", description: "虚张声势", roles: [], phases: [] },
  { name: "vote_history", description: "票型记录", roles: ["SEER"], phases: ["DAY_VOTE"] },
];

describe("SkillPicker（招募告示 · 二 · 技艺）", () => {
  it("kicker 文案与选中标记 ■ / □；点卡片切换", () => {
    const onChange = vi.fn();
    render(<SkillPicker skills={skills} value={["bluff"]} onChange={onChange} />);
    expect(screen.getByText("二 · 技艺 · 已选 1")).toBeInTheDocument();
    expect(screen.getAllByText("■")).toHaveLength(1);
    expect(screen.getAllByText("□")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText(/bluff/));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("全部（*）：计数为技能总数，所有卡 ■", () => {
    render(<SkillPicker skills={skills} value={["*"]} onChange={vi.fn()} />);
    expect(screen.getByText("二 · 技艺 · 已选 2")).toBeInTheDocument();
    expect(screen.getAllByText("■")).toHaveLength(2);
  });
});
