"""GameRunner：驱动纯引擎的编排层 —— 串行开窗、事件落库同序广播（issue #29）。

分层：runtime 只转发 intent，裁决全在 engine；本模块对事件的唯一改写点是 meta。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.engine.config import GameConfig
from app.engine.engine import RosterEntry, create_game, step
from app.engine.events import Event
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.player_port import PlayerPort
from app.store.event_store import EventStore, GameMeta, SeatName


class LobbyError(RuntimeError):
    """大厅规则违规（重复加入、未满员取名册等）。"""


class RunnerTimeouts(BaseModel):
    model_config = ConfigDict(frozen=True)

    speech_sec: float
    action_sec: float

    @classmethod
    def from_config(cls, cfg: GameConfig) -> RunnerTimeouts:
        return cls(
            speech_sec=float(cfg.speech_timeout_sec),
            action_sec=float(cfg.action_timeout_sec),
        )


class GameLobby:
    """建局前大厅：收集座位（真人 join / bot 填充），产出 roster 与 GameMeta。"""

    def __init__(self, config: GameConfig, game_id: str) -> None:
        self._config = config
        self._game_id = game_id
        self._entries: list[RosterEntry] = []

    @property
    def is_full(self) -> bool:
        return len(self._entries) >= self._config.num_players

    def join(self, display_name: str, player_type: Literal["HUMAN", "AGENT"] = "HUMAN") -> int:
        if self.is_full:
            raise LobbyError(f"对局已满员（{self._config.num_players} 座）")
        self._entries.append(RosterEntry(display_name=display_name, player_type=player_type))
        return len(self._entries) - 1

    def fill_with_bots(self) -> None:
        while not self.is_full:
            seat = len(self._entries)
            self._entries.append(RosterEntry(display_name=f"Bot{seat}", player_type="AGENT"))

    def roster(self) -> tuple[RosterEntry, ...]:
        if not self.is_full:
            raise LobbyError(f"未满员：{len(self._entries)}/{self._config.num_players}")
        return tuple(self._entries)

    def game_meta(self) -> GameMeta:
        return GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self.roster())
            ),
        )


def _speech_window(state: GameState) -> bool:
    """当前窗口是否发言型（超时取 speech_timeout_sec）。"""
    if state.phase in (Phase.DAY_SPEECH, Phase.LAST_WORDS):
        return True
    return state.phase in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(
        state.speech_order
    )


class GameRunner:
    def __init__(
        self,
        *,
        store: EventStore,
        config: GameConfig,
        game_id: str,
        roster: Sequence[RosterEntry],
        ports: Mapping[int, PlayerPort],
        connections: ConnectionManager | None = None,
        timeouts: RunnerTimeouts | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._game_id = game_id
        self._roster = tuple(roster)
        self._ports = ports
        self.connections = connections
        self._timeouts = timeouts or RunnerTimeouts.from_config(config)
        self._state: GameState | None = None

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("对局尚未开始")
        return self._state

    async def run(self) -> GameState:
        meta = GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self._roster)
            ),
        )
        self._store.create_game(meta)
        res = create_game(self._config, self._game_id, roster=self._roster)
        self._state = res.state
        await self._commit(res.events)

        guard = 0
        while self.state.phase != Phase.GAME_OVER:
            actors = sorted(expected_actors(self.state))
            if not actors:
                raise RuntimeError(f"无人可行动但未终局：phase={self.state.phase}")
            for seat in actors:
                if seat not in expected_actors(self.state):
                    continue  # 前一行动已终结此窗口（如终局）
                await self._drive_seat(seat)
            guard += 1
            if guard > 100_000:
                raise RuntimeError("对局未收敛")
        return self.state

    # ---------- 内部 ----------

    def _window_timeout(self) -> float:
        if _speech_window(self.state):
            return self._timeouts.speech_sec
        return self._timeouts.action_sec

    async def _drive_seat(self, seat: int) -> None:
        obs = build_observation(self.state, seat)
        deadline_ts = time.time() + self._window_timeout()
        action = await self._ports[seat].act(obs, deadline_ts)
        res = step(self.state, action)
        if res.rejection is not None:
            raise RuntimeError(f"行动被拒：{res.rejection} @ {self.state.phase}")
        self._state = res.state
        await self._commit(res.events)

    async def _commit(self, events: list[Event], timed_out: bool = False) -> None:
        """meta 充实 → 落库 → 广播，同序。runtime 对事件的唯一合法改写点。"""
        wall_ts = datetime.now(UTC).isoformat()
        enriched = [
            e.model_copy(
                update={
                    "meta": {
                        **e.meta,
                        "wall_ts": wall_ts,
                        **({"timeout": "true"} if timed_out else {}),
                    }
                }
            )
            for e in events
        ]
        for e in enriched:
            self._store.append(self._game_id, e)
        if self.connections is not None:
            await self.connections.broadcast(enriched)
