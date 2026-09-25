import { afterEach, describe, expect, it, vi } from "vitest";
import { useAgentLibrary } from "./agents";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  useAgentLibrary.setState({ items: [], skills: [], presets: [], loading: false, error: null });
});

describe("useAgentLibrary", () => {
  it("create() 失败时把 error 落到 store 里的 messageOf(err)，同时把异常继续抛给调用方", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(409, { detail: "已有同名档案：小明" })),
    );

    await expect(
      useAgentLibrary.getState().create({ model: "gpt-4o-mini" }),
    ).rejects.toMatchObject({ status: 409, detail: "已有同名档案：小明" });

    expect(useAgentLibrary.getState().error).toBe("已有同名档案：小明");
    expect(useAgentLibrary.getState().items).toEqual([]); // 未把失败结果塞进列表
  });
});
