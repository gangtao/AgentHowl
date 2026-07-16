"""测试用 LLM 客户端与 Action→决策 逆映射（issue #31）。仅测试进程使用，零网络。"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from app.agent.decisions import (
    NightDecision,
    SheriffDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
)
from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    SelfDestruct,
    SheriffAction,
    Speak,
)

RecordedCall = tuple[str, str, str]  # (model, system_prompt, user_prompt)


class ScriptedLLMClient:
    """按脚本函数返回决策；记录每次调用的 (model, system, user) 供 prompt 断言。"""

    def __init__(self, script: Callable[[type[BaseModel], str, str], BaseModel]) -> None:
        self._script = script
        self.calls: list[RecordedCall] = []

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        model: str,
        temperature: float = 0.3,
    ) -> BaseModel:
        self.calls.append((model, system_prompt, user_prompt))
        return self._script(response_model, system_prompt, user_prompt)


def action_to_decision(action: Action, response_model: type[BaseModel]) -> BaseModel:
    """引擎 Action → 决策模型的逆映射：集成测试里让脚本客户端复用 RandomBot 的合法行动。"""
    if response_model is WolfDeliberation:
        assert isinstance(action, NightAction) and action.target_seat is not None
        return WolfDeliberation(analysis="(scripted)", proposed_target=action.target_seat)
    if response_model is NightDecision:
        assert isinstance(action, NightAction)
        return NightDecision(
            reasoning="(scripted)", action_type=action.action_type, target_seat=action.target_seat
        )
    if response_model is SpeechDecision:
        if isinstance(action, SelfDestruct):
            return SpeechDecision(reasoning="(scripted)", content="", self_destruct=True)
        assert isinstance(action, Speak)
        return SpeechDecision(
            reasoning="(scripted)",
            content=action.content,
            claim_role=action.claim_role,
            badge_flow=list(action.badge_flow),
        )
    if response_model is VoteDecision:
        assert isinstance(action, DayVote)
        return VoteDecision(
            reasoning="(scripted)", target_seat=action.target_seat, abstain=action.abstain
        )
    assert response_model is SheriffDecision
    if isinstance(action, SelfDestruct):
        from app.engine.actions import SheriffActionType

        return SheriffDecision(
            reasoning="(scripted)",
            action_type=SheriffActionType.WITHDRAW,
            self_destruct=True,
        )
    assert isinstance(action, SheriffAction)
    return SheriffDecision(
        reasoning="(scripted)",
        action_type=action.action_type,
        target_seat=action.target_seat,
        direction=action.direction,
    )
