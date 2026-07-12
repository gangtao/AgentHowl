"""EventStore：对局事件的 append-only 持久化层（issue #28，M2.1）。

装载 = reduce(load_events)。规格：docs/superpowers/specs/2026-07-12-event-store-design.md。
分层约束：store 只 import engine；engine 保持零 IO，禁止反向依赖。
本层不含任何裁决/业务逻辑，只做持久化与不变量守卫。
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.engine.config import Faction, GameConfig, RoleType
from app.engine.events import EVENT_PAYLOAD_TYPES, Event, EventType, reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState, Player


class StoreError(Exception):
    """store 层错误基类。"""


class GameExistsError(StoreError):
    """create_game 目标已存在。"""


class GameNotFoundError(StoreError):
    """按 game_id 找不到对局。"""


class SeqConflictError(StoreError):
    """append 的 seq 不等于 last_seq + 1（洞或重复）。"""


class StoreCorruptionError(StoreError):
    """持久化数据不可信：坏行、meta 异常、seq 洞等。"""


class SeatName(BaseModel):
    model_config = ConfigDict(frozen=True)

    seat: int
    display_name: str


class GameMeta(BaseModel):
    """JSONL 首行头记录：冷装载 reduce 所需的全部初始信息。"""

    model_config = ConfigDict(frozen=True)

    game_id: str
    config: GameConfig
    roster: tuple[SeatName, ...]


def event_to_json(event: Event) -> dict[str, object]:
    d = event.model_dump(mode="json")
    # Explicitly serialize payload's actual type (not base EventPayload)
    d["payload"] = event.payload.model_dump(mode="json")
    return d


def event_from_json(data: object) -> Event:
    """从 JSON dict 重建 Event：经 EVENT_PAYLOAD_TYPES 还原具体 payload 类。"""
    if not isinstance(data, dict):
        raise StoreCorruptionError(f"事件记录不是 JSON 对象：{type(data).__name__}")
    try:
        etype = EventType(str(data["type"]))
        payload_cls = EVENT_PAYLOAD_TYPES[etype]
        payload = payload_cls.model_validate(data["payload"])
        return Event.model_validate({**data, "payload": payload})
    except (KeyError, ValueError, ValidationError) as exc:
        raise StoreCorruptionError(f"事件反序列化失败：{exc}") from exc


def initial_state(meta: GameMeta) -> GameState:
    """构造发牌前空白状态（与 engine.create_game 的初始形状一致）。

    真实角色由事件流中的 ROLES_ASSIGNED 写入；此处一律 VILLAGER/GOOD 占位。
    """
    seats = sorted(s.seat for s in meta.roster)
    if seats != list(range(meta.config.num_players)):
        raise StoreError(f"名册座位非法：期望 0..{meta.config.num_players - 1} 稠密，实得 {seats}")
    players = tuple(
        Player(
            seat=s.seat,
            display_name=s.display_name,
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for s in sorted(meta.roster, key=lambda s: s.seat)
    )
    return GameState(
        game_id=meta.game_id,
        config=meta.config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )


_GAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_game_id(game_id: str) -> None:
    """game_id 触盘前校验（路径穿越防护）；两个实现共用同一口径。"""
    if not _GAME_ID_RE.fullmatch(game_id):
        raise StoreError(f"非法 game_id：{game_id!r}（仅允许 [A-Za-z0-9_-]+）")


def _check_append(game_id: str, last_seq: int, event: Event) -> None:
    """append 前置不变量：game_id 归属 + seq 稠密（首事件 seq=1）。"""
    if event.game_id != game_id:
        raise StoreError(f"事件 game_id 不匹配：期望 {game_id}，实得 {event.game_id}")
    if event.seq != last_seq + 1:
        raise SeqConflictError(
            f"seq 不连续：期望 {last_seq + 1}，实得 {event.seq}（game_id={game_id}）"
        )


class EventStore(Protocol):
    """事件持久化契约。实现：InMemoryEventStore / JsonFileEventStore。"""

    def create_game(self, meta: GameMeta) -> None: ...

    def append(self, game_id: str, event: Event) -> None: ...

    def load_meta(self, game_id: str) -> GameMeta: ...

    def load_events(self, game_id: str, from_seq: int = 0) -> list[Event]: ...

    def list_games(self) -> list[str]: ...


class InMemoryEventStore:
    """内存实现：测试与单进程 MVP 用。"""

    def __init__(self) -> None:
        self._games: dict[str, tuple[GameMeta, list[Event]]] = {}

    def create_game(self, meta: GameMeta) -> None:
        _check_game_id(meta.game_id)
        if meta.game_id in self._games:
            raise GameExistsError(f"对局已存在：{meta.game_id}")
        self._games[meta.game_id] = (meta, [])

    def append(self, game_id: str, event: Event) -> None:
        _, events = self._get(game_id)
        last_seq = events[-1].seq if events else 0
        _check_append(game_id, last_seq, event)
        events.append(event)

    def load_meta(self, game_id: str) -> GameMeta:
        return self._get(game_id)[0]

    def load_events(self, game_id: str, from_seq: int = 0) -> list[Event]:
        return [e for e in self._get(game_id)[1] if e.seq >= from_seq]

    def list_games(self) -> list[str]:
        return sorted(self._games)

    def _get(self, game_id: str) -> tuple[GameMeta, list[Event]]:
        try:
            return self._games[game_id]
        except KeyError:
            raise GameNotFoundError(f"对局不存在：{game_id}") from None


def load_state(store: EventStore, game_id: str) -> GameState:
    """装载 = reduce(load_events)：从头记录 + 事件流重建当前状态。"""
    return reduce_all(initial_state(store.load_meta(game_id)), store.load_events(game_id))
