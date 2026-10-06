// 语音播放 store（issue #103）：零过滤——只播放服务端推来 / 列出的 URL。
// 两条播放路径共用同一个播放器单例：
//   - 直播：api/ws.ts 把 speech_audio 帧 enqueue() 进来，按 (seq, part) 顺序（服务端已保证顺序）播放；
//   - 回放：store/game.ts 的 replayGate 调 playSeq()，顺序播完某个 seq 的全部分段再放行回放时钟前进。
// 本文件零 IO（除 lib/audioPlayer.ts 外）；浏览器自动播放策略要求 enabled 只能在用户手势里打开
// （VoiceToggle 的 onClick），不能默认开启或在无点击的情况下置真。

import { create } from "zustand";
import { audioUrl } from "../api/rest";
import type { AudioPartInfo } from "../api/rest";
import { createAudioPlayer } from "../lib/audioPlayer";
import type { AudioPlayer } from "../lib/audioPlayer";

const STORAGE_KEY = "agenthowl.voice";

function readEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false; // 隐私模式等场景下 localStorage 不可用：退化为默认关闭
  }
}

export interface AudioQueueItem {
  seq: number;
  part: number;
  url: string;
  duration: number;
}

interface VoiceState {
  enabled: boolean;
  /** 收到过帧或清单非空即为 true；VoiceToggle 据此决定是否渲染（没有音频就没有开关）。 */
  available: boolean;
  playing: { seq: number; part: number } | null;
  queue: AudioQueueItem[];

  /** 测试注入假播放器；生产环境不调用，播放器按需懒建。 */
  setPlayer(p: AudioPlayer): void;
  setEnabled(v: boolean): void;
  markAvailable(): void;
  enqueue(item: AudioQueueItem): void;
  /** 停播 + 清队列（不改变 enabled，也不改变 available）。 */
  clear(): void;
  /** 回放用：顺序播放某个 seq 的全部分段；enabled=false 时立即 resolve。 */
  playSeq(gameId: string, seq: number, parts: readonly AudioPartInfo[], token?: string): Promise<void>;
}

/** 懒建的单例播放器；测试用 setPlayer() 换成假对象。 */
let player: AudioPlayer | null = null;

function getPlayer(): AudioPlayer {
  if (player === null) player = createAudioPlayer();
  return player;
}

/** clear() 自增代际：仍在 playSeq 的 for 循环 await 中等待的旧调用，恢复执行后发现代际已变
 * 就提前返回，不再继续播放已经被打断的序列。 */
let generation = 0;

/** 队列消费：用 .then 递归而非 async/await，使 enqueue() 调用内就能同步把首条送进
 * player.play()——这样调用方（含测试）在 await 前已能看到第一次 play() 调用。 */
function drain(get: () => VoiceState, set: (partial: Partial<VoiceState>) => void): void {
  const { enabled, playing, queue } = get();
  if (!enabled || playing !== null || queue.length === 0) return;
  const item = queue[0] as AudioQueueItem;
  set({ queue: queue.slice(1), playing: { seq: item.seq, part: item.part } });
  const gen = generation;
  getPlayer()
    .play(item.url)
    .then(() => {
      if (gen !== generation) return; // 期间被 clear() 打断，播放态已经被重置过
      set({ playing: null });
      drain(get, set);
    });
}

export const useVoice = create<VoiceState>((set, get) => ({
  enabled: readEnabled(),
  available: false,
  playing: null,
  queue: [],

  setPlayer(p) {
    player = p;
  },

  setEnabled(v) {
    try {
      localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
    } catch {
      // 同 readEnabled：写不进去就只记在本次会话里
    }
    set({ enabled: v });
    if (v) {
      // 开启瞬间清空积压队列，避免把关闭期间错过的一堆旧句一次性补播出来
      set({ queue: [] });
    } else {
      get().clear();
    }
  },

  markAvailable() {
    if (!get().available) set({ available: true });
  },

  enqueue(item) {
    set({ available: true });
    if (!get().enabled) {
      // 关闭时只保留最近 1 条：开启后按 setEnabled 的逻辑整条丢弃，这里保留只是为了
      // 让「关闭 → 开启」之间始终有个确定的最新状态，不是为了补播。
      set({ queue: [item] });
      return;
    }
    set({ queue: [...get().queue, item] });
    drain(get, set);
  },

  clear() {
    generation += 1;
    player?.stop();
    set({ queue: [], playing: null });
  },

  async playSeq(gameId, seq, parts, token) {
    if (!get().enabled) return;
    const gen = generation;
    for (const part of parts) {
      if (gen !== generation) return;
      set({ playing: { seq, part: part.part } });
      const base = audioUrl(gameId, seq, part.part);
      const url = token ? `${base}?token=${encodeURIComponent(token)}` : base;
      await getPlayer().play(url);
      if (gen !== generation) return;
    }
    set({ playing: null });
  },
}));
