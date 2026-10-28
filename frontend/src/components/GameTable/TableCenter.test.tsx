import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StageContent } from "../../lib/stageContent";
import { TableCenter } from "./TableCenter";

const cases: [string, StageContent, string][] = [
  [
    "wolfCouncil",
    {
      kind: "wolfCouncil",
      proposals: [
        { seat: 3, target: 5 },
        { seat: 9, target: 7 },
      ],
      round: 1,
      hint: "意见不一致会重新提案；第 2 轮仍不一致则空刀。",
    },
    "狼 队 密 议 · 仅狼可见",
  ],
  [
    "witchTarget",
    { kind: "witchTarget", seat: 5, name: "Bot5", antidote: true, poison: false },
    "今 夜 被 刀",
  ],
  ["crystal", { kind: "crystal", seat: 8 }, "查 验"],
  ["crosshair", { kind: "crosshair", seat: 9 }, "准 星"],
  ["moon", { kind: "moon", sub: "请闭眼，等待其他角色行动" }, "天黑请闭眼"],
  [
    "tally",
    {
      kind: "tally",
      cast: 6,
      voters: 11,
      rows: [{ target: 2, name: "Bot2", votes: 5.5, from: [0, 1, 3, 4, 5] }],
      waiting: [6, 7],
      election: false,
    },
    "实时票型 · 按被投者分组",
  ],
  [
    "pkStage",
    {
      kind: "pkStage",
      a: { seat: 0, name: "Gang", votes: 4 },
      b: { seat: 10, name: "Bot10", votes: 3 },
      cast: 7,
      voters: 9,
    },
    "VS",
  ],
  [
    "gmNotes",
    {
      kind: "gmNotes",
      round: 4,
      rows: [{ role: "WEREWOLF", seat: 3, text: "狼人刀 5号", color: "--ah-wolf" }],
    },
    "GM 手记 · 第 4 夜",
  ],
  ["campfire", { kind: "campfire", note: "上警报名中 · 已上警 3 人" }, "上警报名中 · 已上警 3 人"],
];

describe("TableCenter（规格 §4.4）", () => {
  it.each(cases)("%s 渲染关键文案", (_k, content, text) => {
    render(<TableCenter content={content} seats={[]} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("tally：票数 5.5 原样显示并列出投票人", () => {
    render(<TableCenter content={cases[5]![1]} seats={[]} />);
    expect(screen.getByText(/5\.5 票/)).toBeInTheDocument();
    expect(screen.getByText(/← 0 1 3 4 5/)).toBeInTheDocument();
    expect(screen.getByText(/等待 6 7/)).toBeInTheDocument();
  });

  it("witchTarget：药瓶状态行", () => {
    render(<TableCenter content={cases[1]![1]} seats={[]} />);
    expect(screen.getByText(/解药尚在 · 毒药已用/)).toBeInTheDocument();
  });

  it("none 与 bubble 不由 TableCenter 渲染", () => {
    const { container } = render(<TableCenter content={{ kind: "none" }} seats={[]} />);
    expect(container).toBeEmptyDOMElement();
    const { container: c2 } = render(
      <TableCenter content={{ kind: "bubble", speaker: 0, lastTally: null }} seats={[]} />,
    );
    expect(c2).toBeEmptyDOMElement();
  });

  it("bubble 的上轮票型由 lastTally 单独渲染", () => {
    render(
      <TableCenter
        content={{ kind: "bubble", speaker: 0, lastTally: "4号 ·4 ← 2 5 9 7" }}
        seats={[]}
      />,
    );
    expect(screen.getByText("本轮票型（上轮）")).toBeInTheDocument();
    expect(screen.getByText("4号 ·4 ← 2 5 9 7")).toBeInTheDocument();
  });
});
