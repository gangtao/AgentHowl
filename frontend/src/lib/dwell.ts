// 可取消的 sleep：回放阅读停留挂在 replayGate 上，暂停 / 拖动 / 单步 / 回到直播时必须立刻结束，
// 否则恢复播放后时钟会一直卡到原定时长走完（最长 30 s）。

export interface Dwell {
  sleep(ms: number): Promise<void>;
  /** 让所有挂起的 sleep 立即 resolve，并清掉它们的定时器。 */
  cancel(): void;
}

export function createDwell(): Dwell {
  const pending = new Map<ReturnType<typeof setTimeout>, () => void>();
  return {
    sleep(ms) {
      return new Promise<void>((resolve) => {
        const id = setTimeout(() => {
          pending.delete(id);
          resolve();
        }, ms);
        pending.set(id, resolve);
      });
    },
    cancel() {
      for (const [id, resolve] of pending) {
        clearTimeout(id);
        resolve();
      }
      pending.clear();
    },
  };
}
