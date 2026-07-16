"""各阶段 LLM 决策模型与到引擎 Action 的纯映射（issue #31）。

只表达意图，不做合法性裁决——非法值由引擎拒绝、runner 重试兜底。
dispatch 分支镜像 app.cli.bot.RandomBot（同一阶段语义的唯一另一处实现）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.engine.actions import (
    Action,
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
from app.engine.phases import ElectionStage, Phase


class DecisionKind(StrEnum):
    NIGHT = "night"
    WOLF_NIGHT = "wolf_night"
    SPEECH = "speech"
    VOTE = "vote"
    SHERIFF = "sheriff"


class NightDecision(BaseModel):
    """夜间/猎人行动：先写推理，再给行动。"""

    reasoning: str
    action_type: NightActionType
    target_seat: int | None = None


class WolfDeliberation(BaseModel):
    """狼人夜间私有推理（独立 LLM 调用；analysis 只进 night_private 记忆分区）。"""

    analysis: str
    proposed_target: int


class SpeechDecision(BaseModel):
    reasoning: str
    content: str
    claim_role: RoleType | None = None
    badge_flow: list[int] = Field(default_factory=list)
    self_destruct: bool = False


class VoteDecision(BaseModel):
    reasoning: str
    target_seat: int | None = None
    abstain: bool = False


class SheriffDecision(BaseModel):
    reasoning: str
    action_type: SheriffActionType
    target_seat: int | None = None
    direction: Direction | None = None
    self_destruct: bool = False


_RESPONSE_MODELS: dict[DecisionKind, type[BaseModel]] = {
    DecisionKind.NIGHT: NightDecision,
    DecisionKind.WOLF_NIGHT: WolfDeliberation,
    DecisionKind.SPEECH: SpeechDecision,
    DecisionKind.VOTE: VoteDecision,
    DecisionKind.SHERIFF: SheriffDecision,
}


def response_model_for(kind: DecisionKind) -> type[BaseModel]:
    return _RESPONSE_MODELS[kind]


def _is_sheriff(obs: PlayerObservation) -> bool:
    return any(s.get("seat") == obs.my_seat and s.get("is_sheriff") for s in obs.seats)


def decision_kind_for(obs: PlayerObservation) -> DecisionKind:
    ph = Phase(obs.phase)
    if ph == Phase.NIGHT_WEREWOLF:
        return DecisionKind.WOLF_NIGHT
    if ph in (Phase.NIGHT_SEER, Phase.NIGHT_WITCH, Phase.NIGHT_GUARD, Phase.HUNTER_SHOOT):
        return DecisionKind.NIGHT
    if ph == Phase.DAY_SPEECH:
        return DecisionKind.SPEECH
    if ph == Phase.LAST_WORDS:
        return DecisionKind.SHERIFF if _is_sheriff(obs) else DecisionKind.SPEECH
    if ph == Phase.VOTE:
        return DecisionKind.VOTE
    if ph == Phase.VOTE_PK:
        return DecisionKind.SPEECH if obs.pk_speech_pending else DecisionKind.VOTE
    if ph == Phase.SHERIFF_PK:
        return DecisionKind.SPEECH if obs.pk_speech_pending else DecisionKind.SHERIFF
    if ph == Phase.SHERIFF_ELECTION:
        return DecisionKind.SHERIFF
    # 未映射阶段回退发言（镜像 RandomBot 兜底；如 NIGHT_HUNTER_CONFIRM）
    return DecisionKind.SPEECH


def to_action(kind: DecisionKind, decision: BaseModel, seat: int) -> Action:
    if kind is DecisionKind.WOLF_NIGHT:
        assert isinstance(decision, WolfDeliberation)
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.KILL,
            target_seat=decision.proposed_target,
        )
    if kind is DecisionKind.NIGHT:
        assert isinstance(decision, NightDecision)
        return NightAction(
            actor_seat=seat, action_type=decision.action_type, target_seat=decision.target_seat
        )
    if kind is DecisionKind.SPEECH:
        assert isinstance(decision, SpeechDecision)
        if decision.self_destruct:
            return SelfDestruct(actor_seat=seat)
        return Speak(
            actor_seat=seat,
            content=decision.content,
            claim_role=decision.claim_role,
            badge_flow=tuple(decision.badge_flow),
        )
    if kind is DecisionKind.VOTE:
        assert isinstance(decision, VoteDecision)
        return DayVote(actor_seat=seat, target_seat=decision.target_seat, abstain=decision.abstain)
    assert isinstance(decision, SheriffDecision)
    if decision.self_destruct:
        return SelfDestruct(actor_seat=seat)
    return SheriffAction(
        actor_seat=seat,
        action_type=decision.action_type,
        target_seat=decision.target_seat,
        direction=decision.direction,
    )


__all__ = [
    "DecisionKind",
    "ElectionStage",
    "NightDecision",
    "SheriffDecision",
    "SpeechDecision",
    "VoteDecision",
    "WolfDeliberation",
    "decision_kind_for",
    "response_model_for",
    "to_action",
]
