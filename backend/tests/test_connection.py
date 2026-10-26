"""ConnectionManager：按视角过滤广播，复用引擎 visible_events 口径（issue #29）。"""

import pytest

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


@pytest.mark.asyncio
async def test_broadcast_frame_reaches_visible_and_drops_bad_subscriber() -> None:
    """issue #110：帧随来源事件按视角过滤；坏订阅者摘除。"""
    cm = ConnectionManager(state_provider=_state)
    got: list[dict] = []

    async def good(frame: dict) -> None:
        got.append(frame)

    async def bad(frame: dict) -> None:
        raise RuntimeError("boom")

    cm.subscribe_frames("SPECTATOR", good)
    cm.subscribe_frames("SPECTATOR", bad)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 1}, _evt(1, Visibility.PUBLIC))
    await cm.broadcast_frame(
        {"type": "speech_audio_end", "seq": 1, "parts": 1}, _evt(1, Visibility.PUBLIC)
    )
    assert [f["type"] for f in got] == ["speech_audio", "speech_audio_end"]
    cm.unsubscribe_frames("SPECTATOR", good)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 2}, _evt(2, Visibility.PUBLIC))
    assert len(got) == 2


@pytest.mark.asyncio
async def test_frame_filtered_by_viewer() -> None:
    """Review Focus 3：GM_ONLY 只 GM 收；WOLVES 只狼座位（seat 0）与 GM 收；观众 / 村民不收。"""
    cm = ConnectionManager(state_provider=_state)
    got: dict[str, list[int]] = {"GM": [], "SPECTATOR": [], "wolf": [], "villager": []}

    def sub(name: str):  # type: ignore[no-untyped-def]
        async def cb(frame: dict) -> None:
            got[name].append(frame["seq"])

        return cb

    cm.subscribe_frames("GM", sub("GM"))
    cm.subscribe_frames("SPECTATOR", sub("SPECTATOR"))
    cm.subscribe_frames(0, sub("wolf"))
    cm.subscribe_frames(1, sub("villager"))
    await cm.broadcast_frame({"seq": 1}, _evt(1, Visibility.GM_ONLY))
    await cm.broadcast_frame({"seq": 2}, _evt(2, Visibility.WOLVES))
    await cm.broadcast_frame({"seq": 3}, _evt(3, Visibility.PUBLIC))
    assert got == {"GM": [1, 2, 3], "SPECTATOR": [3], "wolf": [2, 3], "villager": [3]}


def _night_evt(seq: int, to: Phase, vis: Visibility) -> Event:
    return Event(
        seq=seq,
        game_id="g",
        ts=float(seq),
        type=EventType.PHASE_CHANGED,
        actor_seat=None,
        payload=PhaseChangedPayload(to=to),
        visibility=vis,
    )


def test_public_phase_folds_night_subphases() -> None:
    from app.runtime.connection import public_phase

    assert public_phase(Phase.NIGHT_WEREWOLF) == "NIGHT"
    assert public_phase(Phase.NIGHT_SEER) == "NIGHT"
    assert public_phase(Phase.NIGHT_HUNTER_CONFIRM) == "NIGHT"
    assert public_phase(Phase.VOTE) == "VOTE"
    assert public_phase(Phase.SHERIFF_ELECTION) == "SHERIFF_ELECTION"


@pytest.mark.asyncio
async def test_phase_subscribers_get_folded_phases_without_events() -> None:
    """issue #128：夜间 PHASE_CHANGED 为 GM_ONLY，观众事件订阅收不到，
    阶段订阅仍要收到折叠后的阶段名。"""
    cm = ConnectionManager(_state)
    seen_events: list[list[Event]] = []
    seen_phases: list[list[tuple[str, int]]] = []

    async def spectator(evs: list[Event]) -> None:
        seen_events.append(evs)

    async def phases(ps: list[tuple[str, int]]) -> None:
        seen_phases.append(ps)

    cm.subscribe("SPECTATOR", spectator)
    cm.subscribe_phases(phases)
    await cm.broadcast(
        [
            _night_evt(1, Phase.NIGHT_WEREWOLF, Visibility.GM_ONLY),
            _night_evt(2, Phase.NIGHT_SEER, Visibility.GM_ONLY),
            _night_evt(3, Phase.VOTE, Visibility.PUBLIC),
        ]
    )
    assert [e.seq for evs in seen_events for e in evs] == [3]  # 事件订阅仍只见 PUBLIC
    assert seen_phases == [[("NIGHT", 1), ("NIGHT", 1), ("VOTE", 1)]]
    # 批次里没有 PHASE_CHANGED：阶段订阅不被调用
    seen_phases.clear()
    await cm.broadcast([_evt(4, Visibility.PUBLIC)])  # _evt 也是 PHASE_CHANGED(VOTE)
    assert seen_phases == [[("VOTE", 1)]]
    cm.unsubscribe_phases(phases)
    await cm.broadcast([_evt(5, Visibility.PUBLIC)])
    assert seen_phases == [[("VOTE", 1)]]


@pytest.mark.asyncio
async def test_raising_phase_subscriber_is_evicted() -> None:
    cm = ConnectionManager(_state)
    calls: list[int] = []

    async def bad(_ps: list[tuple[str, int]]) -> None:
        calls.append(1)
        raise RuntimeError("boom")

    cm.subscribe_phases(bad)
    await cm.broadcast([_evt(1, Visibility.PUBLIC)])
    await cm.broadcast([_evt(2, Visibility.PUBLIC)])
    assert calls == [1]
