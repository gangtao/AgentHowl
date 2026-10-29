// 桌心内容选择器（规格 §4.4）：按阶段决定圆桌中央画什么。纯函数，只收 state / events / 本人的
// YourTurn / 已选目标；不收 viewer——狼队密议只在 state 里有 wolf_proposals 时出现，观众的 state 没有。
//
// 匹配顺序即规格表格顺序：none → wolfCouncil → witchTarget → crystal → crosshair → gmNotes → moon →
// tally / pkStage → speechProgress → campfire。

import type { YourTurn } from "../api/player";
import { PHASE_ZH, isNight } from "../engine/phases";
import {
  currentSpeaker,
  nightSummary,
  sheriffVoteTally,
  voteTally,
  type NightSummaryRow,
} from "../engine/select";
import type { Event, GameState, RoleType, VoteResultPayload } from "../engine/types";
import { townNews } from "./village";

export interface StageInput {
  state: GameState;
  /** 已按回放游标截断的事件流。 */
  events: readonly Event[];
  prompt?: YourTurn | null;
  selectedTarget?: number | null;
  mode: "live" | "replay";
  myRole?: RoleType | null;
}

export interface TallyRow {
  target: number;
  name: string;
  votes: number;
  from: number[];
}

export interface PkSide {
  seat: number;
  name: string;
  votes: number;
}

export type StageContent =
  | { kind: "none" }
  | {
      kind: "wolfCouncil";
      proposals: { seat: number; target: number | null }[];
      round: number;
      hint: string;
    }
  | {
      kind: "witchTarget";
      seat: number;
      name: string;
      antidote: boolean | null;
      poison: boolean | null;
    }
  | { kind: "crystal"; seat: number }
  | { kind: "crosshair"; seat: number }
  | { kind: "moon"; sub: string }
  | {
      kind: "tally";
      cast: number;
      voters: number;
      rows: TallyRow[];
      waiting: number[];
      election: boolean;
    }
  | { kind: "pkStage"; a: PkSide; b: PkSide; cast: number; voters: number }
  | {
      kind: "speechProgress";
      /** 村镇公告「昨夜」行：「平安夜」/「3号、7号 死亡」，没有则 null。 */
      lastNight: string | null;
      /** 上一轮票型「4号 ·4 ｜ 8号 ·2」，没有则 null。 */
      lastTally: string | null;
      done: number;
      total: number;
      /** 当前发言人之后的下一位；最后一位时 null。 */
      next: number | null;
    }
  | { kind: "gmNotes"; round: number; rows: NightSummaryRow[] }
  | { kind: "campfire"; note: string };

const SPEECH_PHASES = new Set(["DAY_SPEECH", "LAST_WORDS", "SHERIFF_PK", "SHERIFF_ELECTION"]);

function nameOf(state: GameState, seat: number): string {
  return state.players.find((p) => p.seat === seat)?.display_name ?? "";
}

function boolOrNull(v: unknown): boolean | null {
  return typeof v === "boolean" ? v : null;
}

/** 本轮票箱 → 按被投者分组的行（含投票人列表）。 */
function groupRows(
  state: GameState,
  votes: Record<number, number | null>,
  tally: [number, number][],
): TallyRow[] {
  return tally.map(([target, n]) => ({
    target,
    name: nameOf(state, target),
    votes: n,
    from: Object.entries(votes)
      .filter(([, t]) => t === target)
      .map(([v]) => Number(v))
      .sort((a, b) => a - b),
  }));
}

/** 上一轮 VOTE_RESULT 的票型一行：`4号 ·4 ｜ 8号 ·2`（投票人在对局记录里，这里不重复）；没有则 null。 */
function lastVoteTally(events: readonly Event[]): string | null {
  let last: VoteResultPayload | null = null;
  for (const e of events) {
    if (e.type === "VOTE_RESULT") last = e.payload as VoteResultPayload;
  }
  if (last === null || last.tally.length === 0) return null;
  return last.tally.map(([target, n]) => `${target}号 ·${n}`).join(" ｜ ");
}

function campfireNote(state: GameState): string {
  if (state.phase === "LOBBY") return "等待开局";
  if (state.phase === "DEATH_ANNOUNCE") return "公布死讯";
  if (state.phase === "SHERIFF_ELECTION" && state.election_stage === "candidacy") {
    return `上警报名中 · 已上警 ${state.sheriff_declared.length} 人`;
  }
  return PHASE_ZH[state.phase] ?? state.phase;
}

export function stageContent(input: StageInput): StageContent {
  const { state, events, prompt = null, selectedTarget = null, mode, myRole = null } = input;
  const phase = state.phase;
  const night = isNight(phase);

  if (phase === "GAME_OVER") return { kind: "none" };

  // 狼队密议只在狼人行动子阶段；之后桌心让给女巫 / 预言家 / GM 手记。
  if (phase === "NIGHT_WEREWOLF" && Object.keys(state.wolf_proposals).length > 0) {
    const proposals = Object.entries(state.wolf_proposals)
      .map(([seat, target]) => ({ seat: Number(seat), target }))
      .sort((a, b) => a.seat - b.seat);
    return {
      kind: "wolfCouncil",
      proposals,
      round: state.wolf_kill_round,
      hint: "意见不一致会重新提案；第 2 轮仍不一致则空刀。",
    };
  }

  if (phase === "NIGHT_WITCH" && state.pending_night.wolf_target !== null) {
    const seat = state.pending_night.wolf_target;
    const priv = prompt?.observation.private ?? {};
    return {
      kind: "witchTarget",
      seat,
      name: nameOf(state, seat),
      antidote: boolOrNull(priv.antidote_available),
      poison: boolOrNull(priv.poison_available),
    };
  }

  if (phase === "NIGHT_SEER" && selectedTarget !== null && myRole === "SEER") {
    return { kind: "crystal", seat: selectedTarget };
  }

  if (
    (phase === "NIGHT_HUNTER_CONFIRM" || state.pending_hunter !== null) &&
    selectedTarget !== null &&
    myRole === "HUNTER"
  ) {
    return { kind: "crosshair", seat: selectedTarget };
  }

  if (night) {
    if (mode === "replay") {
      const rows = nightSummary(events, state.round);
      if (rows.length > 0) return { kind: "gmNotes", round: state.round, rows };
    }
    return { kind: "moon", sub: "请闭眼，等待其他角色行动" };
  }

  const sheriffVote = phase === "SHERIFF_ELECTION" && state.election_stage === "vote";
  const sheriffPkVote = phase === "SHERIFF_PK" && state.election_stage === "vote";
  const dayVote = phase === "VOTE" || phase === "VOTE_PK";
  if (sheriffVote || sheriffPkVote || dayVote) {
    const election = sheriffVote || sheriffPkVote;
    const { votes, tally } = election ? sheriffVoteTally(state, events) : voteTally(state, events);
    const candidates = election ? state.sheriff_candidates : state.vote_candidates;
    const pk = (phase === "VOTE_PK" || sheriffPkVote) && candidates.length === 2;
    const onStage = new Set(pk ? candidates : []);
    const voterSeats = state.players
      .filter((p) => p.alive && p.can_vote && !onStage.has(p.seat))
      .map((p) => p.seat);
    const cast = Object.keys(votes).length;
    const voters = Math.max(voterSeats.length, cast);
    if (pk) {
      const side = (seat: number): PkSide => ({
        seat,
        name: nameOf(state, seat),
        votes: tally.find(([t]) => t === seat)?.[1] ?? 0,
      });
      return {
        kind: "pkStage",
        a: side(candidates[0] as number),
        b: side(candidates[1] as number),
        cast,
        voters,
      };
    }
    return {
      kind: "tally",
      cast,
      voters,
      rows: groupRows(state, votes, tally),
      waiting: voterSeats.filter((s) => !(s in votes)),
      election,
    };
  }

  if (SPEECH_PHASES.has(phase)) {
    const electionNonSpeech =
      phase === "SHERIFF_ELECTION" && state.election_stage !== "speech";
    const speaker = electionNonSpeech ? null : currentSpeaker(state);
    if (speaker !== null) {
      const lastNight = townNews(events, state).find((r) => r.k === "昨夜")?.v ?? null;
      return {
        kind: "speechProgress",
        lastNight,
        lastTally: lastVoteTally(events),
        done: state.speech_idx,
        total: state.speech_order.length,
        next: state.speech_order[state.speech_idx + 1] ?? null,
      };
    }
  }

  return { kind: "campfire", note: campfireNote(state) };
}
