"""ConnectionManager：进程内订阅者按视角接收过滤后的事件流（issue #29）。

过滤复用引擎 observation.visible_events —— 信息隔离的单一实现点；
帧订阅也按视角过滤（issue #110）。本模块不自造任何过滤逻辑。M2.3 的 WS 端点将以订阅者身份接入。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.engine.events import Event, EventType
from app.engine.observation import Viewer, visible_events
from app.engine.phases import Phase
from app.engine.state import GameState

Subscriber = Callable[[list[Event]], Awaitable[None]]
# 原始帧订阅者（issue #103 / #110）：帧不是事件，但必须声明来源事件，按视角过滤后投递
FrameSubscriber = Callable[[dict[str, Any]], Awaitable[None]]
# 阶段订阅者（issue #128）：只收 (公开阶段名, round) 列表，不经手任何事件内容
PhaseSubscriber = Callable[[list[tuple[str, int]]], Awaitable[None]]


def public_phase(phase: Phase) -> str:
    """非 GM 视角可见的阶段名：夜间子阶段一律折叠为 NIGHT。

    引擎即使该神职已死也会进入对应子阶段并立即以 ROLE_SKIPPED 跳过（engine._system_transition），
    暴露子阶段名会让观众 / 玩家从「某子阶段零时长」推断神职死活；现实局里法官只说「天黑请闭眼」
    同样不透露谁在动。白天各阶段的 PHASE_CHANGED 本就是 PUBLIC，原样给出。
    """
    return "NIGHT" if phase.value.startswith("NIGHT_") else phase.value


logger = logging.getLogger(__name__)


# runner 崩溃的终止帧（issue #39）：REST 端点经 ensure_healthy 对崩溃局返 500，WS 连接此前
# 只是无声断流。文案不带异常文本（与 REST 对非 GM 视角不泄露内部细节同口径），详情看服务端日志。
RUNNER_CRASHED_FRAME: dict[str, Any] = {
    "type": "error",
    "code": "RUNNER_CRASHED",
    "detail": "对局运行异常，已停摆（详情见服务端日志）",
}
WS_CLOSE_RUNNER_CRASHED = 4500


def runner_crashed(task: asyncio.Task[Any] | None) -> bool:
    """runner task 以异常结束（非取消）。"""
    return (
        task is not None and task.done() and not task.cancelled() and task.exception() is not None
    )


class ConnectionManager:
    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider
        self._subs: list[tuple[Viewer, Subscriber]] = []
        self._frame_subs: list[tuple[Viewer, FrameSubscriber]] = []
        self._phase_subs: list[PhaseSubscriber] = []

    def subscribe(self, viewer: Viewer, callback: Subscriber) -> None:
        self._subs.append((viewer, callback))

    def unsubscribe(self, viewer: Viewer, callback: Subscriber) -> None:
        self._subs = [(v, cb) for v, cb in self._subs if not (v == viewer and cb is callback)]

    async def broadcast(self, events: list[Event]) -> None:
        """按订阅顺序串行投递；坏订阅者摘除并告警，不中断其余投递（issue #30 加固）。"""
        state = self._state_provider()
        for viewer, cb in list(self._subs):
            visible = visible_events(state, events, viewer)
            if not visible:
                continue
            try:
                await cb(visible)
            except Exception:
                # issue #42：摘除是为了不拖垮其余投递，但对 Agent 座位意味着记忆断流、此后只凭
                # 观察行动——必须以 ERROR 级别留痕，WARNING 在默认日志级别下容易被淹没
                logger.error(
                    "订阅者回调异常，已摘除 viewer=%r：该视角此后收不到事件流"
                    "（若是 Agent 座位，其记忆自此断流，只凭观察行动）",
                    viewer,
                    exc_info=True,
                )
                self.unsubscribe(viewer, cb)
        # 阶段帧（issue #128）：夜间 PHASE_CHANGED / ROUND_STARTED 均为 GM_ONLY，非 GM 视角经
        # visible_events 裁剪后永远看不到夜晚、round 也停在 0。这里只派生 (公开阶段名, round)，
        # 事件本身仍不投递；round 取批次应用后的现值（与 WS 实时路径对 GM 的取法一致）。
        phases = [
            (public_phase(e.payload.to), state.round)  # type: ignore[attr-defined]
            for e in events
            if e.type == EventType.PHASE_CHANGED
        ]
        if not phases:
            return
        for pcb in list(self._phase_subs):
            try:
                await pcb(phases)
            except Exception:
                logger.warning("阶段订阅者回调异常，已摘除", exc_info=True)
                self.unsubscribe_phases(pcb)

    def subscribe_phases(self, callback: PhaseSubscriber) -> None:
        """阶段订阅（issue #128）：非 GM 视角用，只收 (public_phase, round)，不含事件。"""
        self._phase_subs.append(callback)

    def unsubscribe_phases(self, callback: PhaseSubscriber) -> None:
        self._phase_subs = [cb for cb in self._phase_subs if cb is not callback]

    def subscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None:
        """原始帧订阅（speech_audio 等）：帧随来源事件经 visible_events 过滤（issue #110）。"""
        self._frame_subs.append((viewer, callback))

    def unsubscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None:
        self._frame_subs = [
            (v, cb) for v, cb in self._frame_subs if not (v == viewer and cb is callback)
        ]

    async def broadcast_frame_all(self, frame: dict[str, Any]) -> None:
        """不经可见性过滤投给全部帧订阅者：只用于与任何事件无关的终止通知
        （runner 崩溃，issue #39）。坏订阅者同样摘除。"""
        for viewer, cb in list(self._frame_subs):
            try:
                await cb(frame)
            except Exception:
                logger.warning(
                    "帧订阅者回调异常，已摘除 viewer=%r type=%s",
                    viewer,
                    frame.get("type"),
                    exc_info=True,
                )
                self.unsubscribe_frames(viewer, cb)

    async def broadcast_frame(self, frame: dict[str, Any], event: Event) -> None:
        """只投给能看到 event 的视角——与事件广播同一过滤点，不自造判断。"""
        state = self._state_provider()
        for viewer, cb in list(self._frame_subs):
            if not visible_events(state, [event], viewer):
                continue
            try:
                await cb(frame)
            except Exception:
                logger.warning(
                    "帧订阅者回调异常，已摘除 viewer=%r type=%s",
                    viewer,
                    frame.get("type"),
                    exc_info=True,
                )
                self.unsubscribe_frames(viewer, cb)
