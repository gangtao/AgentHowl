"""玩家接入端口：runner 与玩家实现（bot/真人/Agent）之间的唯一缝（issue #29）。

M2.3 真人（WS/REST 桥接）与 M2.4 LLM Agent 实现同一 Protocol。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.cli.bot import RandomBot
from app.engine.actions import Action
from app.engine.observation import PlayerObservation
from app.engine.state import GameState


class PlayerPort(Protocol):
    """runner 询问玩家行动的异步端口；超时/异常兜底由 runner 持有。"""

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action: ...


class BotPlayerPort:
    """服务端内置填充 bot：以全知 state 复用 RandomBot。

    内置 bot 属服务端信任域，不越信息隔离边界；observation 仅用于取 my_seat。
    """

    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        return RandomBot.choose_action(self._state_provider(), observation.my_seat)
