import { beforeEach, describe, expect, it } from "vitest";
import { useVoice } from "./voice";

function fakePlayer() {
  const calls: string[] = [];
  let resolvers: (() => void)[] = [];
  return {
    calls,
    finishOne() {
      resolvers.shift()?.();
    },
    play(url: string) {
      calls.push(url);
      return new Promise<void>((r) => resolvers.push(r));
    },
    stop() {
      resolvers.forEach((r) => r());
      resolvers = [];
    },
  };
}

describe("useVoice", () => {
  beforeEach(() => {
    useVoice.setState({ enabled: false, available: false, playing: null, queue: [] });
  });

  it("关闭时入队不播放但标记 available；开启后新帧按 (seq, part) 顺序播放", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().enqueue({ seq: 5, part: 0, url: "/a/5/0", duration: 1 });
    expect(useVoice.getState().available).toBe(true);
    expect(p.calls).toEqual([]);
    useVoice.getState().setEnabled(true);
    useVoice.getState().enqueue({ seq: 6, part: 0, url: "/a/6/0", duration: 1 });
    useVoice.getState().enqueue({ seq: 6, part: 1, url: "/a/6/1", duration: 1 });
    await Promise.resolve();
    expect(p.calls).toEqual(["/a/6/0"]);
    expect(useVoice.getState().playing).toEqual({ seq: 6, part: 0 });
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(p.calls).toEqual(["/a/6/0", "/a/6/1"]);
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().playing).toBeNull();
  });

  it("playSeq 顺序播放全部 part；关闭时立即 resolve；clear 停止", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    await useVoice.getState().playSeq("g", 9, [{ part: 0, duration: 1 }], undefined);
    expect(p.calls).toEqual([]);
    useVoice.getState().setEnabled(true);
    const done = useVoice
      .getState()
      .playSeq("g", 9, [{ part: 0, duration: 1 }, { part: 1, duration: 1 }], undefined);
    await Promise.resolve();
    expect(p.calls).toEqual(["/api/v1/games/g/audio/9/0"]);
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(p.calls[1]).toBe("/api/v1/games/g/audio/9/1");
    useVoice.getState().clear();
    await done;
  });

  it("playSeq 自取消（fix round 2）：新 seq 打断仍在播的旧 seq，不互相串台", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().setEnabled(true);

    // A 开始播 part0，还挂着没播完
    const doneA = useVoice
      .getState()
      .playSeq("g", 1, [{ part: 0, duration: 1 }, { part: 1, duration: 1 }], undefined);
    expect(p.calls).toEqual(["/api/v1/games/g/audio/1/0"]);
    expect(useVoice.getState().playing).toEqual({ seq: 1, part: 0 });

    // B 在 A 播完之前开始：A 挂起的 play() promise 被 B 的 clear()→player.stop() 结清，
    // 但 A 的 generation 已经不是最新，续行后直接退出——不会再播 A 的 part1。
    const doneB = useVoice
      .getState()
      .playSeq("g", 2, [{ part: 0, duration: 1 }, { part: 1, duration: 1 }], undefined);
    await Promise.resolve();
    await Promise.resolve();
    expect(p.calls).toEqual(["/api/v1/games/g/audio/1/0", "/api/v1/games/g/audio/2/0"]);
    expect(useVoice.getState().playing).toEqual({ seq: 2, part: 0 });

    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(p.calls[2]).toBe("/api/v1/games/g/audio/2/1");
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();

    expect(useVoice.getState().playing).toBeNull();
    // A 从未播出过 part1：全程只有 A 的 part0 + B 的两个 part。
    expect(p.calls).toEqual([
      "/api/v1/games/g/audio/1/0",
      "/api/v1/games/g/audio/2/0",
      "/api/v1/games/g/audio/2/1",
    ]);
    await doneA;
    await doneB;
  });

  it("setEnabled 写 localStorage", () => {
    useVoice.getState().setEnabled(true);
    expect(localStorage.getItem("agenthowl.voice")).toBe("1");
  });
});

describe("useVoice.enqueue 边界", () => {
  beforeEach(() => {
    useVoice.setState({ enabled: false, available: false, playing: null, queue: [] });
  });

  it("关闭期间连续入队只保留最近 1 条", () => {
    useVoice.getState().enqueue({ seq: 1, part: 0, url: "/a/1/0", duration: 1 });
    useVoice.getState().enqueue({ seq: 2, part: 0, url: "/a/2/0", duration: 1 });
    expect(useVoice.getState().queue).toEqual([{ seq: 2, part: 0, url: "/a/2/0", duration: 1 }]);
  });

  it("开启瞬间丢弃关闭期间积压的旧句，不补播", () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().enqueue({ seq: 1, part: 0, url: "/a/1/0", duration: 1 });
    useVoice.getState().setEnabled(true);
    expect(useVoice.getState().queue).toEqual([]);
    expect(p.calls).toEqual([]);
  });
});
