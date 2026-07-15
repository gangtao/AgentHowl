"""玩家接入端口：runner 与玩家实现（bot/真人/Agent）之间的唯一缝（issue #29）。

M2.3 真人（WS/REST 桥接）与 M2.4 LLM Agent 实现同一 Protocol。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

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


class TurnPrompt(BaseModel):
    """your_turn 负载：观察 + 截止时间。available_tools 由 api 层按视角补充。"""

    model_config = ConfigDict(frozen=True)

    observation: PlayerObservation
    deadline_ts: float


class SubmitOutcome(BaseModel):
    """一次提交的裁决结果（PRD §4.1 统一信封的 runtime 侧形态）。"""

    model_config = ConfigDict(frozen=True)

    ok: bool
    event_id: str | None = None
    state_version: int
    rejected_reason: str | None = None


class NotYourTurnError(RuntimeError):
    """未开窗提交（api 映射 409）。"""


@runtime_checkable
class SupportsResultFeedback(Protocol):
    """runner 裁决后回填结果的可选端口能力（Bot 端口不实现即忽略）。"""

    def notify_result(
        self, rejected_reason: str | None, state_version: int, event_id: str | None
    ) -> None: ...


class HumanPlayerPort:
    """外接玩家端口（真人或外部 Agent，经 REST/WS 驱动）。

    act 开窗并等待 submit 解析 Future；超时/重试/默认行动完全由 runner 持有。
    裁决结果由 runner 经 notify_result 回填给 submit 的调用方。
    """

    def __init__(self) -> None:
        self._sender: Callable[[TurnPrompt], Awaitable[None]] | None = None
        self._prompt: TurnPrompt | None = None
        self._pending: asyncio.Future[Action] | None = None
        self._outcome: asyncio.Future[SubmitOutcome] | None = None
        self._armed = asyncio.Event()

    @property
    def current_prompt(self) -> TurnPrompt | None:
        return self._prompt

    def attach_sender(self, sender: Callable[[TurnPrompt], Awaitable[None]]) -> None:
        self._sender = sender

    def detach_sender(self) -> None:
        self._sender = None

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self._prompt = TurnPrompt(observation=observation, deadline_ts=deadline_ts)
        self._pending = asyncio.get_running_loop().create_future()
        self._armed.set()
        if self._sender is not None:
            try:
                await self._sender(self._prompt)
            except Exception:
                self._sender = None  # 坏连接自摘除；玩家可经 REST 轮询发现窗口
        try:
            try:
                return await self._pending
            except asyncio.CancelledError:
                # submit() 已 resolve _pending，但 runner 的 wait_for 超时在同一 tick
                # 取消了本 act 任务：提交方的 _outcome 永远等不到 notify_result 回填，
                # 这里先行回填 WINDOW_CLOSED 避免其挂死，再把取消异常继续向上抛出。
                if self._outcome is not None and not self._outcome.done():
                    self._outcome.set_result(
                        SubmitOutcome(
                            ok=False,
                            event_id=None,
                            state_version=observation.state_version,
                            rejected_reason="WINDOW_CLOSED",
                        )
                    )
                    self._outcome = None
                raise
        finally:
            self._pending = None
            self._prompt = None
            self._armed.clear()

    async def wait_armed(self, timeout: float) -> TurnPrompt | None:
        """my-turn 长轮询：挂起至开窗或超时（返回 None）。"""
        try:
            await asyncio.wait_for(self._armed.wait(), timeout)
        except TimeoutError:
            return None
        return self._prompt

    def submit(self, action: Action) -> asyncio.Future[SubmitOutcome]:
        """提交行动，返回裁决结果 future；未开窗抛 NotYourTurnError。"""
        if self._pending is None or self._pending.done():
            raise NotYourTurnError("当前不在该玩家的行动窗口")
        self._outcome = asyncio.get_running_loop().create_future()
        self._pending.set_result(action)
        return self._outcome

    async def submit_and_wait(self, action: Action, timeout: float = 10.0) -> SubmitOutcome:
        return await asyncio.wait_for(self.submit(action), timeout)

    def notify_result(
        self, rejected_reason: str | None, state_version: int, event_id: str | None
    ) -> None:
        if self._outcome is not None and not self._outcome.done():
            self._outcome.set_result(
                SubmitOutcome(
                    ok=rejected_reason is None,
                    event_id=event_id,
                    state_version=state_version,
                    rejected_reason=rejected_reason,
                )
            )
        self._outcome = None
