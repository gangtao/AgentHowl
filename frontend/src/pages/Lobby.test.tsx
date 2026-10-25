// 建局页「语音播报 / 旁白」联动（issue #110）：旁白依赖语音，关语音时旁白一并取消。

import { fireEvent, render, screen } from "@testing-library/react";
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

function stubLobbyFetch(joinStatus = 200): ReturnType<typeof vi.fn> {
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
    if (url.endsWith("/start")) return ok({ ok: true, num_players: 9 });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
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

async function pickMeOnSeat3(): Promise<void> {
  await screen.findByText("标准 9 人局");
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
  fireEvent.change(await screen.findByLabelText("3号 座位"), { target: { value: "me" } });
  fireEvent.click(screen.getByRole("button", { name: /下一步 · 汇总/ }));
}

describe("Lobby 我自己入座（issue #115）", () => {
  it("建局 → 以 3 号入座 → 开始 → 跳到玩家页；带真人时限", async () => {
    const fetchMock = stubLobbyFetch();
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await pickMeOnSeat3();
    expect(screen.getByText(/你将以 3号 入座/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "创建并开始" })[0] as HTMLElement);
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
    fireEvent.click(screen.getAllByRole("button", { name: "创建并开始" })[0] as HTMLElement);
    await screen.findByText(/409 · 座位 3 已被占用/);
    fireEvent.click(screen.getByRole("button", { name: "删除这局" }));
    await vi.waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, init]) => (u as string).endsWith("/games/g9") && (init as RequestInit).method === "DELETE"),
      ).toBe(true),
    );
    expect(window.location.hash).toBe("#/");
  });
});
