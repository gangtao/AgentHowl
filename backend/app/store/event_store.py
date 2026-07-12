"""EventStore：对局事件的 append-only 持久化层（issue #28，M2.1）。

装载 = reduce(load_events)。规格：docs/superpowers/specs/2026-07-12-event-store-design.md。
分层约束：store 只 import engine；engine 保持零 IO，禁止反向依赖。
本层不含任何裁决/业务逻辑，只做持久化与不变量守卫。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from app.engine.config import Faction, GameConfig, RoleType
from app.engine.events import EVENT_PAYLOAD_TYPES, Event, EventType
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
