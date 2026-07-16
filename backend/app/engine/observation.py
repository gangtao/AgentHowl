"""信息隔离：per-seat observation 与事件可见性过滤。此为唯一过滤点（安全边界）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.engine.config import Faction, RoleType
from app.engine.events import Event, Visibility
from app.engine.phases import expected_actors
from app.engine.state import GameState, living_wolves, player_at

Viewer = int | Literal["SPECTATOR", "GM"]


class PlayerObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    state_version: int
    my_seat: int
    my_role: RoleType
    my_status: Literal["ALIVE", "DEAD"]
    phase: str
    round: int
    seats: list[dict[str, Any]]
    sheriff_seat: int | None
    badge_flow_claims: dict[int, tuple[int, ...]]  # 公开的警徽流声明（speaker -> 座位序列）
    private: dict[str, Any]
    # issue #31：竞选/PK 公开信息（全场可见事实，供 agent 无 state 决策）
    election_stage: str = ""
    sheriff_candidates: list[int] = []
    vote_candidates: list[int] = []
    pk_speech_pending: bool = False
    available_actions: list[int]  # M1：当前是否轮到本人（空=否）；M2 换成工具名


def _public_seats(state: GameState) -> list[dict[str, Any]]:
    return [
        {
            "seat": p.seat,
            "alive": p.alive,
            "is_sheriff": p.is_sheriff,
            "idiot_revealed": p.idiot_revealed,
        }
        for p in state.players
    ]


def build_observation(state: GameState, seat: int) -> PlayerObservation:
    me = player_at(state, seat)
    private: dict[str, Any] = {}

    if me.alive:
        if me.faction == Faction.WOLF:
            private["teammates"] = sorted(w.seat for w in living_wolves(state) if w.seat != seat)
            private["wolf_chat"] = []  # M1 无私聊内容；结构预留
            if state.pending_night.wolf_target is not None:
                private["tonight_kill_proposal"] = state.pending_night.wolf_target

        if me.role == RoleType.SEER:
            private["check_results"] = _seer_results(state, seat)

        if me.role == RoleType.WITCH:
            private["antidote_available"] = me.witch_antidote
            private["poison_available"] = me.witch_poison
            killed = state.pending_night.wolf_target
            knows = me.witch_antidote or state.config.witch.knows_kill_after_antidote_used
            if killed is not None and knows:
                private["tonight_killed_seat"] = killed

        if me.role == RoleType.GUARD:
            private["last_guard_target"] = me.last_guard_target

        if me.role == RoleType.HUNTER:
            private["can_shoot"] = me.hunter_can_shoot

    return PlayerObservation(
        game_id=state.game_id,
        state_version=state.state_version,
        my_seat=seat,
        my_role=me.role,
        my_status="ALIVE" if me.alive else "DEAD",
        phase=state.phase.value,
        round=state.round,
        seats=_public_seats(state),
        sheriff_seat=state.sheriff_seat,
        badge_flow_claims=dict(state.badge_flow_claims),
        private=private,
        election_stage=state.election_stage,
        sheriff_candidates=sorted(state.sheriff_candidates),
        vote_candidates=sorted(state.vote_candidates),
        pk_speech_pending=state.speech_idx < len(state.speech_order),
        available_actions=[seat] if seat in expected_actors(state) else [],
    )


def _seer_results(state: GameState, seat: int) -> list[dict[str, Any]]:
    """预言家验人历史：从 GameState.seer_log 累积读取（跨夜持久，见 SEER_CHECKED reduce）。"""
    return list(state.seer_log.get(seat, []))


def visible_events(state: GameState, events: list[Event], viewer: Viewer) -> list[Event]:
    if viewer == "GM":
        return list(events)
    if viewer == "SPECTATOR":
        return [e for e in events if e.visibility == Visibility.PUBLIC]

    wolf_seats = {p.seat for p in state.players if p.faction == Faction.WOLF}
    out: list[Event] = []
    for e in events:
        is_public = e.visibility == Visibility.PUBLIC
        is_visible_to_wolf = e.visibility == Visibility.WOLVES and viewer in wolf_seats
        is_own_role_self = e.visibility == Visibility.ROLE_SELF and e.actor_seat == viewer
        # GM_ONLY 永不对 seat 可见
        if is_public or is_visible_to_wolf or is_own_role_self:
            out.append(e)
    return out


def make_visibility_filter(state: GameState) -> Callable[[list[Event], Viewer], list[Event]]:
    def _f(events: list[Event], viewer: Viewer) -> list[Event]:
        return visible_events(state, events, viewer)

    return _f
