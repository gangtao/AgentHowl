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

  it("create() 给新档案补 EMPTY_RATING；update() 沿用原积分（积分只由终局推导，POST/PUT 响应不带）", async () => {
    const base = {
      agent_id: "a_new",
      profile: { name: "新", model: "m" },
      created_at: "t",
      updated_at: "t",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(201, base)),
    );
    const created = await useAgentLibrary.getState().create({ name: "新", model: "m" });
    expect(created.rating).toEqual({ rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 });
    expect(useAgentLibrary.getState().items[0]?.rating.games).toBe(0);

    const played = { rating: 1016, games: 1, wins: 1, losses: 0, draws: 0 };
    useAgentLibrary.setState({ items: [{ ...base, rating: played }] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { ...base, updated_at: "t2" })),
    );
    const updated = await useAgentLibrary.getState().update("a_new", { name: "新", model: "m2" });
    expect(updated.rating).toEqual(played);
    expect(useAgentLibrary.getState().items[0]).toEqual({ ...base, updated_at: "t2", rating: played });
  });
});
