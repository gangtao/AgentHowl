// 事件日志 store（规格 §6）：增量 reduce + 回放检查点。零 IO——网络由 src/api/ws.ts 调用本 store
// 的 actions 驱动；本文件不 import React 组件。

import { create } from "zustand";
import { initialState, reduce, reduceAll } from "../engine/reduce";
import type { Event, GameMeta, GameState } from "../engine/types";

/** 每隔多少条事件存一份检查点，供 viewState() 从最近检查点重放而非从头重放。 */
export const CHECKPOINT_EVERY = 50;

export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";
export type PlaybackMode = "live" | "replay";
export type Viewer = "GM" | "SPECTATOR";

export interface Gap {
  expected: number;
  got: number;
}

export interface LoadOptions {
  gameId?: string;
  token?: string;
  viewer?: Viewer;
  /** 默认 "live"；传 "replay" 时（如 GamePage 用 getReplay 一次性装入终局对局，规格 §6）
   * `load()` 会把 `cursor` 置为 0（回放起点），而不是 `null`（跟随最新）。 */
  mode?: PlaybackMode;
}

interface GameStoreState {
  gameId: string | null;
  token: string | null;
  viewer: Viewer | null;
  meta: GameMeta | null;
  events: Event[];
  head: GameState | null;
  checkpoints: Map<number, GameState>;
  mode: PlaybackMode;
  cursor: number | null;
  connection: ConnectionState;
  error: string | null;
  gap: Gap | null;
  playing: boolean;
  /** 播放速度：事件/秒（brief 未规定单位，本实现选定“事件/秒”，见 task-6-report.md）。 */
  speed: number;

  load(meta: GameMeta, opts?: LoadOptions): void;
  appendEvents(batch: readonly Event[]): void;
  /** seq === null → 跟随最新（head）；否则钳到 `[0, lastSeq]`（越界值不抛错，就近夹住）。 */
  setCursor(seq: number | null): void;
  setMode(mode: PlaybackMode): void;
  viewState(): GameState | null;
  play(): void;
  pause(): void;
  setSpeed(speed: number): void;
  stepForward(): void;
  stepBack(): void;
  setConnection(connection: ConnectionState): void;
  setError(error: string | null): void;
  clearGap(): void;
  reset(): void;
}

/** viewState() 的记忆化缓存：模块级、非响应式，key 为 (cursor, events.length)。 */
let viewCache: { cursor: number | null; eventsLength: number; value: GameState | null } | null =
  null;

/** play() 的 setInterval 句柄：模块级，避免把非可序列化的计时器放进 store 状态。 */
let playTimer: ReturnType<typeof setInterval> | null = null;

function clearPlayTimer(): void {
  if (playTimer !== null) {
    clearInterval(playTimer);
    playTimer = null;
  }
}

function lastSeqOf(events: readonly Event[]): number {
  return events.length > 0 ? (events[events.length - 1] as Event).seq : 0;
}

/** play()/setSpeed() 共用的播放节拍：走到末尾（cur >= lastSeq）就 pause()，否则单步前进。
 * 抽成模块级函数避免两处维护同一份逻辑（review Minor-5）。 */
function makeTick(get: () => GameStoreState): () => void {
  return () => {
    const state = get();
    const lastSeq = lastSeqOf(state.events);
    const cur = state.cursor ?? lastSeq;
    if (cur >= lastSeq) {
      get().pause();
      return;
    }
    get().stepForward();
  };
}

/** 取 <= seq 的最近检查点（无则回退到初始状态）。 */
function nearestCheckpoint(
  checkpoints: Map<number, GameState>,
  meta: GameMeta,
  seq: number,
): { baseSeq: number; baseState: GameState } {
  let baseSeq = 0;
  let baseState = initialState(meta);
  for (const [cpSeq, cpState] of checkpoints) {
    if (cpSeq <= seq && cpSeq > baseSeq) {
      baseSeq = cpSeq;
      baseState = cpState;
    }
  }
  return { baseSeq, baseState };
}

export const useGameStore = create<GameStoreState>((set, get) => ({
  gameId: null,
  token: null,
  viewer: null,
  meta: null,
  events: [],
  head: null,
  checkpoints: new Map(),
  mode: "live",
  cursor: null,
  connection: "idle",
  error: null,
  gap: null,
  playing: false,
  speed: 2,

  load(meta, opts) {
    clearPlayTimer();
    viewCache = null;
    const mode = opts?.mode ?? "live";
    set({
      meta,
      gameId: opts?.gameId ?? get().gameId,
      token: opts?.token ?? get().token,
      viewer: opts?.viewer ?? get().viewer,
      events: [],
      head: initialState(meta),
      checkpoints: new Map(),
      mode,
      // replay 模式（如 getReplay 一次性装入终局对局）从头开始播放（规格 §6）；
      // live 模式 cursor=null 跟随最新。
      cursor: mode === "replay" ? 0 : null,
      connection: "idle",
      gap: null,
      playing: false,
      error: null,
    });
  },

  appendEvents(batch) {
    if (batch.length === 0) return;
    const state = get();
    if (state.meta === null) return; // 未 load()，无从 reduce
    let head = state.head ?? initialState(state.meta);
    let lastSeq = lastSeqOf(state.events);
    const events = state.events.slice();
    const checkpoints = new Map(state.checkpoints);
    let gap: Gap | null = null;
    let appliedAny = false;

    for (const e of batch) {
      if (e.seq <= lastSeq) continue; // 已应用过，去重跳过
      if (e.seq !== lastSeq + 1) {
        gap = { expected: lastSeq + 1, got: e.seq };
        break; // 缺口/乱序：本批到此为止，不静默应用后续
      }
      head = reduce(head, e);
      events.push(e);
      lastSeq = e.seq;
      appliedAny = true;
      if (events.length % CHECKPOINT_EVERY === 0) {
        checkpoints.set(e.seq, head);
      }
    }

    if (!appliedAny && gap === null) return; // 纯重复批次：不改变任何东西

    if (appliedAny) {
      viewCache = null;
      set({ events, head, checkpoints, gap });
    } else {
      set({ gap });
    }
  },

  setCursor(seq) {
    const clamped =
      seq === null ? null : Math.min(Math.max(seq, 0), lastSeqOf(get().events));
    if (get().cursor === clamped) return;
    set({ cursor: clamped });
  },

  setMode(mode) {
    if (get().mode === mode) return;
    set({ mode });
  },

  viewState() {
    const state = get();
    if (state.cursor === null) {
      return state.head;
    }
    if (
      viewCache !== null &&
      viewCache.cursor === state.cursor &&
      viewCache.eventsLength === state.events.length
    ) {
      return viewCache.value;
    }
    if (state.meta === null) return null;
    const { baseSeq, baseState } = nearestCheckpoint(state.checkpoints, state.meta, state.cursor);
    const slice = state.events.filter((e) => e.seq > baseSeq && e.seq <= (state.cursor as number));
    const value = reduceAll(baseState, slice);
    viewCache = { cursor: state.cursor, eventsLength: state.events.length, value };
    return value;
  },

  play() {
    if (get().playing) return;
    set({ playing: true });
    clearPlayTimer();
    playTimer = setInterval(makeTick(get), 1000 / get().speed);
  },

  pause() {
    clearPlayTimer();
    set({ playing: false });
  },

  setSpeed(speed) {
    set({ speed });
    if (get().playing) {
      // 重启计时器以套用新速度
      clearPlayTimer();
      playTimer = setInterval(makeTick(get), 1000 / speed);
    }
  },

  stepForward() {
    const state = get();
    const lastSeq = lastSeqOf(state.events);
    const cur = state.cursor ?? lastSeq;
    const next = Math.min(cur + 1, lastSeq);
    set({ cursor: next >= lastSeq ? null : next });
  },

  stepBack() {
    const state = get();
    const lastSeq = lastSeqOf(state.events);
    const cur = state.cursor ?? lastSeq;
    const prev = Math.max(cur - 1, 0);
    set({ cursor: prev });
  },

  setConnection(connection) {
    set({ connection });
  },

  setError(error) {
    set({ error });
  },

  clearGap() {
    set({ gap: null });
  },

  reset() {
    clearPlayTimer();
    viewCache = null;
    set({
      gameId: null,
      token: null,
      viewer: null,
      meta: null,
      events: [],
      head: null,
      checkpoints: new Map(),
      mode: "live",
      cursor: null,
      connection: "idle",
      error: null,
      gap: null,
      playing: false,
      speed: 2,
    });
  },
}));
