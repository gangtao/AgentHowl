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
