// Agent 库排序切换（issue #123）：默认最近更新（服务端顺序）；点「积分」按积分排，再点「最近更新」恢复。

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StoredAgent } from "../api/agents";
import { useAgentLibrary } from "../store/agents";
import { useProviders } from "../store/providers";
import AgentLibrary from "./AgentLibrary";

function agent(id: string, name: string, rating: number, games: number, updated: string): StoredAgent {
  return {
    agent_id: id,
    profile: { name, model: "m", skills: [] },
    created_at: updated,
    updated_at: updated,
    rating: { rating, games, wins: games, losses: 0, draws: 0 },
  };
}

const ITEMS: StoredAgent[] = [
  agent("a_new", "新人", 1000, 0, "2026-10-26T00:00:00+00:00"),
  agent("a_mid", "中坚", 1016, 1, "2026-10-25T00:00:00+00:00"),
  agent("a_vet", "老将", 1016, 5, "2026-10-24T00:00:00+00:00"),
  agent("a_top", "顶尖", 1100, 3, "2026-10-23T00:00:00+00:00"),
];

function stubFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/agents") ? ITEMS : [];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function cardNames(): string[] {
  return screen.getAllByText(/^(新人|中坚|老将|顶尖)$/).map((el) => el.textContent ?? "");
}

describe("AgentLibrary 排序", () => {
  beforeEach(() => {
    useAgentLibrary.setState({ items: [], skills: [], presets: [], loading: false, error: null });
    useProviders.setState({ items: [], loading: false, error: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("默认最近更新；点「积分」后按积分排，再点「最近更新」恢复", async () => {
    stubFetch();
    render(<AgentLibrary />);
    await screen.findByText("顶尖");
    expect(cardNames()).toEqual(["新人", "中坚", "老将", "顶尖"]);
    const byRating = screen.getByRole("button", { name: "积分" });
    expect(screen.getByRole("button", { name: "最近更新" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(byRating);
    expect(cardNames()).toEqual(["顶尖", "老将", "中坚", "新人"]);
    expect(byRating).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "最近更新" }));
    expect(cardNames()).toEqual(["新人", "中坚", "老将", "顶尖"]);
  });
});
