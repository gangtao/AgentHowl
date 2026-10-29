// speakingSeat：发言台 / 座位状态行的「正在发言」座位——正在出声 > 音频未播完的最后一句 > 轮到谁。

import { describe, expect, it } from "vitest";
import { speakingSeat, type SpeakingInput } from "./speakingSeat";

const base: SpeakingInput = {
  voicingActor: null,
  turnSpeaker: 2,
  lastSpeech: { seq: 40, actor: 0 },
  voice: { enabled: true, available: true, finishedSeq: 39 },
  live: true,
};

describe("speakingSeat", () => {
  it("正在出声的座位优先", () => {
    expect(speakingSeat({ ...base, voicingActor: 0 })).toBe(0);
  });

  it("直播开语音：0号的发言事件已到、音频还没播完 → 仍是 0号，不跳到轮到的 2号", () => {
    expect(speakingSeat(base)).toBe(0);
    // 旁白正在播（voicingActor GM）时同样保持 0号
    expect(speakingSeat({ ...base, voicingActor: "GM" })).toBe(0);
  });

  it("那句音频播完（finishedSeq ≥ seq）→ 轮到谁", () => {
    expect(speakingSeat({ ...base, voice: { ...base.voice, finishedSeq: 40 } })).toBe(2);
  });

  it("语音关 / 本局无音频 / 回放 → 不等音频，直接轮到谁", () => {
    expect(speakingSeat({ ...base, voice: { ...base.voice, enabled: false } })).toBe(2);
    expect(speakingSeat({ ...base, voice: { ...base.voice, available: false } })).toBe(2);
    expect(speakingSeat({ ...base, live: false })).toBe(2);
  });

  it("旁白在播且无待播发言 → null（不高亮任何座位，issue #110）", () => {
    expect(
      speakingSeat({ ...base, voicingActor: "GM", voice: { ...base.voice, finishedSeq: 40 } }),
    ).toBeNull();
  });

  it("没有任何发言事件 → 轮到谁", () => {
    expect(speakingSeat({ ...base, lastSpeech: null })).toBe(2);
  });
});
