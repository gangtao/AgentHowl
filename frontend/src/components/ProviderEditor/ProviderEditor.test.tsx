// ProviderEditor：类型选择自动填默认地址；密钥「留空不改」（body 无 api_key）与「清除」（api_key: ""）。

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ProviderInput, ProviderPublic } from "../../api/providers";
import ProviderEditor from "./ProviderEditor";

const EXISTING: ProviderPublic = {
  provider_id: "p_1c7e04a9",
  name: "本地 Ollama",
  kind: "ollama",
  api_base: "http://localhost:11434",
  has_key: true,
  key_hint: "ab12",
  default_model: "qwen2.5:14b",
  created_at: "2026-09-20T00:00:00+00:00",
  updated_at: "2026-09-20T00:00:00+00:00",
};

function renderEditor(provider: ProviderPublic | null): { onSave: ReturnType<typeof vi.fn> } {
  const onSave = vi.fn();
  render(
    <ProviderEditor
      provider={provider}
      others={[]}
      refNames={[]}
      onSave={onSave as (body: ProviderInput) => void}
      onCancel={vi.fn()}
    />,
  );
  return { onSave };
}

function bodyOf(onSave: ReturnType<typeof vi.fn>): Record<string, unknown> {
  return onSave.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

describe("ProviderEditor", () => {
  it("新建时选 Ollama 自动填默认地址", () => {
    const { onSave } = renderEditor(null);
    // 默认就是 ollama；先切到 OpenAI（地址清空），再切回 Ollama
    // ByRole 的 name 字符串是全串精确匹配，不会命中「OpenAI 兼容」
    fireEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    expect((screen.getByLabelText("API 地址") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Ollama" }));
    expect((screen.getByLabelText("API 地址") as HTMLInputElement).value).toBe(
      "http://localhost:11434",
    );

    fireEvent.change(screen.getByLabelText("名字 *"), { target: { value: "本地 Ollama" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodyOf(onSave)).toEqual({
      name: "本地 Ollama",
      kind: "ollama",
      api_base: "http://localhost:11434",
      default_model: null,
    });
  });

  it("DeepSeek 自动填官方地址", () => {
    renderEditor(null);
    fireEvent.click(screen.getByRole("button", { name: "DeepSeek" }));
    expect((screen.getByLabelText("API 地址") as HTMLInputElement).value).toBe(
      "https://api.deepseek.com",
    );
  });

  it("不改地址时不覆盖用户手输的值", () => {
    renderEditor(null);
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "http://box:11434" } });
    fireEvent.click(screen.getByRole("button", { name: "DeepSeek" }));
    expect((screen.getByLabelText("API 地址") as HTMLInputElement).value).toBe("http://box:11434");
  });

  it("编辑态：密钥永不回显，留空保存 → body 不含 api_key", () => {
    const { onSave } = renderEditor(EXISTING);
    const keyInput = screen.getByLabelText("API 密钥") as HTMLInputElement;
    expect(keyInput.type).toBe("password");
    expect(keyInput.value).toBe("");
    expect(keyInput.placeholder).toContain("····ab12");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const body = bodyOf(onSave);
    expect("api_key" in body).toBe(false);
    expect(body).toEqual({
      name: "本地 Ollama",
      kind: "ollama",
      api_base: "http://localhost:11434",
      default_model: "qwen2.5:14b",
    });
  });

  it("「清除」→ body 带 api_key: \"\"", () => {
    const { onSave } = renderEditor(EXISTING);
    fireEvent.click(screen.getByRole("button", { name: "清除" }));
    expect(screen.getByLabelText("API 密钥")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodyOf(onSave).api_key).toBe("");
  });

  it("输入新密钥 → body 带该密钥", () => {
    const { onSave } = renderEditor(EXISTING);
    fireEvent.change(screen.getByLabelText("API 密钥"), { target: { value: "sk-new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(bodyOf(onSave).api_key).toBe("sk-new");
  });

  it("openai_compatible 缺地址时挡住保存", () => {
    renderEditor(null);
    fireEvent.change(screen.getByLabelText("名字 *"), { target: { value: "自建" } });
    fireEvent.click(screen.getByRole("button", { name: "OpenAI 兼容" }));
    expect(screen.getByText("openai_compatible 类型须填写 api_base。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("名字与库内重名时挡住保存", () => {
    render(
      <ProviderEditor
        provider={null}
        others={[EXISTING]}
        refNames={[]}
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("名字 *"), { target: { value: "本地 Ollama" } });
    expect(screen.getByText("已有同名 provider：本地 Ollama")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });
});
