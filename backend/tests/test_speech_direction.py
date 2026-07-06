"""警长发言方向（issue #2）：方向事实、顺序计算与竞选后决策点。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    SheriffDirectionSetPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, sheriff: int | None = None, dead: tuple[int, ...] = ()) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
            alive=(i not in dead),
            is_sheriff=(i == sheriff),
        )
        for i in range(n)
    )


def _state(n: int = 5, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_direction_set_event_reduces_into_state() -> None:
    st = _state()
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_DIRECTION_SET,
        actor_seat=2,
        payload=SheriffDirectionSetPayload(direction="LEFT"),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_speech_direction == "LEFT"
    assert st.sheriff_speech_direction is None  # 原状态不变
    assert new.state_version == st.state_version + 1


def _day_state(
    sheriff: int | None,
    direction: str | None,
    round_: int,
    dead: tuple[int, ...] = (),
    night_deaths: tuple[int, ...] = (),
) -> GameState:
    return _state(
        n=5,
        phase=Phase.DAY_SPEECH,
        round=round_,
        players=_players(5, sheriff=sheriff, dead=dead),
        sheriff_seat=sheriff,
        sheriff_speech_direction=direction,
        night_deaths=night_deaths,
    )


def test_right_is_clockwise_from_sheriff_next() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警右：3,4,0,1,2
    assert _speech_order(_day_state(2, "RIGHT", 1)) == (3, 4, 0, 1, 2)


def test_left_is_counterclockwise_from_sheriff_prev() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警左：1,0,4,3,2
    assert _speech_order(_day_state(2, "LEFT", 1)) == (1, 0, 4, 3, 2)


def test_alternates_from_day_two() -> None:
    from app.engine.engine import _speech_order

    # 基准 RIGHT：round 2 换手 -> 实际 LEFT
    assert _speech_order(_day_state(2, "RIGHT", 2)) == (1, 0, 4, 3, 2)
    # round 3 换回 RIGHT
    assert _speech_order(_day_state(2, "RIGHT", 3)) == (3, 4, 0, 1, 2)


def test_dead_seats_skipped() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警右，座3已死：4,0,1,2
    assert _speech_order(_day_state(2, "RIGHT", 1, dead=(3,))) == (4, 0, 1, 2)


def test_no_sheriff_falls_back_to_death_next() -> None:
    from app.engine.engine import _speech_order

    # 无警长 + SHERIFF_DECIDES：退回死者下家顺时针（死者=2 -> 3,4,0,1）
    st = _day_state(None, None, 1, dead=(2,), night_deaths=(2,))
    assert _speech_order(st) == (3, 4, 0, 1)
