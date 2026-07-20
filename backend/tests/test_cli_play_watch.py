"""CLI 看局（issue #44 Task 2）：全 bot 局经进程内 runner 叙述到终局。"""

import asyncio

from app.cli.play import _parse_view, _wire_game, run_watch
from app.engine.config import build_preset


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


def test_wire_game_threads_speech_and_reflection_models() -> None:
    """分层路由 CLI 旋钮：ai_model_speech / reflection_model 落到 AgentConfig。"""
    from app.agent.agent_player import AgentPlayerPort
    from app.cli.play import _wire_game
    from app.engine.config import build_preset

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _runner, _conns, ports = _wire_game(
        config,
        ai_model="ollama/a",
        ai_model_speech="ollama/b",
        reflection_model="ollama/c",
    )
    p = ports[0]
    assert isinstance(p, AgentPlayerPort)
    assert p._cfg.model == "ollama/a"
    assert p._cfg.model_speech == "ollama/b"
    assert p._cfg.reflection_model == "ollama/c"
