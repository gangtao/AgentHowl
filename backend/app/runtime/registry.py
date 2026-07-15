"""GameRegistry：进程内对局登记与生命周期编排（issue #30）。

api 层唯一入口；本模块不做任何裁决，只做装配（lobby/ports/runner/task）。
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Literal

from app.engine.config import GameConfig
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.game_runner import GameLobby, GameRunner, LobbyError, RunnerTimeouts
from app.runtime.player_port import BotPlayerPort, HumanPlayerPort, PlayerPort
from app.store.event_store import EventStore


class GameHandle:
    """一局的活对象集合。"""

    def __init__(
        self,
        game_id: str,
        config: GameConfig,
        *,
        allow_spectators: bool,
        num_ai_players: int | None,
    ) -> None:
        self.game_id = game_id
        self.config = config
        self.allow_spectators = allow_spectators
        self.num_ai_players = num_ai_players
        self.lobby = GameLobby(config, game_id)
        self.ports: dict[int, PlayerPort] = {}
        self.human_ports: dict[int, HumanPlayerPort] = {}
        self.connections: ConnectionManager | None = None
        self.runner: GameRunner | None = None
        self.task: asyncio.Task[GameState] | None = None

    @property
    def started(self) -> bool:
        return self.runner is not None

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
    def __init__(self, store: EventStore, timeouts: RunnerTimeouts | None = None) -> None:
        self._store = store
        self._timeouts = timeouts
        self._games: dict[str, GameHandle] = {}

    def create(
        self,
        config: GameConfig,
        *,
        allow_spectators: bool,
        num_ai_players: int | None = None,
    ) -> GameHandle:
        game_id = f"g_{secrets.token_hex(4)}"
        handle = GameHandle(
            game_id, config, allow_spectators=allow_spectators, num_ai_players=num_ai_players
        )
        self._games[game_id] = handle
        return handle

    def get(self, game_id: str) -> GameHandle:
        try:
            return self._games[game_id]
        except KeyError:
            raise LookupError(f"对局不存在：{game_id}") from None

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
            handle.lobby.fill_with_bots()
        roster = handle.lobby.roster()  # 未满员在此抛 LobbyError

        def _state_of() -> GameState:
            assert handle.runner is not None
            return handle.runner.state

        handle.connections = ConnectionManager(state_provider=_state_of)
        for seat in range(handle.config.num_players):
            if seat not in handle.ports:
                handle.ports[seat] = BotPlayerPort(state_provider=_state_of)
        runner = GameRunner(
            store=self._store,
            config=handle.config,
            game_id=handle.game_id,
            roster=roster,
            ports=handle.ports,
            connections=handle.connections,
            timeouts=self._timeouts,
        )
        handle.runner = runner
        handle.task = asyncio.create_task(runner.run())
