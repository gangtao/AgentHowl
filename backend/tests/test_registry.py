"""GameRegistry/TokenRegistry：建局-加入-开局生命周期（issue #30）。"""

import asyncio
from collections.abc import Callable

import pytest

from app.api.deps import TokenInfo, TokenRegistry
from app.cli.bot import RandomBot
from app.engine.config import build_preset
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
