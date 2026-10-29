// 座位状态行（规格 §4.1 / R11）：圆桌 / 卡牌座位名字下方那一行——「圆桌只留状态」。
// 纯函数，零 React。零过滤：全部取自 state 与 GamePage 传入的「正在出声者」「票箱」，不看 viewer。
//
// 「正在出声优先」与 #185 同一症结：引擎提交发言后立刻把 speech_idx 推到下一位，而配音还在播上一位，
// 若只看 speech_idx，上一位会被标成「已发言」、下一位被标成「发言中」。speaking 由 GamePage 传入
// （voicingActor ?? turnSpeaker），这里只负责按它判定。

import type { GameState } from "../engine/types";

export type SeatStatusTone = "now" | "done" | "wait" | "dead" | "none";

export interface SeatStatus {
  text: string;
  tone: SeatStatusTone;
}

export interface SeatStatusInput {
  speaking: number | null;
  /** voter → target（null = 弃票）；非投票阶段传 {}。 */
  voteTargets: Record<number, number | null>;
}

const NONE: SeatStatus = { text: "", tone: "none" };

type Kind = "speech" | "vote" | "candidacy" | "other";

function kindOf(state: GameState): Kind {
  switch (state.phase) {
    case "DAY_SPEECH":
    case "LAST_WORDS":
      return "speech";
    case "VOTE":
    case "VOTE_PK":
      return "vote";
    case "SHERIFF_ELECTION":
    case "SHERIFF_PK":
      if (state.election_stage === "speech") return "speech";
      if (state.election_stage === "vote") return "vote";
      if (state.election_stage === "candidacy") return "candidacy";
      return "other";
    default:
      return "other";
  }
}

/** 投票类阶段里站在 PK 台上的座位（他们不投票）。 */
function pkCandidates(state: GameState): readonly number[] {
  if (state.phase === "VOTE_PK") return state.vote_candidates;
  if (state.phase === "SHERIFF_PK") return state.sheriff_candidates;
  return [];
}

export function seatStatus(state: GameState, seat: number, input: SeatStatusInput): SeatStatus {
  const player = state.players.find((p) => p.seat === seat);
  if (player === undefined) return NONE;
  if (!player.alive) return { text: "出局", tone: "dead" };

  switch (kindOf(state)) {
    case "speech": {
      const idx = state.speech_order.indexOf(seat);
      if (idx === -1) return NONE;
      if (seat === input.speaking) return { text: "发言中", tone: "now" };
      return idx < state.speech_idx
        ? { text: "已发言", tone: "done" }
        : { text: "待发言", tone: "wait" };
    }
    case "vote": {
      if (pkCandidates(state).includes(seat)) return { text: "PK 中", tone: "now" };
      if (!player.can_vote) return { text: "无票", tone: "none" };
      if (seat in input.voteTargets) {
        const target = input.voteTargets[seat];
        return target === null || target === undefined
          ? { text: "弃票", tone: "done" }
          : { text: `已投 ${target}号`, tone: "done" };
      }
      return { text: "未投", tone: "wait" };
    }
    case "candidacy": {
      if (!state.sheriff_declared.includes(seat)) return NONE;
      return state.sheriff_withdrawn.includes(seat)
        ? { text: "退水", tone: "done" }
        : { text: "上警", tone: "now" };
    }
    default:
      return NONE;
  }
}
