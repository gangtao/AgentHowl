// AgentCard 战绩行（issue #123）：完整卡与精简卡都渲染 ratingLine 的文案。

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_RATING, type RatingSummary, type StoredAgent } from "../../api/agents";
import AgentCard from "./AgentCard";

function agent(rating: RatingSummary): StoredAgent {
  return {
    agent_id: "a_owl",
    profile: { name: "夜枭", model: "qwen2.5:14b", skills: [] },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
    rating,
  };
}

describe("AgentCard 战绩行", () => {
  it("完整卡与精简卡都渲染战绩行", () => {
    const played: RatingSummary = { rating: 1015.6, games: 12, wins: 7, losses: 4, draws: 1 };
    // 完整卡（角色牌）把战绩拆成「声望 / 战绩」两行；精简卡仍是 ratingLine 一行
    const { unmount } = render(<AgentCard stored={agent(played)} />);
    expect(screen.getByText("1016")).toBeInTheDocument();
    expect(screen.getByText("12 局 · 胜率 58%")).toBeInTheDocument();
    unmount();
    render(<AgentCard stored={agent(EMPTY_RATING)} compact />);
    expect(screen.getByText("尚无战绩")).toBeInTheDocument();
  });
});

describe("AgentCard 角色牌（规格 §6，设计稿 1k）", () => {
  const withPersonality: StoredAgent = {
    agent_id: "a_fox",
    profile: {
      name: "狐语",
      model: "openai/gpt-5",
      temperature: 0.7,
      skills: ["bluff", "vote"],
      personality: { preset: { system: "MBTI", value: "ENTP" } },
    },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
    rating: { rating: 1024.4, games: 12, wins: 7, losses: 5, draws: 0 },
  };
  const bare: StoredAgent = {
    agent_id: "a_abacus",
    profile: { name: "算盘", model: "m" },
    created_at: "t",
    updated_at: "t",
    rating: EMPTY_RATING,
  };

  it("首字渐变圆 / 金色人格行 / 羊皮纸三行 / 技能签 / 模型行 / 操作", () => {
    const onEdit = vi.fn();
    render(<AgentCard stored={withPersonality} onEdit={onEdit} onDelete={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "狐语" })).toBeInTheDocument();
    expect(screen.getByText("「ENTP」")).toBeInTheDocument();
    expect(screen.getByText("1024")).toBeInTheDocument();
    expect(screen.getByText("12 局 · 胜率 58%")).toBeInTheDocument();
    expect(screen.getByText("bluff")).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-5 · T=0.7")).toBeInTheDocument();
    // 更新时间不再占一行，但仍在模型行的 title 里（名册默认按「最近更新」排序）
    expect(screen.getByText("openai/gpt-5 · T=0.7")).toHaveAttribute(
      "title",
      expect.stringMatching(/更新于 2026-09-(19|20) \d\d:\d\d/),
    );
    screen.getByRole("button", { name: "编辑" }).click();
    expect(onEdit).toHaveBeenCalled();
  });

  it("无人格 / 无技能 / 无战绩：省略金色行，显示「无技能」「尚无战绩」", () => {
    render(<AgentCard stored={bare} />);
    expect(screen.queryByText(/^「.*」$/)).toBeNull();
    expect(screen.getByText("无技能")).toBeInTheDocument();
    expect(screen.getByText("尚无战绩")).toBeInTheDocument();
    expect(screen.getByText("m · T=0.3")).toBeInTheDocument();
  });

  it("名字为空：首字圆回退「?」，不崩", () => {
    render(<AgentCard stored={{ ...bare, profile: { name: "  ", model: "m" } }} />);
    expect(screen.getByText("?")).toBeInTheDocument();
  });
});
