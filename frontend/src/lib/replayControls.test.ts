import { describe, expect, it, vi } from "vitest";
import { replayControls } from "./replayControls";
import type { ReplayStoreControls, VoiceClearControl } from "./replayControls";

function fakeStore(): ReplayStoreControls & Record<keyof ReplayStoreControls, ReturnType<typeof vi.fn>> {
  return {
    setCursor: vi.fn(),
    play: vi.fn(),
    pause: vi.fn(),
    setSpeed: vi.fn(),
    stepForward: vi.fn(),
    stepBack: vi.fn(),
  };
}

function fakeVoice(): VoiceClearControl & { clear: ReturnType<typeof vi.fn> } {
  return { clear: vi.fn() };
}

describe("replayControls（issue #103 fix round 2）", () => {
  it("onPause 先 voice.clear() 再 store.pause()", () => {
    const store = fakeStore();
    const voice = fakeVoice();
    const controls = replayControls(store, voice);

    controls.onPause();

    expect(voice.clear).toHaveBeenCalledTimes(1);
    expect(store.pause).toHaveBeenCalledTimes(1);
    // 顺序要对：clear 必须先于 pause，否则旧 playSeq 可能在 pause() 之后才被打断
    expect(voice.clear.mock.invocationCallOrder[0]).toBeLessThan(
      store.pause.mock.invocationCallOrder[0]!,
    );
  });

  it("onCursor/onStep/onLive 都先 clear 再操作游标", () => {
    const store = fakeStore();
    const voice = fakeVoice();
    const controls = replayControls(store, voice);

    controls.onCursor(7);
    expect(voice.clear).toHaveBeenCalledTimes(1);
    expect(store.setCursor).toHaveBeenCalledWith(7);

    controls.onStep(1);
    expect(voice.clear).toHaveBeenCalledTimes(2);
    expect(store.stepForward).toHaveBeenCalledTimes(1);
    expect(store.stepBack).not.toHaveBeenCalled();

    controls.onStep(-1);
    expect(voice.clear).toHaveBeenCalledTimes(3);
    expect(store.stepBack).toHaveBeenCalledTimes(1);

    controls.onLive();
    expect(voice.clear).toHaveBeenCalledTimes(4);
    expect(store.setCursor).toHaveBeenLastCalledWith(null);
  });

  it("onPlay/onSpeed 不打断配音：继续播放或调速不是跳到别的 seq", () => {
    const store = fakeStore();
    const voice = fakeVoice();
    const controls = replayControls(store, voice);

    controls.onPlay();
    controls.onSpeed(4);

    expect(voice.clear).not.toHaveBeenCalled();
    expect(store.play).toHaveBeenCalledTimes(1);
    expect(store.setSpeed).toHaveBeenCalledWith(4);
  });
});
