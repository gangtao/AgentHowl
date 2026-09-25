// 引擎类型：与后端 backend/app/engine/{events.py, state.py, phases.py, config.py} 逐一对应。
// 本文件零 IO、零 React；字段名与后端一致，供 reduce.ts / normalize.ts / select.ts 使用。

export type Phase =
  | "LOBBY"
  | "ROLE_ASSIGN"
  | "NIGHT_GUARD"
  | "NIGHT_WEREWOLF"
  | "NIGHT_WITCH"
  | "NIGHT_SEER"
  | "NIGHT_HUNTER_CONFIRM"
  | "WIN_CHECK"
  | "SHERIFF_ELECTION"
  | "SHERIFF_PK"
  | "DEATH_ANNOUNCE"
  | "LAST_WORDS"
  | "DAY_SPEECH"
  | "VOTE"
  | "VOTE_PK"
  | "EXILE"
  | "HUNTER_SHOOT"
  | "IDIOT_FLIP"
  | "GAME_OVER";

export type ElectionStage =
  "" | "candidacy" | "speech" | "withdraw" | "vote" | "direction" | "announce";

export type RoleType = "WEREWOLF" | "VILLAGER" | "SEER" | "WITCH" | "HUNTER" | "GUARD" | "IDIOT";

export type Faction = "GOOD" | "WOLF";

export type Visibility = "PUBLIC" | "WOLVES" | "ROLE_SELF" | "GM_ONLY";

export type EventType =
  | "GAME_CREATED"
  | "ROLES_ASSIGNED"
  | "GAME_STARTED"
  | "ROUND_STARTED"
  | "PHASE_CHANGED"
  | "GUARD_PROTECTED"
  | "WOLF_KILL_PROPOSED"
  | "WOLF_KILL_DECIDED"
  | "WOLF_KILL_REVOTE"
  | "WITCH_SAVED"
  | "WITCH_POISONED"
  | "SEER_CHECKED"
  | "NIGHT_RESOLVED"
  | "DEATH_ANNOUNCED"
  | "PLAYER_SPOKE"
  | "VOTE_STARTED"
  | "VOTE_CAST"
  | "VOTE_RESULT"
  | "PLAYER_EXILED"
  | "ROLE_SKIPPED"
  | "GAME_OVER"
  | "WITCH_POTION_CONSUMED"
  | "LAST_WORDS"
  | "HUNTER_SHOT"
  | "IDIOT_REVEALED"
  | "SHERIFF_CANDIDACY"
  | "SHERIFF_WITHDREW"
  | "SHERIFF_VOTE_CAST"
  | "SHERIFF_VOTE_STARTED"
  | "SHERIFF_ELECTED"
  | "SHERIFF_DIRECTION_SET"
  | "SHERIFF_BADGE_LOST"
  | "ELECTION_STAGE_CHANGED"
  | "BADGE_PASSED"
  | "WOLF_SELF_DESTRUCT";

// ---- Event payloads（与 events.py 的 *Payload 一一对应） ----

export interface GameCreatedPayload {
  num_players: number;
}
export type GameStartedPayload = Record<string, never>;

export interface RolesAssignedPayload {
  assignments: [number, RoleType][];
}

export interface RoundStartedPayload {
  round: number;
}

export interface PhaseChangedPayload {
  to: Phase;
  speech_order?: number[] | null;
  pending_hunter?: number | null;
  resume_token?: string | null;
}

export interface VoteStartedPayload {
  candidates: number[];
  tie_round: number;
}

export interface GuardProtectedPayload {
  target: number | null;
}

export interface WolfKillProposedPayload {
  wolf_seat: number;
  target: number | null;
}

export interface WolfKillDecidedPayload {
  target: number | null;
}

export interface WolfKillRevotePayload {
  round_no: number;
  proposals: [number, number | null][];
}

export interface WitchActedPayload {
  save?: boolean;
  poison_target?: number | null;
}

export interface SeerCheckedPayload {
  target: number;
  result: Faction;
}

export interface NightResolvedPayload {
  deaths: number[];
}

export interface DeathAnnouncedPayload {
  seats: number[];
}

export interface PlayerSpokePayload {
  content: string;
  claim_role?: RoleType | null;
  badge_flow?: number[];
}

export interface VoteCastPayload {
  voter: number;
  target: number | null;
}

export interface VoteResultPayload {
  tally: [number, number][];
  exiled: number | null;
  tie_seats: number[];
}

export interface PlayerExiledPayload {
  seat: number | null;
}

export interface RoleSkippedPayload {
  role: RoleType;
  reason: string;
}

export interface GameOverPayload {
  winner: string | null;
}

export interface WitchPotionConsumedPayload {
  seat: number;
  antidote?: boolean;
  poison?: boolean;
}

export interface LastWordsPayload {
  seat: number;
  content: string;
}

export interface HunterShotPayload {
  shooter: number;
  victim: number | null;
}

export interface IdiotRevealedPayload {
  seat: number;
}

export interface SheriffCandidacyPayload {
  seat: number;
  running: boolean;
}

export interface SheriffVoteCastPayload {
  voter: number;
  target: number | null;
}

export interface SheriffVoteStartedPayload {
  candidates: number[];
}

export interface SheriffElectedPayload {
  seat: number;
}

export interface SheriffBadgeLostPayload {
  reason: string;
}

export interface ElectionStageChangedPayload {
  stage: ElectionStage;
  speech_order?: number[] | null;
  skip_day?: boolean;
}

export interface SheriffWithdrewPayload {
  seat: number;
}

export interface SheriffDirectionSetPayload {
  direction: string;
}

export interface WolfSelfDestructPayload {
  seat: number;
}

export interface BadgePassedPayload {
  from_seat: number;
  to_seat: number | null;
  consumed_turn?: boolean;
}

// 各事件类型 -> payload 类型的映射（供 Event<P> 精确取型；未在此列出的分支用 EventPayload 兜底）。
export interface EventPayloadMap {
  GAME_CREATED: GameCreatedPayload;
  GAME_STARTED: GameStartedPayload;
  ROLES_ASSIGNED: RolesAssignedPayload;
  ROUND_STARTED: RoundStartedPayload;
  PHASE_CHANGED: PhaseChangedPayload;
  GUARD_PROTECTED: GuardProtectedPayload;
  WOLF_KILL_PROPOSED: WolfKillProposedPayload;
  WOLF_KILL_DECIDED: WolfKillDecidedPayload;
  WOLF_KILL_REVOTE: WolfKillRevotePayload;
  WITCH_SAVED: WitchActedPayload;
  WITCH_POISONED: WitchActedPayload;
  SEER_CHECKED: SeerCheckedPayload;
  NIGHT_RESOLVED: NightResolvedPayload;
  DEATH_ANNOUNCED: DeathAnnouncedPayload;
  PLAYER_SPOKE: PlayerSpokePayload;
  VOTE_STARTED: VoteStartedPayload;
  VOTE_CAST: VoteCastPayload;
  VOTE_RESULT: VoteResultPayload;
  PLAYER_EXILED: PlayerExiledPayload;
  ROLE_SKIPPED: RoleSkippedPayload;
  GAME_OVER: GameOverPayload;
  WITCH_POTION_CONSUMED: WitchPotionConsumedPayload;
  LAST_WORDS: LastWordsPayload;
  HUNTER_SHOT: HunterShotPayload;
  IDIOT_REVEALED: IdiotRevealedPayload;
  SHERIFF_CANDIDACY: SheriffCandidacyPayload;
  SHERIFF_WITHDREW: SheriffWithdrewPayload;
  SHERIFF_VOTE_CAST: SheriffVoteCastPayload;
  SHERIFF_VOTE_STARTED: SheriffVoteStartedPayload;
  SHERIFF_ELECTED: SheriffElectedPayload;
  SHERIFF_DIRECTION_SET: SheriffDirectionSetPayload;
  SHERIFF_BADGE_LOST: SheriffBadgeLostPayload;
  ELECTION_STAGE_CHANGED: ElectionStageChangedPayload;
  BADGE_PASSED: BadgePassedPayload;
  WOLF_SELF_DESTRUCT: WolfSelfDestructPayload;
}

export type EventPayload = EventPayloadMap[EventType];

export interface Event<P = EventPayload> {
  seq: number;
  game_id: string;
  ts: number;
  type: EventType;
  actor_seat: number | null;
  payload: P;
  visibility: Visibility;
  meta: Record<string, string>;
}

// ---- 状态（state.py 逐一对应） ----

export interface Player {
  seat: number;
  display_name: string;
  player_type: "HUMAN" | "AGENT";
  role: RoleType;
  faction: Faction;
  alive: boolean;
  is_sheriff: boolean;
  idiot_revealed: boolean;
  can_vote: boolean;
  witch_antidote: boolean;
  witch_poison: boolean;
  hunter_can_shoot: boolean;
  last_guard_target: number | null;
}

export interface NightActions {
  guard_target: number | null;
  wolf_target: number | null;
  witch_save: boolean;
  witch_poison_target: number | null;
  seer_check: number | null;
}

export interface SeerLogEntry {
  round: number;
  seat: number;
  result: string;
}

// GameState.config 在金样中是完整 GameConfig JSON；这里只声明 reducer/selector 用到的
// 必要字段 + 索引签名，reduce 不改它、normalizeState 原样保留。
export interface GameConfigLite {
  config_id?: string;
  num_players: number;
  sheriff: { enabled: boolean; vote_weight?: number } & Record<string, unknown>;
  roles: { role: RoleType; count: number }[];
  win_condition: string;
  [k: string]: unknown;
}

export interface GameState {
  game_id: string;
  config: GameConfigLite;
  phase: Phase;
  round: number;
  players: Player[];
  sheriff_seat: number | null;
  seer_log: Record<string, SeerLogEntry[]>;
  speech_order: number[];
  speech_idx: number;
  votes: Record<string, number | null>;
  vote_candidates: number[];
  tie_round: number;
  pending_night: NightActions;
  wolf_proposals: Record<string, number | null>;
  wolf_kill_round: number;
  wolf_proposal_history: [number, number | null][][];
  acted_seats: number[];
  night_deaths: number[];
  resolved_first_night: boolean;
  pending_hunter: number | null;
  day_exiled: number | null;
  winner: string | null;
  state_version: number;
  resume_token: string | null;
  skip_day: boolean;
  sheriff_candidates: number[];
  sheriff_declared: number[];
  sheriff_votes: Record<string, number | null>;
  election_stage: ElectionStage;
  sheriff_withdrawn: number[];
  sheriff_confirmed: number[];
  sheriff_speech_direction: string | null;
  badge_flow_claims: Record<string, number[]>;
}

export interface GameMeta {
  game_id: string;
  config: GameConfigLite;
  roster: { seat: number; display_name: string }[];
  agents: Record<string, unknown>;
}
