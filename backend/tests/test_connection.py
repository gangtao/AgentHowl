"""ConnectionManager：按视角过滤广播，复用引擎 visible_events 口径（issue #29）。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    PhaseChangedPayload,
    Visibility,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player
from app.runtime.connection import ConnectionManager


def _state() -> GameState:
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
        )
        for i in range(4)
    )
    return GameState(
        game_id="g",
        config=build_preset("std_9_kill_side"),
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
    )


def _evt(seq: int, vis: Visibility, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g",
        ts=float(seq),
        type=EventType.PHASE_CHANGED,
        actor_seat=actor,
        payload=PhaseChangedPayload(to=Phase.VOTE),
        visibility=vis,
    )


async def test_broadcast_filters_per_viewer() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    got: dict[str, list[Event]] = {"gm": [], "spec": [], "wolf": [], "villager": []}

    async def _mk(key: str):  # type: ignore[no-untyped-def]
        async def cb(events: list[Event]) -> None:
            got[key].extend(events)

        return cb

    mgr.subscribe("GM", await _mk("gm"))
    mgr.subscribe("SPECTATOR", await _mk("spec"))
    mgr.subscribe(0, await _mk("wolf"))  # 座位 0 是狼
    mgr.subscribe(1, await _mk("villager"))

    events = [
        _evt(1, Visibility.PUBLIC),
        _evt(2, Visibility.WOLVES),
        _evt(3, Visibility.ROLE_SELF, actor=1),
        _evt(4, Visibility.GM_ONLY),
    ]
    await mgr.broadcast(events)

    assert [e.seq for e in got["gm"]] == [1, 2, 3, 4]
    assert [e.seq for e in got["spec"]] == [1]
    assert [e.seq for e in got["wolf"]] == [1, 2]
    assert [e.seq for e in got["villager"]] == [1, 3]


async def test_unsubscribe_stops_delivery() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    got: list[Event] = []

    async def cb(events: list[Event]) -> None:
        got.extend(events)

    mgr.subscribe("GM", cb)
    await mgr.broadcast([_evt(1, Visibility.PUBLIC)])
    mgr.unsubscribe("GM", cb)
    await mgr.broadcast([_evt(2, Visibility.PUBLIC)])
    assert [e.seq for e in got] == [1]


async def test_empty_subset_not_called() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    calls: list[int] = []

    async def cb(events: list[Event]) -> None:
        calls.append(len(events))

    mgr.subscribe("SPECTATOR", cb)
    await mgr.broadcast([_evt(1, Visibility.GM_ONLY)])
    assert calls == []


async def test_raising_subscriber_is_evicted_others_delivered() -> None:
    """坏订阅者被摘除并告警，其余订阅者照常收流（issue #30 前置加固）。"""
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    got: list[int] = []

    async def bad(events: list[Event]) -> None:
        raise RuntimeError("坏连接")

    async def good(events: list[Event]) -> None:
        got.extend(e.seq for e in events)

    mgr.subscribe("GM", bad)
    mgr.subscribe("GM", good)
    await mgr.broadcast([_evt(1, Visibility.PUBLIC)])
    assert got == [1]  # bad 抛错不影响 good
    await mgr.broadcast([_evt(2, Visibility.PUBLIC)])
    assert got == [1, 2]  # bad 已被摘除，不再触发
