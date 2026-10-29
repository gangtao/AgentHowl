import { beforeEach, describe, expect, it } from "vitest";
import { AutoplayBlockedError } from "../lib/audioPlayer";
import { firstPendingSeq, useVoice } from "./voice";

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
    useVoice.setState({
      enabled: false,
      available: false,
      playing: null,
      queue: [],
      voicingSeq: null,
      ended: new Set(),
      finishedSeq: null,
    });
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

  it("clear() 默认不改 available；clear(true) 把 available 清回 false（fix round 3）", () => {
    useVoice.setState({ available: true });
    useVoice.getState().clear();
    expect(useVoice.getState().available).toBe(true);
    useVoice.getState().clear(true);
    expect(useVoice.getState().available).toBe(false);
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

  it("voicingSeq 从首段开播到末段播完保持不变，分段之间不闪 null；清空后为 null", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().setEnabled(true);
    expect(useVoice.getState().voicingSeq).toBeNull();
    useVoice.getState().enqueue({ seq: 6, part: 0, url: "/a/6/0", duration: 1 });
    useVoice.getState().enqueue({ seq: 6, part: 1, url: "/a/6/1", duration: 1 });
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBe(6);
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBe(6); // 第二段开播，仍是 6
    useVoice.getState().markEnd(6); // 服务端：分段推完
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBeNull();
    // 回放路径同样
    const done = useVoice.getState().playSeq("g", 9, [{ part: 0, duration: 1 }], undefined);
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBe(9);
    useVoice.getState().clear();
    await done;
    expect(useVoice.getState().voicingSeq).toBeNull();
  });
  it("setEnabled 写 localStorage", () => {
    useVoice.getState().setEnabled(true);
    expect(localStorage.getItem("agenthowl.voice")).toBe("1");
  });
});

describe("useVoice.enqueue 边界", () => {
  beforeEach(() => {
    useVoice.setState({
      enabled: false,
      available: false,
      playing: null,
      queue: [],
      voicingSeq: null,
      ended: new Set(),
      finishedSeq: null,
    });
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

describe("useVoice 自动播放被拒（issue #108）", () => {
  beforeEach(() => {
    useVoice.setState({
      enabled: false,
      available: false,
      playing: null,
      queue: [],
      blocked: false,
      voicingSeq: null,
      ended: new Set(),
      finishedSeq: null,
    });
  });
  it("直播队列：play 抛 AutoplayBlockedError → 关闭开关、blocked=true、不写 localStorage", async () => {
    localStorage.setItem("agenthowl.voice", "1");
    useVoice.getState().setPlayer({
      play: () => Promise.reject(new AutoplayBlockedError()),
      stop: () => undefined,
    });
    useVoice.getState().setEnabled(true);
    useVoice.getState().enqueue({ seq: 1, part: 0, url: "/a/1/0", duration: 1 });
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().enabled).toBe(false);
    expect(useVoice.getState().blocked).toBe(true);
    expect(useVoice.getState().playing).toBeNull();
    expect(localStorage.getItem("agenthowl.voice")).toBe("1");
    useVoice.getState().setEnabled(true); // 用户再点一次
    expect(useVoice.getState().blocked).toBe(false);
  });
  it("回放 playSeq 同样处理，promise 正常 resolve", async () => {
    useVoice.getState().setPlayer({
      play: () => Promise.reject(new AutoplayBlockedError()),
      stop: () => undefined,
    });
    useVoice.getState().setEnabled(true);
    await useVoice.getState().playSeq("g", 3, [{ part: 0, duration: 1 }], undefined);
    expect(useVoice.getState().enabled).toBe(false);
    expect(useVoice.getState().blocked).toBe(true);
  });

  it("分段之间下一段还没到：voicingSeq 不清空；收到 speech_audio_end 且全部播完才清，并记 finishedSeq", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().setEnabled(true);
    useVoice.getState().enqueue({ seq: 6, part: 0, url: "/a/6/0", duration: 1 });
    await Promise.resolve();
    p.finishOne(); // 第 0 段播完，第 1 段还在合成
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().playing).toBeNull();
    expect(useVoice.getState().voicingSeq).toBe(6);
    expect(useVoice.getState().finishedSeq).toBeNull();
    useVoice.getState().enqueue({ seq: 6, part: 1, url: "/a/6/1", duration: 1 });
    await Promise.resolve();
    useVoice.getState().markEnd(6); // 服务端：这句一共 2 段，都推完了
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBeNull();
    expect(useVoice.getState().finishedSeq).toBe(6);
  });

  it("speech_audio_end 在最后一段播完之后才到：到达时立刻收尾", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().setEnabled(true);
    useVoice.getState().enqueue({ seq: 7, part: 0, url: "/a/7/0", duration: 1 });
    await Promise.resolve();
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(useVoice.getState().voicingSeq).toBe(7);
    useVoice.getState().markEnd(7);
    expect(useVoice.getState().voicingSeq).toBeNull();
    expect(useVoice.getState().finishedSeq).toBe(7);
    // 没有任何音频帧就收到 end（不该发生，防御）：finishedSeq 仍推进
    useVoice.getState().markEnd(8);
    expect(useVoice.getState().finishedSeq).toBe(8);
  });

  it("markBegin 记下待播 seq；firstPendingSeq 给出最早未播完的；播完 / clear 后释放（issue #193）", async () => {
    const p = fakePlayer();
    useVoice.getState().setPlayer(p);
    useVoice.getState().setEnabled(true);
    expect(firstPendingSeq(useVoice.getState())).toBeNull();
    useVoice.getState().markBegin(40);
    expect(firstPendingSeq(useVoice.getState())).toBe(40);
    // 还没有任何分段到达也算待播（合成中）
    useVoice.getState().enqueue({ seq: 40, part: 0, url: "/a/40/0", duration: 1 });
    await Promise.resolve();
    useVoice.getState().markEnd(40);
    expect(firstPendingSeq(useVoice.getState())).toBe(40); // 还在播
    p.finishOne();
    await Promise.resolve();
    await Promise.resolve();
    expect(firstPendingSeq(useVoice.getState())).toBeNull();
    expect(useVoice.getState().finishedSeq).toBe(40);
    // 两句先后 begin：最早的那句是门
    useVoice.getState().markBegin(41);
    useVoice.getState().markBegin(43);
    expect(firstPendingSeq(useVoice.getState())).toBe(41);
    useVoice.getState().markEnd(41); // 一段都没合成出来（parts=0）→ 立即放行
    expect(firstPendingSeq(useVoice.getState())).toBe(43);
    useVoice.getState().clear(); // 关语音 / 重连：全部释放
    expect(firstPendingSeq(useVoice.getState())).toBeNull();
  });
});
