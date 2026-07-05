import pytest
from pydantic import ValidationError

from app.engine.config import Faction, RoleType, build_preset
from app.engine.phases import Phase
from app.engine.state import (
    GameState,
    NightActions,
    Player,
    living,
    living_seats,
    living_wolves,
    player_at,
)


def _mk_player(seat: int, role: RoleType, alive: bool = True) -> Player:
    return Player(
        seat=seat,
        display_name=f"P{seat}",
        player_type="AGENT",
        role=role,
        faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
        alive=alive,
    )


def _mk_state() -> GameState:
    players = (
        _mk_player(0, RoleType.WEREWOLF),
        _mk_player(1, RoleType.WEREWOLF, alive=False),
        _mk_player(2, RoleType.SEER),
        _mk_player(3, RoleType.VILLAGER),
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.NIGHT_WEREWOLF,
        round=1,
        players=players,
    )


def test_player_defaults() -> None:
    p = _mk_player(0, RoleType.WITCH)
    assert p.alive is True
    assert p.witch_antidote is True
    assert p.witch_poison is True
    assert p.hunter_can_shoot is True
    assert p.can_vote is True
    assert p.last_guard_target is None


def test_player_at_and_living() -> None:
    state = _mk_state()
    assert player_at(state, 2).role == RoleType.SEER
    assert living_seats(state) == [0, 2, 3]
    assert [p.seat for p in living(state)] == [0, 2, 3]
    assert [p.seat for p in living_wolves(state)] == [0]


def test_player_at_missing_raises() -> None:
    state = _mk_state()
    with pytest.raises(KeyError):
        player_at(state, 99)


def test_nightactions_defaults_empty() -> None:
    na = NightActions()
    assert na.guard_target is None
    assert na.wolf_target is None
    assert na.witch_save is False
    assert na.witch_poison_target is None
    assert na.seer_check is None


def test_gamestate_is_frozen() -> None:
    state = _mk_state()
    with pytest.raises(ValidationError):
        state.round = 2  # type: ignore[misc]
