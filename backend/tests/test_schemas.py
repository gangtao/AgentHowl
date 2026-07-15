"""schemas：工具调用 ↔ 引擎 Action 映射与防冒充（issue #30）。"""

import pytest

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
from app.schemas.actions import ToolCall, ToolCallError, parse_tool_call


def test_speak_mapping_with_claim_and_badge_flow() -> None:
    a = parse_tool_call(
        ToolCall(
            tool="speak",
            arguments={"content": "我是预言家", "claim_role": "SEER", "badge_flow": [3, 5]},
        ),
        actor_seat=4,
    )
    assert a == Speak(
        actor_seat=4,
        content="我是预言家",
        claim_role=RoleType.SEER,
        badge_flow=(3, 5),
    )


def test_speak_claim_none_maps_to_null() -> None:
    a = parse_tool_call(
        ToolCall(tool="speak", arguments={"content": "过", "claim_role": "NONE"}), 1
    )
    assert isinstance(a, Speak) and a.claim_role is None


def test_vote_abstain_and_target() -> None:
    assert parse_tool_call(ToolCall(tool="vote", arguments={"abstain": True}), 2) == DayVote(
        actor_seat=2, abstain=True
    )
    assert parse_tool_call(ToolCall(tool="vote", arguments={"target_seat": 7}), 2) == DayVote(
        actor_seat=2, target_seat=7
    )


def test_night_action_and_sheriff_action() -> None:
    a = parse_tool_call(
        ToolCall(tool="night_action", arguments={"action_type": "check", "target_seat": 3}), 5
    )
    assert a == NightAction(actor_seat=5, action_type=NightActionType.CHECK, target_seat=3)
    b = parse_tool_call(
        ToolCall(
            tool="sheriff_action",
            arguments={"action_type": "set_speech_direction", "direction": "LEFT"},
        ),
        6,
    )
    assert b == SheriffAction(
        actor_seat=6,
        action_type=SheriffActionType.SET_SPEECH_DIRECTION,
        direction=Direction.LEFT,
    )


def test_self_destruct_and_actor_seat_not_spoofable() -> None:
    a = parse_tool_call(ToolCall(tool="self_destruct", arguments={"actor_seat": 99}), 3)
    assert a == SelfDestruct(actor_seat=3)  # body 中 actor_seat 被忽略，一律取 token


def test_bad_tool_and_bad_args_raise_toolcallerror() -> None:
    with pytest.raises(ToolCallError):
        parse_tool_call(ToolCall(tool="no_such_tool"), 1)
    with pytest.raises(ToolCallError):
        parse_tool_call(ToolCall(tool="night_action", arguments={"action_type": "fly"}), 1)
    with pytest.raises(ToolCallError):
        parse_tool_call(ToolCall(tool="speak", arguments={}), 1)  # 缺 content
    with pytest.raises(ToolCallError):
        parse_tool_call(ToolCall(tool="bid_to_speak", arguments={"bid": 2}), 1)  # 未启用


def test_available_tools_by_phase() -> None:
    from app.engine.config import build_preset
    from app.engine.engine import create_game
    from app.engine.observation import build_observation
    from app.engine.phases import expected_actors
    from app.schemas.actions import available_tools_for

    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    seat = sorted(expected_actors(state))[0]
    tools = available_tools_for(build_observation(state, seat))
    assert "night_action" in tools and "get_game_state" in tools and "speak" not in tools
