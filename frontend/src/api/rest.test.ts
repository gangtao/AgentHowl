import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createGame, getGameAvatars, getReplay } from "./rest";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("rest.ts", () => {
  it("createGame 发 POST /api/v1/games 带 JSON body", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(200, {
        game_id: "g1",
        host_token: "h",
        spectator_token: "s",
        gm_token: "gm",
        config: {},
        agents: {},
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await createGame({ preset: "std_9_kill_side" });

    expect(res.game_id).toBe("g1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual({ preset: "std_9_kill_side" });
  });

  it("非 2xx 响应抛 ApiError{status, detail}（detail 取响应 detail）", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(404, { detail: "对局不存在" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createGame({})).rejects.toMatchObject({ status: 404, detail: "对局不存在" });
  });

  it("非 2xx 且 detail 为数组时拍平成字符串", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(422, { detail: [{ loc: ["body", "preset"], msg: "非法" }] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    try {
      await createGame({});
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(422);
      expect(apiErr.detail).toContain("非法");
    }
  });

  it("getReplay 带 Authorization: Bearer", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, []));
    vi.stubGlobal("fetch", fetchMock);

    await getReplay("g1", "tok-123");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games/g1/replay");
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok-123" });
  });

  // issue #98：已结束对局公开回放——省略 token 时绝不能发 Authorization 头。
  it("getReplay 省略 token 时不发 Authorization", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, []));
    vi.stubGlobal("fetch", fetchMock);

    await getReplay("g1");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games/g1/replay");
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("getGameAvatars：有 token 带 Authorization，无 token 不带", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ "0": "a.png" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await getGameAvatars("g_x", "tok")).toEqual({ "0": "a.png" });
    expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers).toMatchObject(
      { Authorization: "Bearer tok" },
    );
    await getGameAvatars("g_x");
    expect(
      (fetchMock.mock.calls[1] as unknown as [string, RequestInit])[1].headers,
    ).not.toHaveProperty("Authorization");
  });
});
