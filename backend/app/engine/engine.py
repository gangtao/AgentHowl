"""引擎主循环：create_game / step / advance。

step 固定为「校验 → 决定事件 → reduce 应用」；advance 纯系统推进到下一个行动点。
事件是唯一写路径；seq == state_version（每事件 +1），ts=float(seq) 为逻辑 tick。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.engine import rng
from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    NightActionType,
    RejectedReason,
    SelfDestruct,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import (
    Faction,
    GameConfig,
    RoleType,
    SpeechOrderRule,
    WolfKillRule,
    faction_of,
    validate_config,
)
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    EngineInvariantError,
    Event,
    EventPayload,
    EventType,
    GameOverPayload,
    GuardProtectedPayload,
    HunterShotPayload,
    IdiotRevealedPayload,
    LastWordsPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RolesAssignedPayload,
    RoleSkippedPayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    SheriffCandidacyPayload,
    SheriffDirectionSetPayload,
    SheriffElectedPayload,
    SheriffVoteCastPayload,
    Visibility,
    VoteCastPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WitchActedPayload,
    WitchPotionConsumedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfSelfDestructPayload,
    reduce,
)
from app.engine.phases import (
    Phase,
    expected_actors,
    next_night_phase,
    night_phase_sequence,
)
from app.engine.resolver import check_win, count_votes, resolve_night
from app.engine.state import (
    GameState,
    Player,
    living,
    living_of_role,
    living_seats,
    player_at,
)

_MAX_SYSTEM_STEPS = 10_000


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: GameState
    events: list[Event]
    rejection: RejectedReason | None = None


def _emit(
    state: GameState,
    type_: EventType,
    payload: EventPayload,
    visibility: Visibility,
    actor: int | None = None,
) -> tuple[GameState, Event]:
    seq = state.state_version + 1
    ev = Event(
        seq=seq,
        game_id=state.game_id,
        ts=float(seq),
        type=type_,
        actor_seat=actor,
        payload=payload,
        visibility=visibility,
    )
    return reduce(state, ev), ev


# ---------- 建局 ----------


def create_game(config: GameConfig, game_id: str) -> StepResult:
    validate_config(config)
    players = tuple(
        Player(
            seat=seat,
            display_name=f"P{seat}",
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for seat in range(config.num_players)
    )
    state = GameState(
        game_id=game_id,
        config=config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )

    expanded: list[RoleType] = []
    for slot in config.roles:
        expanded.extend([slot.role] * slot.count)
    seed = config.seed if config.seed is not None else 0
    dealt = rng.shuffle(seed=seed, purpose="deal", items=expanded)
    assignments = tuple((seat, dealt[seat]) for seat in range(config.num_players))

    events: list[Event] = []
    state, e = _emit(
        state,
        EventType.ROLES_ASSIGNED,
        RolesAssignedPayload(assignments=assignments, new_rng_state=state.rng_state + 1),
        Visibility.GM_ONLY,
    )
    events.append(e)
    # 进入首夜
    state, more = _begin_night(state, first=True)
    events.extend(more)
    state, adv = advance(state)
    events.extend(adv)
    return StepResult(state=state, events=events)


def _begin_night(state: GameState, first: bool) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    state, e = _emit(
        state,
        EventType.ROUND_STARTED,
        RoundStartedPayload(round=state.round + 1),
        Visibility.GM_ONLY,
    )
    events.append(e)
    seq = night_phase_sequence(state.config)
    first_phase = seq[0] if seq else Phase.WIN_CHECK
    state, e = _emit(
        state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=first_phase), Visibility.GM_ONLY
    )
    events.append(e)
    return state, events


# ---------- 校验 ----------


def _validate(state: GameState, action: Action) -> RejectedReason | None:
    if isinstance(action, SelfDestruct):
        return _validate_self_destruct(state, action)
    if isinstance(action, SheriffAction):
        return _validate_sheriff(state, action)

    actor = action.actor_seat
    try:
        pl = player_at(state, actor)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    # HUNTER_SHOOT/LAST_WORDS 的行动者本就是「刚出局」的死者，需放行；
    # 其余阶段仍要求 actor 存活。
    if not pl.alive and state.phase not in (Phase.HUNTER_SHOOT, Phase.LAST_WORDS):
        return RejectedReason.DEAD_ACTOR
    if actor not in expected_actors(state):
        return RejectedReason.NOT_YOUR_TURN

    if isinstance(action, NightAction):
        return _validate_night(state, pl, action)
    if isinstance(action, Speak):
        # 发言仅在白天发言或遗言阶段合法（内容对引擎不透明）
        if state.phase not in (Phase.DAY_SPEECH, Phase.LAST_WORDS):
            return RejectedReason.WRONG_PHASE
        if (
            state.phase == Phase.DAY_SPEECH
            and state.config.speech_order_rule == SpeechOrderRule.BIDDING
        ):
            return RejectedReason.BIDDING_NOT_IMPLEMENTED
        return None
    if isinstance(action, DayVote):
        if state.phase not in (Phase.VOTE, Phase.VOTE_PK):
            return RejectedReason.WRONG_PHASE
        return _validate_vote(state, pl, action)
    return RejectedReason.WRONG_PHASE


def _alive_target(state: GameState, seat: int | None) -> bool:
    if seat is None:
        return False
    try:
        return player_at(state, seat).alive
    except KeyError:
        return False


def _validate_self_destruct(state: GameState, a: SelfDestruct) -> RejectedReason | None:
    try:
        pl = player_at(state, a.actor_seat)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    if not pl.alive:
        return RejectedReason.DEAD_ACTOR
    if pl.faction != Faction.WOLF:
        return RejectedReason.NOT_SELF_DESTRUCTABLE
    if state.phase not in (Phase.DAY_SPEECH, Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        return RejectedReason.NOT_SELF_DESTRUCTABLE
    return None


def _validate_night(state: GameState, pl: Player, a: NightAction) -> RejectedReason | None:
    ph = state.phase
    at = a.action_type

    if ph == Phase.NIGHT_GUARD:
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.GUARD:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        if a.target_seat == pl.seat and not state.config.guard.can_guard_self:
            return RejectedReason.GUARD_SELF_FORBIDDEN
        if (
            pl.last_guard_target is not None
            and a.target_seat == pl.last_guard_target
            and not state.config.guard.can_guard_same_target_consecutively
        ):
            return RejectedReason.GUARD_SAME_TARGET
        return None

    if ph == Phase.NIGHT_WEREWOLF:
        if at == NightActionType.SKIP:
            if not state.config.allow_wolf_empty_knife:
                return RejectedReason.WRONG_PHASE
            return None
        if at != NightActionType.KILL:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        assert a.target_seat is not None
        tgt = player_at(state, a.target_seat)
        if tgt.faction == Faction.WOLF and not state.config.allow_wolf_self_knife:
            return RejectedReason.INVALID_TARGET
        return None

    if ph == Phase.NIGHT_WITCH:
        if at == NightActionType.SKIP:
            return None
        if at == NightActionType.SAVE:
            if not pl.witch_antidote:
                return RejectedReason.WITCH_NO_ANTIDOTE
            killed = state.pending_night.wolf_target
            if killed is None:
                return RejectedReason.INVALID_TARGET  # 无刀口可救
            if killed == pl.seat:
                w = state.config.witch
                first_night = state.round == 1
                allowed = w.self_rescue_always or (first_night and w.self_rescue_first_night)
                if not allowed:
                    return RejectedReason.WITCH_SELF_RESCUE_FORBIDDEN
            return None
        if at == NightActionType.POISON:
            if not pl.witch_poison:
                return RejectedReason.WITCH_NO_POISON
            if not _alive_target(state, a.target_seat):
                return RejectedReason.DEAD_TARGET
            return None
        return RejectedReason.WRONG_PHASE

    if ph == Phase.NIGHT_SEER:
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.CHECK:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None

    if ph == Phase.HUNTER_SHOOT:
        pl2 = player_at(state, a.actor_seat)
        if not pl2.hunter_can_shoot:
            return RejectedReason.HUNTER_CANNOT_SHOOT
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.SHOOT:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None

    return RejectedReason.WRONG_PHASE


def _validate_vote(state: GameState, pl: Player, v: DayVote) -> RejectedReason | None:
    if not pl.can_vote:
        return RejectedReason.CANNOT_VOTE
    if v.abstain or v.target_seat is None:
        return None
    if not _alive_target(state, v.target_seat):
        return RejectedReason.DEAD_TARGET
    if state.vote_candidates and v.target_seat not in state.vote_candidates:
        return RejectedReason.INVALID_TARGET
    return None


def _validate_sheriff(state: GameState, a: SheriffAction) -> RejectedReason | None:
    try:
        pl = player_at(state, a.actor_seat)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    # 将死警长在其 LAST_WORDS 回合可用 pass_badge/tear_badge，此时 actor 已死亡，需豁免。
    if not pl.alive and state.phase != Phase.LAST_WORDS:
        return RejectedReason.DEAD_ACTOR
    if a.actor_seat not in expected_actors(state):
        return RejectedReason.NOT_YOUR_TURN
    at = a.action_type
    if state.phase == Phase.LAST_WORDS:
        if at not in (SheriffActionType.PASS_BADGE, SheriffActionType.TEAR_BADGE):
            return RejectedReason.WRONG_PHASE
        if not pl.is_sheriff:
            return RejectedReason.NOT_A_CANDIDATE
        if at == SheriffActionType.PASS_BADGE and not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None
    if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "candidacy":
        if at not in (SheriffActionType.RUN_FOR_SHERIFF, SheriffActionType.WITHDRAW):
            return RejectedReason.WRONG_PHASE
        return None
    if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "direction":
        if at != SheriffActionType.SET_SPEECH_DIRECTION:
            return RejectedReason.WRONG_PHASE
        if a.direction is None:
            return RejectedReason.INVALID_TARGET
        if a.actor_seat != state.sheriff_seat:
            return RejectedReason.NOT_YOUR_TURN
        return None
    if state.phase in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        if at != SheriffActionType.VOTE_SHERIFF:
            return RejectedReason.WRONG_PHASE
        if a.target_seat not in state.sheriff_candidates:
            return RejectedReason.NOT_A_CANDIDATE
        return None
    return RejectedReason.WRONG_PHASE


# ---------- 应用行动 ----------


def _apply_action(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    if isinstance(action, NightAction):
        return _apply_night(state, action)
    if isinstance(action, Speak):
        if state.phase == Phase.LAST_WORDS:
            s, e = _emit(
                state,
                EventType.LAST_WORDS,
                LastWordsPayload(seat=action.actor_seat, content=action.content),
                Visibility.PUBLIC,
                actor=action.actor_seat,
            )
            return s, [e]
        s, e = _emit(
            state,
            EventType.PLAYER_SPOKE,
            PlayerSpokePayload(
                content=action.content, claim_role=action.claim_role, badge_flow=action.badge_flow
            ),
            Visibility.PUBLIC,
            actor=action.actor_seat,
        )
        return s, [e]
    if isinstance(action, DayVote):
        target = None if action.abstain else action.target_seat
        s, e = _emit(
            state,
            EventType.VOTE_CAST,
            VoteCastPayload(voter=action.actor_seat, target=target),
            Visibility.PUBLIC,
            actor=action.actor_seat,
        )
        return s, [e]
    if isinstance(action, SheriffAction):
        return _apply_sheriff(state, action)
    if isinstance(action, SelfDestruct):
        return _apply_self_destruct(state, action)
    raise EngineInvariantError(f"不应到达：{type(action)}")


def _apply_self_destruct(state: GameState, action: SelfDestruct) -> tuple[GameState, list[Event]]:
    s, e = _emit(
        state,
        EventType.WOLF_SELF_DESTRUCT,
        WolfSelfDestructPayload(seat=action.actor_seat),
        Visibility.PUBLIC,
        actor=action.actor_seat,
    )
    events: list[Event]
    # 竞选期自爆吞警徽
    if (
        state.phase
        in (
            Phase.SHERIFF_ELECTION,
            Phase.SHERIFF_PK,
        )
        and state.config.sheriff.wolf_selfdestruct_eats_badge
    ):
        s = s.model_copy(update={"election_stage": ""})
        s, e2 = _emit(
            s, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=None), Visibility.PUBLIC
        )
        events = [e, e2]
    else:
        events = [e]
    # 跳过当天剩余流程，直接入夜
    s2, more = _after_self_destruct(s)
    return s2, [*events, *more]


def _after_self_destruct(state: GameState) -> tuple[GameState, list[Event]]:
    """自爆后续接：白天自爆直接判胜/入夜；竞选期自爆先补公布首夜死讯再入夜。

    自爆的警长零遗言覆盖，警徽必须在此兜底自动流失（竞选路径下 sheriff_seat 已因吞警徽
    置空，本调用是幂等 no-op；DAY_SPEECH 路径下正确撕毁自爆者持有的警徽）。
    """
    state, badge_ev = _auto_badge_if_orphaned(state, recipients=())
    events: list[Event] = list(badge_ev)
    if state.phase == Phase.DAY_SPEECH:
        # 白天自爆：当天死讯早已公布，直接判胜/入夜
        winner = check_win(state)
        if winner is not None:
            s, e = _emit(
                state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
            )
            return s, [*events, e]
        state, ev0 = _after_day_death(state)
        return state, [*events, *ev0]
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言）
    state = state.model_copy(update={"election_stage": ""})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    # _announce_and_continue_night 会进入 DAY_SPEECH；自爆要求跳过白天 -> 强制推进到入夜
    if state.phase == Phase.DAY_SPEECH:
        winner = check_win(state)
        if winner is not None:
            state, e = _emit(
                state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
            )
            return state, [*ev, e]
        state, ev2 = _after_day_death(state)
        return state, [*ev, *ev2]
    return state, ev


def _apply_sheriff(state: GameState, a: SheriffAction) -> tuple[GameState, list[Event]]:
    at = a.action_type
    if at in (SheriffActionType.RUN_FOR_SHERIFF, SheriffActionType.WITHDRAW):
        running = at == SheriffActionType.RUN_FOR_SHERIFF
        s, e = _emit(
            state,
            EventType.SHERIFF_CANDIDACY,
            SheriffCandidacyPayload(seat=a.actor_seat, running=running),
            Visibility.PUBLIC,
            actor=a.actor_seat,
        )
        return s, [e]
    if at in (SheriffActionType.PASS_BADGE, SheriffActionType.TEAR_BADGE):
        to = a.target_seat if at == SheriffActionType.PASS_BADGE else None
        # 消耗该发言回合（LAST_WORDS 用 pass_badge/tear_badge 顶替本轮发言）；
        # 经事件推进 speech_idx。
        s, e = _emit(
            state,
            EventType.BADGE_PASSED,
            BadgePassedPayload(from_seat=a.actor_seat, to_seat=to, consumed_turn=True),
            Visibility.PUBLIC,
            actor=a.actor_seat,
        )
        return s, [e]
    if at == SheriffActionType.SET_SPEECH_DIRECTION:
        assert a.direction is not None  # 校验已保证
        s, e = _emit(
            state,
            EventType.SHERIFF_DIRECTION_SET,
            SheriffDirectionSetPayload(direction=a.direction.value),
            Visibility.PUBLIC,
            actor=a.actor_seat,
        )
        # 方向已定 -> 游标推进到 announce，由 _advance_election 续接死讯公布
        s = s.model_copy(update={"election_stage": "announce"})
        return s, [e]
    if at != SheriffActionType.VOTE_SHERIFF:
        # 校验层应已拦截；此守卫防止未来枚举增长时静默误分类为投票
        raise EngineInvariantError(f"未处理的警长行动类型：{at}")
    s, e = _emit(
        state,
        EventType.SHERIFF_VOTE_CAST,
        SheriffVoteCastPayload(voter=a.actor_seat, target=a.target_seat),
        Visibility.PUBLIC,
        actor=a.actor_seat,
    )
    return s, [e]


def _apply_night(state: GameState, a: NightAction) -> tuple[GameState, list[Event]]:
    ph = state.phase
    at = a.action_type
    actor = a.actor_seat

    if ph == Phase.NIGHT_GUARD:
        target = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(
            state,
            EventType.GUARD_PROTECTED,
            GuardProtectedPayload(target=target),
            Visibility.ROLE_SELF,
            actor=actor,
        )
        return s, [e]

    if ph == Phase.NIGHT_WEREWOLF:
        target = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(
            state,
            EventType.WOLF_KILL_PROPOSED,
            WolfKillProposedPayload(wolf_seat=actor, target=target),
            Visibility.WOLVES,
            actor=actor,
        )
        return s, [e]

    if ph == Phase.NIGHT_WITCH:
        if at == NightActionType.SAVE:
            s, e = _emit(
                state,
                EventType.WITCH_SAVED,
                WitchActedPayload(save=True),
                Visibility.ROLE_SELF,
                actor=actor,
            )
            return s, [e]
        if at == NightActionType.POISON:
            s, e = _emit(
                state,
                EventType.WITCH_POISONED,
                WitchActedPayload(poison_target=a.target_seat),
                Visibility.ROLE_SELF,
                actor=actor,
            )
            # 用毒后本人 witch_poison 置 False：通过修改 player 完成（事件驱动）
            s = _consume_witch_potion(s, actor, poison=True)
            return s, [e]
        s, e = _emit(
            state,
            EventType.ROLE_SKIPPED,
            RoleSkippedPayload(role=RoleType.WITCH, reason="skip"),
            Visibility.ROLE_SELF,
            actor=actor,
        )
        return s, [e]

    if ph == Phase.NIGHT_SEER:
        if at == NightActionType.SKIP:
            s, e = _emit(
                state,
                EventType.ROLE_SKIPPED,
                RoleSkippedPayload(role=RoleType.SEER, reason="skip"),
                Visibility.ROLE_SELF,
                actor=actor,
            )
            return s, [e]
        assert a.target_seat is not None
        result = faction_of(player_at(state, a.target_seat).role)
        s, e = _emit(
            state,
            EventType.SEER_CHECKED,
            SeerCheckedPayload(target=a.target_seat, result=result),
            Visibility.ROLE_SELF,
            actor=actor,
        )
        return s, [e]

    if ph == Phase.HUNTER_SHOOT:
        victim = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(
            state,
            EventType.HUNTER_SHOT,
            HunterShotPayload(shooter=actor, victim=victim),
            Visibility.PUBLIC,
            actor=actor,
        )
        return s, [e]

    raise EngineInvariantError(f"夜间行动落在非夜间阶段 {ph}")


def _consume_witch_potion(
    state: GameState, seat: int, *, antidote: bool = False, poison: bool = False
) -> GameState:
    s, _ = _emit(
        state,
        EventType.WITCH_POTION_CONSUMED,
        WitchPotionConsumedPayload(seat=seat, antidote=antidote, poison=poison),
        Visibility.GM_ONLY,
        actor=seat,
    )
    return s


# ---------- step / advance ----------


def step(state: GameState, action: Action) -> StepResult:
    rej = _validate(state, action)
    if rej is not None:
        return StepResult(state=state, events=[], rejection=rej)
    state, events = _apply_action(state, action)
    state, more = advance(state)
    return StepResult(state=state, events=[*events, *more])


def advance(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    guard = 0
    while state.phase != Phase.GAME_OVER and not expected_actors(state):
        state, evs = _system_transition(state)
        if not evs:
            break
        events.extend(evs)
        guard += 1
        if guard > _MAX_SYSTEM_STEPS:
            raise EngineInvariantError("系统推进未收敛（可能存在阶段死循环）")
    return state, events


def _wolf_consensus(state: GameState) -> int | None:
    """按 config.wolf_kill_rule 从狼队提案决定刀口（None=空刀）。"""
    proposals = state.wolf_proposals
    rule = state.config.wolf_kill_rule

    if rule == WolfKillRule.MAJORITY:
        # 相对多数；空刀票(None)同票计数；任何并列（含与空刀票并列）-> 空刀。
        # 注意：即使 allow_wolf_empty_knife=False（提案层已禁 skip），平票仍决策为
        # None —— 与规格「意见不统一视为空刀」同性质，属预期行为。
        counts: dict[int | None, int] = {}
        for t in proposals.values():
            counts[t] = counts.get(t, 0) + 1
        if not counts:
            return None
        top = max(counts.values())
        leaders = [t for t in counts if counts[t] == top]
        if len(leaders) == 1 and leaders[0] is not None:
            return leaders[0]
        return None

    if rule == WolfKillRule.RANDOM_PROPOSAL:
        # 非 None 提案多重集（同目标多票权重更高），排序后确定性抽取
        pool = sorted(t for t in proposals.values() if t is not None)
        if not pool:
            return None
        seed = state.config.seed if state.config.seed is not None else 0
        idx = rng.derive_int(seed=seed, purpose="wolf_kill", seq=state.rng_state, modulo=len(pool))
        return pool[idx]

    # UNANIMOUS_OR_NO_KILL（默认）：全员一致且非 None 才刀
    vals = set(proposals.values())
    if len(vals) == 1 and None not in vals:
        return next(iter(vals))
    return None


def _night_role_present(state: GameState, phase: Phase) -> bool:
    role_by_phase = {
        Phase.NIGHT_GUARD: RoleType.GUARD,
        Phase.NIGHT_WITCH: RoleType.WITCH,
        Phase.NIGHT_SEER: RoleType.SEER,
        Phase.NIGHT_HUNTER_CONFIRM: RoleType.HUNTER,
    }
    role = role_by_phase.get(phase)
    if role is None:
        return True
    members = living_of_role(state, role)
    if not members:
        return False
    if phase == Phase.NIGHT_WITCH:
        return any(m.witch_antidote or m.witch_poison for m in members)
    return True


def _role_of_night_phase(phase: Phase) -> RoleType:
    for role, ph in {
        RoleType.GUARD: Phase.NIGHT_GUARD,
        RoleType.WITCH: Phase.NIGHT_WITCH,
        RoleType.SEER: Phase.NIGHT_SEER,
        RoleType.HUNTER: Phase.NIGHT_HUNTER_CONFIRM,
    }.items():
        if ph == phase:
            return role
    return RoleType.WEREWOLF


def _system_transition(state: GameState) -> tuple[GameState, list[Event]]:
    ph = state.phase
    events: list[Event] = []

    # --- 夜间子阶段收尾 ---
    if ph in night_phase_sequence(state.config):
        if ph == Phase.NIGHT_WEREWOLF:
            state, e = _emit(
                state,
                EventType.WOLF_KILL_DECIDED,
                WolfKillDecidedPayload(target=_wolf_consensus(state)),
                Visibility.GM_ONLY,
            )
            events.append(e)
        elif not _night_role_present(state, ph):
            state, e = _emit(
                state,
                EventType.ROLE_SKIPPED,
                RoleSkippedPayload(role=_role_of_night_phase(ph), reason="absent_or_dead"),
                Visibility.GM_ONLY,
            )
            events.append(e)
        nxt = next_night_phase(state.config, ph)
        if nxt is not None:
            state, e = _emit(
                state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=nxt), Visibility.GM_ONLY
            )
            events.append(e)
            return state, events
        # 夜序结束 -> 结算
        state, ev = _resolve_night_and_continue(state)
        return state, [*events, *ev]

    if ph == Phase.DAY_SPEECH:
        # 发言轮结束 -> 投票
        state, e = _emit(
            state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE), Visibility.PUBLIC
        )
        events.append(e)
        state, e = _emit(
            state,
            EventType.VOTE_STARTED,
            VoteStartedPayload(candidates=(), tie_round=0),
            Visibility.PUBLIC,
        )
        events.append(e)
        return state, events

    if ph in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        return _advance_election(state)

    if ph == Phase.VOTE:
        return _tally_and_continue(state)

    if ph == Phase.VOTE_PK:
        return _tally_and_continue(state)

    if ph == Phase.EXILE:
        return _after_exile(state)

    if ph == Phase.HUNTER_SHOOT:
        # 猎人已开枪（HUNTER_SHOT 事件已应用），按 resume_token 续接
        token = state.resume_token
        victim_dead = state.night_deaths  # 夜间语境
        if token == "night_after_hunter":
            state = state.model_copy(update={"resume_token": None})
            winner = check_win(state)
            if winner is not None:
                s, e = _emit(
                    state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
                )
                return s, [e]
            return _finish_night_deaths(state, victim_dead, [])
        # day_after_hunter
        state = state.model_copy(update={"resume_token": None})
        winner = check_win(state)
        if winner is not None:
            s, e = _emit(
                state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
            )
            return s, [e]
        return _enter_day_last_words(state, extra=())

    if ph == Phase.LAST_WORDS:
        token = state.resume_token
        state = state.model_copy(update={"resume_token": None})
        if token == "day_speech":
            return _enter_day_speech(state)
        return _after_day_death(state)

    return state, events


# ---------- 夜晚结算与白天收尾 ----------


def _last_words_recipients(
    state: GameState, deaths: tuple[int, ...], is_night: bool
) -> tuple[int, ...]:
    rule = state.config.last_words
    if not is_night:
        return deaths  # 白天出局者始终有遗言
    from app.engine.config import LastWordsRule

    if rule == LastWordsRule.ALWAYS_NIGHT:
        return deaths
    if rule == LastWordsRule.FIRST_NIGHT_ONLY:
        return deaths if state.round == 1 else ()
    # N_EQUALS_WOLVES：前 (狼数) 个夜晚的死者有遗言（M1 采用「round <= 初始狼数」口径）
    initial_wolves = sum(
        slot.count for slot in state.config.roles if slot.role == RoleType.WEREWOLF
    )
    return deaths if state.round <= initial_wolves else ()


def _dead_hunter_can_shoot(
    state: GameState, deaths: frozenset[int], poisoned: int | None
) -> int | None:
    for seat in sorted(deaths):
        pl = player_at(state, seat)
        if pl.role == RoleType.HUNTER and pl.hunter_can_shoot and seat != poisoned:
            return seat
    return None


def _resolve_night_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    na = state.pending_night
    if na.witch_save and na.wolf_target is not None:
        witches = living_of_role(state, RoleType.WITCH)
        if witches:
            state = _consume_witch_potion(state, witches[0].seat, antidote=True)

    deaths = resolve_night(state.config, na)
    ordered = tuple(sorted(deaths))
    state, e = _emit(
        state, EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=ordered), Visibility.GM_ONLY
    )
    events.append(e)

    winner = _check_win_with_deaths(state, deaths)
    if winner is not None and state.config.wolf_first_kill_priority:
        state, e = _emit(
            state,
            EventType.DEATH_ANNOUNCED,
            DeathAnnouncedPayload(seats=ordered),
            Visibility.PUBLIC,
        )
        events.append(e)
        state, e = _emit(
            state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
        )
        events.append(e)
        return state, events

    # 首日：公布死讯前竞选
    if (
        state.round == 1
        and state.config.sheriff.enabled
        and state.config.sheriff.election_before_first_death_announce
    ):
        state = state.model_copy(update={"night_deaths": ordered, "election_stage": "candidacy"})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.SHERIFF_ELECTION),
            Visibility.PUBLIC,
        )
        return state, [*events, e]

    return _announce_and_continue_night(state, ordered, events)


def _announce_and_continue_night(
    state: GameState, ordered: tuple[int, ...], events: list[Event]
) -> tuple[GameState, list[Event]]:
    state, e = _emit(
        state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC
    )
    events.append(e)
    winner2 = check_win(state)
    if winner2 is not None:
        state, e = _emit(
            state, EventType.GAME_OVER, GameOverPayload(winner=winner2), Visibility.PUBLIC
        )
        events.append(e)
        return state, events

    # 夜间猎人开枪（被毒不可）
    shooter = _dead_hunter_can_shoot(
        state, frozenset(ordered), state.pending_night.witch_poison_target
    )
    if shooter is not None:
        state = state.model_copy(
            update={
                "pending_hunter": shooter,
                "resume_token": "night_after_hunter",
                "night_deaths": ordered,
            }
        )
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.HUNTER_SHOOT),
            Visibility.PUBLIC,
        )
        return state, [*events, e]

    return _finish_night_deaths(state, ordered, events)


def _advance_election(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    if state.election_stage == "direction":
        # 方向子阶段必有存活警长为行动者；到达此处说明不变量被破坏
        raise EngineInvariantError("方向决策阶段不应无行动者")
    if state.election_stage == "announce":
        state = state.model_copy(update={"election_stage": ""})
        return _announce_and_continue_night(state, state.night_deaths, events)
    if state.election_stage == "candidacy":
        # 全员声明完毕
        if not state.sheriff_candidates:
            return _finish_election(state, elected=None, events=events)
        state = state.model_copy(update={"election_stage": "vote", "sheriff_votes": {}})
        return state, events  # 进入 vote 阶段，等待警下投票
    # vote 阶段收尾
    weights = {s: 1.0 for s in living_seats(state)}
    elected, tie = count_votes(state.sheriff_votes, weights)
    if elected is not None:
        return _finish_election(state, elected=elected, events=events)
    if tie and state.phase == Phase.SHERIFF_ELECTION:
        # 进入 PK：候选缩小为平票者
        state = state.model_copy(update={"sheriff_candidates": tie, "sheriff_votes": {}})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.SHERIFF_PK),
            Visibility.PUBLIC,
        )
        return state, [e]
    # PK 再平票 -> 警徽流失
    return _finish_election(state, elected=None, events=events)


def _finish_election(
    state: GameState, elected: int | None, events: list[Event]
) -> tuple[GameState, list[Event]]:
    state, e = _emit(
        state, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=elected), Visibility.PUBLIC
    )
    events.append(e)
    if elected is not None and state.config.speech_order_rule == SpeechOrderRule.SHERIFF_DECIDES:
        # 警长先定发言方向，再公布死讯；若当选经 PK 产生（phase 仍为 SHERIFF_PK），
        # 需先切回 SHERIFF_ELECTION 阶段，方向子阶段的 expected_actors 才能被正确识别
        if state.phase != Phase.SHERIFF_ELECTION:
            state, e2 = _emit(
                state,
                EventType.PHASE_CHANGED,
                PhaseChangedPayload(to=Phase.SHERIFF_ELECTION),
                Visibility.PUBLIC,
            )
            events.append(e2)
        state = state.model_copy(update={"election_stage": "direction"})
        return state, events
    state = state.model_copy(update={"election_stage": ""})
    # 竞选结束 -> 回到「公布死讯并继续」
    return _announce_and_continue_night(state, state.night_deaths, events)


def _auto_badge_if_orphaned(
    state: GameState, recipients: tuple[int, ...]
) -> tuple[GameState, list[Event]]:
    """警长死亡但本轮无遗言机会覆盖其发言时，自动撕警徽兜底（防止警徽悬空）。"""
    if state.sheriff_seat is not None:
        holder = player_at(state, state.sheriff_seat)
        if not holder.alive and state.sheriff_seat not in recipients:
            s, e = _emit(
                state,
                EventType.BADGE_PASSED,
                BadgePassedPayload(from_seat=state.sheriff_seat, to_seat=None),
                Visibility.PUBLIC,
                actor=state.sheriff_seat,
            )
            return s, [e]
    return state, []


def _finish_night_deaths(
    state: GameState, ordered: tuple[int, ...], events: list[Event]
) -> tuple[GameState, list[Event]]:
    recipients = _last_words_recipients(state, ordered, is_night=True)
    state, badge_ev = _auto_badge_if_orphaned(state, recipients)
    events = [*events, *badge_ev]
    if recipients:
        state = state.model_copy(update={"resume_token": "day_speech"})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.LAST_WORDS, speech_order=recipients),
            Visibility.PUBLIC,
        )
        return state, [*events, e]
    state, ev = _enter_day_speech(state)
    return state, [*events, *ev]


def _check_win_with_deaths(state: GameState, deaths: frozenset[int]) -> str | None:
    if not deaths:
        return check_win(state)
    players = state.players
    for seat in deaths:
        players = tuple(
            pl.model_copy(update={"alive": False}) if pl.seat == seat else pl for pl in players
        )
    hypo = state.model_copy(update={"players": players})
    return check_win(hypo)


def _speech_order(state: GameState) -> tuple[int, ...]:
    alive = living_seats(state)
    if not alive:
        return ()
    rule = state.config.speech_order_rule
    n = state.config.num_players

    def _clockwise_from(start: int) -> tuple[int, ...]:
        seq = [(start + i) % n for i in range(n)]
        return tuple(s for s in seq if s in alive)

    def _counterclockwise_from(start: int) -> tuple[int, ...]:
        seq = [(start - i) % n for i in range(n)]
        return tuple(s for s in seq if s in alive)

    def _death_next_order() -> tuple[int, ...]:
        last_death = (
            max(state.night_deaths)
            if state.night_deaths
            else (state.day_exiled if state.day_exiled is not None else -1)
        )
        return _clockwise_from((last_death + 1) % n) if last_death >= 0 else tuple(alive)

    if rule == SpeechOrderRule.FIXED_CLOCKWISE or rule == SpeechOrderRule.BIDDING:
        return tuple(alive)  # BIDDING 下顺序仅占位；Speak 会被拒
    if rule == SpeechOrderRule.DEATH_NEXT:
        return _death_next_order()
    if rule == SpeechOrderRule.ODD_EVEN_CLOCK:
        base = _clockwise_from(alive[0])
        return base if state.round % 2 == 1 else tuple(reversed(base))
    # SHERIFF_DECIDES：警长在场且已定向 -> 按基准方向 + 奇偶换手；否则退回 death-next
    if state.sheriff_seat is not None and state.sheriff_speech_direction is not None:
        base_dir = state.sheriff_speech_direction
        # 竞选在 round 1：奇数天用基准方向，偶数天换手
        opposite = "LEFT" if base_dir == "RIGHT" else "RIGHT"
        effective = base_dir if state.round % 2 == 1 else opposite
        if effective == "RIGHT":
            return _clockwise_from((state.sheriff_seat + 1) % n)
        return _counterclockwise_from((state.sheriff_seat - 1) % n)
    return _death_next_order()


def _enter_day_speech(state: GameState) -> tuple[GameState, list[Event]]:
    order = _speech_order(state)
    s, e = _emit(
        state,
        EventType.PHASE_CHANGED,
        PhaseChangedPayload(to=Phase.DAY_SPEECH, speech_order=order),
        Visibility.PUBLIC,
    )
    return s, [e]


def _tally_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    weights = {
        p.seat: (state.config.sheriff.vote_weight if p.is_sheriff else 1.0) for p in living(state)
    }
    exiled, tie = count_votes(state.votes, weights)
    tally = tuple(
        sorted(
            (
                (seat, weights_sum(state.votes, weights, seat))
                for seat in _voted_targets(state.votes)
            ),
            key=lambda x: x[0],
        )
    )
    state, e = _emit(
        state,
        EventType.VOTE_RESULT,
        VoteResultPayload(tally=tally, exiled=exiled, tie_seats=tie),
        Visibility.PUBLIC,
    )
    events.append(e)

    if exiled is not None:
        exiled_pl = player_at(state, exiled)
        if exiled_pl.role == RoleType.IDIOT and not exiled_pl.idiot_revealed:
            # 白痴翻牌：免死一次、失投票权，当天投票作废，直接进入下一夜
            state, e = _emit(
                state,
                EventType.PHASE_CHANGED,
                PhaseChangedPayload(to=Phase.IDIOT_FLIP),
                Visibility.PUBLIC,
            )
            events.append(e)
            state, e = _emit(
                state,
                EventType.IDIOT_REVEALED,
                IdiotRevealedPayload(seat=exiled),
                Visibility.PUBLIC,
                actor=exiled,
            )
            events.append(e)
            state, ev = _after_day_death(state)
            return state, [*events, *ev]
        state, e = _emit(
            state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE), Visibility.PUBLIC
        )
        events.append(e)
        state, e = _emit(
            state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=exiled), Visibility.PUBLIC
        )
        events.append(e)
        # EXILE 阶段的后续（猎人/白痴/遗言/胜负）交给 advance 再次进入 EXILE 分支处理
        return state, events

    # 平票
    if tie and state.tie_round == 0 and state.config.tie_rule.name.startswith("PK"):
        # 进入 PK：平票者发言 + 其余人重投（Stage 1 简化为直接重投，PK 发言在 Stage 3 补）
        state, e = _emit(
            state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK), Visibility.PUBLIC
        )
        events.append(e)
        state, e = _emit(
            state,
            EventType.VOTE_STARTED,
            VoteStartedPayload(candidates=tie, tie_round=1),
            Visibility.PUBLIC,
        )
        events.append(e)
        return state, events

    # 再平票或 NO_EXILE：无人出局
    if state.config.tie_rule.name == "PK_THEN_RANDOM" and tie:
        seed = state.config.seed if state.config.seed is not None else 0
        idx = rng.derive_int(seed=seed, purpose="tie", seq=state.rng_state, modulo=len(tie))
        chosen = sorted(tie)[idx]
        state, e = _emit(
            state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE), Visibility.PUBLIC
        )
        events.append(e)
        state, e = _emit(
            state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=chosen), Visibility.PUBLIC
        )
        events.append(e)
        return state, events

    state, e = _emit(
        state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=None), Visibility.PUBLIC
    )
    events.append(e)
    state, ev = _after_day_death(state)
    return state, [*events, *ev]


def _voted_targets(votes: dict[int, int | None]) -> set[int]:
    return {t for t in votes.values() if t is not None}


def weights_sum(votes: dict[int, int | None], weights: dict[int, float], target: int) -> float:
    return sum(weights.get(voter, 1.0) for voter, t in votes.items() if t == target)


def _after_exile(state: GameState) -> tuple[GameState, list[Event]]:
    exiled = state.day_exiled
    if exiled is not None:
        pl = player_at(state, exiled)
        if pl.role == RoleType.HUNTER and pl.hunter_can_shoot:
            state = state.model_copy(
                update={"pending_hunter": exiled, "resume_token": "day_after_hunter"}
            )
            state, e = _emit(
                state,
                EventType.PHASE_CHANGED,
                PhaseChangedPayload(to=Phase.HUNTER_SHOOT),
                Visibility.PUBLIC,
            )
            return state, [e]
    return _enter_day_last_words(state, extra=())


def _enter_day_last_words(
    state: GameState, extra: tuple[int, ...]
) -> tuple[GameState, list[Event]]:
    dead_today = tuple(
        sorted(set(([state.day_exiled] if state.day_exiled is not None else []) + list(extra)))
    )
    recipients = _last_words_recipients(state, dead_today, is_night=False)
    state, badge_ev = _auto_badge_if_orphaned(state, recipients)
    if recipients:
        state = state.model_copy(update={"resume_token": "after_day"})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.LAST_WORDS, speech_order=recipients),
            Visibility.PUBLIC,
        )
        return state, [*badge_ev, e]
    state, ev = _after_day_death(state)
    return state, [*badge_ev, *ev]


def _after_day_death(state: GameState) -> tuple[GameState, list[Event]]:
    winner = check_win(state)
    if winner is not None:
        state, e = _emit(
            state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
        )
        return state, [e]
    if state.round >= state.config.max_rounds:
        state, e = _emit(
            state, EventType.GAME_OVER, GameOverPayload(winner=None), Visibility.PUBLIC
        )
        return state, [e]
    state, ev = _begin_night(state, first=False)
    return state, ev
