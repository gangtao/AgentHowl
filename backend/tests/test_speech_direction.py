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
