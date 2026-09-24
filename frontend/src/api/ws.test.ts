import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useGameStore } from "../store/game";
import { CLOSE_TEXT, useLiveEvents } from "./ws";
import type { Event, GameMeta } from "../engine/types";

// ---- 假 WebSocket：挂到 globalThis，记录 URL，支持 emit(frame) / close(code) ----
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  emit(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  close(code = 1000): void {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.({ code });
  }

  send(): void {
    // 观战/上帝视角只读，本 hook 不发送任何帧
  }
}

const meta = { game_id: "g1", config: {}, roster: [], agents: {} } as unknown as GameMeta;

function makeEvent(seq: number): Event {
  return {
    seq,
    game_id: "g1",
    ts: seq,
    type: "PLAYER_SPOKE",
    actor_seat: 0,
    payload: { content: `e${seq}` },
    visibility: "PUBLIC",
    meta: {},
  } as unknown as Event;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  useGameStore.getState().reset();
  useGameStore.getState().load(meta, { gameId: "g1", token: "tok", viewer: "SPECTATOR" });
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) =>
    setTimeout(() => cb(0), 16),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useLiveEvents", () => {
  it("连接 URL 含 token 与 from_seq=1", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", token: "tok", enabled: true }));
    expect(FakeWebSocket.instances).toHaveLength(1);
    const url = FakeWebSocket.instances[0]!.url;
    expect(url).toContain("token=tok");
    expect(url).toContain("from_seq=1");
  });

  it("连续 emit 3 个 game_event 后，一帧 rAF 内只调用一次 appendEvents", () => {
    const appendSpy = vi.spyOn(useGameStore.getState(), "appendEvents");
    renderHook(() => useLiveEvents({ gameId: "g1", token: "tok", enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.emit({ type: "game_event", seq: 1, event: makeEvent(1) });
    socket.emit({ type: "game_event", seq: 2, event: makeEvent(2) });
    socket.emit({ type: "game_event", seq: 3, event: makeEvent(3) });

    expect(appendSpy).not.toHaveBeenCalled();

    vi.advanceTimersByTime(16);

    expect(appendSpy).toHaveBeenCalledTimes(1);
    expect(appendSpy.mock.calls[0]?.[0]).toHaveLength(3);
    expect(useGameStore.getState().events).toHaveLength(3);
  });

  it("close(4404) → error 为「对局不存在」且不重连", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", token: "tok", enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.close(4404);

    expect(useGameStore.getState().error).toBe(CLOSE_TEXT[4404]);
    expect(useGameStore.getState().connection).toBe("error");

    vi.advanceTimersByTime(20000);
    expect(FakeWebSocket.instances).toHaveLength(1); // 未重连
  });

  it("意外 close(1006) 且未终局 → 1s 后重连，且 URL from_seq=lastSeq+1", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", token: "tok", enabled: true }));
    const socket = FakeWebSocket.instances[0]!;
    socket.emit({ type: "game_event", seq: 1, event: makeEvent(1) });
    vi.advanceTimersByTime(16); // 让 seq=1 落盘到 lastSeqRef

    socket.close(1006);
    expect(FakeWebSocket.instances).toHaveLength(1); // 尚未重连

    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1]!.url).toContain("from_seq=2");
  });

  it("收到 game_over 后 close 不重连", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", token: "tok", enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.emit({ type: "game_over", winner: "GOOD" });
    socket.close(1000);

    vi.advanceTimersByTime(20000);
    expect(FakeWebSocket.instances).toHaveLength(1); // 未重连
  });
});
