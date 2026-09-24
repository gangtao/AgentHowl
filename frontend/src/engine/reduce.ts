// TS 同构引擎：逐字对齐 backend/app/engine/events.py::reduce / event_store.py::initial_state。
// 纯函数、零 IO。state = reduce_all(initial, events)。

import type {
  BadgePassedPayload,
  DeathAnnouncedPayload,
  ElectionStageChangedPayload,
  Event,
  GameMeta,
  GameOverPayload,
  GameState,
  GuardProtectedPayload,
  HunterShotPayload,
  IdiotRevealedPayload,
  LastWordsPayload,
  NightActions,
  NightResolvedPayload,
  PhaseChangedPayload,
  Player,
  PlayerExiledPayload,
  PlayerSpokePayload,
  RoleSkippedPayload,
  RolesAssignedPayload,
  RoundStartedPayload,
  SeerCheckedPayload,
  SeerLogEntry,
  SheriffBadgeLostPayload,
  SheriffCandidacyPayload,
  SheriffDirectionSetPayload,
  SheriffElectedPayload,
  SheriffVoteCastPayload,
  SheriffVoteStartedPayload,
  SheriffWithdrewPayload,
  VoteCastPayload,
  VoteStartedPayload,
  WitchActedPayload,
  WitchPotionConsumedPayload,
  WolfKillDecidedPayload,
  WolfKillProposedPayload,
  WolfKillRevotePayload,
  WolfSelfDestructPayload,
} from "./types";

/** 升序去重插入（对应后端 frozenset | {x}，金样中序列化为升序数组）。 */
function addSorted(arr: readonly number[], x: number): number[] {
  if (arr.includes(x)) return [...arr];
  return [...arr, x].sort((a, b) => a - b);
}

function replacePlayer(
  players: readonly Player[],
  seat: number,
  updates: Partial<Player>,
): Player[] {
  return players.map((p) => (p.seat === seat ? { ...p, ...updates } : p));
}

function actorOf(event: Event): number {
  if (event.actor_seat === null) {
    throw new Error(`事件 ${event.type} 缺少 actor_seat`);
  }
  return event.actor_seat;
}

const INITIAL_NIGHT_ACTIONS: NightActions = {
  guard_target: null,
  wolf_target: null,
  witch_save: false,
  witch_poison_target: null,
  seer_check: null,
};

/** 构造发牌前空白状态：与 event_store.initial_state 同构，真实角色由 ROLES_ASSIGNED 写入。 */
export function initialState(meta: GameMeta): GameState {
  const roster = [...meta.roster].sort((a, b) => a.seat - b.seat);
  const players: Player[] = roster.map((r) => ({
    seat: r.seat,
    display_name: r.display_name,
    player_type: "AGENT",
    role: "VILLAGER",
    faction: "GOOD",
    alive: true,
    is_sheriff: false,
    idiot_revealed: false,
    can_vote: true,
    witch_antidote: true,
    witch_poison: true,
    hunter_can_shoot: true,
    last_guard_target: null,
  }));
  return {
    game_id: meta.game_id,
    config: meta.config,
    phase: "LOBBY",
    round: 0,
    players,
    sheriff_seat: null,
    seer_log: {},
    speech_order: [],
    speech_idx: 0,
    votes: {},
    vote_candidates: [],
    tie_round: 0,
    pending_night: INITIAL_NIGHT_ACTIONS,
    wolf_proposals: {},
    wolf_kill_round: 1,
    wolf_proposal_history: [],
    acted_seats: [],
    night_deaths: [],
    resolved_first_night: false,
    pending_hunter: null,
    day_exiled: null,
    winner: null,
    state_version: 0,
    resume_token: null,
    skip_day: false,
    sheriff_candidates: [],
    sheriff_declared: [],
    sheriff_votes: {},
    election_stage: "",
    sheriff_withdrawn: [],
    sheriff_confirmed: [],
    sheriff_speech_direction: null,
    badge_flow_claims: {},
  };
}

function applyEvent(state: GameState, event: Event): Partial<GameState> {
  const p = event.payload;
  switch (event.type) {
    case "GAME_CREATED":
    case "GAME_STARTED":
      // 生命周期标记事件：状态无字段变化。
      return {};

    case "ROLES_ASSIGNED": {
      const roleBySeat = new Map((p as RolesAssignedPayload).assignments);
      const players = state.players.map((pl) => {
        const role = roleBySeat.get(pl.seat);
        if (role === undefined) return pl;
        return {
          ...pl,
          role,
          faction: role === "WEREWOLF" ? ("WOLF" as const) : ("GOOD" as const),
        };
      });
      return { players };
    }

    case "ROUND_STARTED": {
      const rp = p as RoundStartedPayload;
      return {
        round: rp.round,
        pending_night: INITIAL_NIGHT_ACTIONS,
        wolf_proposals: {},
        wolf_kill_round: 1,
        wolf_proposal_history: [],
        acted_seats: [],
        night_deaths: [],
        votes: {},
        vote_candidates: [],
        tie_round: 0,
        speech_order: [],
        speech_idx: 0,
        skip_day: false,
      };
    }

    case "PHASE_CHANGED": {
      const pp = p as PhaseChangedPayload;
      const upd: Partial<GameState> = { phase: pp.to, resume_token: pp.resume_token ?? null };
      if (pp.speech_order != null) {
        upd.speech_order = pp.speech_order;
        upd.speech_idx = 0;
      }
      if (pp.pending_hunter != null) {
        upd.pending_hunter = pp.pending_hunter;
      }
      return upd;
    }

    case "VOTE_STARTED": {
      const vp = p as VoteStartedPayload;
      return { votes: {}, vote_candidates: vp.candidates, tie_round: vp.tie_round };
    }

    case "GUARD_PROTECTED": {
      const gp = p as GuardProtectedPayload;
      const actor = actorOf(event);
      return {
        pending_night: { ...state.pending_night, guard_target: gp.target },
        acted_seats: addSorted(state.acted_seats, actor),
        players: replacePlayer(state.players, actor, { last_guard_target: gp.target }),
      };
    }

    case "WOLF_KILL_PROPOSED": {
      const wp = p as WolfKillProposedPayload;
      return {
        wolf_proposals: { ...state.wolf_proposals, [wp.wolf_seat]: wp.target },
        acted_seats: addSorted(state.acted_seats, wp.wolf_seat),
      };
    }

    case "WOLF_KILL_DECIDED": {
      const wd = p as WolfKillDecidedPayload;
      return { pending_night: { ...state.pending_night, wolf_target: wd.target } };
    }

    case "WOLF_KILL_REVOTE": {
      const wr = p as WolfKillRevotePayload;
      return {
        wolf_proposals: {},
        wolf_kill_round: state.wolf_kill_round + 1,
        wolf_proposal_history: [...state.wolf_proposal_history, wr.proposals],
      };
    }

    case "WITCH_SAVED": {
      const actor = actorOf(event);
      return {
        pending_night: { ...state.pending_night, witch_save: true },
        acted_seats: addSorted(state.acted_seats, actor),
      };
    }

    case "WITCH_POISONED": {
      const wa = p as WitchActedPayload;
      const actor = actorOf(event);
      return {
        pending_night: { ...state.pending_night, witch_poison_target: wa.poison_target ?? null },
        acted_seats: addSorted(state.acted_seats, actor),
      };
    }

    case "SEER_CHECKED": {
      const sc = p as SeerCheckedPayload;
      const actor = actorOf(event);
      const log: Record<string, SeerLogEntry[]> = { ...state.seer_log };
      const entry: SeerLogEntry = { round: state.round, seat: sc.target, result: sc.result };
      log[actor] = [...(log[actor] ?? []), entry];
      return {
        pending_night: { ...state.pending_night, seer_check: sc.target },
        acted_seats: addSorted(state.acted_seats, actor),
        seer_log: log,
      };
    }

    case "NIGHT_RESOLVED": {
      const nr = p as NightResolvedPayload;
      return { night_deaths: nr.deaths, resolved_first_night: true };
    }

    case "DEATH_ANNOUNCED": {
      const da = p as DeathAnnouncedPayload;
      let players = state.players;
      for (const seat of da.seats) {
        players = replacePlayer(players, seat, { alive: false });
      }
      return { players };
    }

    case "PLAYER_SPOKE": {
      const ps = p as PlayerSpokePayload;
      const upd: Partial<GameState> = { speech_idx: state.speech_idx + 1 };
      if (ps.badge_flow && ps.badge_flow.length > 0) {
        upd.badge_flow_claims = { ...state.badge_flow_claims, [actorOf(event)]: ps.badge_flow };
      }
      return upd;
    }

    case "VOTE_CAST": {
      const vc = p as VoteCastPayload;
      return { votes: { ...state.votes, [vc.voter]: vc.target } };
    }

    case "VOTE_RESULT":
      // 纯公示，不改状态；出局在 PLAYER_EXILED。
      return {};

    case "PLAYER_EXILED": {
      const pe = p as PlayerExiledPayload;
      if (pe.seat === null) return { day_exiled: null };
      return {
        players: replacePlayer(state.players, pe.seat, { alive: false }),
        day_exiled: pe.seat,
      };
    }

    case "LAST_WORDS": {
      void (p as LastWordsPayload);
      return { speech_idx: state.speech_idx + 1 };
    }

    case "HUNTER_SHOT": {
      const hs = p as HunterShotPayload;
      const upd: Partial<GameState> = { pending_hunter: null };
      if (hs.victim !== null) {
        upd.players = replacePlayer(state.players, hs.victim, { alive: false });
      }
      return upd;
    }

    case "IDIOT_REVEALED": {
      const ir = p as IdiotRevealedPayload;
      return {
        players: replacePlayer(state.players, ir.seat, { idiot_revealed: true, can_vote: false }),
      };
    }

    case "ROLE_SKIPPED": {
      void (p as RoleSkippedPayload);
      if (event.actor_seat !== null) {
        return { acted_seats: addSorted(state.acted_seats, event.actor_seat) };
      }
      return {};
    }

    case "SHERIFF_CANDIDACY": {
      const sc = p as SheriffCandidacyPayload;
      const declared = addSorted(state.sheriff_declared, sc.seat);
      let candidates = state.sheriff_candidates;
      if (sc.running && !candidates.includes(sc.seat)) {
        candidates = [...candidates, sc.seat];
      }
      const upd: Partial<GameState> = {
        sheriff_declared: declared,
        sheriff_candidates: candidates,
      };
      if (state.election_stage === "withdraw") {
        upd.sheriff_confirmed = addSorted(state.sheriff_confirmed, sc.seat);
      }
      return upd;
    }

    case "SHERIFF_WITHDREW": {
      const sw = p as SheriffWithdrewPayload;
      const candidates = state.sheriff_candidates.filter((s) => s !== sw.seat);
      const upd: Partial<GameState> = {
        sheriff_candidates: candidates,
        sheriff_withdrawn: addSorted(state.sheriff_withdrawn, sw.seat),
      };
      if (state.election_stage === "withdraw") {
        upd.sheriff_confirmed = addSorted(state.sheriff_confirmed, sw.seat);
      }
      return upd;
    }

    case "SHERIFF_VOTE_CAST": {
      const sv = p as SheriffVoteCastPayload;
      return { sheriff_votes: { ...state.sheriff_votes, [sv.voter]: sv.target } };
    }

    case "SHERIFF_VOTE_STARTED": {
      const svs = p as SheriffVoteStartedPayload;
      return { sheriff_candidates: svs.candidates, sheriff_votes: {} };
    }

    case "SHERIFF_ELECTED": {
      const se = p as SheriffElectedPayload;
      let players = state.players;
      if (state.sheriff_seat !== null) {
        players = replacePlayer(players, state.sheriff_seat, { is_sheriff: false });
      }
      players = replacePlayer(players, se.seat, { is_sheriff: true });
      return { sheriff_seat: se.seat, players };
    }

    case "SHERIFF_BADGE_LOST": {
      void (p as SheriffBadgeLostPayload);
      let players = state.players;
      if (state.sheriff_seat !== null) {
        players = replacePlayer(players, state.sheriff_seat, { is_sheriff: false });
      }
      return { sheriff_seat: null, players };
    }

    case "SHERIFF_DIRECTION_SET": {
      const sd = p as SheriffDirectionSetPayload;
      return { sheriff_speech_direction: sd.direction };
    }

    case "ELECTION_STAGE_CHANGED": {
      const ec = p as ElectionStageChangedPayload;
      const upd: Partial<GameState> = { election_stage: ec.stage };
      if (ec.speech_order != null) {
        upd.speech_order = ec.speech_order;
        upd.speech_idx = 0;
      }
      if (ec.stage === "withdraw") {
        upd.sheriff_confirmed = [];
      }
      if (ec.skip_day) {
        upd.skip_day = true;
      }
      return upd;
    }

    case "WOLF_SELF_DESTRUCT": {
      const wsd = p as WolfSelfDestructPayload;
      return { players: replacePlayer(state.players, wsd.seat, { alive: false }) };
    }

    case "BADGE_PASSED": {
      const bp = p as BadgePassedPayload;
      let players = replacePlayer(state.players, bp.from_seat, { is_sheriff: false });
      if (bp.to_seat !== null) {
        players = replacePlayer(players, bp.to_seat, { is_sheriff: true });
      }
      const upd: Partial<GameState> = { players, sheriff_seat: bp.to_seat };
      if (bp.consumed_turn) {
        upd.speech_idx = state.speech_idx + 1;
      }
      return upd;
    }

    case "GAME_OVER": {
      const go = p as GameOverPayload;
      // 终局清中断游标：引擎在续接分支里先清 resume_token 再判胜（issue #37）。
      return { winner: go.winner, phase: "GAME_OVER", resume_token: null };
    }

    case "WITCH_POTION_CONSUMED": {
      const wpc = p as WitchPotionConsumedPayload;
      const playerUpd: Partial<Player> = {};
      if (wpc.antidote) playerUpd.witch_antidote = false;
      if (wpc.poison) playerUpd.witch_poison = false;
      return { players: replacePlayer(state.players, wpc.seat, playerUpd) };
    }

    default:
      throw new Error(`未知事件类型：${String(event.type)}`);
  }
}

/** 把单个事件应用到状态，返回新状态。唯一写路径。 */
export function reduce(state: GameState, event: Event): GameState {
  const updates = applyEvent(state, event);
  return { ...state, ...updates, state_version: state.state_version + 1 };
}

export function reduceAll(initial: GameState, events: readonly Event[]): GameState {
  let state = initial;
  for (const ev of events) {
    state = reduce(state, ev);
  }
  return state;
}
