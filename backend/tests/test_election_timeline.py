"""竞选子阶段事件化（issue #17）：ELECTION_STAGE_CHANGED 契约与时间线重建。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    Visibility,
    reduce,
)
from app.engine.phases import ElectionStage, Phase
from app.engine.state import GameState, Player


def _base_state() -> GameState:
    players = tuple(
        Player(seat=s, display_name=f"P{s}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for s in range(4)
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.SHERIFF_ELECTION,
        players=players,
    )


def _stage_evt(stage: ElectionStage) -> Event:
    return Event(
        seq=1,
        game_id="g1",
        ts=1.0,
        type=EventType.ELECTION_STAGE_CHANGED,
        payload=ElectionStageChangedPayload(stage=stage),
        visibility=Visibility.PUBLIC,
    )


def test_election_stage_enum_values() -> None:
    assert ElectionStage.NONE.value == ""
    assert ElectionStage.CANDIDACY.value == "candidacy"
    assert ElectionStage.WITHDRAW.value == "withdraw"
    assert ElectionStage.VOTE.value == "vote"
    assert ElectionStage.DIRECTION.value == "direction"
    assert ElectionStage.ANNOUNCE.value == "announce"


def test_reduce_writes_election_stage() -> None:
    state = _base_state()
    new = reduce(state, _stage_evt(ElectionStage.WITHDRAW))
    assert new.election_stage == "withdraw"
    assert new.state_version == state.state_version + 1
    assert state.election_stage == ""  # 原状态不变（纯函数）
    back = reduce(new, _stage_evt(ElectionStage.NONE))
    assert back.election_stage == ""
