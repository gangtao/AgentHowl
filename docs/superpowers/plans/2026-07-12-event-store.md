# EventStore 实施计划（issue #28，M2.1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `backend/app/store/event_store.py`：append-only 事件持久化（内存 + JSONL 双实现），装载 = `reduce(load_events)`。

**Architecture:** `EventStore` Protocol + 两个对等实现（`InMemoryEventStore`、`JsonFileEventStore`），共享一个校验核心。JSONL 首行为 `GameMeta` 头记录；事件编解码放 store 侧（经 `EVENT_PAYLOAD_TYPES` 还原具体 payload 类），引擎零改动。规格见 `docs/superpowers/specs/2026-07-12-event-store-design.md`。

**Tech Stack:** Python 3.11+ / Pydantic v2 / pytest。无新依赖。

## Global Constraints

- 所有命令在 `backend/` 下运行：`uv run pytest`、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format .`
- ruff line-length = 100；mypy strict：所有函数全量注解
- 注释/docstring 中文，标识符/API 英文（CLAUDE.md 约定）
- store 只 import engine；engine 禁止 import store（零 IO 不变量）
- 全同步接口；不引入 fsync/异步/句柄缓存/快照/Postgres（规格 YAGNI 清单）
- `from_seq` 为闭区间下界：返回 `seq >= from_seq`，默认 0 全量
- 引擎事实：`_emit` 保证 `seq = state_version + 1`，空白态 `state_version=0`，故首事件 `seq=1`、序列稠密
- 工作分支：`feat/event-store`（已存在，含规格提交）

---

### Task 1: 包骨架 + 错误类型 + GameMeta + 事件编解码 + initial_state

**Files:**
- Create: `backend/app/store/__init__.py`
- Create: `backend/app/store/event_store.py`
- Test: `backend/tests/test_event_store.py`

**Interfaces:**
- Consumes: `app.engine.events.Event / EVENT_PAYLOAD_TYPES / EventType / reduce_all`；`app.engine.state.GameState / Player`；`app.engine.config.GameConfig / RoleType / Faction`；`app.engine.phases.Phase`
- Produces（后续任务依赖，签名以此为准）:
  - `StoreError(Exception)`；子类 `GameExistsError / GameNotFoundError / SeqConflictError / StoreCorruptionError`
  - `SeatName(BaseModel, frozen)`: `seat: int`, `display_name: str`
  - `GameMeta(BaseModel, frozen)`: `game_id: str`, `config: GameConfig`, `roster: tuple[SeatName, ...]`
  - `event_to_json(event: Event) -> dict[str, object]`
  - `event_from_json(data: object) -> Event`（坏数据 → `StoreCorruptionError`）
  - `initial_state(meta: GameMeta) -> GameState`（名册非稠密 0..n-1 或与 `config.num_players` 不符 → `StoreError`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_event_store.py`：

```python
"""EventStore 测试：编解码、契约（双实现参数化）、文件专项。issue #28。"""

import pytest

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import Event, reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState
from app.store.event_store import (
    GameMeta,
    SeatName,
    StoreError,
    event_from_json,
    event_to_json,
    initial_state,
)


def _run_fixture_game(seed: int = 42) -> tuple[GameMeta, GameState, list[Event]]:
    """跑一局 9 人 bot 对局，返回 (meta, 终局状态, 事件流)。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id="g1")
    roster = tuple(
        SeatName(seat=p.seat, display_name=p.display_name) for p in final.players
    )
    return GameMeta(game_id="g1", config=final.config, roster=roster), final, events


def _assert_replay_matches(replayed: GameState, final: GameState) -> None:
    """回放状态与实时终局一致（口径与 test_determinism 一致，排除游标字段）。"""
    assert replayed.phase == final.phase == Phase.GAME_OVER
    assert replayed.winner == final.winner
    assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
    assert [p.role for p in replayed.players] == [p.role for p in final.players]
    assert replayed.sheriff_seat == final.sheriff_seat
    assert replayed.election_stage == final.election_stage


class TestCodec:
    def test_roundtrip_whole_game(self) -> None:
        """整局事件 JSON 往返后逐条相等（payload 具体类不丢失）。"""
        _, _, events = _run_fixture_game()
        for ev in events:
            restored = event_from_json(event_to_json(ev))
            assert restored == ev
            assert type(restored.payload) is type(ev.payload)

    def test_bad_event_type_fails_loud(self) -> None:
        from app.store.event_store import StoreCorruptionError

        _, _, events = _run_fixture_game()
        d = event_to_json(events[0])
        d["type"] = "NO_SUCH_EVENT"
        with pytest.raises(StoreCorruptionError):
            event_from_json(d)

    def test_non_dict_fails_loud(self) -> None:
        from app.store.event_store import StoreCorruptionError

        with pytest.raises(StoreCorruptionError):
            event_from_json("not a dict")


class TestInitialState:
    def test_replay_from_initial_state(self) -> None:
        """initial_state(meta) 作为回放起点，reduce_all 后与实时终局一致。"""
        meta, final, events = _run_fixture_game()
        replayed = reduce_all(initial_state(meta), events)
        _assert_replay_matches(replayed, final)

    def test_sparse_roster_rejected(self) -> None:
        meta, _, _ = _run_fixture_game()
        holed = GameMeta(
            game_id=meta.game_id,
            config=meta.config,
            roster=meta.roster[1:],  # 缺 0 号座
        )
        with pytest.raises(StoreError):
            initial_state(holed)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.store'`

- [ ] **Step 3: 最小实现**

`backend/app/store/__init__.py`：

```python
# AgentHowl 包标记
```

`backend/app/store/event_store.py`：

```python
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
    return event.model_dump(mode="json")


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
        raise StoreError(
            f"名册座位非法：期望 0..{meta.config.num_players - 1} 稠密，实得 {seats}"
        )
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全部通过（203 passed 左右）；mypy/ruff 零报错

```bash
git add backend/app/store backend/tests/test_event_store.py
git commit -m "feat(store): GameMeta 头记录、事件编解码与 initial_state (issue #28)"
```

---

### Task 2: EventStore Protocol + 校验核心 + InMemoryEventStore + load_state

**Files:**
- Modify: `backend/app/store/event_store.py`（追加）
- Test: `backend/tests/test_event_store.py`（追加）

**Interfaces:**
- Consumes: Task 1 全部符号；`app.engine.events.reduce_all`
- Produces:
  - `class EventStore(Protocol)`：`create_game(meta: GameMeta) -> None`；`append(game_id: str, event: Event) -> None`；`load_meta(game_id: str) -> GameMeta`；`load_events(game_id: str, from_seq: int = 0) -> list[Event]`；`list_games() -> list[str]`
  - `InMemoryEventStore`（实现同上五方法）
  - `load_state(store: EventStore, game_id: str) -> GameState`
  - 内部共享核心：`_check_game_id(game_id: str) -> None`（正则 `^[A-Za-z0-9_-]+$`，违规 → `StoreError`）；`_check_append(game_id: str, last_seq: int, event: Event) -> None`

- [ ] **Step 1: 写失败测试（契约测试，参数化 fixture 先只挂 memory）**

在 `backend/tests/test_event_store.py` 顶部的 `from app.store.event_store import (...)`
中追加名字：`EventStore`、`GameExistsError`、`GameNotFoundError`、
`InMemoryEventStore`、`SeqConflictError`、`load_state`。然后追加：

```python
@pytest.fixture(params=["memory"])
def store(request: pytest.FixtureRequest) -> EventStore:
    """契约测试跑在所有实现上；Task 3 追加 "jsonl" 参数。"""
    assert request.param == "memory"
    return InMemoryEventStore()


class TestContract:
    def test_roundtrip_and_load_state(self, store: EventStore) -> None:
        meta, final, events = _run_fixture_game()
        store.create_game(meta)
        for ev in events:
            store.append("g1", ev)
        assert store.load_meta("g1") == meta
        assert store.load_events("g1") == events
        _assert_replay_matches(load_state(store, "g1"), final)

    def test_from_seq_inclusive(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        for ev in events:
            store.append("g1", ev)
        assert store.load_events("g1", from_seq=5) == [e for e in events if e.seq >= 5]
        assert store.load_events("g1", from_seq=events[-1].seq + 1) == []

    def test_seq_duplicate_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        store.append("g1", events[0])
        with pytest.raises(SeqConflictError):
            store.append("g1", events[0])

    def test_seq_gap_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        with pytest.raises(SeqConflictError):
            store.append("g1", events[1])  # 首事件必须 seq=1

    def test_cross_game_id_rejected(self, store: EventStore) -> None:
        meta, _, events = _run_fixture_game()
        store.create_game(meta)
        alien = events[0].model_copy(update={"game_id": "other"})
        with pytest.raises(StoreError):
            store.append("g1", alien)

    def test_unknown_game_fails(self, store: EventStore) -> None:
        _, _, events = _run_fixture_game()
        with pytest.raises(GameNotFoundError):
            store.load_meta("nope")
        with pytest.raises(GameNotFoundError):
            store.load_events("nope")
        with pytest.raises(GameNotFoundError):
            store.append("nope", events[0])

    def test_duplicate_create_rejected(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        store.create_game(meta)
        with pytest.raises(GameExistsError):
            store.create_game(meta)

    def test_bad_game_id_rejected(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        for bad in ("", "a/b", "..", "a b", "中"):
            evil = GameMeta(game_id=bad, config=meta.config, roster=meta.roster)
            with pytest.raises(StoreError):
                store.create_game(evil)

    def test_list_games_sorted(self, store: EventStore) -> None:
        meta, _, _ = _run_fixture_game()
        for gid in ("g2", "g1"):
            store.create_game(
                GameMeta(game_id=gid, config=meta.config, roster=meta.roster)
            )
        assert store.list_games() == ["g1", "g2"]
```

注意：`test_roundtrip_and_load_state` 等用例内 `store.append("g1", ...)` 的 game_id
与 `_run_fixture_game` 固定的 `game_id="g1"` 一致。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: FAIL —— `ImportError: cannot import name 'EventStore'`

- [ ] **Step 3: 最小实现**

追加到 `backend/app/store/event_store.py`（导入区补 `import re`、
`from typing import Protocol`，engine 导入补 `reduce_all`）：

```python
_GAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_game_id(game_id: str) -> None:
    """game_id 触盘前校验（路径穿越防护）；两个实现共用同一口径。"""
    if not _GAME_ID_RE.fullmatch(game_id):
        raise StoreError(f"非法 game_id：{game_id!r}（仅允许 [A-Za-z0-9_-]+）")


def _check_append(game_id: str, last_seq: int, event: Event) -> None:
    """append 前置不变量：game_id 归属 + seq 稠密（首事件 seq=1）。"""
    if event.game_id != game_id:
        raise StoreError(
            f"事件 game_id 不匹配：期望 {game_id}，实得 {event.game_id}"
        )
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
    return reduce_all(
        initial_state(store.load_meta(game_id)), store.load_events(game_id)
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: 14 passed（5 旧 + 9 新）

- [ ] **Step 5: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全部通过

```bash
git add backend/app/store/event_store.py backend/tests/test_event_store.py
git commit -m "feat(store): EventStore Protocol、校验核心与内存实现 (issue #28)"
```

---

### Task 3: JsonFileEventStore 主路径（JSONL 头记录 + 重启恢复）

**Files:**
- Modify: `backend/app/store/event_store.py`（追加）
- Test: `backend/tests/test_event_store.py`（fixture 加参 + 文件专项）

**Interfaces:**
- Consumes: Task 1/2 全部符号
- Produces: `JsonFileEventStore(data_dir: Path)`，实现 `EventStore` 五方法。
  文件格式：`<data_dir>/<game_id>.jsonl`，每行
  `{"kind": "meta" | "event", "data": {...}}`，第 0 行必须是唯一 meta。
  实例内维护写通缓存（磁盘为真相，重启 = 新实例重读）。
  本任务坏行一律 `StoreCorruptionError`；残尾修复在 Task 4 放宽。

- [ ] **Step 1: 扩 fixture + 写失败测试**

修改 `backend/tests/test_event_store.py` 的 fixture 为双参数（替换原 fixture）；
顶部导入区补 `from pathlib import Path`，store 导入块补 `JsonFileEventStore`：

```python
@pytest.fixture(params=["memory", "jsonl"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> EventStore:
    """契约测试跑在所有实现上。"""
    if request.param == "memory":
        return InMemoryEventStore()
    return JsonFileEventStore(tmp_path / "data")
```

追加文件专项测试：

```python
class TestJsonFile:
    def test_restart_reloads(self, tmp_path: Path) -> None:
        """同一 data_dir 新建实例（模拟进程重启）后装载与续写均正常。"""
        meta, final, events = _run_fixture_game()
        s1 = JsonFileEventStore(tmp_path / "d")
        s1.create_game(meta)
        for ev in events[:-1]:
            s1.append("g1", ev)

        s2 = JsonFileEventStore(tmp_path / "d")
        assert s2.load_meta("g1") == meta
        assert s2.load_events("g1") == events[:-1]
        s2.append("g1", events[-1])  # seq 续接
        _assert_replay_matches(load_state(s2, "g1"), final)

    def test_list_games_from_disk(self, tmp_path: Path) -> None:
        meta, _, _ = _run_fixture_game()
        s1 = JsonFileEventStore(tmp_path / "d")
        s1.create_game(meta)
        s2 = JsonFileEventStore(tmp_path / "d")
        assert s2.list_games() == ["g1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: FAIL —— `ImportError: cannot import name 'JsonFileEventStore'`

- [ ] **Step 3: 最小实现**

追加到 `backend/app/store/event_store.py`（导入区补 `import json`、
`from pathlib import Path`）：

```python
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
        self._write_line(
            self._path(game_id), {"kind": "event", "data": event_to_json(event)}
        )
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
        """逐行解析信封。Task 4 在此加入残尾修复；当前坏行一律 fail-loud。"""
        records: list[dict[str, object]] = []
        raw = path.read_bytes()
        for i, line in enumerate(raw.split(b"\n")[:-1]):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreCorruptionError(f"{path.name}:{i}：坏行：{exc}") from exc
            if not isinstance(rec, dict):
                raise StoreCorruptionError(f"{path.name}:{i}：记录不是 JSON 对象")
            records.append(rec)
        if raw and not raw.endswith(b"\n"):
            raise StoreCorruptionError(f"{path.name}：文件未以换行结尾")
        return records
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: 25 passed（契约 9 用例 ×2 实现 + 编解码/initial_state 5 + 文件专项 2）

- [ ] **Step 5: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全部通过

```bash
git add backend/app/store/event_store.py backend/tests/test_event_store.py
git commit -m "feat(store): JsonFileEventStore JSONL 实现与重启恢复 (issue #28)"
```

---

### Task 4: 残尾开箱修复 + 其余损坏 fail-loud

**Files:**
- Modify: `backend/app/store/event_store.py`（改 `_read_records`）
- Test: `backend/tests/test_event_store.py`（追加损坏专项）

**Interfaces:**
- Consumes: Task 3 的 `JsonFileEventStore._read_records`
- Produces: 行为变化——**未以换行结尾的尾部字节视为崩溃中断的 append**：
  装载时忽略并当场截断文件（开箱修复）；其余任何缺陷仍 `StoreCorruptionError`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_event_store.py` 的 `TestJsonFile`：

```python
    def _populated_dir(self, tmp_path: Path) -> tuple[Path, GameMeta, list[Event]]:
        meta, _, events = _run_fixture_game()
        s = JsonFileEventStore(tmp_path / "d")
        s.create_game(meta)
        for ev in events[:10]:
            s.append("g1", ev)
        return tmp_path / "d" / "g1.jsonl", meta, events

    def test_torn_tail_repaired(self, tmp_path: Path) -> None:
        """残尾行（崩溃中断的 append）开箱截断，装载与续写正常。"""
        path, _, events = self._populated_dir(tmp_path)
        with path.open("ab") as f:
            f.write(b'{"kind": "event", "da')  # 无换行的半行

        s = JsonFileEventStore(path.parent)
        assert s.load_events("g1") == events[:10]
        s.append("g1", events[10])  # 修复后可继续追加
        assert not path.read_bytes().rstrip(b"\n").endswith(b'"da')
        # 再次冷装载验证文件已物理修复
        assert JsonFileEventStore(path.parent).load_events("g1") == events[:11]

    def test_middle_bad_line_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        lines[3] = b"@@garbage@@"
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_terminated_bad_tail_fails_loud(self, tmp_path: Path) -> None:
        """以换行结尾的坏行不是残尾，是真损坏。"""
        path, _, _ = self._populated_dir(tmp_path)
        with path.open("ab") as f:
            f.write(b"@@garbage@@\n")
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_duplicate_meta_fails_loud(self, tmp_path: Path) -> None:
        path, meta, _ = self._populated_dir(tmp_path)
        with path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"kind": "meta", "data": meta.model_dump(mode="json")}) + "\n"
            )
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_seq_hole_in_file_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        del lines[3]  # 抠掉一条中间事件 → seq 洞
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")

    def test_meta_not_first_fails_loud(self, tmp_path: Path) -> None:
        path, _, _ = self._populated_dir(tmp_path)
        lines = path.read_bytes().split(b"\n")
        lines[0], lines[1] = lines[1], lines[0]
        path.write_bytes(b"\n".join(lines))
        with pytest.raises(StoreCorruptionError):
            JsonFileEventStore(path.parent).load_events("g1")
```

测试文件导入区补：`import json`、`StoreCorruptionError`。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_event_store.py -k "TestJsonFile" -v`
Expected: `test_torn_tail_repaired` FAIL（当前实现对未换行尾部抛
`StoreCorruptionError`）；其余 5 个损坏用例 PASS（Task 3 已 fail-loud）

- [ ] **Step 3: 实现残尾修复**

替换 `_read_records` 中"文件未以换行结尾"的分支为开箱截断（标准 WAL 实践——
我们每行单次 write 落盘，写到一半只会缺尾部换行；以换行结尾的行必是完整写入）：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_event_store.py -v`
Expected: 31 passed

- [ ] **Step 5: 全量质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全部通过（229 passed 左右）

```bash
git add backend/app/store/event_store.py backend/tests/test_event_store.py
git commit -m "feat(store): 残尾开箱修复，其余损坏 fail-loud，闭环 issue #28"
```

---

## 完成后

按 finishing-a-development-branch 流程：push `feat/event-store`、开 PR 关联
issue #28（用户在 GitHub 上自行合并；不在本地 merge main）。
