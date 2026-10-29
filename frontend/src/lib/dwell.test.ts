// createDwell：可取消的 sleep——回放阅读停留在暂停 / 拖动时必须立刻结束。

import { afterEach, describe, expect, it, vi } from "vitest";
import { createDwell } from "./dwell";

afterEach(() => vi.useRealTimers());

describe("createDwell", () => {
  it("sleep 到点 resolve；cancel 让挂起的 sleep 立即 resolve", async () => {
    vi.useFakeTimers();
    const d = createDwell();
    let a = false;
    let b = false;
    void d.sleep(1000).then(() => {
      a = true;
    });
    vi.advanceTimersByTime(1000);
    await Promise.resolve();
    expect(a).toBe(true);
    void d.sleep(5000).then(() => {
      b = true;
    });
    d.cancel();
    await Promise.resolve();
    expect(b).toBe(true);
    // 取消后定时器已清掉：再推进时间不会再触发什么
    expect(vi.getTimerCount()).toBe(0);
  });
});
