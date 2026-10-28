// 对局页测试：终局对局经 /meta + /replay 装入；覆盖 token / share / cookie（无凭据）三种凭据（issue #114）。

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameMeta } from "../engine/types";
import { useGameStore } from "../store/game";
import { useTurn } from "../store/turn";
import { useVoice } from "../store/voice";
import GamePage from "./GamePage";
import { metaFromState } from "./metaFromState";

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
  const fetchMock = vi.fn(async (rawUrl: string) => {
    const url = rawUrl.split("?")[0] as string;
    if (url.endsWith("/meta")) return metaRes();
    if (url.endsWith("/audio")) return jsonResponse(200, {});
    return jsonResponse(200, events);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  useTurn.getState().reset();
  vi.unstubAllGlobals();
  useGameStore.getState().reset();
});

describe("GamePage 聚光牌跟随配音（issue #110）", () => {
  it("voicingSeq 指向无 actor 的事件时显示 GM；找不到事件时退回轮到谁", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    const narrated = events.find((e) => e.actor_seat === null && e.type === "VOTE_STARTED");
    expect(narrated).toBeDefined();
    act(() => useVoice.setState({ voicingSeq: narrated!.seq, playing: { seq: narrated!.seq, part: 0 } }));
    expect(await screen.findByText("旁白中 🔊")).toBeInTheDocument();
    act(() => useVoice.setState({ voicingSeq: 999999, playing: null }));
    expect(screen.queryByText("旁白中 🔊")).toBeNull();
    expect(screen.queryByRole("status", { name: /旁白中/ })).toBeNull();
    useVoice.getState().clear();
  });

  it("带 actor_seat 的非发言事件（HUNTER_SHOT 等）也显示 GM，不高亮座位", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    const shot = events.find((e) => e.type === "HUNTER_SHOT" && e.actor_seat !== null);
    expect(shot).toBeDefined();
    act(() => useVoice.setState({ voicingSeq: shot!.seq, playing: { seq: shot!.seq, part: 0 } }));
    expect(await screen.findByRole("status", { name: "GM 旁白中" })).toBeInTheDocument();
    expect(screen.getByText("旁白中 🔊")).toBeInTheDocument();
    useVoice.getState().clear();
  });
});

describe("GamePage 凭据模式（issue #114）", () => {
  it("cookie 模式：无 token、viewer=GM，/meta 裸请求（带 cookie）→ 装入回放", async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" viewer="GM" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games/g_x/meta");
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("share 模式：请求带 ?share=", async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" share="S" viewer="SPECTATOR" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    const urls = fetchMock.mock.calls.map((c) => c[0]);
    expect(urls).toContain("/api/v1/games/g_x/meta?share=S");
    expect(urls).toContain("/api/v1/games/g_x/replay?share=S");
  });

  it("401 → 显示登录提示", async () => {
    stubFetch(() => jsonResponse(401, { detail: "未登录" }));
    render(<GamePage gameId="g_x" viewer="GM" />);
    expect(await screen.findByText("村口有人守着")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去登录" })).toHaveAttribute("href", "#/login");
  });
});

describe("GamePage 视角以服务端为准（issue #115）", () => {
  it("/meta 的 viewer 覆盖 URL 提示", async () => {
    stubFetch(() => jsonResponse(200, { ...meta, viewer: "SPECTATOR" }));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    expect(useGameStore.getState().viewer).toBe("SPECTATOR");
  });

  it("建局者入座期间用 GM 链接进来 → 封锁错误态，给玩家入口", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束，上帝视角回放未开放" });
      if (url.endsWith("/state"))
        return jsonResponse(403, { detail: "建局者已入座，对局结束前不能查看上帝视角" });
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="T" viewer="GM" />);
    await screen.findByText("建局者已入座，对局结束前不能查看上帝视角");
    const link = screen.getByRole("link", { name: /以玩家身份进入/ });
    expect(link.getAttribute("href")).toBe("#/g/g_x");
  });
});

describe("GamePage 玩家视角（issue #115）", () => {
  const playerState = {
    viewer: 2,
    game_id: "g_x",
    state_version: 7,
    my_seat: 2,
    my_role: "SEER",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2].map((seat) => ({ seat, alive: true, is_sheriff: false, idiot_revealed: false, display_name: `P${seat}` })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: {},
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
  };

  it("/state 为 PlayerObservation 时显示身份栏与行动区，收到 your_turn 后出现发言输入", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束" });
      if (url.endsWith("/state")) return jsonResponse(200, playerState);
      if (url.endsWith("/avatars")) return jsonResponse(200, {});
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", vi.fn(() => ({ close() {} })));
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号 · 预言家/);
    expect(screen.getByText("等待其他玩家…")).toBeInTheDocument();
    expect(useGameStore.getState().viewer).toBe(2);
    act(() =>
      useTurn.getState().setPrompt({
        observation: { ...playerState, phase: "DAY_SPEECH" } as never,
        available_tools: ["speak", "get_state"],
        deadline_ts: Date.now() / 1000 + 60,
      }),
    );
    expect(await screen.findByLabelText("发言内容")).toBeInTheDocument();
  });

  function stubPlayerFetch(state: unknown): void {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (rawUrl: string) => {
        const url = rawUrl.split("?")[0] as string;
        if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束" });
        if (url.endsWith("/state")) return jsonResponse(200, state);
        return jsonResponse(200, {});
      }),
    );
  }

  /** 可控 readyState 的假 WebSocket：send 是否成功取决于 open。 */
  function stubSocket(open: boolean): void {
    vi.stubGlobal(
      "WebSocket",
      vi.fn(() => ({ readyState: open ? 1 : 0, send() {}, close() {} })),
    );
  }

  const speakPrompt = {
    observation: { ...playerState, phase: "DAY_SPEECH" } as never,
    available_tools: ["speak", "get_state"] as never,
    deadline_ts: Date.now() / 1000 + 60,
  };

  async function submitSpeech(): Promise<void> {
    act(() => useTurn.getState().setPrompt(speakPrompt));
    fireEvent.change(await screen.findByLabelText("发言内容"), { target: { value: "我是好人" } });
    fireEvent.click(screen.getByRole("button", { name: "发送发言" }));
  }

  it("提交时 socket 未就绪：记「连接未就绪」且不进入 pending", async () => {
    stubPlayerFetch(playerState);
    stubSocket(false);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号/);
    await submitSpeech();
    expect(useTurn.getState().lastError).toMatch(/连接未就绪/);
    expect(useTurn.getState().pending).toBe(false);
  });

  it("提交时 socket 已开：进入 pending", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号/);
    await submitSpeech();
    expect(useTurn.getState().pending).toBe(true);
    expect(useTurn.getState().lastError).toBeNull();
  });

  it("夜间：有 your_turn 时不遮罩；无 prompt 时显示「请闭眼」", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号/);
    // 阶段由事件流推进（快照的 phase 不进 store）
    act(() =>
      useGameStore.getState().appendEvents([
        {
          seq: 1,
          game_id: "g_x",
          ts: 1,
          type: "PHASE_CHANGED",
          actor_seat: null,
          payload: { to: "NIGHT_SEER", round: 1 },
          visibility: "PUBLIC",
          meta: {},
        } as unknown as Event,
      ]),
    );
    await screen.findByText("请闭眼，等待其他角色行动");
    act(() =>
      useTurn.getState().setPrompt({
        ...speakPrompt,
        observation: { ...playerState, phase: "NIGHT_SEER" } as never,
        available_tools: ["check", "get_state"] as never,
      }),
    );
    expect(screen.queryByText("请闭眼，等待其他角色行动")).toBeNull();
  });

  it("终局：出现「查看全局回放」，点击跳到全局回放 hash；残留 prompt 不再渲染 ActionBar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (rawUrl: string) => {
        const url = rawUrl.split("?")[0] as string;
        if (url.endsWith("/meta")) return jsonResponse(200, { ...meta, viewer: 2 });
        if (url.endsWith("/audio")) return jsonResponse(200, {});
        return jsonResponse(200, events);
      }),
    );
    vi.stubGlobal("WebSocket", vi.fn());
    window.location.hash = "#/other";
    act(() => useTurn.getState().setPrompt(speakPrompt));
    render(<GamePage gameId="g_x" token="P" />);
    const btn = await screen.findByRole("button", { name: "查看全局回放" });
    expect(screen.queryByLabelText("发言内容")).toBeNull();
    fireEvent.click(btn);
    expect(window.location.hash).toBe("#/g/g_x");
  });

  it("进行中不显示「查看全局回放」", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText(/我是 2号/);
    expect(screen.queryByRole("button", { name: "查看全局回放" })).toBeNull();
  });
});

describe("metaFromState 公开规则（issue #80）", () => {
  it("观众 / 玩家快照带 config.sheriff 时以服务端票权为准，缺的字段用名单兜底", () => {
    const seats = [0, 1, 2].map((seat) => ({ seat, display_name: `P${seat}` }));
    const meta = metaFromState("g_x", { seats, config: { num_players: 3, sheriff: { enabled: true, vote_weight: 2 } } });
    expect(meta.config.sheriff.vote_weight).toBe(2);
    expect(meta.config.num_players).toBe(3);
    expect(meta.config.roles).toEqual([]);
    expect(meta.roster).toHaveLength(3);
  });

  it("旧服务端不带 config 时仍回退 1.5", () => {
    const meta = metaFromState("g_x", { seats: [{ seat: 0, display_name: "P0" }] });
    expect(meta.config.sheriff.vote_weight).toBe(1.5);
    expect(meta.config.num_players).toBe(1);
  });
});

describe("GamePage 直播收尾（issue #81）", () => {
  const spectatorState = {
    viewer: "SPECTATOR",
    game_id: "g_x",
    phase: "NIGHT_WEREWOLF",
    round: 1,
    seats: meta.roster.map((r) => ({ ...r, alive: true, is_sheriff: false, idiot_revealed: false })),
    sheriff_seat: null,
    winner: null,
  };

  it("直播 head 到 GAME_OVER 后自动装入完整回放，游标停在终局", async () => {
    let finished = false;
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) {
        return finished
          ? jsonResponse(200, { ...meta, viewer: "SPECTATOR" })
          : jsonResponse(403, { detail: "对局未结束" });
      }
      if (url.endsWith("/state")) return jsonResponse(200, spectatorState);
      if (url.endsWith("/replay")) return jsonResponse(200, events);
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", vi.fn(() => ({ close() {} })));
    render(<GamePage gameId="g_x" share="S" viewer="SPECTATOR" />);
    await waitFor(() => expect(screen.queryByText("正在载入对局…")).toBeNull());
    expect(useGameStore.getState().mode).toBe("live");
    const replayCalls = (): number =>
      fetchMock.mock.calls.filter((c) => (c[0] as string).includes("/replay")).length;
    expect(replayCalls()).toBe(0);
    // 直播推到终局（WS 已桩掉，直接灌 store）；此时服务端 /meta 已开放
    finished = true;
    act(() => useGameStore.getState().appendEvents(events));
    await waitFor(() => expect(useGameStore.getState().mode).toBe("replay"));
    const st = useGameStore.getState();
    expect(st.events).toHaveLength(events.length);
    expect(st.cursor).toBe((events[events.length - 1] as Event).seq);
    expect(replayCalls()).toBe(1);
    expect(screen.getByText(new RegExp(`回放显示到 seq ${(events[events.length - 1] as Event).seq}`))).toBeInTheDocument();
  });

  it("未开局轮询只重试 /state，不再每轮打 /meta 吃 403", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta")) return jsonResponse(403, { detail: "对局未结束" });
      if (url.endsWith("/state")) return jsonResponse(409, { detail: "尚未开局" });
      return jsonResponse(200, {});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    const paths = (): string[] => fetchMock.mock.calls.map((c) => (c[0] as string).split("?")[0] as string);
    await waitFor(() => expect(paths().filter((p) => p.endsWith("/state")).length).toBeGreaterThanOrEqual(2), {
      timeout: 4000,
    });
    expect(paths().filter((p) => p.endsWith("/meta"))).toHaveLength(1);
  });
});
