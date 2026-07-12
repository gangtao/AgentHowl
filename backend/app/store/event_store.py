"""EventStore：对局事件的 append-only 持久化层（issue #28，M2.1）。

装载 = reduce(load_events)。规格：docs/superpowers/specs/2026-07-12-event-store-design.md。
分层约束：store 只 import engine；engine 保持零 IO，禁止反向依赖。
本层不含任何裁决/业务逻辑，只做持久化与不变量守卫。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
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


class JsonFileEventStore:
    """JSONL 文件实现：一局一文件，逐行追加，进程重启可恢复。

    并发假设：单进程单写者（MVP）。写通缓存以磁盘为真相，重启 = 新实例重读。
    不做 fsync：MVP 单机可接受，崩溃丢尾由残尾修复兜底（Task 4）。
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        # 写通缓存：首次触碰某局时从盘装载
        self._cache: dict[str, tuple[GameMeta, list[Event]]] = {}

    def create_game(self, meta: GameMeta) -> None:
        _check_game_id(meta.game_id)
        path = self._path(meta.game_id)
        if path.exists():
            raise GameExistsError(f"对局已存在：{meta.game_id}")
        self._write_line(path, {"kind": "meta", "data": meta.model_dump(mode="json")})
        self._cache[meta.game_id] = (meta, [])

    def append(self, game_id: str, event: Event) -> None:
        _, events = self._ensure_loaded(game_id)
        last_seq = events[-1].seq if events else 0
        _check_append(game_id, last_seq, event)
        self._write_line(self._path(game_id), {"kind": "event", "data": event_to_json(event)})
        events.append(event)

    def load_meta(self, game_id: str) -> GameMeta:
        return self._ensure_loaded(game_id)[0]

    def load_events(self, game_id: str, from_seq: int = 0) -> list[Event]:
        return [e for e in self._ensure_loaded(game_id)[1] if e.seq >= from_seq]

    def list_games(self) -> list[str]:
        return sorted(p.stem for p in self._data_dir.glob("*.jsonl"))

    # ---------- 内部 ----------

    def _path(self, game_id: str) -> Path:
        _check_game_id(game_id)
        return self._data_dir / f"{game_id}.jsonl"

    def _write_line(self, path: Path, record: dict[str, object]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _ensure_loaded(self, game_id: str) -> tuple[GameMeta, list[Event]]:
        if game_id not in self._cache:
            self._cache[game_id] = self._load_from_disk(game_id)
        return self._cache[game_id]

    def _load_from_disk(self, game_id: str) -> tuple[GameMeta, list[Event]]:
        path = self._path(game_id)
        if not path.exists():
            raise GameNotFoundError(f"对局不存在：{game_id}")
        records = self._read_records(path)
        if not records or records[0].get("kind") != "meta":
            raise StoreCorruptionError(f"{path.name}：首行必须是 meta 记录")
        try:
            meta = GameMeta.model_validate(records[0]["data"])
        except (KeyError, ValidationError) as exc:
            raise StoreCorruptionError(f"{path.name}：meta 记录损坏：{exc}") from exc
        events: list[Event] = []
        for i, rec in enumerate(records[1:], start=1):
            if rec.get("kind") != "event":
                raise StoreCorruptionError(
                    f"{path.name}:{i}：非法记录 kind={rec.get('kind')!r}（meta 重复？）"
                )
            ev = event_from_json(rec.get("data"))
            if ev.seq != i:
                raise StoreCorruptionError(
                    f"{path.name}:{i}：seq 洞或错位：期望 {i}，实得 {ev.seq}"
                )
            if ev.game_id != game_id:
                raise StoreCorruptionError(
                    f"{path.name}:{i}：事件 game_id={ev.game_id}，与文件不符"
                )
            events.append(ev)
        return meta, events

    def _read_records(self, path: Path) -> list[dict[str, object]]:
        """逐行解析信封。唯一豁免：未换行的残尾字节（崩溃中断的 append）
        视为未完成写入，忽略并当场截断（开箱修复）；其余缺陷一律 fail-loud。"""
        records: list[dict[str, object]] = []
        raw = path.read_bytes()
        good_len = 0
        for i, line in enumerate(raw.split(b"\n")[:-1]):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreCorruptionError(f"{path.name}:{i}：坏行：{exc}") from exc
            if not isinstance(rec, dict):
                raise StoreCorruptionError(f"{path.name}:{i}：记录不是 JSON 对象")
            records.append(rec)
            good_len += len(line) + 1
        if good_len < len(raw):
            with path.open("rb+") as f:
                f.truncate(good_len)
        return records
