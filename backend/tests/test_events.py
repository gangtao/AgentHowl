from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    GuardProtectedPayload,
    PhaseChangedPayload,
    Visibility,
    reduce,
    reduce_all,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _base_state() -> GameState:
    players = tuple(
        Player(
            seat=s,
            display_name=f"P{s}",
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for s in range(4)
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.NIGHT_WEREWOLF,
        players=players,
    )


def _evt(seq: int, type_: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g1",
        ts=float(seq),
        type=type_,
        actor_seat=actor,
        payload=payload,  # type: ignore[arg-type]
        visibility=Visibility.GM_ONLY,
    )


def test_phase_changed_updates_phase_and_bumps_version() -> None:
    state = _base_state()
    ev = _evt(1, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WITCH))
    new = reduce(state, ev)
    assert new.phase == Phase.NIGHT_WITCH
    assert new.state_version == state.state_version + 1
    assert state.phase == Phase.NIGHT_WEREWOLF  # 原状态不变（纯函数）


def test_death_announced_marks_dead() -> None:
    state = _base_state()
    ev = _evt(1, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(2,)))
    new = reduce(state, ev)
    assert next(p for p in new.players if p.seat == 2).alive is False
    assert next(p for p in new.players if p.seat == 0).alive is True


def test_guard_protected_persists_last_guard_target() -> None:
    state = _base_state()
    ev = _evt(1, EventType.GUARD_PROTECTED, GuardProtectedPayload(target=3), actor=0)
    new = reduce(state, ev)
    assert next(pl for pl in new.players if pl.seat == 0).last_guard_target == 3


def test_reduce_all_applies_in_order() -> None:
    state = _base_state()
    events = [
        _evt(1, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(2,))),
        _evt(2, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH)),
    ]
    new = reduce_all(state, events)
    assert new.phase == Phase.DAY_SPEECH
    assert next(p for p in new.players if p.seat == 2).alive is False
    assert new.state_version == 2
