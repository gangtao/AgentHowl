import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";
import { useGameStore } from "../store/game";
import { useVoice } from "../store/voice";
import { useTurn } from "../store/turn";
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
  readyState = 1;
  sent: string[] = [];

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

  send(data: string): void {
    this.sent.push(data);
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
  useTurn.getState().reset();
  useVoice.setState({ enabled: false, available: false, playing: null, queue: [] });
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
  it("连接 URL 三种形式：token / share / cookie", () => {
    const loc = location.host || "localhost";
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const base = `${proto}://${loc}/api/v1/ws`;
    renderHook(() => useLiveEvents({ gameId: "g_1", auth: { token: "T" }, enabled: true }));
    renderHook(() => useLiveEvents({ gameId: "g_1", auth: { share: "S" }, enabled: true }));
    renderHook(() => useLiveEvents({ gameId: "g_1", auth: {}, enabled: true }));
    const urls = FakeWebSocket.instances.map((i) => i.url);
    expect(urls[0]).toBe(`${base}?token=T&from_seq=1`);
    expect(urls[1]).toBe(`${base}?game_id=g_1&share=S&from_seq=1`);
    expect(urls[2]).toBe(`${base}?game_id=g_1&from_seq=1`);
  });

  it("连续 emit 3 个 game_event 后，一帧 rAF 内只调用一次 appendEvents", () => {
    const appendSpy = vi.spyOn(useGameStore.getState(), "appendEvents");
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
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
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.close(4404);

    expect(useGameStore.getState().error).toBe(CLOSE_TEXT[4404]);
    expect(useGameStore.getState().connection).toBe("error");

    vi.advanceTimersByTime(20000);
    expect(FakeWebSocket.instances).toHaveLength(1); // 未重连
  });

  it("意外 close(1006) 且未终局 → 1s 后重连，且 URL from_seq=lastSeq+1", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
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

  it("gap 分支清空 rAF 缓冲：残留陈旧事件不会在补发后触发第二次重连", () => {
    // 缺口判定只对 GM 视角成立（非 GM 的流经服务端裁剪，跳号是常态）
    useGameStore.getState().load(meta, { gameId: "g1", token: "tok", viewer: "GM" });
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket1 = FakeWebSocket.instances[0]!;

    // 攒 202 条到 rAF 缓冲：前 150 条连续，之后跳号到 300 起再垫 52 条——
    // flush 只 splice(0,200)，缺口（seq=151 缺失，出现 300）落在这 200 条以内，
    // splice 之后仍残留 2 条陈旧事件（seq=350、351）留在缓冲区最前面。
    for (let seq = 1; seq <= 150; seq++) {
      socket1.emit({ type: "game_event", seq, event: makeEvent(seq) });
    }
    for (let seq = 300; seq <= 351; seq++) {
      socket1.emit({ type: "game_event", seq, event: makeEvent(seq) });
    }

    vi.advanceTimersByTime(16); // 触发 flush：命中缺口 → clearGap + 清空剩余缓冲 + reconnect()

    expect(useGameStore.getState().gap).toBeNull();
    expect(useGameStore.getState().events).toHaveLength(150); // 缺口前缀已应用

    vi.advanceTimersByTime(1000); // 退避到期，发起重连
    expect(FakeWebSocket.instances).toHaveLength(2);
    const socket2 = FakeWebSocket.instances[1]!;
    expect(socket2.url).toContain("from_seq=151");

    // 新连接从 151 开始补发：若缓冲没清干净，陈旧的 seq=350 会排在这些真事件前面，
    // 立刻又判定一次假缺口，把这批真事件也丢掉。
    for (let seq = 151; seq <= 160; seq++) {
      socket2.emit({ type: "game_event", seq, event: makeEvent(seq) });
    }
    vi.advanceTimersByTime(16);

    expect(useGameStore.getState().gap).toBeNull();
    expect(useGameStore.getState().events).toHaveLength(160); // 150 + 10，无重复缺口
    expect(FakeWebSocket.instances).toHaveLength(2); // 全程只重连过一次
  });

  it("speech_audio 帧 → useVoice.enqueue，url 带本连接的 token；speech_audio_end 被忽略", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.emit({ type: "speech_audio", seq: 3, part: 0, url: "/a/3/0", duration: 1.5 });

    expect(useVoice.getState().available).toBe(true);
    // fix round 1（issue #103）：<audio> 发不出 Authorization 头，直播期间该端点匿名必 401，
    // enqueue 的 url 必须带上 ?token=，否则直播配音一句都放不出来。
    expect(useVoice.getState().queue).toEqual([
      { seq: 3, part: 0, url: "/a/3/0?token=tok", duration: 1.5, kind: "speech" },
    ]);
    // game store 不受影响：speech_audio 不是游戏事件，不进 appendEvents
    expect(useGameStore.getState().events).toHaveLength(0);

    socket.emit({ type: "speech_audio_end", seq: 3, parts: 1 });

    // 忽略：队列/available 均不因 speech_audio_end 改变
    expect(useVoice.getState().queue).toEqual([
      { seq: 3, part: 0, url: "/a/3/0?token=tok", duration: 1.5, kind: "speech" },
    ]);
  });

  it("RUNNER_CRASHED 错误帧 → 连接错误态 + 横幅，随后的 close(4500) 不重连（issue #39）", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket = FakeWebSocket.instances[0]!;
    socket.onopen?.();
    socket.emit({ type: "error", code: "RUNNER_CRASHED", detail: "对局运行异常，已停摆（详情见服务端日志）" });
    expect(useGameStore.getState().connection).toBe("error");
    expect(useGameStore.getState().error).toContain("对局运行异常");
    socket.close(4500);
    vi.advanceTimersByTime(10_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(useGameStore.getState().error).toBe(CLOSE_TEXT[4500]);
  });

  it("收到 game_over 后 close 不重连", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket = FakeWebSocket.instances[0]!;

    socket.emit({ type: "game_over", winner: "GOOD" });
    socket.close(1000);

    vi.advanceTimersByTime(20000);
    expect(FakeWebSocket.instances).toHaveLength(1); // 未重连
  });
});

describe("回合帧（issue #115）", () => {
  it("game_over 清掉残留的 turn.prompt", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const socket = FakeWebSocket.instances[0]!;
    socket.emit({
      type: "your_turn",
      observation: { my_role: "SEER", phase: "DAY_SPEECH" },
      available_tools: ["speak"],
      deadline_ts: 9999999999,
    });
    expect(useTurn.getState().prompt).not.toBeNull();
    socket.emit({ type: "game_over", winner: "GOOD" });
    expect(useTurn.getState().prompt).toBeNull();
  });

  it("your_turn 写入 turn.prompt；action_result ok 清掉；ok=false 保留并记拒因；error 帧记 lastError", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { my_seat: 0, state_version: 3 }, available_tools: ["vote"], deadline_ts: 99 });
    expect(useTurn.getState().prompt?.available_tools).toEqual(["vote"]);
    useTurn.getState().markPending(); // 已提交（send() 内部会标记）
    ws.emit({ type: "action_result", ok: false, event_id: null, state_version: null, rejected_reason: "目标已死亡" });
    expect(useTurn.getState().prompt).not.toBeNull();
    expect(useTurn.getState().lastResult?.rejected_reason).toBe("目标已死亡");
    useTurn.getState().markPending();
    ws.emit({ type: "action_result", ok: true, event_id: "evt_9", state_version: 4, rejected_reason: null });
    expect(useTurn.getState().prompt).toBeNull();
    ws.emit({ type: "error", detail: "行动窗口已关闭" });
    expect(useTurn.getState().lastError).toBe("行动窗口已关闭");
  });

  it("action_accepted 帧 → turn.accept()（pending 清、accepted 置位、prompt 保留）", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { my_seat: 0, state_version: 3 }, available_tools: ["vote"], deadline_ts: 99 });
    useTurn.getState().markPending();
    ws.emit({ type: "action_accepted", detail: "已提交" });
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().accepted).toBe(true);
    expect(useTurn.getState().prompt).not.toBeNull();
  });

  it("phase_change 帧与 game_event 同缓冲按序应用：先到的事件不会覆盖后到的阶段（issue #128）", () => {
    // 非 GM 视角：夜间阶段只能来自 phase_change 帧
    useGameStore.getState().load(meta, { gameId: "g1", token: "tok", viewer: 2 });
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    const phaseEvent = (seq: number, to: string): Event =>
      ({ ...makeEvent(seq), type: "PHASE_CHANGED", actor_seat: null, payload: { to } }) as unknown as Event;
    // 同一帧批次：PUBLIC 的 PHASE_CHANGED(VOTE) 在前，折叠的 NIGHT phase_change 在后
    ws.emit({ type: "game_event", seq: 1, event: phaseEvent(1, "VOTE") });
    ws.emit({ type: "phase_change", to: "NIGHT", round: 2 });
    vi.advanceTimersByTime(16);
    expect(useGameStore.getState().viewState()?.phase).toBe("NIGHT");
    expect(useGameStore.getState().viewState()?.round).toBe(2);
    // 反过来：阶段帧在前、事件在后 → 事件里的 PHASE_CHANGED 生效
    ws.emit({ type: "phase_change", to: "NIGHT", round: 3 });
    ws.emit({ type: "game_event", seq: 5, event: phaseEvent(5, "DAY_SPEECH") });
    vi.advanceTimersByTime(16);
    expect(useGameStore.getState().viewState()?.phase).toBe("DAY_SPEECH");
    expect(useGameStore.getState().viewState()?.round).toBe(3);
  });

  it("detail 为空的 error 帧也结束 pending，并给出兜底文案", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    useTurn.getState().markPending();
    ws.emit({ type: "error", detail: "" });
    expect(useTurn.getState().pending).toBe(false);
    expect(useTurn.getState().lastError).toBe("服务端返回了未说明的错误");
  });

  it("入座视角：行动 error 帧只进 useTurn，不写页面横幅；非座位视角仍写横幅", () => {
    useGameStore.getState().load(meta, { gameId: "g1", token: "tok", viewer: 2 });
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    useTurn.getState().markPending();
    ws.emit({ type: "error", detail: "当前不在该玩家的行动窗口" });
    expect(useTurn.getState().lastError).toBe("当前不在该玩家的行动窗口");
    expect(useGameStore.getState().error).toBeNull();
    // 终局关闭码仍写横幅
    ws.close(4404);
    expect(useGameStore.getState().error).toBe("对局不存在");
  });

  it("非座位视角的 error 帧仍写页面横幅", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "error", detail: "该连接无行动权限或座位无端口" });
    expect(useGameStore.getState().error).toBe("该连接无行动权限或座位无端口");
  });

  it("send 经 socket 发出 ToolCall 并置 pending；未连接返回 false", () => {
    const { result } = renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    expect(result.current.send({ tool: "vote", arguments: { abstain: true } })).toBe(true);
    expect(JSON.parse(ws.sent[0] as string)).toEqual({ tool: "vote", arguments: { abstain: true } });
    expect(useTurn.getState().pending).toBe(true);
    ws.readyState = 3;
    expect(result.current.send({ tool: "vote", arguments: { abstain: true } })).toBe(false);
  });

  it("断线清 pending；重连后再次收到 your_turn 覆盖 prompt", () => {
    renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { state_version: 1 }, available_tools: ["speak"], deadline_ts: 1 });
    useTurn.getState().markPending();
    ws.close(1006);
    expect(useTurn.getState().pending).toBe(false);
    vi.advanceTimersByTime(1000);
    const ws2 = FakeWebSocket.instances[1] as FakeWebSocket;
    ws2.onopen?.();
    ws2.emit({ type: "your_turn", observation: { state_version: 2 }, available_tools: ["speak"], deadline_ts: 2 });
    expect(useTurn.getState().prompt?.deadline_ts).toBe(2);
  });

  it("send() 把当前 prompt 的 state_version 放进信封；window_closed / code=NOT_YOUR_TURN 的 error 清掉残留 prompt（issue #125）", () => {
    const { result } = renderHook(() => useLiveEvents({ gameId: "g1", auth: { token: "tok" }, enabled: true }));
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    ws.onopen?.();
    ws.emit({ type: "your_turn", observation: { my_seat: 0, state_version: 7 }, available_tools: ["vote"], deadline_ts: 99 });
    expect(result.current.send({ tool: "vote", arguments: { abstain: true } })).toBe(true);
    expect(JSON.parse(ws.sent[ws.sent.length - 1] as string)).toEqual({ tool: "vote", arguments: { abstain: true }, state_version: 7 });
    // 本连接提交过 7 号窗口：window_closed(7) 不动 prompt（结果由 action_result 收尾）
    ws.emit({ type: "window_closed", state_version: 7 });
    expect(useTurn.getState().prompt?.observation.state_version).toBe(7);
    ws.emit({ type: "error", code: "NOT_YOUR_TURN", detail: "当前不在该玩家的行动窗口" });
    expect(useTurn.getState().prompt).toBeNull();
    // 另一标签页提交了 8 号窗口：本连接未提交 → window_closed(8) 清 prompt
    ws.emit({ type: "your_turn", observation: { my_seat: 0, state_version: 8 }, available_tools: ["vote"], deadline_ts: 99 });
    ws.emit({ type: "window_closed", state_version: 8 });
    expect(useTurn.getState().prompt).toBeNull();
    expect(useTurn.getState().lastError).toContain("本窗口已结束");
  });
});
