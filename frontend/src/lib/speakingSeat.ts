// 「正在发言」的座位（发言台与座位状态行共用）：正在出声的座位 > 直播开语音时「发言事件已到、音频还没播完」
// 的最后一位 > 轮到谁。纯函数，零过滤（只看 state / 事件 / 语音播放态，不看视角）。
//
// 为什么需要中间那条：引擎提交发言后立刻把发言权交给下一位，而配音要先合成、再分段推送、再播放，
// 事件到达与音频开播之间有几秒空档，分段之间也可能有空档；只看 voicingSeq 会在这些空档里把发言台
// 跳到下一位的「正在组织语言…」再跳回来（用户反馈：0号正在发言，突然跳出 2号）。服务端本就等音频播完才让
// 下一位开始，所以在那句音频播完（finishedSeq ≥ seq）之前，台上就该一直是这一位。

export interface SpeakingInput {
  /** 正在出声的事件的 actor：座位 / "GM"（旁白等无座位事件）/ null（没在出声）。 */
  voicingActor: number | "GM" | null;
  /** state 里轮到谁（currentSpeaker）。 */
  turnSpeaker: number | null;
  /** 事件流里最后一条发言 / 遗言。 */
  lastSpeech: { seq: number; actor: number | null } | null;
  voice: {
    enabled: boolean;
    /** 本局收到过音频帧或清单非空。 */
    available: boolean;
    /** 已播完（或被打断放弃）的最大配音 seq。 */
    finishedSeq: number | null;
  };
  /** 直播；回放由 replayGate 顺序播放，不存在这种空档。 */
  live: boolean;
}

export function speakingSeat(i: SpeakingInput): number | null {
  if (typeof i.voicingActor === "number") return i.voicingActor;
  if (
    i.live &&
    i.voice.enabled &&
    i.voice.available &&
    i.lastSpeech !== null &&
    i.lastSpeech.actor !== null &&
    (i.voice.finishedSeq ?? -1) < i.lastSpeech.seq
  ) {
    return i.lastSpeech.actor;
  }
  if (i.voicingActor === "GM") return null;
  return i.turnSpeaker;
}
