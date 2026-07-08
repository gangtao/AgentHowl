"""全员上警裁决 + SHERIFF_BADGE_LOST（issue #9）。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    BadgeLostReason,
    Event,
    EventType,
    SheriffBadgeLostPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0, 1)) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(n: int = 6, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _badge_lost_events(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.SHERIFF_BADGE_LOST]


def test_badge_lost_reduce_strips_incumbent() -> None:
    # 移植 issue #19 的全化语义到新事件
    st = _state(sheriff_seat=2)
    players = tuple(
        p.model_copy(update={"is_sheriff": True}) if p.seat == 2 else p for p in st.players
    )
    st = st.model_copy(update={"players": players})
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_BADGE_LOST,
        actor_seat=None,
        payload=SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_seat is None
    assert not any(p.is_sheriff for p in new.players)
