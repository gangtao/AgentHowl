// 对局页测试：终局对局经 /meta + /replay 装入；覆盖 token / share / cookie（无凭据）三种凭据（issue #114）。

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import type { Event, GameMeta } from "../engine/types";
import { useAuth } from "../store/auth";
import { useGameStore } from "../store/game";
import { usePrefs } from "../store/prefs";
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
  usePrefs.setState({ tableStyle: "round" });
});

describe("GamePage 桌面皮肤（规格 §7）", () => {
  it("偏好 cards 时桌子区渲染 CardBoard，切回 round 渲染圆桌；座位契约不变", async () => {
    usePrefs.setState({ tableStyle: "cards" });
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    expect(await screen.findByTestId("card-board")).toBeInTheDocument();
    const seatsOnCards = document.querySelectorAll("button[data-seat]").length;
    expect(seatsOnCards).toBe(9);
    fireEvent.change(screen.getByLabelText("桌面皮肤"), { target: { value: "round" } });
    expect(screen.queryByTestId("card-board")).toBeNull();
    expect(document.querySelectorAll("button[data-seat]").length).toBe(9);
  });
});

describe("GamePage 发言高亮跟随配音（issue #110）", () => {
  it("voicingSeq 指向无 actor 的事件（旁白）时不把任何座位标成发言中；找不到事件时退回轮到谁", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const narrated = events.find((e) => e.actor_seat === null && e.type === "VOTE_STARTED");
    expect(narrated).toBeDefined();
    act(() =>
      useVoice.setState({ voicingSeq: narrated!.seq, playing: { seq: narrated!.seq, part: 0 } }),
    );
    expect(screen.queryByRole("button", { name: /发言中/ })).toBeNull();
    act(() => useVoice.setState({ voicingSeq: 999999, playing: null }));
    expect(screen.queryByRole("button", { name: /发言中/ })).toBeNull();
    useVoice.getState().clear();
  });

  it("带 actor_seat 的非发言事件（HUNTER_SHOT 等）也不高亮座位", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const shot = events.find((e) => e.type === "HUNTER_SHOT");
    expect(shot?.actor_seat).not.toBeNull();
    act(() => useVoice.setState({ voicingSeq: shot!.seq, playing: { seq: shot!.seq, part: 0 } }));
    expect(screen.queryByRole("button", { name: /发言中/ })).toBeNull();
    useVoice.getState().clear();
  });
});

describe("GamePage 凭据模式（issue #114）", () => {
  it("cookie 模式：无 token、viewer=GM，/meta 裸请求（带 cookie）→ 装入回放", async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/games/g_x/meta");
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("share 模式：请求带 ?share=", async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" share="S" viewer="SPECTATOR" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
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

  it("已登录用户遇到 401/403：按钮是「回到村志」而不是会循环的「去登录」（issue #170）", async () => {
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    try {
      stubFetch(() => jsonResponse(401, { detail: "未登录" }));
      render(<GamePage gameId="g_x" viewer="GM" />);
      expect(await screen.findByText("村口有人守着")).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "去登录" })).toBeNull();
      expect(screen.getByRole("link", { name: "回到村志" })).toHaveAttribute("href", "#/history");
    } finally {
      useAuth.setState({ status: "anon", user: null });
    }
  });
});

describe("GamePage 视角以服务端为准（issue #115）", () => {
  it("/meta 的 viewer 覆盖 URL 提示", async () => {
    stubFetch(() => jsonResponse(200, { ...meta, viewer: "SPECTATOR" }));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    expect(useGameStore.getState().viewer).toBe("SPECTATOR");
  });

  it("建局者入座期间用 GM 链接进来 → 封锁错误态，给玩家入口", async () => {
    const fetchMock = vi.fn(async (rawUrl: string) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/meta"))
        return jsonResponse(403, { detail: "对局未结束，上帝视角回放未开放" });
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
    seats: [0, 1, 2].map((seat) => ({
      seat,
      alive: true,
      is_sheriff: false,
      idiot_revealed: false,
      display_name: `P${seat}`,
    })),
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
    vi.stubGlobal(
      "WebSocket",
      vi.fn(() => ({ close() {} })),
    );
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    expect(screen.getByText("预言家")).toBeInTheDocument();
    expect(screen.getByText("旁听中")).toBeInTheDocument();
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
    await screen.findByText("2号 · P2");
    await submitSpeech();
    expect(useTurn.getState().lastError).toMatch(/连接未就绪/);
    expect(useTurn.getState().pending).toBe(false);
  });

  it("提交时 socket 已开：进入 pending", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    await submitSpeech();
    expect(useTurn.getState().pending).toBe(true);
    expect(useTurn.getState().lastError).toBeNull();
  });

  it("夜间：有 your_turn 时不遮罩；无 prompt 时显示「请闭眼」", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
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
    // 没有遮罩可以摘了：有 prompt 时行动区可用（桌心的月亮卡照常显示）
    expect(screen.getByRole("region", { name: "行动区" })).toBeInTheDocument();
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
    await screen.findByText("2号 · P2");
    expect(screen.queryByRole("button", { name: "查看全局回放" })).toBeNull();
  });

  it("投票回合：点桌上可选座位 → HUD 胶囊同步选中（aria-pressed）", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    act(() =>
      useTurn.getState().setPrompt({
        observation: { ...playerState, phase: "VOTE" } as never,
        available_tools: ["vote", "get_state"] as never,
        deadline_ts: Date.now() / 1000 + 60,
      }),
    );
    const seat0 = await screen.findByRole("button", { name: /^0号 P0/ });
    expect(seat0).toBeEnabled();
    expect(screen.getByRole("button", { name: /^2号 P2/ })).toBeDisabled(); // 自己不可投
    fireEvent.click(seat0);
    expect(screen.getByRole("button", { name: "0号" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "确认投票 · 0号" })).toBeEnabled();
  });

  it("投票中切换桌面皮肤：选中目标保留，卡牌上可选座位仍可点并同步 HUD，切回圆桌亦然（规格 §7）", async () => {
    stubPlayerFetch(playerState);
    stubSocket(true);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    act(() =>
      useTurn.getState().setPrompt({
        observation: { ...playerState, phase: "VOTE" } as never,
        available_tools: ["vote", "get_state"] as never,
        deadline_ts: Date.now() / 1000 + 60,
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^0号 P0/ }));
    fireEvent.change(screen.getByLabelText("桌面皮肤"), { target: { value: "cards" } });
    expect(await screen.findByTestId("card-board")).toBeInTheDocument();
    expect(document.querySelector('button[data-seat="0"]')).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(screen.getByRole("button", { name: "确认投票 · 0号" })).toBeEnabled();
    const card1 = document.querySelector('button[data-seat="1"][data-selectable]') as HTMLElement;
    expect(card1).not.toBeNull();
    fireEvent.click(card1);
    expect(screen.getByRole("button", { name: "确认投票 · 1号" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("桌面皮肤"), { target: { value: "round" } });
    expect(screen.queryByTestId("card-board")).toBeNull();
    expect(screen.getByRole("button", { name: /^1号 P1/ })).toHaveAttribute(
      "data-selected",
      "true",
    );
  });
});

describe("metaFromState 公开规则（issue #80）", () => {
  it("观众 / 玩家快照带 config.sheriff 时以服务端票权为准，缺的字段用名单兜底", () => {
    const seats = [0, 1, 2].map((seat) => ({ seat, display_name: `P${seat}` }));
    const meta = metaFromState("g_x", {
      seats,
      config: { num_players: 3, sheriff: { enabled: true, vote_weight: 2 } },
    });
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
    seats: meta.roster.map((r) => ({
      ...r,
      alive: true,
      is_sheriff: false,
      idiot_revealed: false,
    })),
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
    vi.stubGlobal(
      "WebSocket",
      vi.fn(() => ({ close() {} })),
    );
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
    // 游标停在终局 → 结算页覆盖舞台（规格 §4.8）
    expect(await screen.findByRole("region", { name: "游戏结束" })).toBeInTheDocument();
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
    const paths = (): string[] =>
      fetchMock.mock.calls.map((c) => (c[0] as string).split("?")[0] as string);
    await waitFor(
      () => expect(paths().filter((p) => p.endsWith("/state")).length).toBeGreaterThanOrEqual(2),
      {
        timeout: 4000,
      },
    );
    expect(paths().filter((p) => p.endsWith("/meta"))).toHaveLength(1);
  });
});

describe("GamePage 终局结算页（规格 §4.8）", () => {
  it("回放游标在中段不显示结算页，拖到末尾显示", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    expect(screen.queryByRole("region", { name: "游戏结束" })).toBeNull();
    const last = (events[events.length - 1] as Event).seq;
    act(() => useGameStore.getState().setCursor(Math.floor(last / 2)));
    expect(screen.queryByRole("region", { name: "游戏结束" })).toBeNull();
    act(() => useGameStore.getState().setCursor(last));
    expect(await screen.findByRole("region", { name: "游戏结束" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "狼人阵营胜" })).toBeInTheDocument();
  });
});

describe("GamePage 终审修复（PR ② 评审）", () => {
  const playerState = {
    viewer: 2,
    game_id: "g_x",
    state_version: 7,
    my_seat: 2,
    my_role: "WEREWOLF",
    my_status: "ALIVE",
    phase: "DAY_SPEECH",
    round: 1,
    seats: [0, 1, 2].map((seat) => ({
      seat,
      alive: true,
      is_sheriff: false,
      idiot_revealed: false,
      display_name: `P${seat}`,
    })),
    sheriff_seat: null,
    badge_flow_claims: {},
    private: { teammates: [0] },
    election_stage: "",
    sheriff_candidates: [],
    vote_candidates: [],
    pk_speech_pending: false,
    badge_only: false,
    available_actions: [],
  };
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
    vi.stubGlobal(
      "WebSocket",
      vi.fn(() => ({ readyState: 1, send() {}, close() {} })),
    );
  }

  it("队友来自 /state 快照与 your_turn 的观察，提交成功清掉 prompt 后仍然可见（Important 1）", async () => {
    stubPlayerFetch(playerState);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    // 引导快照里就有 teammates：没有 prompt 也应显示队友
    expect(screen.getByText("队友 0号")).toBeInTheDocument();
    act(() =>
      useTurn.getState().setPrompt({
        observation: { ...playerState, private: { teammates: [0, 1] } } as never,
        available_tools: ["speak", "get_state"] as never,
        deadline_ts: Date.now() / 1000 + 60,
      }),
    );
    expect(screen.getByText("队友 0号 · 1号")).toBeInTheDocument();
    act(() => {
      useTurn.getState().markPending();
      useTurn
        .getState()
        .resolve({ ok: true, event_id: "e", state_version: 7, rejected_reason: null });
    });
    expect(useTurn.getState().prompt).toBeNull();
    expect(screen.getByText("队友 0号 · 1号")).toBeInTheDocument();
  });

  it("夜间被刀的猎人收到确认窗口时身份牌显示「已出局」（Important 3）", async () => {
    stubPlayerFetch({ ...playerState, my_role: "HUNTER", my_status: "DEAD", private: {} });
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    expect(screen.getByText("已出局")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "已出局" })).toBeInTheDocument();
  });

  it("回放：配音正在读第一轮某句时，发言台显示的是游标处那句而不是全局最后一句（Important 5）", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const first = events.find((e) => e.type === "PLAYER_SPOKE") as Event;
    const content = (first.payload as { content: string }).content;
    act(() => useGameStore.getState().setCursor(first.seq));
    act(() => useVoice.setState({ voicingSeq: first.seq, playing: { seq: first.seq, part: 0 } }));
    // 第一句发言可能是竞选发言：发言台头部按阶段写「发言中 / 竞选发言 / 遗言」
    const stand = await screen.findByRole("status", {
      name: new RegExp(`^${first.actor_seat}号 .* (发言中|竞选发言|遗言)$`),
    });
    expect(stand.querySelector('[data-testid="stand-text"]')).toHaveTextContent(content.slice(0, 20));
    useVoice.getState().clear();
  });

  it("玩家直播收尾后拖动绳索条回中段 → 结算页让位（Important 6）", async () => {
    stubPlayerFetch(playerState);
    render(<GamePage gameId="g_x" token="P" />);
    await screen.findByText("2号 · P2");
    act(() =>
      useGameStore.getState().appendEvents([
        {
          seq: 1,
          game_id: "g_x",
          ts: 1,
          type: "PHASE_CHANGED",
          actor_seat: null,
          payload: { to: "DAY_SPEECH" },
          visibility: "PUBLIC",
          meta: {},
        },
        {
          seq: 2,
          game_id: "g_x",
          ts: 2,
          type: "GAME_OVER",
          actor_seat: null,
          payload: { winner: "WOLF" },
          visibility: "PUBLIC",
          meta: {},
        },
      ] as unknown as Event[]),
    );
    expect(await screen.findByRole("region", { name: "游戏结束" })).toBeInTheDocument();
    act(() => useGameStore.getState().setCursor(1));
    expect(screen.queryByRole("region", { name: "游戏结束" })).toBeNull();
  });
});

describe("GamePage 回放阅读停留（规格 §7 / issue #189）", () => {
  it("语音关：发言 seq 的门控返回阅读等待，暂停后立即 resolve；非发言 seq 为 null", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    useVoice.setState({ enabled: false });
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
    const gate = useGameStore.getState().replayGate;
    expect(gate).not.toBeNull();
    const spoke = events.find((e) => e.type === "PLAYER_SPOKE")!;
    const vote = events.find((e) => e.type === "VOTE_CAST")!;
    expect(gate!(vote.seq)).toBeNull();
    const p = gate!(spoke.seq);
    expect(p).not.toBeNull();
    let done = false;
    void p!.then(() => {
      done = true;
    });
    await Promise.resolve();
    expect(done).toBe(false);
    // 先播放再暂停：暂停键要调用 controls.onPause → 取消阅读等待
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    fireEvent.click(screen.getByRole("button", { name: "暂停" }));
    await Promise.resolve();
    await Promise.resolve();
    expect(done).toBe(true);
  });
});

describe("GamePage 右栏：发言台 + 对局记录（规格 §3 / §8）", () => {
  async function mountReplay(): Promise<void> {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" token="t" viewer="GM" />);
    await screen.findByText(new RegExp(`▶ 回放 · ${events.length} 条事件`));
  }

  it("回放到发言阶段：右栏上半是发言台、下半是对局记录；不再有气泡与事件流页签", async () => {
    await mountReplay();
    const spoke = events.find((e) => e.type === "PLAYER_SPOKE") as Event;
    act(() => useGameStore.getState().setCursor(spoke.seq));
    expect(await screen.findByRole("status", { name: /(发言中|竞选发言)$/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "对局记录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /事件流/ })).toBeNull();
    expect(document.querySelector(`article[data-seq="${spoke.seq}"]`)).toHaveAttribute(
      "data-current",
      "true",
    );
  });

  it("回放到投票阶段：右栏上半是信息卡（票型），记录仍在", async () => {
    await mountReplay();
    const vote = events.find((e) => e.type === "VOTE_CAST") as Event;
    act(() => useGameStore.getState().setCursor(vote.seq));
    await screen.findByLabelText("信息栏");
    expect(screen.queryByRole("status", { name: /(发言中|竞选发言|遗言)$/ })).toBeNull();
    expect(screen.getByRole("region", { name: "对局记录" })).toBeInTheDocument();
  });

  it("配音读上一位时发言台显示上一位，座位状态行上一位「发言中」下一位「待发言」", async () => {
    await mountReplay();
    const spokes = events.filter((e) => e.type === "PLAYER_SPOKE");
    // 找同一阶段相邻的两句（seq 连续，中间没有阶段切换）
    const idx = spokes.findIndex((e, i) => i > 0 && e.seq === (spokes[i - 1] as Event).seq + 1);
    expect(idx).toBeGreaterThan(0);
    const e1 = spokes[idx - 1] as Event;
    const e2 = spokes[idx] as Event;
    act(() => useGameStore.getState().setCursor(e2.seq));
    act(() => useVoice.setState({ voicingSeq: e1.seq, playing: { seq: e1.seq, part: 0 } }));
    expect(
      await screen.findByRole("status", { name: new RegExp(`^${e1.actor_seat}号 `) }),
    ).toBeInTheDocument();
    expect(
      document.querySelector(`button[data-seat="${e1.actor_seat}"] [data-tone="now"]`),
    ).toHaveTextContent("发言中");
    const nextTone = document.querySelector(`button[data-seat="${e2.actor_seat}"] [data-tone]`);
    expect(nextTone?.textContent === "待发言" || nextTone?.textContent === "已发言").toBe(true);
    useVoice.getState().clear();
  });
});
