import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../engine/__fixtures__/std_9_kill_side-3.json";
import { normalizeState } from "../engine/normalize";
import { initialState, reduceAll } from "../engine/reduce";
import type { Event, GameMeta, GameState } from "../engine/types";
import { useGameStore } from "./game";

const meta = fixture.meta as unknown as GameMeta;
const events = fixture.events as unknown as Event[];
const states = fixture.states as unknown as GameState[];

beforeEach(() => {
  useGameStore.getState().reset();
});

afterEach(() => {
  useGameStore.getState().pause();
  vi.useRealTimers();
});

describe("useGameStore", () => {
  it("load(meta) 后 head.state_version === 0", () => {
    useGameStore.getState().load(meta);
    expect(useGameStore.getState().head?.state_version).toBe(0);
  });

  it("appendEvents(events.slice(0,60)) 后 head 等于 states[59]（normalize 后）", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60));
    const head = useGameStore.getState().head;
    expect(head).not.toBeNull();
    expect(normalizeState(head!)).toEqual(normalizeState(states[59]!));
  });

  it("重复追加同一批不改变 head/events", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60));
    const before = useGameStore.getState();
    useGameStore.getState().appendEvents(events.slice(0, 60));
    const after = useGameStore.getState();
    expect(after.events).toBe(before.events);
    expect(after.head).toBe(before.head);
    expect(after.events.length).toBe(60);
  });

  it("追加 seq 跳号的批次 → gap 被记录且不应用", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60)); // seq 1..60
    useGameStore.getState().appendEvents(events.slice(70, 80)); // seq 71..80：跳号
    const state = useGameStore.getState();
    expect(state.gap).toEqual({ expected: 61, got: 71 });
    expect(state.events.length).toBe(60); // 未应用
    expect(normalizeState(state.head!)).toEqual(normalizeState(states[59]!));
  });

  it("setCursor(30) → viewState() 等于 states[29]", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60));
    useGameStore.getState().setCursor(30);
    const view = useGameStore.getState().viewState();
    expect(view).not.toBeNull();
    expect(normalizeState(view!)).toEqual(normalizeState(states[29]!));
  });

  it("setCursor(null) → viewState() 回到 head", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60));
    useGameStore.getState().setCursor(30);
    useGameStore.getState().setCursor(null);
    const view = useGameStore.getState().viewState();
    expect(normalizeState(view!)).toEqual(normalizeState(useGameStore.getState().head!));
  });

  it("load(meta, {mode:'replay'}) → mode==='replay'、cursor===0、viewState() 等于 initialState(meta)", () => {
    useGameStore.getState().load(meta, { mode: "replay" });
    const state = useGameStore.getState();
    expect(state.mode).toBe("replay");
    expect(state.cursor).toBe(0);
    expect(normalizeState(state.viewState()!)).toEqual(normalizeState(initialState(meta)));
  });

  it("setMode() 可在直播中途切换（不影响 cursor）", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().setMode("replay");
    expect(useGameStore.getState().mode).toBe("replay");
  });

  it("setCursor 钳制到 [0, lastSeq]：越界值分别夹到两端", () => {
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events.slice(0, 60)); // lastSeq = 60

    useGameStore.getState().setCursor(99999);
    expect(useGameStore.getState().cursor).toBe(60);
    expect(normalizeState(useGameStore.getState().viewState()!)).toEqual(
      normalizeState(states[59]!),
    );

    useGameStore.getState().setCursor(-5);
    expect(useGameStore.getState().cursor).toBe(0);
    expect(normalizeState(useGameStore.getState().viewState()!)).toEqual(
      normalizeState(initialState(meta)),
    );

    useGameStore.getState().setCursor(null);
    expect(useGameStore.getState().cursor).toBeNull();
  });

  it("检查点：追加全部事件后，cursor=121 的 viewState() 与 reduceAll(initial, events.slice(0,121)) 一致", () => {
    // fixture 只有 129 条事件（brief 示例用的 137 超出本金样长度，改用同性质的
    // 非检查点对齐游标 121：checkpoints 落在 seq=50/100，121 落在 100 之后，
    // 借此验证「最近检查点 + 增量 reduce」与「全量 reduceAll」结果一致）。
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events);
    useGameStore.getState().setCursor(121);
    const view = useGameStore.getState().viewState();
    const expected = reduceAll(initialState(meta), events.slice(0, 121));
    expect(normalizeState(view!)).toEqual(normalizeState(expected));
  });

  it("play() + 假计时推进到末尾后自动 playing=false", () => {
    vi.useFakeTimers();
    useGameStore.getState().load(meta);
    useGameStore.getState().appendEvents(events);
    useGameStore.getState().setCursor(0);
    useGameStore.getState().setSpeed(1000); // 加快节奏，避免测试等太久
    useGameStore.getState().play();
    expect(useGameStore.getState().playing).toBe(true);

    vi.advanceTimersByTime(1000);

    expect(useGameStore.getState().playing).toBe(false);
    const view = useGameStore.getState().viewState();
    expect(normalizeState(view!)).toEqual(normalizeState(states[states.length - 1]!));
  });
});
