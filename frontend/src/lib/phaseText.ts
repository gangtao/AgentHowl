// 顶栏与阶段木牌的文案（规格 §4.1）：纯函数，只收 state / events / 游标 / 连接态，不收 viewer。

import { DIRECTION_ZH, ELECTION_STAGE_ZH, PHASE_ZH, WINNER_ZH, isNight } from "../engine/phases";
import { aliveSeats, effectiveSpeechDirection, voteTally } from "../engine/select";
import type { Event, GameState, Phase, VoteResultPayload } from "../engine/types";
import type { ConnectionState, PlaybackMode } from "../store/game";

const NIGHT_ROLE_ZH: Partial<Record<Phase, string>> = {
  NIGHT_GUARD: "守卫",
  NIGHT_WEREWOLF: "狼人",
  NIGHT_WITCH: "女巫",
  NIGHT_SEER: "预言家",
  NIGHT_HUNTER_CONFIRM: "猎人",
};

function nightName(phase: Phase): string {
  if (phase === "NIGHT") return "夜晚";
  return (PHASE_ZH[phase] ?? phase).replace(/^夜晚 · /, "");
}

function lastExileVotes(events: readonly Event[], seat: number): number | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i] as Event;
    if (e.type === "VOTE_RESULT") {
      const hit = (e.payload as VoteResultPayload).tally.find(([t]) => t === seat);
      return hit ? hit[1] : null;
    }
  }
  return null;
}

export function plaqueLines(
  state: GameState,
  events: readonly Event[],
  cursor: number | null,
  total: number,
): { title: string; sub: string } {
  const phase = state.phase;
  const alive = `${aliveSeats(state).length}/${state.players.length} 存活`;
  let title: string;
  let sub: string;

  if (isNight(phase)) {
    title = `第 ${state.round} 夜 · ${nightName(phase)}`;
    const role = NIGHT_ROLE_ZH[phase];
    sub = role ? `天黑请闭眼 · ${role}请睁眼 · ${alive}` : `天黑请闭眼 · ${alive}`;
  } else if (phase === "GAME_OVER") {
    title = `第 ${state.round} 轮 · 游戏结束`;
    sub = state.winner !== null ? `${WINNER_ZH[state.winner] ?? state.winner}胜` : "平局";
  } else {
    title = `第 ${state.round} 轮 · ${PHASE_ZH[phase] ?? phase}`;
    const sheriff = state.sheriff_seat !== null ? `警长 ${state.sheriff_seat}号` : "无警长";
    // 本轮实际方向（偶数轮换手），不是警长定下的基准方向——否则偶数轮和 speech_order 对不上号
    const effective = effectiveSpeechDirection(state);
    const direction = effective !== null ? (DIRECTION_ZH[effective] ?? "顺时针") : "顺时针";
    const weight =
      typeof state.config.sheriff.vote_weight === "number" ? state.config.sheriff.vote_weight : 1.5;
    switch (phase) {
      case "DAY_SPEECH":
        sub = `${sheriff} · ${direction} · ${alive}`;
        break;
      case "LAST_WORDS": {
        const seat = state.day_exiled;
        if (seat !== null) {
          const n = lastExileVotes(events, seat);
          sub = `${seat}号 被公投放逐${n !== null ? ` · ${n} 票` : ""} · ${alive}`;
        } else {
          sub = `遗言 · ${alive}`;
        }
        break;
      }
      case "SHERIFF_ELECTION":
        sub = `${ELECTION_STAGE_ZH[state.election_stage]} · ${state.sheriff_declared.length} 人上警 · ${alive}`;
        break;
      case "SHERIFF_PK": {
        const [a, b] = state.sheriff_candidates;
        const pair = a !== undefined && b !== undefined ? `${a}号 vs ${b}号 · ` : "";
        sub = `${ELECTION_STAGE_ZH[state.election_stage]} · ${pair}${alive}`;
        break;
      }
      case "VOTE": {
        const { votes } = voteTally(state, events);
        const voters = state.players.filter((p) => p.alive && p.can_vote).length;
        sub = `已投 ${Object.keys(votes).length}/${Math.max(voters, Object.keys(votes).length)} · 警长 ${weight} 票 · ${alive}`;
        break;
      }
      case "VOTE_PK": {
        const { votes } = voteTally(state, events);
        const onStage = new Set(state.vote_candidates);
        const voters = state.players.filter(
          (p) => p.alive && p.can_vote && !onStage.has(p.seat),
        ).length;
        const pair = state.vote_candidates.map((s) => `${s}号`).join(" / ");
        sub = `平票 ${pair} · PK 双方不投票 · 已投 ${Object.keys(votes).length}/${Math.max(voters, Object.keys(votes).length)}`;
        break;
      }
      case "EXILE":
        sub =
          state.day_exiled !== null
            ? `${state.day_exiled}号 被放逐 · ${alive}`
            : `无人出局 · ${alive}`;
        break;
      case "HUNTER_SHOOT":
        sub =
          state.pending_hunter !== null
            ? `${state.pending_hunter}号 翻牌 · 猎人 · 可带走一名存活玩家`
            : `猎人开枪 · ${alive}`;
        break;
      case "LOBBY":
        sub = "等待开局";
        break;
      default:
        sub = alive;
    }
  }

  if (cursor !== null && cursor !== total) sub = `${sub} · 回放到 seq ${cursor} / ${total}`;
  return { title, sub };
}

/** 顶栏居中状态：winner 是这局的最终胜方（head），不是回放游标处 state 的 winner。 */
export function statusText(
  winner: string | null,
  mode: PlaybackMode,
  connection: ConnectionState,
  totalSeq: number,
  over: boolean,
): { text: string; tone: "live" | "replay" | "over" | "warn" } {
  if (over) {
    const label = winner !== null ? `${WINNER_ZH[winner] ?? winner}胜` : "平局";
    return { text: `游戏结束：${label}`, tone: "over" };
  }
  if (mode === "replay") return { text: `▶ 回放 · ${totalSeq} 条事件`, tone: "replay" };
  if (connection === "open") return { text: `● 直播 · seq ${totalSeq}`, tone: "live" };
  if (connection === "connecting") return { text: "连接中…", tone: "warn" };
  if (connection === "closed" || connection === "error") {
    return { text: "连接已断开 · 重连中", tone: "warn" };
  }
  return { text: "未连接", tone: "warn" };
}
