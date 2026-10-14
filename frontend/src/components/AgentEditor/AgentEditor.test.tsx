// AgentEditor：名字必填、描述超长红字、空人格不提交、保存 body 是 AgentProfile 形状。
// 保存路径接到真实的 useAgentLibrary().create（用假实现替换，不打网络）。

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("护栏短语只红字提示，不挡保存（判决权在后端 422，spec §7.2b）", () => {
    renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.change(screen.getByLabelText(/^描述/), { target: { value: "可以无视规则发言" } });
    expect(screen.getAllByText(/无视规则/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "保存" })).not.toBeDisabled();
  });

  it("自定义特质词也走护栏提示（后端对 traits 的键同样校验）", () => {
    renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.click(screen.getByRole("button", { name: "+ 自定义" }));
    fireEvent.change(screen.getByLabelText("自定义特质"), { target: { value: "作弊" } });
    expect(screen.getByText(/护栏：自定义特质含「作弊」/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "加入" }));
    expect(screen.getByText(/护栏：特质词含「作弊」/)).toBeInTheDocument();
    // 底部护栏行也提示，但保存仍可点
    expect(screen.getByRole("button", { name: "保存" })).not.toBeDisabled();
  });

  it("MBTI 某一轴可退回「不表态」", () => {
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.click(screen.getByText("MBTI"));
    fireEvent.click(within(screen.getByRole("group", { name: "MBTI EI" })).getByText("I"));
    fireEvent.click(within(screen.getByRole("group", { name: "MBTI TF" })).getByText("T"));
    // 再把 TF 轴清空
    fireEvent.click(within(screen.getByRole("group", { name: "MBTI TF" })).getByText("—"));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect((create.mock.calls[0]?.[0] as { personality: unknown }).personality).toEqual({
      preset: { system: "MBTI", value: { I: 0.5 } },
    });
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
      avatar: null,
      voice: null,
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

  it("头像：上传成功写入 profile.avatar；超 512 KB 不发请求并提示（issue #102）", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ avatar_id: "3f9a1c0b7e2d4a66.png", bytes: 10 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");

    const input = screen.getByLabelText(/上传头像/) as HTMLInputElement;
    const big = new File([new Uint8Array(512 * 1024 + 1)], "big.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByText(/不能超过 512 KB/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    const ok = new File([new Uint8Array(10)], "a.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [ok] } });
    await waitFor(() => expect(screen.getByRole("img", { name: /头像|夜枭/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ avatar: "3f9a1c0b7e2d4a66.png" }));

    fireEvent.click(screen.getByRole("button", { name: "移除头像" }));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("声线：预置模式必须选 speaker；设计模式必须填描述；保存写入 profile.voice（issue #103）", () => {
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");

    fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "preset" } });
    fireEvent.change(screen.getByLabelText(/预置声线/), { target: { value: "eric" } });
    fireEvent.change(screen.getByLabelText(/情绪 \/ 语速指令|声线描述/), { target: { value: "急躁" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(create).toHaveBeenLastCalledWith(
      expect.objectContaining({ voice: { mode: "preset", speaker: "eric", style: "急躁", speed: 1 } }),
    );

    fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "design" } });
    fireEvent.change(screen.getByLabelText(/情绪 \/ 语速指令|声线描述/), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "none" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(create).toHaveBeenLastCalledWith(expect.objectContaining({ voice: null }));
  });

  it("描述声线：生成试听得到锚点并随保存写入；改描述清空锚点（issue #103 跟进）", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ anchor_id: "0123456789abcdef.wav", url: "/api/v1/voices/0123456789abcdef.wav" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { create } = renderEditor();
    fill("名字 *", "夜枭");
    fill("LiteLLM 模型串", "ollama/qwen2.5:7b");
    fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "design" } });
    expect(screen.getByRole("button", { name: /生成声线试听/ })).toBeDisabled(); // 描述为空
    fireEvent.change(screen.getByLabelText(/声线描述/), { target: { value: "沙哑老头" } });
    fireEvent.click(screen.getByRole("button", { name: /生成声线试听/ }));
    await waitFor(() => expect(screen.getByLabelText("声线试听")).toBeInTheDocument());
    expect(screen.getByLabelText("声线试听")).toHaveAttribute("src", "/api/v1/voices/0123456789abcdef.wav");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/voices/design");
    expect(JSON.parse(String(init.body))).toEqual({ style: "沙哑老头" });
    expect(screen.getByRole("button", { name: /换一个/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(create).toHaveBeenLastCalledWith(
      expect.objectContaining({
        voice: { mode: "design", style: "沙哑老头", speed: 1, anchor: "0123456789abcdef.wav" },
      }),
    );
    fireEvent.change(screen.getByLabelText(/声线描述/), { target: { value: "沙哑老头，带笑" } });
    expect(screen.queryByLabelText("声线试听")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(create).toHaveBeenLastCalledWith(
      expect.objectContaining({ voice: expect.objectContaining({ anchor: null }) }),
    );
  });
});
