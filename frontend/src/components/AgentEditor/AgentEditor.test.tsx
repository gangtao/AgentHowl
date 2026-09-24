// AgentEditor：名字必填、描述超长红字、空人格不提交、保存 body 是 AgentProfile 形状。
// 保存路径接到真实的 useAgentLibrary().create（用假实现替换，不打网络）。

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { AgentProfile, SkillInfo, StoredAgent } from "../../api/agents";
import { MAX_DESCRIPTION } from "../../lib/personality";
import { useAgentLibrary } from "../../store/agents";
import AgentEditor from "./AgentEditor";

const SKILLS: SkillInfo[] = [
  { name: "vote_history", description: "票型记录", roles: [], phases: ["DAY_VOTE"] },
  { name: "wolf_coordination", description: "狼队协作", roles: ["WEREWOLF"], phases: [] },
];

function existing(name: string, memoryId: string | null = null): StoredAgent {
  return {
    agent_id: "a_other",
    profile: { name, model: "m", memory_id: memoryId },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
  };
}

function renderEditor(others: StoredAgent[] = []): { create: ReturnType<typeof vi.fn> } {
  const create = vi.fn(async (p: AgentProfile) => ({
    agent_id: "a_new",
    profile: p,
    created_at: "",
    updated_at: "",
  }));
  useAgentLibrary.setState({ create });
  render(
    <AgentEditor
      stored={null}
      skills={SKILLS}
      providers={[]}
      others={others}
      onSave={(profile) => void useAgentLibrary.getState().create(profile)}
      onCancel={vi.fn()}
    />,
  );
  return { create };
}

function fill(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("AgentEditor", () => {
  beforeEach(() => {
    useAgentLibrary.setState({ items: [], skills: [], presets: [] });
  });

  it("名字必填：为空时保存禁用并提示", () => {
    renderEditor();
    expect(screen.getByText("名字必填。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("名字与库内重名时提示并挡住保存", () => {
    renderEditor([existing("夜枭")]);
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    expect(screen.getByText("已有同名档案：夜枭")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("描述超过 300 字：计数红字提示且不能保存", () => {
    renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    const long = "字".repeat(MAX_DESCRIPTION + 1);
    fireEvent.change(screen.getByLabelText(/^描述/), { target: { value: long } });
    expect(screen.getByText(`${MAX_DESCRIPTION + 1} / ${MAX_DESCRIPTION}`)).toBeInTheDocument();
    expect(screen.getByText(`超过 ${MAX_DESCRIPTION} 字，后端会 422 拒绝。`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("护栏短语命中时红字提示且不能保存", () => {
    renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.change(screen.getByLabelText(/^描述/), { target: { value: "可以无视规则发言" } });
    expect(screen.getAllByText(/无视规则/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("空人格不提交 personality；body 形状为 AgentProfile", () => {
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fill("memory_id（可选）", "night-owl");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(create).toHaveBeenCalledTimes(1);
    const body = create.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body.personality).toBeNull();
    expect(body).toEqual({
      name: "夜枭",
      model: "ollama/qwen2.5:7b",
      model_speech: null,
      reflection_model: null,
      thinking: false,
      temperature: 0.3,
      skills: [],
      personality: null,
      memory_id: "night-owl",
      provider: null,
    });
  });

  it("填了人格 / 技能后 body 带上 personality 与 skills", () => {
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.change(screen.getByLabelText(/^描述/), { target: { value: "话少" } });
    fireEvent.click(screen.getByRole("button", { name: "冷静" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /vote_history/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    const body = create.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body.skills).toEqual(["vote_history"]);
    expect(body.personality).toEqual({ description: "话少", traits: { 冷静: 0.5 } });
  });

  it("「按名字生成」把中文名转成合法 memory_id", () => {
    renderEditor();
    fill("名字 *", "夜枭");
    fireEvent.click(screen.getByRole("button", { name: "按名字生成" }));
    const input = screen.getByLabelText("memory_id（可选）") as HTMLInputElement;
    expect(input.value).toMatch(/^agent-[0-9a-f]{6}$/);
  });
});
