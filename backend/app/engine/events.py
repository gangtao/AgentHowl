"""事件溯源：类型化 payload、Event、reduce。

reduce 是唯一写路径。state = reduce_all(initial, events)。
每个事件应用后 state_version += 1，rng_state 由使用随机的事件在 payload 里带出新值。
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.engine.config import Faction, RoleType, faction_of
from app.engine.phases import Phase
from app.engine.state import GameState, NightActions, Player


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"
    WOLVES = "WOLVES"
    ROLE_SELF = "ROLE_SELF"
    GM_ONLY = "GM_ONLY"


class EventType(StrEnum):
    GAME_CREATED = "GAME_CREATED"
    ROLES_ASSIGNED = "ROLES_ASSIGNED"
    GAME_STARTED = "GAME_STARTED"
    ROUND_STARTED = "ROUND_STARTED"
    PHASE_CHANGED = "PHASE_CHANGED"
    GUARD_PROTECTED = "GUARD_PROTECTED"
    WOLF_KILL_PROPOSED = "WOLF_KILL_PROPOSED"
    WOLF_KILL_DECIDED = "WOLF_KILL_DECIDED"
    WITCH_SAVED = "WITCH_SAVED"
    WITCH_POISONED = "WITCH_POISONED"
    SEER_CHECKED = "SEER_CHECKED"
    NIGHT_RESOLVED = "NIGHT_RESOLVED"
    DEATH_ANNOUNCED = "DEATH_ANNOUNCED"
    PLAYER_SPOKE = "PLAYER_SPOKE"
    VOTE_STARTED = "VOTE_STARTED"
    VOTE_CAST = "VOTE_CAST"
    VOTE_RESULT = "VOTE_RESULT"
    PLAYER_EXILED = "PLAYER_EXILED"
    ROLE_SKIPPED = "ROLE_SKIPPED"
    GAME_OVER = "GAME_OVER"
    WITCH_POTION_CONSUMED = "WITCH_POTION_CONSUMED"
    # Stage 2/3 追加：LAST_WORDS, HUNTER_SHOT, IDIOT_REVEALED,
    # SHERIFF_CANDIDACY, SHERIFF_WITHDREW, SHERIFF_ELECTED, BADGE_PASSED,
    # WOLF_SELF_DESTRUCT ...
    LAST_WORDS = "LAST_WORDS"
    HUNTER_SHOT = "HUNTER_SHOT"
    IDIOT_REVEALED = "IDIOT_REVEALED"
    SHERIFF_CANDIDACY = "SHERIFF_CANDIDACY"
    SHERIFF_WITHDREW = "SHERIFF_WITHDREW"
    SHERIFF_VOTE_CAST = "SHERIFF_VOTE_CAST"
    SHERIFF_ELECTED = "SHERIFF_ELECTED"
    SHERIFF_BADGE_LOST = "SHERIFF_BADGE_LOST"
    BADGE_PASSED = "BADGE_PASSED"
    WOLF_SELF_DESTRUCT = "WOLF_SELF_DESTRUCT"


class EventPayload(BaseModel):
    model_config = ConfigDict(frozen=True)


class RolesAssignedPayload(EventPayload):
    # 座位->角色（GM_ONLY）；用 list[tuple] 以便确定性序列化
    assignments: tuple[tuple[int, RoleType], ...]
    new_rng_state: int


class RoundStartedPayload(EventPayload):
    round: int


class PhaseChangedPayload(EventPayload):
    to: Phase
    speech_order: tuple[int, ...] | None = None  # 进入 DAY_SPEECH/PK 发言时一并设定顺序


class VoteStartedPayload(EventPayload):
    candidates: tuple[int, ...]  # 空=全体存活可投；PK 时限定被投对象
    tie_round: int  # 0=首轮，1=PK


class GuardProtectedPayload(EventPayload):
    target: int | None  # None=空守


class WolfKillProposedPayload(EventPayload):
    wolf_seat: int
    target: int | None  # None=空刀


class WolfKillDecidedPayload(EventPayload):
    target: int | None  # None=空刀（含意见不统一）


class WitchActedPayload(EventPayload):
    save: bool = False
    poison_target: int | None = None


class SeerCheckedPayload(EventPayload):
    target: int
    result: Faction


class NightResolvedPayload(EventPayload):
    deaths: tuple[int, ...]


class DeathAnnouncedPayload(EventPayload):
    seats: tuple[int, ...]


class PlayerSpokePayload(EventPayload):
    content: str
    claim_role: RoleType | None = None
    badge_flow: tuple[int, ...] = ()


class VoteCastPayload(EventPayload):
    voter: int
    target: int | None  # None=弃票


class VoteResultPayload(EventPayload):
    tally: tuple[tuple[int, float], ...]  # (target_seat, weighted_votes)
    exiled: int | None
    tie_seats: tuple[int, ...]


class PlayerExiledPayload(EventPayload):
    seat: int | None  # None=无人出局


class RoleSkippedPayload(EventPayload):
    role: RoleType
    reason: str  # "absent" | "dead" | "no_potion" ...


class GameOverPayload(EventPayload):
    winner: str | None  # "GOOD" | "WOLF" | None(平局)


class WitchPotionConsumedPayload(EventPayload):
    seat: int
    antidote: bool = False
    poison: bool = False


class LastWordsPayload(EventPayload):
    seat: int
    content: str


class HunterShotPayload(EventPayload):
    shooter: int
    victim: int | None  # None=不开枪


class IdiotRevealedPayload(EventPayload):
    seat: int


class SheriffCandidacyPayload(EventPayload):
    seat: int
    running: bool  # True=上警, False=不上警


class SheriffVoteCastPayload(EventPayload):
    voter: int
    target: int | None


class SheriffElectedPayload(EventPayload):
    seat: int | None  # None=警徽流失


def _replace_player(
    players: tuple[Player, ...], seat: int, **updates: object
) -> tuple[Player, ...]:
    return tuple(p.model_copy(update=updates) if p.seat == seat else p for p in players)


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    game_id: str
    ts: float  # 纯引擎内是逻辑 tick；墙钟时间由 runtime(M2) 写入 meta
    type: EventType
    actor_seat: int | None = None
    payload: EventPayload
    visibility: Visibility
    meta: dict[str, str] = {}


def _actor(event: Event) -> int:
    if event.actor_seat is None:
        raise ValueError(f"事件 {event.type} 缺少 actor_seat")
    return event.actor_seat


def reduce(state: GameState, event: Event) -> GameState:
    """把单个事件应用到状态，返回新状态。唯一写路径。"""
    updates = _reduce_dispatch(state, event)
    updates["state_version"] = state.state_version + 1
    return state.model_copy(update=updates)


def _reduce_dispatch(state: GameState, event: Event) -> dict[str, object]:
    p = event.payload
    t = event.type

    if t == EventType.ROLES_ASSIGNED and isinstance(p, RolesAssignedPayload):
        role_by_seat = dict(p.assignments)
        players = tuple(
            pl.model_copy(
                update={
                    "role": role_by_seat[pl.seat],
                    "faction": faction_of(role_by_seat[pl.seat]),
                }
            )
            for pl in state.players
        )
        return {"players": players, "rng_state": p.new_rng_state}

    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        # 新的一夜：清空夜晚收集与投票暂存
        return {
            "round": p.round,
            "pending_night": NightActions(),
            "wolf_proposals": {},
            "acted_seats": frozenset(),
            "night_deaths": (),
            "votes": {},
            "vote_candidates": (),
            "tie_round": 0,
            "speech_order": (),
            "speech_idx": 0,
        }

    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        upd: dict[str, object] = {"phase": p.to}
        if p.speech_order is not None:
            upd["speech_order"] = p.speech_order
            upd["speech_idx"] = 0
        return upd

    if t == EventType.VOTE_STARTED and isinstance(p, VoteStartedPayload):
        return {"votes": {}, "vote_candidates": p.candidates, "tie_round": p.tie_round}

    if t == EventType.GUARD_PROTECTED and isinstance(p, GuardProtectedPayload):
        return {
            "pending_night": state.pending_night.model_copy(update={"guard_target": p.target}),
            "acted_seats": state.acted_seats | {_actor(event)},
            "players": _replace_player(state.players, _actor(event), last_guard_target=p.target),
        }

    if t == EventType.WOLF_KILL_PROPOSED and isinstance(p, WolfKillProposedPayload):
        proposals = dict(state.wolf_proposals)
        proposals[p.wolf_seat] = p.target
        return {
            "wolf_proposals": proposals,
            "acted_seats": state.acted_seats | {p.wolf_seat},
        }

    if t == EventType.WOLF_KILL_DECIDED and isinstance(p, WolfKillDecidedPayload):
        return {"pending_night": state.pending_night.model_copy(update={"wolf_target": p.target})}

    if t == EventType.WITCH_SAVED and isinstance(p, WitchActedPayload):
        return {
            "pending_night": state.pending_night.model_copy(update={"witch_save": True}),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.WITCH_POISONED and isinstance(p, WitchActedPayload):
        return {
            "pending_night": state.pending_night.model_copy(
                update={"witch_poison_target": p.poison_target}
            ),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        log = {k: list(v) for k, v in state.seer_log.items()}
        entry = {"round": state.round, "seat": p.target, "result": p.result.value}
        log.setdefault(_actor(event), []).append(entry)
        return {
            "pending_night": state.pending_night.model_copy(update={"seer_check": p.target}),
            "acted_seats": state.acted_seats | {_actor(event)},
            "seer_log": log,
        }

    if t == EventType.NIGHT_RESOLVED and isinstance(p, NightResolvedPayload):
        # 结算只记录死者名单；实际置死在 DEATH_ANNOUNCED（保证「结算/公布」两步可分别过滤可见性）
        return {"night_deaths": p.deaths, "resolved_first_night": True}

    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        players = state.players
        for seat in p.seats:
            players = _replace_player(players, seat, alive=False)
        return {"players": players}

    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        return {"speech_idx": state.speech_idx + 1}

    if t == EventType.VOTE_CAST and isinstance(p, VoteCastPayload):
        votes = dict(state.votes)
        votes[p.voter] = p.target
        return {"votes": votes}

    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        return {}  # 纯公示，不改状态；出局在 PLAYER_EXILED

    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        if p.seat is None:
            return {"day_exiled": None}
        players = _replace_player(state.players, p.seat, alive=False)
        return {"players": players, "day_exiled": p.seat}

    if t == EventType.LAST_WORDS and isinstance(p, LastWordsPayload):
        return {"speech_idx": state.speech_idx + 1}

    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        shot_updates: dict[str, object] = {"pending_hunter": None}
        if p.victim is not None:
            shot_updates["players"] = _replace_player(state.players, p.victim, alive=False)
        return shot_updates

    if t == EventType.IDIOT_REVEALED and isinstance(p, IdiotRevealedPayload):
        # 翻牌免死：不出局、失投票权、标记已翻
        players = _replace_player(state.players, p.seat, idiot_revealed=True, can_vote=False)
        return {"players": players}

    if t == EventType.ROLE_SKIPPED and isinstance(p, RoleSkippedPayload):
        # 玩家主动 skip（actor 非空）也算「已行动」；系统跳过缺席/死亡角色 actor 为 None
        if event.actor_seat is not None:
            return {"acted_seats": state.acted_seats | {event.actor_seat}}
        return {}

    if t == EventType.SHERIFF_CANDIDACY and isinstance(p, SheriffCandidacyPayload):
        declared = state.sheriff_declared | {p.seat}
        candidates = state.sheriff_candidates
        if p.running and p.seat not in candidates:
            candidates = (*candidates, p.seat)
        return {"sheriff_declared": declared, "sheriff_candidates": candidates}

    if t == EventType.SHERIFF_VOTE_CAST and isinstance(p, SheriffVoteCastPayload):
        sv = dict(state.sheriff_votes)
        sv[p.voter] = p.target
        return {"sheriff_votes": sv}

    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        if p.seat is None:
            return {"sheriff_seat": None}
        players = _replace_player(state.players, p.seat, is_sheriff=True)
        return {"sheriff_seat": p.seat, "players": players}

    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        return {"winner": p.winner, "phase": Phase.GAME_OVER}

    if t == EventType.WITCH_POTION_CONSUMED and isinstance(p, WitchPotionConsumedPayload):
        updates: dict[str, object] = {}
        if p.antidote:
            updates["witch_antidote"] = False
        if p.poison:
            updates["witch_poison"] = False
        return {"players": _replace_player(state.players, p.seat, **updates)}

    # GAME_CREATED / GAME_STARTED 仅审计
    return {}


def reduce_all(initial: GameState, events: Iterable[Event]) -> GameState:
    state = initial
    for ev in events:
        state = reduce(state, ev)
    return state
