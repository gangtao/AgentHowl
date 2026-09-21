"""全 Agent 集成（issue #31 Task 7）：9 座全 AgentPlayerPort 经真 runner 跑到终局。

脚本客户端"全知"取 runner state 只为产出合法决策（测试域白盒），
被测路径（AgentPlayerPort → prompts → runner）本身仍只见 observation。
"""

import asyncio

from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.memory import ReflectionResult
from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.phases import Phase
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import PlayerPort
from app.runtime.registry import GameHandle, GameRegistry
from app.store.event_store import InMemoryEventStore
from tests.llm_helpers import ScriptedLLMClient, action_to_decision

TIMEOUTS = RunnerTimeouts(speech_sec=30.0, action_sec=30.0)


def _omniscient_script(handle: GameHandle, seat: int):
    """RandomBot 的合法行动 → 决策模型逆映射；反思调用返回固定摘要。"""

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is ReflectionResult:
            return ReflectionResult(summary="(scripted reflect)", qa=[])
        assert handle.runner is not None
        action = RandomBot.choose_action(handle.runner.state, seat)
        return action_to_decision(action, rm)

    return script


def _make_registry(broken_seat: int | None = None) -> GameRegistry:
    holder: dict[str, GameHandle] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        holder.setdefault("h", handle)
        if seat == broken_seat:

            def boom(rm: type[BaseModel], system: str, user: str) -> BaseModel:
                raise RuntimeError("agent LLM 永久故障")

            client = ScriptedLLMClient(boom)
        else:
            client = ScriptedLLMClient(_omniscient_script(handle, seat))
        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=AgentConfig(model="scripted", agent_seed=7),
            client=client,
        )

    return GameRegistry(InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory)


async def _run_full_game(registry: GameRegistry) -> GameHandle:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(
        config, allow_spectators=False, num_ai_players=None, ai_model="scripted"
    )
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER
    return handle


async def test_all_agent_game_reaches_game_over_and_memory_ingests() -> None:
    handle = await _run_full_game(_make_registry())
    # 每个座位都是 AgentPlayerPort 且 memory 确有摄入（订阅接线生效）
    for seat, port in handle.ports.items():
        assert isinstance(port, AgentPlayerPort), f"座位 {seat} 不是 AgentPlayerPort"
        assert port.memory.entries, f"座位 {seat} memory 未摄入任何事件"
    # 隔离抽查：非狼座位的 memory 不含 WOLVES 事件
    from app.engine.config import Faction

    assert handle.runner is not None
    state = handle.runner.state
    for p in state.players:
        if p.faction != Faction.WOLF:
            port = handle.ports[p.seat]
            assert isinstance(port, AgentPlayerPort)
            kinds = {e.kind for e in port.memory.entries}
            assert "WOLF_KILL_PROPOSED" not in kinds
            assert "WOLF_KILL_DECIDED" not in kinds
            assert "WOLF_KILL_REVOTE" not in kinds


async def test_broken_agent_falls_back_to_default_and_game_completes() -> None:
    await _run_full_game(_make_registry(broken_seat=0))  # 0 号 LLM 永久故障仍收敛


async def test_ai_model_none_keeps_bot_fill() -> None:
    registry = GameRegistry(InMemoryEventStore(), TIMEOUTS)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(config, allow_spectators=False)
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    from app.runtime.player_port import BotPlayerPort

    assert all(isinstance(p, BotPlayerPort) for p in handle.ports.values())
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER


def test_create_game_request_accepts_ai_model() -> None:
    from app.schemas.games import CreateGameRequest

    req = CreateGameRequest(ai_model="ollama/llama3.1", ai_model_speech="ollama/qwen2.5")
    assert req.ai_model == "ollama/llama3.1"
    assert CreateGameRequest().ai_model is None  # 默认关（现有行为零变化）


async def test_per_seat_profiles_reach_agent_config() -> None:
    """两座位不同档案 → 各自 AgentConfig.model 不同（经 profile_for + to_agent_config）。"""
    from app.agent.profile import AgentProfile, to_agent_config

    seen: dict[int, str] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        profile = handle.profile_for(seat)
        assert profile is not None
        cfg = to_agent_config(profile, handle.config)
        seen[seat] = cfg.model
        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=cfg,
            client=ScriptedLLMClient(_omniscient_script(handle, seat)),
        )

    registry = GameRegistry(InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(
        config,
        allow_spectators=False,
        agents={"0": AgentProfile(model="scripted-zero"), "*": AgentProfile(model="scripted")},
    )
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER
    assert seen[0] == "scripted-zero" and seen[1] == "scripted" and len(seen) == 9


async def test_two_games_accumulate_experience_and_second_game_prompt_has_it() -> None:
    """两座位配 memory_id：第 1 局终局后复盘落盘（局中零写入）；

    第 2 局系统 prompt 含往局教训与对手行。
    """
    from app.agent.experience import GameReflection
    from app.agent.profile import AgentProfile
    from app.runtime.experience_store import InMemoryExperienceStore
    from app.runtime.postgame import opponents_for

    store = InMemoryExperienceStore()
    clients: dict[int, ScriptedLLMClient] = {}

    def make_registry() -> GameRegistry:
        def factory(seat: int, handle: GameHandle) -> PlayerPort:
            base = _omniscient_script(handle, seat)

            def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
                if rm is GameReflection:
                    return GameReflection(
                        lessons=[f"(lesson {seat}) 当被怀疑时，应先摆事实"],
                        opponent_notes={s: [f"(note by {seat})"] for s in range(9)},
                    )
                return base(rm, system, user)

            client = ScriptedLLMClient(script)
            clients[seat] = client
            return AgentPlayerPort(
                seat=seat,
                game_config=handle.config,
                agent_config=AgentConfig(model="scripted", agent_seed=7),
                client=client,
                experience=handle.experiences.get(seat),
                opponents=opponents_for(seat, handle.seat_memory_ids),
            )

        return GameRegistry(
            InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory, experience_store=store
        )

    agents = {
        "0": AgentProfile(model="scripted", memory_id="alice"),
        "1": AgentProfile(model="scripted", memory_id="bob"),
        "*": AgentProfile(model="scripted"),
    }
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def postgame_of(handle: GameHandle):  # done-callback 在下一轮循环才挂上任务
        for _ in range(10):
            if handle.postgame_task is not None:
                return handle.postgame_task
            await asyncio.sleep(0)
        raise AssertionError("postgame_task 未被调度")

    reg1 = make_registry()
    h1 = reg1.create(config, allow_spectators=False, agents=agents)
    reg1.start(h1)
    assert store.saves == 0
    assert h1.task is not None
    await asyncio.wait_for(h1.task, timeout=120)
    assert store.saves == 0  # 对局中（含终局瞬间）不写；写入只在 postgame 任务里
    await asyncio.wait_for(await postgame_of(h1), timeout=60)
    assert store.saves == 2
    alice = store.load("alice")
    assert alice.games_played == 1 and alice.lessons[0].text.startswith("(lesson 0)")
    assert [n.text for n in alice.opponent_notes["bob"]] == ["(note by 0)"]
    assert set(alice.opponent_notes) == {"bob"}  # 无 memory_id 座位与自己被丢弃
    # 第 1 局的系统 prompt 不含经验（首局）
    assert all("跨局经验" not in c[1] for s in (0, 1) for c in clients[s].calls)

    reg2 = make_registry()
    h2 = reg2.create(config, allow_spectators=False, agents=agents)
    reg2.start(h2)
    assert h2.experiences[0].games_played == 1
    assert h2.task is not None
    await asyncio.wait_for(h2.task, timeout=120)
    # 0 号可能首夜被刀而一次未行动；取 0/1 中有决策调用的那位（两位同时首夜出局极罕见）
    s = next(s for s in (0, 1) if any("== 局势 ==" in c[2] for c in clients[s].calls))
    system = next(c[1] for c in clients[s].calls if "== 局势 ==" in c[2])
    assert "== 跨局经验 ==" in system and f"(lesson {s})" in system
    assert f"{1 - s}号：(note by {s})" in system  # 对手 memory_id 映射回本局座位
    assert all("跨局经验" not in c[1] for c in clients[2].calls)  # 无 memory_id 座位无经验
    await asyncio.wait_for(await postgame_of(h2), timeout=60)
    assert store.load("alice").games_played == 2 and store.saves == 4
