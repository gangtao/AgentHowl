import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_RATING, type StoredAgent } from "../../api/agents";
import AgentMiniList from "./AgentMiniList";

const lib: StoredAgent[] = [
  {
    agent_id: "a_fox",
    profile: { name: "狐语", model: "openai/gpt-5" },
    created_at: "",
    updated_at: "",
    rating: { rating: 1024, games: 12, wins: 7, losses: 5, draws: 0 },
  },
  {
    agent_id: "a_owl",
    profile: { name: "夜枭", model: "m" },
    created_at: "",
    updated_at: "",
    rating: EMPTY_RATING,
  },
];

describe("AgentMiniList", () => {
  it("卡片含首字 / 名字 / 模型简称 / 战绩；点选 aria-pressed，再点取消", () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <AgentMiniList library={lib} selected={null} onSelect={onSelect} onNewAgent={vi.fn()} />,
    );
    const fox = screen.getByRole("button", { name: /狐语/ });
    expect(fox).toHaveTextContent("gpt-5");
    expect(fox).toHaveTextContent("1024 分 · 12 局 · 胜率 58%");
    expect(fox).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(fox);
    expect(onSelect).toHaveBeenCalledWith("a_fox");
    rerender(
      <AgentMiniList library={lib} selected="a_fox" onSelect={onSelect} onNewAgent={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /狐语/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /狐语/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("搜索过滤与空态文案", () => {
    const onNew = vi.fn();
    const { rerender } = render(
      <AgentMiniList library={lib} selected={null} onSelect={vi.fn()} onNewAgent={onNew} />,
    );
    fireEvent.change(screen.getByLabelText("搜索档案"), { target: { value: "zzz" } });
    expect(screen.getByText("没有匹配的档案。")).toBeInTheDocument();
    rerender(<AgentMiniList library={[]} selected={null} onSelect={vi.fn()} onNewAgent={onNew} />);
    expect(screen.getByText(/档案库是空的/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ 新建 Agent" }));
    expect(onNew).toHaveBeenCalled();
  });
});
