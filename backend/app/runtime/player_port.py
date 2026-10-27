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
from app.engine.events import Event
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


# 提交后等待裁决结果的时长：串行窗口（发言等）结果即时返回；同步窗口（上警 / 投票 / 狼刀提案）
# 要等全体行动者到齐才裁决，结果可能迟到整个时限——超过这个时长 WS 先回 action_accepted、
# REST 先回 202 accepted，结果随后经 WS / 状态拉取获得（issue #115 浏览器实测、#134）。
ACCEPT_WAIT_SEC = 2.0


class SubmitOutcome(BaseModel):
    """一次提交的裁决结果（PRD §4.1 统一信封的 runtime 侧形态）。"""

    model_config = ConfigDict(frozen=True)

    ok: bool
    event_id: str | None = None
    state_version: int
    rejected_reason: str | None = None


class NotYourTurnError(RuntimeError):
    """未开窗提交（api 映射 409）。"""


class StalePromptError(NotYourTurnError):
    """提交信封的 state_version 与当前窗口不符（issue #125）：迟到提交不得落入下一窗口。"""


@runtime_checkable
class SupportsResultFeedback(Protocol):
    """runner 裁决后回填结果的可选端口能力（Bot 端口不实现即忽略）。"""

    def notify_result(
        self, rejected_reason: str | None, state_version: int, event_id: str | None
    ) -> None: ...


@runtime_checkable
class SupportsEventIngest(Protocol):
    """可摄入可见事件流的端口能力（AgentPlayerPort 实现；registry 据此订阅 memory）。"""

    async def on_events(self, events: list[Event]) -> None: ...


class HumanPlayerPort:
    """外接玩家端口（真人或外部 Agent，经 REST/WS 驱动）。

    act 开窗并等待 submit 解析 Future；超时/重试/默认行动完全由 runner 持有。
    裁决结果由 runner 经 notify_result 回填给 submit 的调用方。
    """

    def __init__(self) -> None:
        self._senders: list[Callable[[TurnPrompt], Awaitable[None]]] = []
        # 窗口结束通知（issue #125）：无论被谁提交还是超时取消，都把该窗口的 state_version
        # 告诉每条连接，其它标签页据此清掉残留 prompt
        self._closers: list[Callable[[int], None]] = []
        self._prompt: TurnPrompt | None = None
        self._pending: asyncio.Future[Action] | None = None
        self._outcome: asyncio.Future[SubmitOutcome] | None = None
        self._armed = asyncio.Event()

    @property
    def current_prompt(self) -> TurnPrompt | None:
        return self._prompt

    def attach_sender(self, sender: Callable[[TurnPrompt], Awaitable[None]]) -> None:
        """登记一条推送通道；同座位多连接（如同账号多标签页）都收到 prompt，先提交者生效。"""
        if not any(s is sender for s in self._senders):
            self._senders.append(sender)

    def detach_sender(self, sender: Callable[[TurnPrompt], Awaitable[None]]) -> None:
        """只摘除调用方自己的通道，不影响同座位其它连接。"""
        self._senders = [s for s in self._senders if s is not sender]

    def attach_closer(self, closer: Callable[[int], None]) -> None:
        """登记窗口结束回调（issue #125）：参数为已结束窗口的 state_version。"""
        if not any(c is closer for c in self._closers):
            self._closers.append(closer)

    def detach_closer(self, closer: Callable[[int], None]) -> None:
        self._closers = [c for c in self._closers if c is not closer]

    def _notify_closed(self, state_version: int) -> None:
        for closer in list(self._closers):
            try:
                closer(state_version)
            except Exception:
                self.detach_closer(closer)

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self._prompt = TurnPrompt(observation=observation, deadline_ts=deadline_ts)
        self._pending = asyncio.get_running_loop().create_future()
        self._armed.set()
        for sender in list(self._senders):
            try:
                await sender(self._prompt)
            except Exception:
                self.detach_sender(sender)  # 坏连接自摘除；不影响其它连接，玩家亦可经 REST 轮询
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
            self._notify_closed(observation.state_version)

    async def wait_armed(self, timeout: float) -> TurnPrompt | None:
        """my-turn 长轮询：挂起至开窗或超时（返回 None）。已开窗时立即返回，
        timeout=0 也拿得到 prompt（asyncio.wait_for 对 0 超时会先取消再判定，不能依赖它）。"""
        if self._armed.is_set():
            return self._prompt
        try:
            await asyncio.wait_for(self._armed.wait(), timeout)
        except TimeoutError:
            return None
        return self._prompt

    def submit(
        self, action: Action, state_version: int | None = None
    ) -> asyncio.Future[SubmitOutcome]:
        """提交行动，返回裁决结果 future；未开窗抛 NotYourTurnError。

        state_version（issue #125）：信封带上时必须等于当前 prompt 的观察版本，否则抛
        StalePromptError——迟到的提交不会被当作下一窗口的行动。
        """
        if self._pending is None or self._pending.done() or self._prompt is None:
            raise NotYourTurnError("当前不在该玩家的行动窗口")
        if state_version is not None and state_version != self._prompt.observation.state_version:
            raise StalePromptError("提交针对的行动窗口已结束（state_version 不匹配）")
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
