"""CLI 看局（issue #44 Task 2）：全 bot 局经进程内 runner 叙述到终局。"""

import argparse
import asyncio

import pytest

from app.cli.play import _parse_view, _positive_int, _wire_game, run_watch
from app.engine.config import build_preset


def test_wolf_rounds_rejects_non_positive() -> None:
    # F6（终审修复）：--wolf-rounds 0 应是 argparse 错误而非引擎里的 traceback
    assert _positive_int("2") == 2
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("0")


def test_parse_view() -> None:
    assert _parse_view("gm") == "GM"
    assert _parse_view("spectator") == "SPECTATOR"
    assert _parse_view("seat:3") == 3


def test_wire_game_ports_and_no_start() -> None:
    from app.runtime.player_port import BotPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    runner, conns, ports = _wire_game(config)
    assert len(ports) == 9 and all(isinstance(p, BotPlayerPort) for p in ports.values())
    assert runner is not None and conns is not None  # 未 run


def test_watch_game_narrates_to_gameover(capsys) -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def _no_read(prompt: str) -> str:  # step=False 时不会被调用
        raise AssertionError("看局非 step 模式不应读输入")

    state = asyncio.run(run_watch(config, view="GM", delay=0.0, step=False, read_line=_no_read))
    from app.engine.phases import Phase

    assert state.phase == Phase.GAME_OVER
    out = capsys.readouterr().out
    assert "游戏结束" in out  # GAME_OVER 叙述
    assert "第 1 轮" in out or "阶段" in out  # 有阶段/轮次叙述
    assert "[GM]" in out  # GM 视角含夜间内幕行


def test_watch_spectator_hides_gm_lines(capsys) -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def _no_read(prompt: str) -> str:
        raise AssertionError("不应读输入")

    asyncio.run(run_watch(config, view="SPECTATOR", delay=0.0, step=False, read_line=_no_read))
    out = capsys.readouterr().out
    assert "游戏结束" in out
    assert "[GM]" not in out  # 观战视角无夜间内幕


def test_wire_game_threads_profiles_per_seat() -> None:
    """每座位档案落到各自 AgentConfig；无档案座位为 BotPlayerPort；档案名进 roster。"""
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    agents = {
        "0": AgentProfile(name="老张", model="ollama/a", model_speech="ollama/b", thinking=True),
        "2": AgentProfile(model="ollama/c", reflection_model="ollama/d", temperature=0.9),
    }
    runner, _conns, ports = _wire_game(config, agents=agents)
    p0, p2 = ports[0], ports[2]
    assert isinstance(p0, AgentPlayerPort) and isinstance(p2, AgentPlayerPort)
    assert (p0._cfg.model, p0._cfg.model_speech, p0._cfg.thinking) == ("ollama/a", "ollama/b", True)
    assert (p2._cfg.model, p2._cfg.reflection_model, p2._cfg.temperature) == (
        "ollama/c",
        "ollama/d",
        0.9,
    )
    assert isinstance(ports[1], BotPlayerPort)
    assert runner._roster[0].display_name == "老张" and runner._roster[1].display_name == "P1"
    # 任一档案 thinking → 放宽超时
    from app.cli.play import _THINK_TIMEOUTS

    assert runner._timeouts == _THINK_TIMEOUTS


def test_wire_game_star_profile_and_human_seat() -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.cli.play import _CLI_TIMEOUTS
    from app.runtime.player_port import HumanPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    runner, _c, ports = _wire_game(
        config, human_seat=4, agents={"*": AgentProfile(model="ollama/z")}
    )
    assert isinstance(ports[4], HumanPlayerPort)
    assert all(isinstance(ports[s], AgentPlayerPort) for s in range(9) if s != 4)
    assert runner._timeouts == _CLI_TIMEOUTS


def test_load_agent_profiles_yaml_and_errors(tmp_path) -> None:
    from app.cli.play import load_agent_profiles

    good = tmp_path / "agents.yaml"
    good.write_text(
        'seats:\n  "0": {name: 老张, model: ollama/a, thinking: true}\n  "*": {model: ollama/b}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(good))
    assert agents["0"].name == "老张" and agents["0"].thinking is True
    assert agents["*"].model == "ollama/b"

    bad_key = tmp_path / "bad.yaml"
    bad_key.write_text('seats:\n  "0": {model: ollama/a, modle_speech: x}\n', encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError, match="bad.yaml"):
        load_agent_profiles(str(bad_key))

    no_seats = tmp_path / "noseats.yaml"
    no_seats.write_text("agents: {}\n", encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError, match="seats"):
        load_agent_profiles(str(no_seats))

    with pytest.raises(argparse.ArgumentTypeError):
        load_agent_profiles(str(tmp_path / "missing.yaml"))


def test_apply_wolf_knobs() -> None:
    from app.cli.play import _apply_wolf_knobs
    from app.engine.config import WolfKillRule, build_preset

    base = build_preset("std_9_kill_side")
    assert _apply_wolf_knobs(base, None, None) == base
    cfg = _apply_wolf_knobs(base, "majority", 3)
    assert cfg.wolf_kill_rule == WolfKillRule.MAJORITY and cfg.wolf_consensus_rounds == 3
    random_cfg = _apply_wolf_knobs(base, "random", None)
    assert random_cfg.wolf_kill_rule == WolfKillRule.RANDOM_PROPOSAL
    unanimous_cfg = _apply_wolf_knobs(base, "unanimous", 1)
    assert unanimous_cfg.wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
