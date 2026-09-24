import { afterEach, describe, expect, it, vi } from "vitest";
import { useProviders } from "./providers";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  useProviders.setState({ items: [], loading: false, error: null });
});

describe("useProviders", () => {
  it("test() 请求层失败时把 error 落到 store，且继续抛给调用方", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(404, { detail: "provider 不存在：p_dead" })),
    );

    await expect(useProviders.getState().test("p_dead")).rejects.toMatchObject({
      status: 404,
      detail: "provider 不存在：p_dead",
    });

    expect(useProviders.getState().error).toBe("provider 不存在：p_dead");
  });
});
