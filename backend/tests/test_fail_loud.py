"""引擎 fail-loud（issue #4）：畸形事件在 reduce 处抛错；预留集合已随 issue #29 清空。"""

import pytest

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    EVENT_PAYLOAD_TYPES,
    DeathAnnouncedPayload,
    EngineInvariantError,
    Event,
    EventType,
    PhaseChangedPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _state() -> GameState:
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(4)
    )
    return GameState(
        game_id="g",
        config=build_preset("std_9_kill_side"),
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
    )


def _evt(type_: EventType, payload: object) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=type_,
        actor_seat=None,
        payload=payload,  # type: ignore[arg-type]
        visibility=Visibility.GM_ONLY,
    )


def test_mismatched_payload_raises() -> None:
    # 已知类型 + 错误 payload 类 -> 抛错（此前静默 bump state_version）
    ev = _evt(EventType.PHASE_CHANGED, DeathAnnouncedPayload(seats=(1,)))
    with pytest.raises(EngineInvariantError, match="payload"):
        reduce(_state(), ev)


def test_lifecycle_event_with_wrong_payload_raises() -> None:
    # GAME_CREATED 已实现：错误 payload 类 -> 抛 payload 错配（预留集合已清空，issue #29）
    ev = _evt(EventType.GAME_CREATED, PhaseChangedPayload(to=Phase.DAY_SPEECH))
    with pytest.raises(EngineInvariantError, match="payload"):
        reduce(_state(), ev)


def test_mapping_covers_exactly_implemented_types() -> None:
    reserved: set[EventType] = set()
    # 枚举新增成员时此断言强制作者决策：入映射（实现）或入 reserved（预留）
    assert set(EVENT_PAYLOAD_TYPES) == set(EventType) - reserved


def test_valid_event_still_reduces() -> None:
    ev = _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE))
    new = reduce(_state(), ev)
    assert new.phase == Phase.VOTE
    assert new.state_version == 1


def test_exception_reexported_from_engine() -> None:
    from app.engine.engine import EngineInvariantError as FromEngine

    assert FromEngine is EngineInvariantError


def test_apply_sheriff_vote_positive_path() -> None:
    # 正例：VOTE_SHERIFF 落入兜底并正常发射 SHERIFF_VOTE_CAST
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.engine import _apply_sheriff

    st = _state().model_copy(
        update={
            "phase": Phase.SHERIFF_ELECTION,
            "election_stage": "vote",
            "sheriff_candidates": (1,),
        }
    )
    new, events = _apply_sheriff(
        st,
        SheriffAction(actor_seat=2, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1),
    )
    assert [e.type for e in events] == [EventType.SHERIFF_VOTE_CAST]
    assert new.sheriff_votes == {2: 1}
