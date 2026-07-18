"""CLI 玩局（issue #44 Task 3）：mini-syntax 解析 + 真人座经脚本 reader 跑完整局。"""

import asyncio

import pytest

from app.cli.play_human import CliInputError, parse_line, run_play
from app.engine.actions import (
    DayVote,
    NightAction,
    NightActionType,
    SelfDestruct,
    Speak,
)
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation
from app.engine.phases import Phase
from app.schemas.actions import parse_tool_call


def _obs(phase: str = "DAY_SPEECH") -> PlayerObservation:
    return PlayerObservation(
        game_id="g",
        state_version=1,
        my_seat=2,
        my_role=RoleType.VILLAGER,
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private={},
        available_actions=[2],
    )


def test_parse_line_speak_vote_night_selfdestruct() -> None:
    assert parse_tool_call(parse_line("speak 我怀疑3号", _obs()), actor_seat=2) == Speak(
        actor_seat=2, content="我怀疑3号"
    )
    assert parse_tool_call(parse_line("vote 3", _obs("VOTE")), actor_seat=2) == DayVote(
        actor_seat=2, target_seat=3
    )
    assert parse_tool_call(parse_line("vote abstain", _obs("VOTE")), actor_seat=2) == DayVote(
        actor_seat=2, abstain=True
    )
    assert parse_tool_call(
        parse_line("night check 5", _obs("NIGHT_SEER")), actor_seat=2
    ) == NightAction(actor_seat=2, action_type=NightActionType.CHECK, target_seat=5)
    assert parse_tool_call(
        parse_line("night skip", _obs("NIGHT_WITCH")), actor_seat=2
    ) == NightAction(actor_seat=2, action_type=NightActionType.SKIP)
    assert parse_tool_call(parse_line("self_destruct", _obs()), actor_seat=2) == SelfDestruct(
        actor_seat=2
    )


def test_parse_line_rejects_bad_input() -> None:
    with pytest.raises(CliInputError):
        parse_line("", _obs())
    with pytest.raises(CliInputError):
        parse_line("frobnicate 3", _obs())
    with pytest.raises(CliInputError):
        parse_line("vote", _obs("VOTE"))  # 缺目标且非 abstain


def _action_to_line(action: object) -> str:
    """测试用逆映射：RandomBot 合法行动 → mini-syntax 行。"""
    if isinstance(action, Speak):
        return f"speak {action.content or '过'}"
    if isinstance(action, DayVote):
        return "vote abstain" if action.abstain else f"vote {action.target_seat}"
    if isinstance(action, NightAction):
        if action.target_seat is None:
            return f"night {action.action_type.value}"
        return f"night {action.action_type.value} {action.target_seat}"
    if isinstance(action, SelfDestruct):
        return "self_destruct"
    from app.engine.actions import SheriffAction

    assert isinstance(action, SheriffAction)
    tail = ""
    if action.target_seat is not None:
        tail = f" {action.target_seat}"
    elif action.direction is not None:
        tail = f" {action.direction.value.lower()}"
    return f"sheriff {action.action_type.value}{tail}"


async def test_human_seat_plays_full_game_via_scripted_reader() -> None:
    from app.cli.bot import RandomBot

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    captured: dict[str, object] = {}

    async def reader(prompt: str) -> str:
        runner = captured["r"]
        return _action_to_line(RandomBot.choose_action(runner.state, 2))  # type: ignore[attr-defined]

    state = await asyncio.wait_for(
        run_play(config, seat=2, read_line=reader, on_wired=lambda r: captured.__setitem__("r", r)),
        timeout=120,
    )
    assert state.phase == Phase.GAME_OVER  # 真人座（脚本合法落子）整局跑通


async def test_human_bad_line_then_recovers(capsys) -> None:
    from app.cli.bot import RandomBot

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    captured: dict[str, object] = {}
    calls = {"n": 0}

    async def reader(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "garbage nonsense"  # 首次非法 → 应提示并重读，不卡死
        runner = captured["r"]
        return _action_to_line(RandomBot.choose_action(runner.state, 2))  # type: ignore[attr-defined]

    state = await asyncio.wait_for(
        run_play(config, seat=2, read_line=reader, on_wired=lambda r: captured.__setitem__("r", r)),
        timeout=120,
    )
    assert state.phase == Phase.GAME_OVER
    assert "⚠" in capsys.readouterr().out  # 非法输入被提示
