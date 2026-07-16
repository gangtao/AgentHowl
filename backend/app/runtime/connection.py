"""ConnectionManager：进程内订阅者按视角接收过滤后的事件流（issue #29）。

过滤复用引擎 observation.visible_events —— 信息隔离的单一实现点；
本模块不自造任何过滤逻辑。M2.3 的 WS 端点将以订阅者身份接入。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.engine.events import Event
from app.engine.observation import Viewer, visible_events
from app.engine.state import GameState

Subscriber = Callable[[list[Event]], Awaitable[None]]

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider
        self._subs: list[tuple[Viewer, Subscriber]] = []

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
                logger.warning("订阅者回调异常，已摘除 viewer=%r", viewer, exc_info=True)
                self.unsubscribe(viewer, cb)
