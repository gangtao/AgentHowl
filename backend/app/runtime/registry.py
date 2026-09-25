"""GameRegistry：进程内对局登记与生命周期编排（issue #30）。

api 层唯一入口；本模块不做任何裁决，只做装配（lobby/ports/runner/task）。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from typing import Literal

from app.agent.experience import AgentExperience
from app.agent.profile import (
    AgentProfile,
    AgentProfiles,
    legacy_to_profiles,
    merge_profiles,
    profile_for,
    validate_profiles,
)
from app.agent.provider import Provider
from app.agent.skills import SkillLibrary, default_library
from app.engine.config import GameConfig
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.experience_store import ExperienceStore, InMemoryExperienceStore
from app.runtime.game_runner import GameLobby, GameRunner, LobbyError, RunnerTimeouts
from app.runtime.player_port import (
    BotPlayerPort,
    HumanPlayerPort,
    PlayerPort,
    SupportsEventIngest,
)
from app.runtime.postgame import opponents_for, run_postgame, seat_memory_ids
from app.runtime.provider_store import InMemoryProviderStore, ProviderStore
from app.store.event_store import EventStore

logger = logging.getLogger(__name__)


class GameHandle:
    """一局的活对象集合。"""

    def __init__(
        self,
        game_id: str,
        config: GameConfig,
        *,
        allow_spectators: bool,
        num_ai_players: int | None,
        agents: AgentProfiles,
    ) -> None:
        self.game_id = game_id
        self.config = config
        self.allow_spectators = allow_spectators
        self.num_ai_players = num_ai_players
        self.agents = agents
        self.lobby = GameLobby(config, game_id)
        self.ports: dict[int, PlayerPort] = {}
        self.human_ports: dict[int, HumanPlayerPort] = {}
        self.connections: ConnectionManager | None = None
        self.runner: GameRunner | None = None
        self.task: asyncio.Task[GameState] | None = None
        # 跨局记忆（issue #59）：start 时装配；task 正常结束后由 registry 调度 postgame
        self.seat_memory_ids: dict[int, str] = {}
        self.experiences: dict[int, AgentExperience] = {}
        self.postgame_task: asyncio.Task[dict[str, AgentExperience]] | None = None
        # 座位 → Provider（issue #26）：start() 按 profile.provider 装配，供 agent 端口工厂使用
        self.providers: dict[int, Provider] = {}

    @property
    def started(self) -> bool:
        return self.runner is not None

    def profile_for(self, seat: int) -> AgentProfile | None:
        return profile_for(self.agents, seat)

    def live_state(self) -> GameState:
        if self.runner is None:
            raise LobbyError(f"对局 {self.game_id} 尚未开始")
        return self.runner.state

    def ensure_healthy(self) -> None:
        """runner task 崩溃则 fail-loud（api 映射 500）。"""
        if self.task is not None and self.task.done() and not self.task.cancelled():
            exc = self.task.exception()
            if exc is not None:
                raise RuntimeError(f"对局 {self.game_id} 已崩溃：{exc}") from exc


class GameRegistry:
    def __init__(
        self,
        store: EventStore,
        timeouts: RunnerTimeouts | None = None,
        agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None,
        skill_library: SkillLibrary | None = None,
        experience_store: ExperienceStore | None = None,
        provider_store: ProviderStore | None = None,
    ) -> None:
        self._store = store
        self._timeouts = timeouts
        self._games: dict[str, GameHandle] = {}
        self._agent_port_factory = agent_port_factory
        self._skill_library = skill_library
        self._experience_store: ExperienceStore = (
            experience_store if experience_store is not None else InMemoryExperienceStore()
        )
        self._provider_store: ProviderStore = (
            provider_store if provider_store is not None else InMemoryProviderStore()
        )

    @property
    def skill_library(self) -> SkillLibrary:
        return self._skill_library if self._skill_library is not None else default_library()

    @property
    def experience_store(self) -> ExperienceStore:
        return self._experience_store

    def create(
        self,
        config: GameConfig,
        *,
        allow_spectators: bool,
        num_ai_players: int | None = None,
        agents: AgentProfiles | None = None,
        ai_model: str | None = None,
        ai_model_speech: str | None = None,
    ) -> GameHandle:
        # 旧入口 ai_model 折叠为 "*" 默认档案；与显式 agents["*"] 冲突、座位键非法 → ValueError
        resolved = merge_profiles(agents, legacy_to_profiles(ai_model, ai_model_speech))
        providers = {p.provider_id for p in self._provider_store.list()}
        validate_profiles(resolved, config.num_players, self.skill_library, providers=providers)
        game_id = f"g_{secrets.token_hex(4)}"
        handle = GameHandle(
            game_id,
            config,
            allow_spectators=allow_spectators,
            num_ai_players=num_ai_players,
            agents=resolved,
        )
        self._games[game_id] = handle
        return handle

    def get(self, game_id: str) -> GameHandle:
        try:
            return self._games[game_id]
        except KeyError:
            raise LookupError(f"对局不存在：{game_id}") from None

    @property
    def store(self) -> EventStore:
        return self._store

    def join(
        self, handle: GameHandle, display_name: str, player_type: Literal["HUMAN", "AGENT"]
    ) -> int:
        """经 API 加入的座位（真人或外部 Agent）一律配 HumanPlayerPort —— 同一玩家 API。"""
        if handle.started:
            raise LobbyError("对局已开始，无法加入")
        seat = handle.lobby.join(display_name, player_type)
        port = HumanPlayerPort()
        handle.human_ports[seat] = port
        handle.ports[seat] = port
        return seat

    def start(self, handle: GameHandle, fill_with_bots: bool = True) -> None:
        if handle.started:
            raise LobbyError("对局已开始")
        joined = len(handle.ports)
        if handle.num_ai_players is not None:
            empty = handle.config.num_players - joined
            if empty != handle.num_ai_players:
                raise LobbyError(f"num_ai_players={handle.num_ai_players} 与空位数 {empty} 不符")
        if fill_with_bots:

            def _bot_name(seat: int) -> str:
                p = handle.profile_for(seat)
                return p.name if p is not None and p.name else f"Bot{seat}"

            handle.lobby.fill_with_bots(name_for=_bot_name)
        roster = handle.lobby.roster()  # 未满员在此抛 LobbyError

        def _state_of() -> GameState:
            assert handle.runner is not None
            return handle.runner.state

        # 跨局记忆装配：真人/外部端口已占的座位（此时 handle.ports 只含 join 过的座位）
        # 档案整体不生效，含 memory_id；坏文件在此 fail-loud
        handle.seat_memory_ids = seat_memory_ids(
            handle.agents, handle.config.num_players, exclude=handle.ports.keys()
        )
        for seat, mid in handle.seat_memory_ids.items():
            handle.experiences[seat] = self._experience_store.load(mid)

        # Provider 装配（issue #26）：create() 已校验存在性；此处仍可能因并发删除而落空
        for seat in range(handle.config.num_players):
            profile = handle.profile_for(seat)
            if profile is not None and profile.provider:
                provider = self._provider_store.get(profile.provider)
                if provider is None:
                    raise LobbyError(f"provider 已被删除：{profile.provider}")
                handle.providers[seat] = provider

        handle.connections = ConnectionManager(state_provider=_state_of)
        effective: AgentProfiles = {}  # 实际建成 Agent 端口的座位 → 档案，写进 meta（issue #64）
        for seat in range(handle.config.num_players):
            if seat not in handle.ports:
                profile = handle.profile_for(seat)
                if profile is None:
                    handle.ports[seat] = BotPlayerPort(state_provider=_state_of)
                else:
                    handle.ports[seat] = self._build_agent_port(seat, handle)
                    effective[str(seat)] = profile
        runner = GameRunner(
            store=self._store,
            config=handle.config,
            game_id=handle.game_id,
            roster=roster,
            ports=handle.ports,
            connections=handle.connections,
            timeouts=self._timeouts,
            agents=effective,
        )
        handle.runner = runner
        # 订阅须在 create_task 之前完成，否则 GAME_CREATED/ROLES_ASSIGNED 首批事件漏投
        for seat, port in handle.ports.items():
            if isinstance(port, SupportsEventIngest):
                handle.connections.subscribe(seat, port.on_events)
        handle.task = asyncio.create_task(runner.run())
        if handle.seat_memory_ids:
            handle.task.add_done_callback(lambda t: self._schedule_postgame(handle, t))

    def _schedule_postgame(self, handle: GameHandle, task: asyncio.Task[GameState]) -> None:
        """runner 正常终局后异步复盘；崩溃/取消不复盘。任务对象挂在 handle 上供测试 await。"""
        if task.cancelled() or task.exception() is not None:
            return
        handle.postgame_task = asyncio.create_task(
            run_postgame(
                game_id=handle.game_id,
                final_state=task.result(),
                profiles=handle.agents,
                ports=handle.ports,
                store=self._experience_store,
            )
        )
        handle.postgame_task.add_done_callback(lambda t: _log_postgame(handle.game_id, t))

    def _build_agent_port(self, seat: int, handle: GameHandle) -> PlayerPort:
        if self._agent_port_factory is not None:
            return self._agent_port_factory(seat, handle)
        from app.agent.agent_player import build_agent_port  # 惰性：litellm 仅在需要时加载

        profile = handle.profile_for(seat)
        assert profile is not None
        return build_agent_port(
            seat,
            handle.config,
            profile,
            library=self.skill_library,
            experience=handle.experiences.get(seat),
            opponents=opponents_for(seat, handle.seat_memory_ids),
            provider=handle.providers.get(seat),
        )


def _log_postgame(game_id: str, task: asyncio.Task[dict[str, AgentExperience]]) -> None:
    """复盘任务无人 await：取消/异常至少留日志（关停时优雅等待见后续 issue）。"""
    if task.cancelled():
        logger.warning("对局 %s 局后复盘被取消，本局经验未落盘", game_id)
    elif (exc := task.exception()) is not None:
        logger.error("对局 %s 局后复盘异常：%s", game_id, exc, exc_info=exc)
