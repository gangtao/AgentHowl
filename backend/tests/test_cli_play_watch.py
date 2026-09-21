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


def test_wire_game_any_thinking_ignores_unused_profile() -> None:
    """F5（终审修复）：human_seat 顶掉的座位档案不参与 any_thinking 判断。"""
    from app.agent.profile import AgentProfile
    from app.cli.play import _CLI_TIMEOUTS

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    agents = {"0": AgentProfile(model="ollama/a", thinking=True)}
    runner, _conns, _ports = _wire_game(config, human_seat=0, agents=agents)
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

    dup_key = tmp_path / "dup.yaml"
    dup_key.write_text(
        'seats:\n  0: {model: ollama/a}\n  "0": {model: ollama/b}\n', encoding="utf-8"
    )
    with pytest.raises(argparse.ArgumentTypeError, match="重复"):
        load_agent_profiles(str(dup_key))


def test_main_rejects_conflict_and_bad_seat_and_orphan_knobs(tmp_path, capsys) -> None:
    from app.cli.play import main

    star = tmp_path / "star.yaml"
    star.write_text('seats:\n  "*": {model: ollama/a}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["--agents", str(star), "--ai-model", "ollama/b"])
    assert e.value.code == 2 and "agents['*']" in capsys.readouterr().err

    bad = tmp_path / "bad.yaml"
    bad.write_text('seats:\n  "9": {model: ollama/a}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["--agents", str(bad)])  # 默认 preset 9 人，座位 9 越界
    assert e.value.code == 2 and "座位" in capsys.readouterr().err

    with pytest.raises(SystemExit) as e:
        main(["--agents", str(star), "--thinking"])
    assert e.value.code == 2 and "--thinking" in capsys.readouterr().err


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


def test_wire_game_passes_skills_to_agent_ports(tmp_path) -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.agent.skills import SkillLibrary

    d = tmp_path / "ext-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: ext-skill\ndescription: d\n---\n外部正文\n", encoding="utf-8"
    )
    lib = SkillLibrary.load([tmp_path])
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _r, _c, ports = _wire_game(
        config, agents={"*": AgentProfile(model="m", skills=["ext-skill"])}, library=lib
    )
    p = ports[0]
    assert isinstance(p, AgentPlayerPort) and [s.name for s in p._skills] == ["ext-skill"]


def test_main_rejects_unknown_skill_and_accepts_skills_dir(tmp_path, capsys) -> None:
    from app.cli.play import main

    d = tmp_path / "skills" / "house"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: house\ndescription: d\n---\n正文\n", encoding="utf-8")
    agents = tmp_path / "agents.yaml"
    agents.write_text('seats:\n  "*": {model: ollama/a, skills: [house]}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:  # 未指定 --skills-dir → house 未知
        main(["--agents", str(agents)])
    assert e.value.code == 2 and "house" in capsys.readouterr().err
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit) as e:
        main(["--agents", str(agents), "--skills-dir", str(missing)])
    assert e.value.code == 2 and "目录" in capsys.readouterr().err


def test_load_agent_profiles_personality_and_guardrail(tmp_path) -> None:
    from app.cli.play import load_agent_profiles

    good = tmp_path / "p.yaml"
    good.write_text(
        'seats:\n  "0": {model: ollama/a,\n'
        "    personality: {description: 老油条, traits: {多疑: 0.9}}}\n"
        '  "3": {model: ollama/b, personality: {preset: {system: MBTI, value: enfp},\n'
        "    style_notes: 爱用感叹号}}\n",
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(good))
    assert agents["0"].personality is not None and agents["0"].personality.traits == {"多疑": 0.9}
    assert agents["3"].personality is not None and agents["3"].personality.preset is not None
    assert agents["3"].personality.preset.value == "ENFP"

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        'seats:\n  "0": {model: ollama/a, personality: {description: 你知道谁是狼}}\n',
        encoding="utf-8",
    )
    with pytest.raises(argparse.ArgumentTypeError, match="越权"):
        load_agent_profiles(str(bad))


def test_load_agent_profiles_memory_id_and_wire_passes_experience(tmp_path) -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.experience import AgentExperience
    from app.cli.play import load_agent_profiles, load_experiences
    from app.runtime.experience_store import InMemoryExperienceStore

    y = tmp_path / "p.yaml"
    y.write_text(
        'seats:\n  "0": {model: ollama/a, memory_id: alice}\n'
        '  "3": {model: ollama/b, memory_id: bob}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(y))
    assert agents["0"].memory_id == "alice" and agents["3"].memory_id == "bob"
    store = InMemoryExperienceStore()
    store.save(AgentExperience(memory_id="alice", games_played=2))
    exps = load_experiences(agents, 9, store)
    assert exps["alice"].games_played == 2 and exps["bob"].games_played == 0
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _r, _c, ports = _wire_game(config, agents=agents, experiences=exps)
    p0, p3 = ports[0], ports[3]
    assert isinstance(p0, AgentPlayerPort) and isinstance(p3, AgentPlayerPort)
    assert p0._experience is exps["alice"] and p0._opponents == {"bob": 3}
    assert p3._opponents == {"alice": 0}


def test_wire_game_human_seat_memory_id_is_inert(tmp_path) -> None:
    """终审 F1：human_seat 的 memory_id 档案不生效，其他座位也不把它当有记忆的对手。"""
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.experience import AgentExperience
    from app.agent.profile import AgentProfile
    from app.cli.play import load_experiences
    from app.runtime.experience_store import InMemoryExperienceStore

    store = InMemoryExperienceStore()
    store.save(AgentExperience(memory_id="alice", games_played=5))
    agents = {
        "0": AgentProfile(model="ollama/a", memory_id="alice"),
        "3": AgentProfile(model="ollama/b", memory_id="bob"),
    }
    exps = load_experiences(agents, 9, store, human_seat=0)
    assert set(exps) == {"bob"}  # alice 的档案不生效，其经验文件不读
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _r, _c, ports = _wire_game(config, human_seat=0, agents=agents, experiences=exps)
    p3 = ports[3]
    assert isinstance(p3, AgentPlayerPort)
    assert p3._opponents == {}  # 看不到 0 号（真人占座，不算有记忆的对手）


def test_load_experiences_human_seat_skips_corrupt_file(tmp_path) -> None:
    """终审 F1：真人座位的坏经验文件不应导致 load_experiences fail-loud（该文件根本不读）。"""
    from app.cli.play import load_agent_profiles, load_experiences
    from app.runtime.experience_store import JsonFileExperienceStore

    y = tmp_path / "p.yaml"
    y.write_text(
        'seats:\n  "0": {model: ollama/a, memory_id: alice}\n'
        '  "3": {model: ollama/b, memory_id: bob}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(y))
    d = tmp_path / "mem"
    d.mkdir()
    (d / "alice.json").write_text("{bad", encoding="utf-8")
    exps = load_experiences(agents, 9, JsonFileExperienceStore(d), human_seat=0)
    assert set(exps) == {"bob"}


def test_main_memory_dir_default_and_duplicate_memory_id(tmp_path, capsys) -> None:
    from app.cli.play import main

    y = tmp_path / "dup.yaml"
    y.write_text(
        'seats:\n  "0": {model: ollama/a, memory_id: a}\n  "1": {model: ollama/b, memory_id: a}\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main(["--agents", str(y)])
    assert "重复" in capsys.readouterr().err


def test_main_corrupt_memory_file_is_parser_error(tmp_path, capsys) -> None:
    """终审 F6：坏的经验文件在 main() 里应是明确的参数错误（退出码 2），不是裸 traceback。"""
    from app.cli.play import main

    y = tmp_path / "p.yaml"
    y.write_text('seats:\n  "0": {model: ollama/a, memory_id: alice}\n', encoding="utf-8")
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "alice.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--agents", str(y), "--memory-dir", str(mem), "--delay", "0"])
    assert "alice.json" in capsys.readouterr().err


def test_watch_game_with_memory_runs_postgame_and_persists(tmp_path, capsys, monkeypatch) -> None:
    """随机 bot 局 + 一个脚本化 Agent 座位配 memory_id：结束后复盘落盘并打印摘要。"""
    from pydantic import BaseModel

    import app.cli.play as play_mod
    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.experience import GameReflection
    from app.agent.memory import ReflectionResult
    from app.agent.profile import AgentProfile
    from app.cli.bot import RandomBot
    from app.runtime.experience_store import JsonFileExperienceStore
    from tests.llm_helpers import ScriptedLLMClient, action_to_decision

    holder: dict[str, object] = {}

    def fake_build_agent_port(
        seat, game_config, profile, *, library=None, experience=None, opponents=None
    ):
        def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
            if rm is ReflectionResult:
                return ReflectionResult(summary="(r)", qa=[])
            if rm is GameReflection:
                return GameReflection(lessons=["(cli lesson)"], opponent_notes={})
            runner = holder["runner"]
            return action_to_decision(RandomBot.choose_action(runner.state, seat), rm)  # type: ignore[attr-defined]

        return AgentPlayerPort(
            seat=seat,
            game_config=game_config,
            agent_config=AgentConfig(model="scripted"),
            client=ScriptedLLMClient(script),
            experience=experience,
            opponents=opponents,
        )

    import app.agent.agent_player as ap

    monkeypatch.setattr(ap, "build_agent_port", fake_build_agent_port)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    mem = tmp_path / "mem"
    store = JsonFileExperienceStore(mem)
    agents = {"0": AgentProfile(model="m", memory_id="alice")}

    async def _no_read(prompt: str) -> str:
        raise AssertionError("看局非 step 模式不应读输入")

    orig_wire = play_mod._wire_game

    def wire(config, **kw):
        out = orig_wire(config, **kw)
        holder["runner"] = out[0]
        return out

    monkeypatch.setattr(play_mod, "_wire_game", wire)
    state = asyncio.run(
        run_watch(
            config,
            view="GM",
            delay=0.0,
            step=False,
            agents=agents,
            experience_store=store,
            read_line=_no_read,
        )
    )
    from app.engine.phases import Phase

    assert state.phase == Phase.GAME_OVER
    out = capsys.readouterr().out
    assert "记忆 alice" in out.splitlines()[0]  # 档案表列
    assert "复盘中" in out and "记忆 alice：1 局，教训 1" in out
    assert store.load("alice").lessons[0].text == "(cli lesson)"


def test_wire_game_records_effective_profiles_in_meta() -> None:
    """issue #64：CLI 局的 meta.agents 同样只含实际建成 Agent 端口的座位（真人座位除外）。"""
    from app.agent.profile import AgentProfile

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    star, two = AgentProfile(model="ollama/z"), AgentProfile(model="ollama/two")
    runner, _c, _ports = _wire_game(config, human_seat=4, agents={"*": star, "2": two})
    expected = {str(s): (two if s == 2 else star) for s in range(9) if s != 4}
    assert runner._agents == expected
    bare, _c2, _p2 = _wire_game(config)
    assert bare._agents == {}
