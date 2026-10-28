// 建局页「语音播报 / 旁白」联动（issue #110）：旁白依赖语音，关语音时旁白一并取消。

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../store/auth";
import Lobby from "./Lobby";

function stubFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/tts/status")
        ? { enabled: true, ok: true, url: null, detail: null, supports_style: false }
        : [];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Lobby 旁白开关", () => {
  it("语音未勾时旁白禁用；勾语音→勾旁白→取消语音后旁白取消勾选并禁用", async () => {
    stubFetch();
    render(<Lobby />);
    const voice = (await screen.findByLabelText(/语音播报/)) as HTMLInputElement;
    const narration = screen.getByLabelText(/^旁白/) as HTMLInputElement;
    expect(narration).toBeDisabled();

    fireEvent.click(voice);
    expect(narration).not.toBeDisabled();
    fireEvent.click(narration);
    expect(narration.checked).toBe(true);

    fireEvent.click(voice);
    expect(narration.checked).toBe(false);
    expect(narration).toBeDisabled();

    // 重新勾语音时旁白不能「复活」（内部状态已清掉）
    fireEvent.click(voice);
    expect(narration.checked).toBe(false);
  });
});

const PRESET = {
  name: "std_9_kill_side",
  num_players: 9,
  roles: [],
  sheriff: true,
  win_condition: "KILL_SIDE",
  description_zh: "标准 9 人局",
};

function stubLobbyFetch(joinStatus = 200, startStatus = 200, deleteStatus = 204): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (rawUrl: string, init?: RequestInit) => {
    const url = rawUrl.split("?")[0] as string;
    const ok = (body: unknown, status = 200): Response =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/tts/status")) return ok({ enabled: false, ok: false, url: null, detail: null, supports_style: false });
    if (url.endsWith("/presets")) return ok([PRESET]);
    if (url.endsWith("/games") && init?.method === "POST")
      return ok({ game_id: "g9", host_token: "H", gm_token: "G", share_token: null, config: {}, agents: {}, voice: false, narration: false });
    if (url.endsWith("/join"))
      return joinStatus === 200 ? ok({ player_token: "P", seat: 3, ws_url: "/api/v1/ws?token=P" }) : ok({ detail: "座位 3 已被占用" }, joinStatus);
    if (url.endsWith("/start"))
      return startStatus === 200 ? ok({ ok: true, num_players: 9 }) : ok({ detail: "无法开始" }, startStatus);
    if (init?.method === "DELETE")
      return deleteStatus === 204 ? new Response(null, { status: 204 }) : ok({ detail: "删除失败" }, deleteStatus);
    return ok([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function bodyOf(fetchMock: ReturnType<typeof vi.fn>, suffix: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(([u]) => (u as string).split("?")[0]?.endsWith(suffix)) as
    | [string, RequestInit]
    | undefined;
  return JSON.parse((call?.[1]?.body as string) ?? "{}") as Record<string, unknown>;
}

const LAUNCH = "点燃篝火 · 开局";

async function pickMeOnSeat3(): Promise<void> {
  await screen.findByText("标准 9 人局");
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
  // 圆桌入座：点 3 号座位 → 木牌菜单「我自己」
  fireEvent.click(await screen.findByRole("button", { name: "入座 3号" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "我自己" }));
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 开局卷轴/ }));
}

describe("Lobby 我自己入座（issue #115）", () => {
  it("建局 → 以 3 号入座 → 开始 → 跳到玩家页；带真人时限", async () => {
    const fetchMock = stubLobbyFetch();
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    expect(screen.getByText(/你将以 3号 入座/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await vi.waitFor(() => expect(window.location.hash).toBe("#/g/g9?player=P"));
    expect(bodyOf(fetchMock, "/join")).toEqual({ display_name: "alice", seat: 3 });
    const create = bodyOf(fetchMock, "/games");
    expect(create.config_override).toEqual({ speech_timeout_sec: 120, action_timeout_sec: 60 });
    expect(create.agents).toEqual({});
  });

  it("join 失败：展示错误并可删除这局", async () => {
    const fetchMock = stubLobbyFetch(409);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await vi.waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, init]) => (u as string).endsWith("/games/g9") && (init as RequestInit).method === "DELETE"),
      ).toBe(true),
    );
    expect(window.location.hash).toBe("#/");
  });

  it("失败后「点燃篝火 · 开局」禁用，删除后恢复", async () => {
    stubLobbyFetch(409);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    for (const b of screen.getAllByRole("button", { name: LAUNCH })) expect(b).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: "删除这局" })).toBeNull());
    for (const b of screen.getAllByRole("button", { name: LAUNCH })) expect(b).toBeEnabled();
  });

  it("删除返回 404（对局已不存在）：清掉失败对局，「点燃篝火 · 开局」恢复", async () => {
    stubLobbyFetch(409, 200, 404);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: "删除这局" })).toBeNull());
    for (const b of screen.getAllByRole("button", { name: LAUNCH })) expect(b).toBeEnabled();
  });

  it("删除返回其它错误：保留失败对局与错误，仍可重试删除", async () => {
    stubLobbyFetch(409, 200, 500);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await screen.findByText(/500 · 删除失败/);
    expect(screen.getByRole("button", { name: "删除这局" })).toBeInTheDocument();
    for (const b of screen.getAllByRole("button", { name: LAUNCH })) expect(b).toBeDisabled();
  });

  it("start 失败：不跳转，保留可删除的失败对局", async () => {
    stubLobbyFetch(200, 409);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await screen.findByText(/409 · 无法开始/);
    expect(screen.getByRole("button", { name: "删除这局" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/");
  });
});

const LIBRARY_ROWS = [
  {
    agent_id: "a_owl",
    profile: { name: "夜枭", model: "m", skills: [] },
    created_at: "t",
    updated_at: "t",
    rating: { rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 },
  },
  {
    agent_id: "a_nice",
    profile: { name: "老好人", model: "m", skills: [] },
    created_at: "t",
    updated_at: "t",
    rating: { rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 },
  },
];

describe("Lobby 建局归因（issue #123）", () => {
  it("座位选库内档案 + 填满档案 → 请求体 agent_ids 含座位键与 \"*\"，与 agents 键一致", async () => {
    const fetchMock = stubLobbyFetch();
    const inner = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (rawUrl: string, init?: RequestInit) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/agents") && (init?.method ?? "GET") === "GET")
        return new Response(JSON.stringify(LIBRARY_ROWS), { status: 200, headers: { "Content-Type": "application/json" } });
      return inner(rawUrl, init);
    });
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await screen.findByText("标准 9 人局");
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
    fireEvent.click(await screen.findByRole("button", { name: "入座 3号" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "夜枭" }));
    fireEvent.change(screen.getByLabelText("填满其余座位"), { target: { value: "a_nice" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 开局卷轴/ }));
    // 卷轴座位行：3号 夜枭 + 其余 8 座由「老好人」填满（右栏卡的汇总也有同句，限定在卷轴内查）
    const scroll = within(screen.getByRole("region", { name: "开局卷轴" }));
    expect(scroll.getByText("3号 夜枭")).toBeInTheDocument();
    expect(scroll.getByText(/其余 8 座由「老好人」填满/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: LAUNCH })[0] as HTMLElement);
    await vi.waitFor(() => expect(bodyOf(fetchMock, "/games").agent_ids).toBeDefined());
    const create = bodyOf(fetchMock, "/games");
    expect(create.agent_ids).toEqual({ "3": "a_owl", "*": "a_nice" });
    expect(Object.keys(create.agents as object).sort()).toEqual(["*", "3"]);
  });
});

const PRESET_12 = {
  name: "std_12_yn_hunter_idiot",
  num_players: 12,
  roles: [],
  sheriff: true,
  win_condition: "KILL_SIDE",
  description_zh: "12 人预女猎白",
};

function withPresets(fetchMock: ReturnType<typeof vi.fn>, presets: unknown[]): void {
  const inner = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
  fetchMock.mockImplementation(async (rawUrl: string, init?: RequestInit) => {
    const url = rawUrl.split("?")[0] as string;
    if (url.endsWith("/presets"))
      return new Response(JSON.stringify(presets), { status: 200, headers: { "Content-Type": "application/json" } });
    return inner(rawUrl, init);
  });
}

describe("Lobby 三步布局（UI 改版 PR ③）", () => {
  it("换 preset 座位数变少：越界的「我自己」被丢弃，汇总不再显示我在 N号", async () => {
    const fetchMock = stubLobbyFetch();
    withPresets(fetchMock, [PRESET_12, PRESET]);
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    render(<Lobby />);
    // 档案库 store 跨用例共享，刷新前可能仍选着上个用例的 9 人板：显式点 12 人剧本牌
    fireEvent.click(await screen.findByRole("button", { name: /12 人预女猎白/ }));
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
    fireEvent.click(await screen.findByRole("button", { name: "入座 10号" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "我自己" }));
    expect(screen.getByText("12 座位 · 0 个 Agent · 我在 10号 · 11 个随机 bot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /← 上一步/ }));
    fireEvent.click(screen.getByRole("button", { name: /标准 9 人局/ }));
    expect(screen.getByText("9 座位 · 0 个 Agent · 9 个随机 bot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
    expect(screen.getAllByRole("button", { name: /^入座 \d+号$/ })).toHaveLength(9);
  });

  it("档案库为空：第 2 步显示空库提示，圆桌 9 个 bot 座位，第 3 步仍可开局", async () => {
    stubLobbyFetch();
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    render(<Lobby />);
    await screen.findByText("标准 9 人局");
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
    // /agents 刷新是异步的（store 可能还留着上个用例的档案），等空库提示出现
    expect((await screen.findAllByText(/档案库是空的/)).length).toBeGreaterThan(0);
    const seats = await screen.findAllByRole("button", { name: /^入座 \d+号$/ });
    expect(seats).toHaveLength(9);
    for (const b of seats) expect(b).toHaveAttribute("data-kind", "bot");
    // 第 2 步右栏按钮禁用；进入第 3 步后两处都可用
    expect(screen.getByRole("button", { name: LAUNCH })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 开局卷轴/ }));
    for (const b of screen.getAllByRole("button", { name: LAUNCH })) expect(b).toBeEnabled();
    expect(screen.getByText("全 AI 对局 · 创建后进入上帝视角")).toBeInTheDocument();
  });

  it("第 3 步顶部进度条高亮「③ 点燃篝火」，左栏步骤隐藏", async () => {
    stubLobbyFetch();
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    render(<Lobby />);
    await pickMeOnSeat3();
    expect(screen.queryByText("建 局 三 步")).toBeNull();
    const nav = screen.getByRole("navigation", { name: "建局进度" });
    expect(nav).toHaveTextContent("① 选择剧本");
    expect(nav.querySelector('[aria-current="step"]')).toHaveTextContent("③ 点燃篝火");
    fireEvent.click(screen.getByRole("button", { name: "← 上一步 · 分配座位" }));
    expect(screen.getByText("建 局 三 步")).toBeInTheDocument();
  });
});
