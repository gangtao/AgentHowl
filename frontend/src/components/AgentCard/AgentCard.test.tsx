// AgentCard 战绩行（issue #123）：完整卡与精简卡都渲染 ratingLine 的文案。

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
    const { unmount } = render(<AgentCard stored={agent(played)} />);
    expect(screen.getByText("1016 分 · 12 局 · 胜率 58%")).toBeInTheDocument();
    unmount();
    render(<AgentCard stored={agent(EMPTY_RATING)} compact />);
    expect(screen.getByText("尚无战绩")).toBeInTheDocument();
  });
});
