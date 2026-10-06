// 单个 HTMLAudioElement 的薄封装（issue #103）：零 IO 以外唯一的「真浏览器」依赖，
// 便于在 store/voice.ts 的测试里用 setPlayer() 注入假对象。play() 在 ended/error 均 resolve
// （出错不该卡住队列——下一句照常播），stop() 暂停当前播放并 resolve 挂起的 play()。

export interface AudioPlayer {
  play(url: string): Promise<void>;
  stop(): void;
}

export function createAudioPlayer(): AudioPlayer {
  const el = typeof Audio !== "undefined" ? new Audio() : null;
  let pending: (() => void) | null = null;
  const settle = (): void => {
    const r = pending;
    pending = null;
    r?.();
  };
  if (el) {
    el.addEventListener("ended", settle);
    el.addEventListener("error", settle);
  }
  return {
    play(url) {
      if (!el) return Promise.resolve();
      settle(); // 上一句若还挂着（理论上不该发生），先结清，避免悬空 resolve
      return new Promise<void>((resolve) => {
        pending = resolve;
        el.src = url;
        void el.play().catch(settle);
      });
    },
    stop() {
      if (el) {
        el.pause();
        el.removeAttribute("src");
      }
      settle();
    },
  };
}
