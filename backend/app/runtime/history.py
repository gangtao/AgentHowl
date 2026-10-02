"""历史对局摘要（issue #98）：只读事件文件派生列表，零网络。

status：末条事件为 GAME_OVER → finished；否则 registry 里有活 handle → live；否则 aborted
（重启丢掉的中途局）。单个坏文件跳过并 warning，不拖垮整张列表。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.engine.events import Event, EventType
from app.runtime.registry import GameRegistry
from app.store.event_store import EventStore, GameMeta

logger = logging.getLogger(__name__)

GameStatus = Literal["finished", "live", "aborted"]


class SeatSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    seat: int
    display_name: str
    agent: bool  # meta.agents 里有该座位的档案（或 "*" 兜底）


class GameSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    game_id: str
    preset: str
    num_players: int
    status: GameStatus
    started_at: str | None
    ended_at: str | None
    winner: str | None
    rounds: int
    seats: list[SeatSummary]
    seq: int


def is_finished(events: Sequence[Event]) -> bool:
    return bool(events) and events[-1].type == EventType.GAME_OVER


def summarize_game(meta: GameMeta, events: Sequence[Event], live: bool) -> GameSummary:
    finished = is_finished(events)
    status: GameStatus = "finished" if finished else ("live" if live else "aborted")
    winner = None
    if finished:
        winner = getattr(events[-1].payload, "winner", None)
    rounds = max(
        (int(getattr(e.payload, "round", 0)) for e in events if e.type == EventType.ROUND_STARTED),
        default=0,
    )
    agents = meta.agents
    seats = [
        SeatSummary(
            seat=s.seat,
            display_name=s.display_name,
            agent=str(s.seat) in agents or ("*" in agents),
        )
        for s in meta.roster
    ]
    return GameSummary(
        game_id=meta.game_id,
        preset=meta.config.config_id,
        num_players=meta.config.num_players,
        status=status,
        started_at=events[0].meta.get("wall_ts") if events else None,
        ended_at=events[-1].meta.get("wall_ts") if finished else None,
        winner=None if winner is None else str(winner),
        rounds=rounds,
        seats=seats,
        seq=events[-1].seq if events else 0,
    )


def _is_live(registry: GameRegistry, game_id: str) -> bool:
    try:
        handle = registry.get(game_id)
    except LookupError:
        return False
    return handle.task is not None and not handle.task.done()


def list_history(store: EventStore, registry: GameRegistry) -> list[GameSummary]:
    out: list[GameSummary] = []
    for game_id in store.list_games():
        try:
            meta = store.load_meta(game_id)
            events = store.load_events(game_id)
        except Exception as exc:  # noqa: BLE001 —— 坏文件不拖垮列表
            logger.warning("历史对局 %s 读取失败，已跳过：%s", game_id, exc)
            continue
        out.append(summarize_game(meta, events, live=_is_live(registry, game_id)))
    # 有时间戳的在前且按时间倒序；无时间戳的排最后
    out.sort(key=lambda s: (s.started_at is not None, s.started_at or ""), reverse=True)
    return out
