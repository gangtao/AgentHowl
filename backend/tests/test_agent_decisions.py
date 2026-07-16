"""agent 决策模型与 Action 映射（issue #31 Task 2）：纯函数，零 LLM 零 IO。"""

import pytest

from app.agent.decisions import (
    DecisionKind,
    NightDecision,
    SheriffDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
    decision_kind_for,
    response_model_for,
    to_action,
)
from app.engine.actions import (
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SelfDestruct,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import RoleType
from app.engine.observation import PlayerObservation


def _obs(phase: str, **kw) -> PlayerObservation:
    """最小 observation 桩：仅 dispatch 所需字段有意义。"""
    seats = kw.pop("seats", [{"seat": 0, "alive": True, "is_sheriff": False}])
    return PlayerObservation(
        game_id="g_t",
        state_version=7,
        my_seat=0,
        my_role=kw.pop("my_role", RoleType.VILLAGER),
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=seats,
        sheriff_seat=None,
        badge_flow_claims={},
        private={},
        available_actions=[0],
        **kw,
    )


@pytest.mark.parametrize(
    ("phase", "kw", "expected"),
    [
        ("NIGHT_WEREWOLF", {}, DecisionKind.WOLF_NIGHT),
        ("NIGHT_SEER", {}, DecisionKind.NIGHT),
        ("NIGHT_WITCH", {}, DecisionKind.NIGHT),
        ("NIGHT_GUARD", {}, DecisionKind.NIGHT),
        ("HUNTER_SHOOT", {}, DecisionKind.NIGHT),
        ("DAY_SPEECH", {}, DecisionKind.SPEECH),
        ("VOTE", {}, DecisionKind.VOTE),
        ("VOTE_PK", {"pk_speech_pending": True}, DecisionKind.SPEECH),
        ("VOTE_PK", {"pk_speech_pending": False}, DecisionKind.VOTE),
        ("SHERIFF_ELECTION", {"election_stage": "candidacy"}, DecisionKind.SHERIFF),
        ("SHERIFF_ELECTION", {"election_stage": "vote"}, DecisionKind.SHERIFF),
        ("SHERIFF_PK", {"pk_speech_pending": True}, DecisionKind.SPEECH),
        ("SHERIFF_PK", {"pk_speech_pending": False}, DecisionKind.SHERIFF),
        # 未映射阶段回退发言（镜像 RandomBot 兜底分支）
        ("NIGHT_HUNTER_CONFIRM", {}, DecisionKind.SPEECH),
    ],
)
def test_dispatch(phase: str, kw: dict, expected: DecisionKind) -> None:
    assert decision_kind_for(_obs(phase, **kw)) is expected


def test_dispatch_last_words_sheriff_vs_plain() -> None:
    sheriff_seats = [{"seat": 0, "alive": True, "is_sheriff": True}]
    assert decision_kind_for(_obs("LAST_WORDS", seats=sheriff_seats)) is DecisionKind.SHERIFF
    assert decision_kind_for(_obs("LAST_WORDS")) is DecisionKind.SPEECH


def test_response_model_roundtrip() -> None:
    assert response_model_for(DecisionKind.WOLF_NIGHT) is WolfDeliberation
    assert response_model_for(DecisionKind.NIGHT) is NightDecision
    assert response_model_for(DecisionKind.SPEECH) is SpeechDecision
    assert response_model_for(DecisionKind.VOTE) is VoteDecision
    assert response_model_for(DecisionKind.SHERIFF) is SheriffDecision


def test_to_action_mappings() -> None:
    a1 = to_action(
        DecisionKind.WOLF_NIGHT, WolfDeliberation(analysis="x", proposed_target=3), seat=1
    )
    assert a1 == NightAction(actor_seat=1, action_type=NightActionType.KILL, target_seat=3)

    a2 = to_action(
        DecisionKind.NIGHT,
        NightDecision(reasoning="r", action_type=NightActionType.CHECK, target_seat=5),
        seat=2,
    )
    assert a2 == NightAction(actor_seat=2, action_type=NightActionType.CHECK, target_seat=5)

    a3 = to_action(
        DecisionKind.SPEECH,
        SpeechDecision(
            reasoning="r",
            content="大家好",
            claim_role=RoleType.SEER,
            badge_flow=[4, 5],
        ),
        seat=3,
    )
    assert a3 == Speak(actor_seat=3, content="大家好", claim_role=RoleType.SEER, badge_flow=(4, 5))

    a4 = to_action(DecisionKind.VOTE, VoteDecision(reasoning="r", target_seat=6), seat=4)
    assert a4 == DayVote(actor_seat=4, target_seat=6, abstain=False)

    a5 = to_action(DecisionKind.VOTE, VoteDecision(reasoning="r", abstain=True), seat=4)
    assert a5 == DayVote(actor_seat=4, target_seat=None, abstain=True)

    a6 = to_action(
        DecisionKind.SHERIFF,
        SheriffDecision(
            reasoning="r",
            action_type=SheriffActionType.SET_SPEECH_DIRECTION,
            direction=Direction.LEFT,
        ),
        seat=5,
    )
    assert a6 == SheriffAction(
        actor_seat=5,
        action_type=SheriffActionType.SET_SPEECH_DIRECTION,
        target_seat=None,
        direction=Direction.LEFT,
    )


def test_self_destruct_overrides() -> None:
    a = to_action(
        DecisionKind.SPEECH, SpeechDecision(reasoning="r", content="", self_destruct=True), seat=7
    )
    assert a == SelfDestruct(actor_seat=7)
    b = to_action(
        DecisionKind.SHERIFF,
        SheriffDecision(reasoning="r", action_type=SheriffActionType.WITHDRAW, self_destruct=True),
        seat=8,
    )
    assert b == SelfDestruct(actor_seat=8)
