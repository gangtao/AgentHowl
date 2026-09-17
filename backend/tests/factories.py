"""测试专用工厂。Stage 1 用无猎人/白痴/警长的 9 人板跑通核心循环。"""

from __future__ import annotations

from app.engine.actions import Speak
from app.engine.config import (
    GameConfig,
    GuardRule,
    RoleSlot,
    RoleType,
    SheriffRule,
    WinCondition,
)
from app.engine.engine import step
from app.engine.events import Event
from app.engine.phases import campaign_speaking
from app.engine.state import GameState


def stage1_config(seed: int) -> GameConfig:
    """3 狼 + 3 民 + 预言家 + 女巫 + 守卫 = 9 人，屠边，无警长。"""
    return GameConfig(
        config_id="stage1_test",
        name="Stage1 测试板",
        num_players=9,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=3),
            RoleSlot(role=RoleType.VILLAGER, count=3),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.GUARD, count=1),
        ],
        win_condition=WinCondition.KILL_SIDE,
        night_order=[
            RoleType.GUARD,
            RoleType.WEREWOLF,
            RoleType.WITCH,
            RoleType.SEER,
        ],
        guard=GuardRule(),
        sheriff=SheriffRule(enabled=False),
        seed=seed,
    )


def run_campaign_speeches(
    state: GameState, content: str = "竞选发言"
) -> tuple[GameState, list[Event]]:
    """让上警发言队列里的候选人依次发言，直到离开 speech 子阶段（issue #47）。"""
    events: list[Event] = []
    while campaign_speaking(state):
        seat = state.speech_order[state.speech_idx]
        res = step(state, Speak(actor_seat=seat, content=content))
        assert res.rejection is None, res.rejection
        state = res.state
        events.extend(res.events)
    return state, events
