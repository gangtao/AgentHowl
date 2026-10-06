// 回放引导（`#/g/{id}?replay=1`，issue #98 规格 §5）：无 token 拉 /meta + /replay，
// 401/403 统一「暂不可回放」文案（不暴露 token），成功路径不连 WS。

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameMeta } from "../engine/types";
import { useGameStore } from "../store/game";
import GamePage from "./GamePage";

const meta = fixture.meta as unknown as GameMeta;
const events = fixture.events as unknown as Event[];

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** 按路径分发的 fetch 桩：/meta 返回 metaRes()，/replay 返回事件流，
 * /audio（发言音频清单，issue #103）返回空清单——本文件不测配音，给个空对象足够。 */
function stubFetch(metaRes: () => Response): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/meta")) return metaRes();
    if (url.endsWith("/audio")) return jsonResponse(200, {});
    return jsonResponse(200, events);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  useGameStore.getState().reset();
});

describe("GamePage 回放模式（无 token）", () => {
  it("401 显示「暂不可回放」且不提 token", async () => {
    stubFetch(() => jsonResponse(401, { detail: "缺少 Bearer token" }));

    render(<GamePage gameId="g_x" replay />);

    expect(await screen.findByText(/暂不可回放/)).toBeInTheDocument();
    // 回放访客本就没有 token、也无从提供，错误里不能把它说成 token 问题（复核 M1）。
    expect(document.body.textContent).not.toMatch(/token/i);
  });

  it("403 显示同一条文案", async () => {
    stubFetch(() => jsonResponse(403, { detail: "对局未结束，终局后才可回放" }));

    render(<GamePage gameId="g_x" replay />);

    expect(await screen.findByText(/暂不可回放/)).toBeInTheDocument();
  });

  it("成功路径：装入全量事件且不连 WS", async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, meta));
    const wsCtor = vi.fn();
    vi.stubGlobal("WebSocket", wsCtor);

    render(<GamePage gameId="g_x" replay />);

    // 顶栏在装入后显示「已结束 · N 条事件」。
    expect(await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`))).toBeInTheDocument();
    expect(useGameStore.getState().events).toHaveLength(events.length);
    expect(useGameStore.getState().mode).toBe("replay");
    expect(wsCtor).not.toHaveBeenCalled();

    // 所有请求（含引导成功后补拉的 /avatars、/audio 清单）都不带 Authorization（已结束对局公开回放）。
    for (const [url, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(url).toMatch(/\/api\/v1\/games\/g_x\/(meta|replay|avatars|audio)$/);
      expect(init.headers).not.toHaveProperty("Authorization");
    }
  });
});
