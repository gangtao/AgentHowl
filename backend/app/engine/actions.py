"""玩家行动意图模型（与 §4.1 工具 schema 一一对应）与拒绝原因。

行动只表达意图；是否合法由 engine.validate 裁决。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.engine.config import RoleType


class NightActionType(StrEnum):
    KILL = "kill"
    CHECK = "check"
    SAVE = "save"
    POISON = "poison"
    GUARD = "guard"
    SHOOT = "shoot"
    SKIP = "skip"


class SheriffActionType(StrEnum):
    RUN_FOR_SHERIFF = "run_for_sheriff"
    WITHDRAW = "withdraw"
    VOTE_SHERIFF = "vote_sheriff"
    PASS_BADGE = "pass_badge"
    TEAR_BADGE = "tear_badge"
    SET_SPEECH_DIRECTION = "set_speech_direction"


class Direction(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class RejectedReason(StrEnum):
    NOT_YOUR_TURN = "NOT_YOUR_TURN"
    WRONG_PHASE = "WRONG_PHASE"
    DEAD_ACTOR = "DEAD_ACTOR"
    DEAD_TARGET = "DEAD_TARGET"
    INVALID_TARGET = "INVALID_TARGET"
    ALREADY_ACTED = "ALREADY_ACTED"
    NOT_WEREWOLF = "NOT_WEREWOLF"
    GUARD_SAME_TARGET = "GUARD_SAME_TARGET"
    GUARD_SELF_FORBIDDEN = "GUARD_SELF_FORBIDDEN"
    WITCH_NO_ANTIDOTE = "WITCH_NO_ANTIDOTE"
    WITCH_NO_POISON = "WITCH_NO_POISON"
    WITCH_SELF_RESCUE_FORBIDDEN = "WITCH_SELF_RESCUE_FORBIDDEN"
    WITCH_TWO_POTIONS_FORBIDDEN = "WITCH_TWO_POTIONS_FORBIDDEN"
    HUNTER_CANNOT_SHOOT = "HUNTER_CANNOT_SHOOT"
    NOT_A_CANDIDATE = "NOT_A_CANDIDATE"
    CANNOT_VOTE = "CANNOT_VOTE"
    NOT_SELF_DESTRUCTABLE = "NOT_SELF_DESTRUCTABLE"
    BIDDING_NOT_IMPLEMENTED = "BIDDING_NOT_IMPLEMENTED"
    BADGE_FLOW_INVALID = "BADGE_FLOW_INVALID"


class NightAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    action_type: NightActionType
    target_seat: int | None = None


class DayVote(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    target_seat: int | None = None
    abstain: bool = False


class Speak(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    content: str
    claim_role: RoleType | None = None
    badge_flow: tuple[int, ...] = ()


class SheriffAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    action_type: SheriffActionType
    target_seat: int | None = None
    direction: Direction | None = None


class SelfDestruct(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int


Action = NightAction | DayVote | Speak | SheriffAction | SelfDestruct
