"""RatingIndex（issue #123）：从事件日志推导各档案积分，进程内缓存，不落盘。

IO 层，持有 EventStore。不依赖终局钩子：snapshot() 每次遍历 list_games()，已结束且带
agent_ids 的对局只 reduce 一次（结果不可变），其余不缓存。坏文件跳过 + warning，与 list_history
一致。snapshot() 是同步函数，由 Starlette 线程池执行（agents 端点为同步 def），
可能与事件循环及自身并发；缓存值不可变、重复计算结果相同，因此并发只多做一次计算，
不影响正确性。
"""

from __future__ import annotations

import logging

from app.engine.events import EventType, reduce_all
from app.runtime.rating import AgentRating, FinishedGame, compute_ratings
from app.store.event_store import EventStore, initial_state

logger = logging.getLogger(__name__)


class RatingIndex:
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._cache: dict[str, FinishedGame] = {}

    def extract_finished(self, game_id: str) -> FinishedGame | None:
        """已结束且带 agent_ids 的对局 → FinishedGame（缓存）；否则 None 且不缓存。"""
        cached = self._cache.get(game_id)
        if cached is not None:
            return cached
        try:
            meta = self._store.load_meta(game_id)
            if not meta.agent_ids:
                return None
            events = self._store.load_events(game_id)
            if not events or events[-1].type != EventType.GAME_OVER:
                return None
            final = reduce_all(initial_state(meta), events)
            last = events[-1]
            winner = getattr(last.payload, "winner", None)
            finished = FinishedGame(
                game_id=game_id,
                ended_at=last.meta.get("wall_ts") or str(last.ts),
                winner=None if winner is None else str(winner),
                seat_factions={p.seat: p.faction for p in final.players},
                agent_ids={int(seat): aid for seat, aid in meta.agent_ids.items()},
            )
        except Exception as exc:  # noqa: BLE001 —— 坏文件不拖垮积分表
            logger.warning("对局 %s 读取失败，积分已跳过：%s", game_id, exc, exc_info=True)
            return None
        self._cache[game_id] = finished
        return finished

    def snapshot(self) -> dict[str, AgentRating]:
        """当前全部档案的积分（纯函数重算，线性）。"""
        games = [
            fg for gid in self._store.list_games() if (fg := self.extract_finished(gid)) is not None
        ]
        return compute_ratings(games)
