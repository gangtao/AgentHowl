// 纯选择器：输入 GameState + Event[] 前缀，产出 UI 可直接渲染的派生数据。零 IO、零 React。
// 文案尽量对齐 backend/app/cli/render.py::render_event；未在 render.py 显式处理的事件类型
// （如 WITCH_SAVED/WITCH_POISONED/NIGHT_RESOLVED 等）render.py 本身也走通用回退，
// 本文件在 nightSummary 中为它们写了更友好的专用文案——这是有意的偏离，详见 task-5-report。

import { ELECTION_STAGE_ZH, ROLE_ZH, isNight } from "./phases";
import type {
  BadgePassedPayload,
  DeathAnnouncedPayload,
  ElectionStageChangedPayload,
  Event,
  GameOverPayload,
  GameState,
  GuardProtectedPayload,
  HunterShotPayload,
  LastWordsPayload,
  NightResolvedPayload,
  PhaseChangedPayload,
  PlayerExiledPayload,
  PlayerSpokePayload,
  RoleType,
  RoundStartedPayload,
  SeerCheckedPayload,
  SheriffCandidacyPayload,
  SheriffElectedPayload,
  SheriffVoteCastPayload,
  SheriffVoteStartedPayload,
  VoteCastPayload,
  VoteResultPayload,
  WitchActedPayload,
  WolfKillDecidedPayload,
  WolfKillProposedPayload,
  WolfKillRevotePayload,
  WolfSelfDestructPayload,
} from "./types";

function seatsZh(xs: readonly number[]): string {
  return xs.length > 0 ? xs.map((s) => `${s}号`).join("、") : "无";
}

// ---- 存活 / 阵营 ----

export function aliveSeats(state: GameState): number[] {
  return state.players.filter((p) => p.alive).map((p) => p.seat);
}

export function wolfSeats(state: GameState): number[] {
  return state.players.filter((p) => p.faction === "WOLF").map((p) => p.seat);
}

export function currentSpeaker(state: GameState): number | null {
  return state.speech_order[state.speech_idx] ?? null;
}

// ---- 投票计票（对齐 backend engine.py::_tally_and_continue / resolver.count_votes） ----

export interface TallyResult {
  /** voter -> target（null=弃票），本轮 VOTE_CAST/SHERIFF_VOTE_CAST 重建的票箱。 */
  votes: Record<number, number | null>;
  /** (target_seat, weighted_votes) 按座位升序，对应 VoteResultPayload.tally。 */
  tally: [number, number][];
}

function eventsAfterLast(events: readonly Event[], startType: string): Event[] {
  let idx = -1;
  events.forEach((e, i) => {
    if (e.type === startType) idx = i;
  });
  return events.slice(idx + 1);
}

function castsFrom(events: readonly Event[], castType: string): Record<number, number | null> {
  const votes: Record<number, number | null> = {};
  for (const e of events) {
    if (e.type === castType) {
      const c = e.payload as VoteCastPayload | SheriffVoteCastPayload;
      votes[c.voter] = c.target;
    }
  }
  return votes;
}

function tallyFromVotes(
  votes: Record<number, number | null>,
  weightOf: (voter: number) => number,
): [number, number][] {
  const sums = new Map<number, number>();
  for (const [voterStr, target] of Object.entries(votes)) {
    if (target === null) continue;
    const voter = Number(voterStr);
    sums.set(target, (sums.get(target) ?? 0) + weightOf(voter));
  }
  return [...sums.entries()].sort((a, b) => a[0] - b[0]);
}

/** 当前投票轮（最近一次 VOTE_STARTED 之后）的票箱与加权计票；警长票权重取 config.sheriff.vote_weight（默认 1.5）。 */
export function voteTally(state: GameState, events: readonly Event[]): TallyResult {
  const votes = castsFrom(eventsAfterLast(events, "VOTE_STARTED"), "VOTE_CAST");
  const voteWeight =
    typeof state.config.sheriff.vote_weight === "number" ? state.config.sheriff.vote_weight : 1.5;
  const weightOf = (voter: number): number => {
    const pl = state.players.find((p) => p.seat === voter);
    return pl?.is_sheriff ? voteWeight : 1;
  };
  return { votes, tally: tallyFromVotes(votes, weightOf) };
}

/**
 * 警长选举计票：不加权。
 * `state` 参数只为与 voteTally(state, events) 签名对称而保留——加权票要看「投票者是否已持有
 * 警徽」，而选警长这一刻警徽本就还不存在（无在任警长），所以这里恒为等权 1，不需要读 state。
 */
export function sheriffVoteTally(state: GameState, events: readonly Event[]): TallyResult {
  void state;
  const votes = castsFrom(eventsAfterLast(events, "SHERIFF_VOTE_STARTED"), "SHERIFF_VOTE_CAST");
  return { votes, tally: tallyFromVotes(votes, () => 1) };
}

// ---- 夜间摘要 ----

export interface NightSummaryRow {
  role: RoleType | null;
  seat: number | null;
  text: string;
  /** Nocturne tokens 中的 CSS 变量名（如 "--ah-wolf"），由组件层 var(...) 解析。 */
  color: string;
}

function sliceRound(events: readonly Event[], round: number): Event[] {
  const startIdx = events.findIndex(
    (e) => e.type === "ROUND_STARTED" && (e.payload as RoundStartedPayload).round === round,
  );
  if (startIdx === -1) return [];
  const rest = events.slice(startIdx + 1);
  const endIdx = rest.findIndex((e) => e.type === "ROUND_STARTED");
  return endIdx === -1 ? rest : rest.slice(0, endIdx);
}

export function nightSummary(events: readonly Event[], round: number): NightSummaryRow[] {
  const rows: NightSummaryRow[] = [];
  for (const e of sliceRound(events, round)) {
    switch (e.type) {
      case "GUARD_PROTECTED": {
        const p = e.payload as GuardProtectedPayload;
        rows.push({
          role: "GUARD",
          seat: e.actor_seat,
          text: p.target !== null ? `守卫守护 ${p.target}号` : "守卫空守",
          color: "--ah-line-guard",
        });
        break;
      }
      case "WOLF_KILL_PROPOSED": {
        const p = e.payload as WolfKillProposedPayload;
        rows.push({
          role: "WEREWOLF",
          seat: p.wolf_seat,
          text: `${p.wolf_seat}号狼提议刀 ${p.target !== null ? `${p.target}号` : "空刀"}`,
          color: "--ah-wolf",
        });
        break;
      }
      case "WOLF_KILL_DECIDED": {
        const p = e.payload as WolfKillDecidedPayload;
        rows.push({
          role: "WEREWOLF",
          seat: null,
          text: p.target !== null ? `狼队决定刀 ${p.target}号` : "狼队空刀",
          color: "--ah-wolf",
        });
        break;
      }
      case "WOLF_KILL_REVOTE": {
        const p = e.payload as WolfKillRevotePayload;
        const body = p.proposals
          .map(([s, t]) => `${s}号→${t === null ? "空刀" : `${t}号`}`)
          .join("、");
        rows.push({
          role: "WEREWOLF",
          seat: null,
          text: `狼队第 ${p.round_no} 轮意见不一致（${body}），重新提案`,
          color: "--ah-wolf",
        });
        break;
      }
      case "WITCH_SAVED": {
        void (e.payload as WitchActedPayload);
        rows.push({
          role: "WITCH",
          seat: e.actor_seat,
          text: "女巫使用解药",
          color: "--ah-line-save",
        });
        break;
      }
      case "WITCH_POISONED": {
        const p = e.payload as WitchActedPayload;
        const target = p.poison_target ?? null;
        rows.push({
          role: "WITCH",
          seat: e.actor_seat,
          text: target !== null ? `女巫使用毒药 → ${target}号` : "女巫未使用毒药",
          color: "--ah-line-poison",
        });
        break;
      }
      case "SEER_CHECKED": {
        const p = e.payload as SeerCheckedPayload;
        rows.push({
          role: "SEER",
          seat: e.actor_seat,
          text: `预言家查验 ${p.target}号：${p.result === "WOLF" ? "狼人" : "好人"}`,
          color: "--ah-line-seer",
        });
        break;
      }
      case "NIGHT_RESOLVED": {
        const p = e.payload as NightResolvedPayload;
        rows.push({
          role: null,
          seat: null,
          text: p.deaths.length > 0 ? `本夜结算：${seatsZh(p.deaths)} 出局` : "本夜结算：平安夜",
          color: p.deaths.length > 0 ? "--ah-err" : "--ah-ok",
        });
        break;
      }
      default:
        break;
    }
  }
  return rows;
}

// ---- 发言 / 遗言 / 系统 / GM 统一 feed ----

export type SpeechItemKind = "speech" | "last_words" | "gm" | "system";

export interface SpeechItem {
  seq: number;
  type: string;
  kind: SpeechItemKind;
  actor_seat: number | null;
  text: string;
}

function kindOf(e: Event): SpeechItemKind {
  if (e.type === "PLAYER_SPOKE") return "speech";
  if (e.type === "LAST_WORDS") return "last_words";
  if (e.visibility === "GM_ONLY" || e.visibility === "WOLVES") return "gm";
  return "system";
}

/** 对齐 render.py::render_event 的分支集合；未显式处理的类型走与后端相同的通用回退。 */
function renderEventText(e: Event): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "ROUND_STARTED":
      return `———— 第 ${(e.payload as RoundStartedPayload).round} 轮 ————`;
    case "PHASE_CHANGED":
      return `【阶段】${(e.payload as PhaseChangedPayload).to}`;
    case "PLAYER_SPOKE": {
      const sp = e.payload as PlayerSpokePayload;
      const claim = sp.claim_role ? `（自称${ROLE_ZH[sp.claim_role]}）` : "";
      const badge =
        sp.badge_flow && sp.badge_flow.length > 0
          ? `（警徽流${JSON.stringify(sp.badge_flow)}）`
          : "";
      return `${e.actor_seat}号发言${claim}${badge}：${sp.content}`;
    }
    case "LAST_WORDS": {
      const lw = e.payload as LastWordsPayload;
      return `${lw.seat}号遗言：${lw.content}`;
    }
    case "DEATH_ANNOUNCED": {
      const da = e.payload as DeathAnnouncedPayload;
      return da.seats.length > 0
        ? `【天亮】昨夜出局：${seatsZh(da.seats)}`
        : "【天亮】平安夜，无人出局";
    }
    case "PLAYER_EXILED": {
      const pe = e.payload as PlayerExiledPayload;
      return pe.seat !== null ? `【放逐】${pe.seat}号被票出` : "【放逐】无人出局";
    }
    case "HUNTER_SHOT": {
      const hs = e.payload as HunterShotPayload;
      return hs.victim !== null
        ? `${hs.shooter}号猎人开枪带走 ${hs.victim}号`
        : `${hs.shooter}号猎人未开枪`;
    }
    case "WOLF_SELF_DESTRUCT":
      return `💥 ${(e.payload as WolfSelfDestructPayload).seat}号狼人自爆！`;
    case "VOTE_STARTED":
      return "【投票开始】";
    case "VOTE_CAST": {
      const vc = e.payload as VoteCastPayload;
      return vc.target !== null ? `  ${vc.voter}号 → ${vc.target}号` : `  ${vc.voter}号 弃票`;
    }
    case "VOTE_RESULT": {
      const vr = e.payload as VoteResultPayload;
      return vr.exiled !== null
        ? `【计票】${vr.exiled}号得票最高，出局`
        : `【计票】平票：${seatsZh(vr.tie_seats)}`;
    }
    case "ELECTION_STAGE_CHANGED": {
      const ec = e.payload as ElectionStageChangedPayload;
      const order = ec.speech_order != null ? `，顺序：${seatsZh(ec.speech_order)}` : "";
      return `【竞选】${ELECTION_STAGE_ZH[ec.stage]}${order}`;
    }
    case "SHERIFF_CANDIDACY": {
      const sc = e.payload as SheriffCandidacyPayload;
      return `${sc.seat}号${sc.running ? "上警竞选" : "不上警"}`;
    }
    case "SHERIFF_VOTE_STARTED":
      return `【竞选】警长开票，候选：${seatsZh((e.payload as SheriffVoteStartedPayload).candidates)}`;
    case "SHERIFF_ELECTED":
      return `【警长】${(e.payload as SheriffElectedPayload).seat}号当选警长`;
    case "BADGE_PASSED": {
      const bp = e.payload as BadgePassedPayload;
      return bp.to_seat !== null
        ? `${bp.from_seat}号移交警徽给 ${bp.to_seat}号`
        : `${bp.from_seat}号撕毁警徽`;
    }
    case "GAME_OVER": {
      const go = e.payload as GameOverPayload;
      const who = go.winner === "GOOD" ? "好人阵营" : go.winner === "WOLF" ? "狼人阵营" : "平局";
      return `═══════ 游戏结束：${who}胜（${go.winner ?? "平局"}）═══════`;
    }
    case "SEER_CHECKED": {
      const sc2 = e.payload as SeerCheckedPayload;
      return `[GM] 预言家查验 ${sc2.target}号：${sc2.result === "WOLF" ? "狼人" : "好人"}`;
    }
    case "GUARD_PROTECTED": {
      const gp = e.payload as GuardProtectedPayload;
      return gp.target !== null ? `[GM] 守卫守护 ${gp.target}号` : "[GM] 守卫空守";
    }
    case "WOLF_KILL_PROPOSED": {
      const wp = e.payload as WolfKillProposedPayload;
      return `[GM] ${wp.wolf_seat}号狼提议刀 ${wp.target !== null ? `${wp.target}号` : "空刀"}`;
    }
    case "WOLF_KILL_DECIDED": {
      const wd = e.payload as WolfKillDecidedPayload;
      return wd.target !== null ? `[GM] 狼队决定刀 ${wd.target}号` : "[GM] 狼队空刀";
    }
    case "WOLF_KILL_REVOTE": {
      const wr = e.payload as WolfKillRevotePayload;
      const body = wr.proposals
        .map(([s, t]) => `${s}号→${t === null ? "空刀" : `${t}号`}`)
        .join("、");
      return `[GM] 狼队第 ${wr.round_no} 轮意见不一致（${body}），重新提案`;
    }
    default: {
      // 通用回退：对齐 render.py 对未特判类型的处理（非 raw dict）。
      const actor = e.actor_seat !== null ? `${e.actor_seat}号 ` : "";
      const body = Object.entries(p)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join("，");
      return `[${e.type}] ${actor}${body}`.trimEnd();
    }
  }
}

/** 发言 + 遗言 + 系统行 + GM 行的统一 feed；含 seq 供回放截断。 */
export function speechItems(events: readonly Event[]): SpeechItem[] {
  return events.map((e) => ({
    seq: e.seq,
    type: e.type,
    kind: kindOf(e),
    actor_seat: e.actor_seat,
    text: renderEventText(e),
  }));
}

// ---- ReplayBar 分段 ----

export interface RoundSegment {
  fromSeq: number;
  toSeq: number;
  kind: "night" | "day";
}

/**
 * 按 PHASE_CHANGED/ROUND_STARTED 把事件流切成夜/日连续段，供 ReplayBar 着色。
 * 对局开局的 GAME_CREATED/ROLES_ASSIGNED/GAME_STARTED（首个 ROUND_STARTED 之前）没有
 * 对应的夜/日阶段事件，按「白天」归段，保证 segments 从 events[0].seq 起连续覆盖到末尾——
 * 不假设 seq 连续无洞：段的收尾 seq 取上一个事件的真实 seq，而非 e.seq - 1。
 */
export function roundSegments(events: readonly Event[]): RoundSegment[] {
  if (events.length === 0) return [];
  const segments: RoundSegment[] = [];
  let currentKind: "night" | "day" = "day";
  let fromSeq = events[0]!.seq;
  let prevSeq: number | null = null;

  for (const e of events) {
    let kind: "night" | "day" | null = null;
    if (e.type === "ROUND_STARTED") {
      kind = "night";
    } else if (e.type === "PHASE_CHANGED") {
      kind = isNight((e.payload as PhaseChangedPayload).to) ? "night" : "day";
    }
    if (kind !== null && kind !== currentKind) {
      if (prevSeq !== null) {
        segments.push({ fromSeq, toSeq: prevSeq, kind: currentKind });
      }
      currentKind = kind;
      fromSeq = e.seq;
    }
    prevSeq = e.seq;
  }
  if (prevSeq !== null) segments.push({ fromSeq, toSeq: prevSeq, kind: currentKind });
  return segments;
}
