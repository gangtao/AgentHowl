"""退水（issue #6）：SHERIFF_WITHDREW 事实、确认子阶段与投票权剥夺。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    SheriffWithdrewPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0,)) -> tuple[Player, ...]:
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
        "players": _players(n, wolves=(0, 1)),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_withdrew_event_reduces_out_of_candidates_into_withdrawn() -> None:
    st = _state(sheriff_candidates=(1, 2, 3), election_stage="withdraw")
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_WITHDREW,
        actor_seat=2,
        payload=SheriffWithdrewPayload(seat=2),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_candidates == (1, 3)
    assert new.sheriff_withdrawn == frozenset({2})
    assert st.sheriff_candidates == (1, 2, 3)  # 原状态不变
