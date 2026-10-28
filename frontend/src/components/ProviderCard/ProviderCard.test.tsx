import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProviderPublic } from "../../api/providers";
import ProviderCard from "./ProviderCard";

const base: ProviderPublic = {
  provider_id: "p1",
  name: "本地 Ollama",
  kind: "ollama",
  api_base: "http://localhost:11434",
  has_key: false,
  key_hint: null,
  default_model: "qwen2.5:14b",
  created_at: "t",
  updated_at: "t",
};

describe("ProviderCard（炼金工坊 · 药剂木牌）", () => {
  it("药剂圆 / kind 行 / 状态 / 羊皮纸信息条 / 引用 / 操作", () => {
    const onTest = vi.fn();
    render(
      <ProviderCard
        provider={base}
        refNames={["狐语", "算盘"]}
        onTest={onTest}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "本地 Ollama" })).toBeInTheDocument();
    expect(screen.getByText("Ollama 药剂")).toBeInTheDocument();
    expect(screen.getByText("● 未测试")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:11434")).toBeInTheDocument();
    expect(screen.getByText("未配置")).toBeInTheDocument();
    expect(screen.getByText("qwen2.5:14b")).toBeInTheDocument();
    expect(screen.getByText(/被 2 个 Agent 引用：狐语、算盘/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(onTest).toHaveBeenCalled();
  });

  it("未知 kind 不崩；已连通 / 失败文案与密钥尾号", () => {
    const { rerender } = render(
      <ProviderCard
        provider={{ ...base, kind: "mystery" as never, has_key: true, key_hint: "Zz0=" }}
        refNames={[]}
        test={{ ok: true, latency_ms: 42, error: null }}
        onTest={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("mystery 药剂")).toBeInTheDocument();
    expect(screen.getByText("● 已连通 · 42 ms")).toBeInTheDocument();
    expect(screen.getByText("已配置 ····Zz0=")).toBeInTheDocument();
    expect(screen.getByText("未被引用")).toBeInTheDocument();
    rerender(
      <ProviderCard
        provider={base}
        refNames={[]}
        test={{ ok: false, latency_ms: null, error: "connection refused" }}
        onTest={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("● 失败 · ? ms")).toBeInTheDocument();
    expect(screen.getByText("connection refused")).toBeInTheDocument();
  });
});
