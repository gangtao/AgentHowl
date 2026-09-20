"""GameRegistry/TokenRegistry：建局-加入-开局生命周期（issue #30）。"""

import asyncio
from collections.abc import Callable

import pytest

from app.api.deps import TokenInfo, TokenRegistry
from app.cli.bot import RandomBot
from app.engine.config import RoleType, build_preset
from app.engine.phases import Phase
from app.runtime.game_runner import LobbyError, RunnerTimeouts
from app.runtime.player_port import PlayerPort
from app.runtime.registry import GameHandle, GameRegistry
from app.store.event_store import InMemoryEventStore


def _registry(
    agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None,
) -> GameRegistry:
    return GameRegistry(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=agent_port_factory,
    )


def test_token_registry_roundtrip_and_unknown() -> None:
    tokens = TokenRegistry()
    info = TokenInfo(game_id="g_1", seat=3, kind="PLAYER")
    t = tokens.issue(info)
    assert tokens.resolve(t) == info
    assert tokens.resolve("nope") is None
    assert tokens.issue(info) != t  # 不透明随机串


async def test_all_ai_game_runs_to_game_over() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    handle = reg.create(cfg, allow_spectators=True)
    assert handle.game_id.startswith("g_")
    reg.start(handle, fill_with_bots=True)
    assert handle.task is not None
    final = await handle.task
    assert final.phase == Phase.GAME_OVER
    handle.ensure_healthy()  # 正常终局不抛


async def test_join_gets_human_port_and_start_guards() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    handle = reg.create(cfg, allow_spectators=False)
    seat = reg.join(handle, "Alice", "HUMAN")
    assert seat == 0 and 0 in handle.human_ports
    agent_seat = reg.join(handle, "ExtAgent", "AGENT")
    assert agent_seat == 1 and 1 in handle.human_ports  # 外部 Agent 同为 HumanPlayerPort

    with pytest.raises(LobbyError):
        reg.start(handle, fill_with_bots=False)  # 未满员且不填充

    reg.start(handle, fill_with_bots=True)
    with pytest.raises(LobbyError):
        reg.start(handle)  # 重复开局
    with pytest.raises(LobbyError):
        reg.join(handle, "Late", "HUMAN")  # 开局后加入

    async def drive(seat: int) -> None:
        port = handle.human_ports[seat]
        while True:
            prompt = await port.wait_armed(5.0)
            if prompt is None:
                return
            outcome = await port.submit_and_wait(
                RandomBot.choose_action(handle.live_state(), seat), timeout=5.0
            )
            assert outcome.ok, outcome.rejected_reason

    drivers = [asyncio.ensure_future(drive(s)) for s in (0, 1)]
    assert handle.task is not None
    final = await handle.task
    for d in drivers:
        d.cancel()
    results = await asyncio.gather(*drivers, return_exceptions=True)
    for r in results:
        # 正常退出(None)或被取消是预期；驱动协程内的断言失败必须让测试失败
        assert r is None or isinstance(r, asyncio.CancelledError), r
    assert final.phase == Phase.GAME_OVER


async def test_num_ai_players_validated_at_start() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = reg.create(cfg, allow_spectators=True, num_ai_players=7)
    reg.join(handle, "Alice", "HUMAN")  # 1 真人 + 7 AI = 8 != 9
    with pytest.raises(LobbyError):
        reg.start(handle)
    reg.join(handle, "Bob", "HUMAN")  # 2 + 7 = 9 ✓
    reg.start(handle)

    async def drive(seat: int) -> None:
        port = handle.human_ports[seat]
        while True:
            prompt = await port.wait_armed(5.0)
            if prompt is None:
                return
            await port.submit_and_wait(
                RandomBot.choose_action(handle.live_state(), seat), timeout=5.0
            )

    drivers = [asyncio.ensure_future(drive(s)) for s in (0, 1)]
    assert handle.task is not None
    await handle.task
    for d in drivers:
        d.cancel()
    results = await asyncio.gather(*drivers, return_exceptions=True)
    for r in results:
        # 正常退出(None)或被取消是预期；驱动协程内的断言失败必须让测试失败
        assert r is None or isinstance(r, asyncio.CancelledError), r


def test_get_unknown_game_raises_lookup() -> None:
    reg = _registry()
    with pytest.raises(LookupError):
        reg.get("g_nope")


async def test_create_with_agents_resolves_per_seat_and_names_bots() -> None:
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort

    # 有档案的座位由 agent 工厂建端口（此处注入桩，避免 litellm）
    reg = _registry(agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state))
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    agents = {"0": AgentProfile(name="老张", model="ollama/a"), "2": AgentProfile(model="ollama/b")}
    handle = reg.create(cfg, allow_spectators=False, agents=agents)
    assert handle.profile_for(0) is agents["0"] and handle.profile_for(2) is agents["2"]
    assert handle.profile_for(1) is None
    reg.start(handle, fill_with_bots=True)
    names = [e.display_name for e in handle.lobby.roster()]
    # 无 name 缺省 Bot{seat}
    assert names[0] == "老张" and names[1] == "Bot1" and names[2] == "Bot2"
    assert handle.task is not None
    handle.task.cancel()


def test_create_legacy_ai_model_folds_to_star_and_conflict_raises() -> None:
    from app.agent.profile import AgentProfile

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(
        cfg, allow_spectators=False, ai_model="ollama/a", ai_model_speech="ollama/b"
    )
    star = handle.profile_for(7)
    assert star is not None and star.model == "ollama/a" and star.model_speech == "ollama/b"
    with pytest.raises(ValueError, match="agents"):
        reg.create(
            cfg,
            allow_spectators=False,
            agents={"*": AgentProfile(model="x")},
            ai_model="ollama/a",
        )
    with pytest.raises(ValueError, match="座位"):
        reg.create(cfg, allow_spectators=False, agents={"9": AgentProfile(model="x")})


async def test_human_joined_seat_ignores_profile() -> None:
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort, HumanPlayerPort

    reg = _registry(agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state))
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(cfg, allow_spectators=False, agents={"0": AgentProfile(model="x")})
    reg.join(handle, "Alice", "HUMAN")  # 占 0 号
    reg.start(handle, fill_with_bots=True)
    assert isinstance(handle.ports[0], HumanPlayerPort)
    assert handle.lobby.roster()[0].display_name == "Alice"
    assert handle.task is not None
    handle.task.cancel()


def test_create_validates_skills_against_library(tmp_path) -> None:
    from app.agent.profile import AgentProfile
    from app.agent.skills import SkillLibrary
    from app.store.event_store import InMemoryEventStore

    d = tmp_path / "custom-skill"
    d.mkdir()
    text = "---\nname: custom-skill\ndescription: d\n---\n正文\n"
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    reg = GameRegistry(store=InMemoryEventStore(), skill_library=SkillLibrary.load([tmp_path]))
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(
        cfg,
        allow_spectators=False,
        agents={"*": AgentProfile(model="m", skills=["custom-skill"])},
    )
    assert handle.profile_for(0) is not None
    with pytest.raises(ValueError, match="nope"):
        reg.create(
            cfg,
            allow_spectators=False,
            agents={"*": AgentProfile(model="m", skills=["nope"])},
        )


def test_create_without_library_uses_builtin(tmp_path) -> None:
    from app.agent.profile import AgentProfile

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    reg.create(
        cfg,
        allow_spectators=False,
        agents={"*": AgentProfile(model="m", skills=["vote-discipline"])},
    )
    with pytest.raises(ValueError, match="no-such-skill"):
        reg.create(
            cfg,
            allow_spectators=False,
            agents={"*": AgentProfile(model="m", skills=["no-such-skill"])},
        )


async def test_memory_id_loads_experience_wires_opponents_and_runs_postgame() -> None:
    from pydantic import BaseModel

    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.experience import AgentExperience, GameReflection
    from app.agent.memory import ReflectionResult
    from app.agent.profile import AgentProfile
    from app.runtime.experience_store import InMemoryExperienceStore
    from app.runtime.postgame import opponents_for
    from tests.llm_helpers import ScriptedLLMClient, action_to_decision

    store = InMemoryExperienceStore()
    seeded = AgentExperience(memory_id="alice")
    seeded.record_game(
        game_id="g0",
        role=RoleType.VILLAGER,
        won=True,
        reflection=GameReflection(lessons=["(seeded) 慎投"], opponent_notes={1: ["跟票"]}),
        seat_to_memory_id={0: "alice", 1: "bob"},
        my_seat=0,
        ts="t",
    )
    store.save(seeded)
    seen: dict[int, tuple[object, dict[str, int]]] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        seen[seat] = (handle.experiences.get(seat), opponents_for(seat, handle.seat_memory_ids))

        def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
            if rm is ReflectionResult:
                return ReflectionResult(summary="(r)", qa=[])
            if rm is GameReflection:
                return GameReflection(lessons=[f"(lesson of {seat})"], opponent_notes={})
            assert handle.runner is not None
            return action_to_decision(RandomBot.choose_action(handle.runner.state, seat), rm)

        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=AgentConfig(model="scripted", agent_seed=1),
            client=ScriptedLLMClient(script),
            experience=handle.experiences.get(seat),
            opponents=opponents_for(seat, handle.seat_memory_ids),
        )

    reg = GameRegistry(
        InMemoryEventStore(),
        RunnerTimeouts(speech_sec=30.0, action_sec=30.0),
        agent_port_factory=factory,
        experience_store=store,
    )
    agents = {
        "0": AgentProfile(model="m", memory_id="alice"),
        "1": AgentProfile(model="m", memory_id="bob"),
        "*": AgentProfile(model="m"),
    }
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = reg.create(config, allow_spectators=False, agents=agents)
    reg.start(handle)
    assert handle.seat_memory_ids == {0: "alice", 1: "bob"}
    exp0, opp0 = seen[0]
    assert isinstance(exp0, AgentExperience) and exp0.games_played == 1 and opp0 == {"bob": 1}
    assert seen[1][1] == {"alice": 0} and seen[2] == (None, {"alice": 0, "bob": 1})
    assert store.saves == 1  # 只有测试自己的 seed；对局中不写
    assert handle.task is not None
    await asyncio.wait_for(handle.task, timeout=120)
    assert store.saves == 1  # 终局瞬间仍未写：写入只在 postgame 任务里
    updated = await asyncio.wait_for(await _postgame_of(handle), timeout=60)
    assert set(updated) == {"alice", "bob"} and store.saves == 3
    alice = store.load("alice")
    assert alice.games_played == 2 and alice.lessons[-1].text == "(lesson of 0)"
    assert store.load("bob").lessons[-1].text == "(lesson of 1)"


async def _postgame_of(handle: GameHandle) -> "asyncio.Task[object]":
    """done-callback 与 await 的唤醒同在下一轮事件循环；让出几步再取 postgame_task。"""
    for _ in range(10):
        if handle.postgame_task is not None:
            return handle.postgame_task  # type: ignore[return-value]
        await asyncio.sleep(0)
    raise AssertionError("postgame_task 未被调度")


async def test_no_memory_id_means_no_postgame_task() -> None:
    reg = _registry()  # 文件已有的辅助工厂；若无则用 GameRegistry(InMemoryEventStore(), TIMEOUTS)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = reg.create(config, allow_spectators=False, ai_model=None)
    reg.start(handle)
    assert handle.task is not None
    await asyncio.wait_for(handle.task, timeout=60)
    await asyncio.sleep(0)
    assert handle.postgame_task is None and handle.seat_memory_ids == {}


def test_create_rejects_duplicate_and_star_memory_id() -> None:
    from app.agent.profile import AgentProfile

    reg = GameRegistry(InMemoryEventStore())
    config = build_preset("std_9_kill_side")
    with pytest.raises(ValueError, match="重复"):
        reg.create(
            config,
            allow_spectators=False,
            agents={
                "0": AgentProfile(model="m", memory_id="a"),
                "1": AgentProfile(model="m", memory_id="a"),
            },
        )
    with pytest.raises(ValueError, match="'\\*'"):
        reg.create(
            config, allow_spectators=False, agents={"*": AgentProfile(model="m", memory_id="a")}
        )
