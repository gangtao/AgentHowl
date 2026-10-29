// 倒计时 hook（从旧 SpeechBubble 搬出，发言台 / HUD 共用）：按服务端截止时间（秒）每秒刷新剩余秒数。
// deadline 为 null 时返回 null；now 可注入（测试）。

import { useEffect, useState } from "react";

export const defaultNow = (): number => Date.now() / 1000;

export function useCountdown(deadline: number | null, now: () => number = defaultNow): number | null {
  const [left, setLeft] = useState<number | null>(() =>
    deadline === null ? null : Math.max(0, Math.ceil(deadline - now())),
  );
  useEffect(() => {
    if (deadline === null) {
      setLeft(null);
      return;
    }
    const tick = (): void => setLeft(Math.max(0, Math.ceil(deadline - now())));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline, now]);
  return left;
}
