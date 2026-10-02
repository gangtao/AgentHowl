# 历史对局与无 token 回放（issue #98）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端重启后，前端「历史对局」页能列出 `data/games/` 里的全部对局并逐局回放；已结束对局无需 token 即可回放（开关可关）。

**Architecture:** 新增纯读的 `app/runtime/history.py` 从事件文件派生对局摘要；`rest.py` 加 `GET /games`，已结束对局的 `/replay` `/meta` `/speeches` 在内存 registry 无 handle 时退回 store；`AGENTHOWL_PUBLIC_HISTORY` 控制是否要求 token。前端加 `#/history` 页与 `#/g/{id}?replay=1` 无 token 回放引导。引擎零改动。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / uv；React 18 + TS strict + Zustand 4 + Vitest。

**Spec:** `docs/superpowers/specs/2026-10-02-game-history-design.md`

## Global Constraints

- 引擎零改动；`app/runtime`、`app/api` 模块级不 import `agent_player` / `llm_client`（`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫）。
- 开关开（默认）时公开的只有**已结束**对局（事件流末条 `GAME_OVER`）的事件流与 meta；进行中对局的 `/state` `/events` WS 行为、现有 token 流程**逐字不变**（现有测试不改语义即通过）。
- 列表与回放响应不含 token、不含 Provider 信息（meta 从不含密钥）。
- 中文注释、英文标识符；ruff 100（中文宽 2）；mypy strict；后端测试零网络零 mock（`InMemoryEventStore` / `tmp_path`）；前端测试假 `fetch`。
- 每个任务结束前全绿：后端 `uv run pytest -q -x --ignore=tests/test_api_e2e.py`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、litellm 守卫；前端 `npm run check`、`npm run build`。
- commit message 结尾空一行后附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

---

### Task 1: 对局摘要 `app/runtime/history.py`

**Files:**
- Create: `backend/app/runtime/history.py`
- Test: `backend/tests/test_history.py`（新）

**Interfaces:**
- Produces: `SeatSummary{seat, display_name, agent}`、`GameSummary{game_id, preset, num_players, status, started_at, ended_at, winner, rounds, seats, seq}`、`summarize_game(meta, events, live) -> GameSummary`、`is_finished(events) -> bool`、`list_history(store, registry) -> list[GameSummary]`。
- Consumes: `app.store.event_store.EventStore`（`list_games/load_meta/load_events`）、`GameMeta{game_id, config, roster, agents}`、`app.runtime.registry.GameRegistry`（`get(game_id)` 抛 `LookupError`；`GameHandle.task: asyncio.Task | None`）。

- [ ] **Step 1: 写失败测试** `backend/tests/test_history.py`

```python
"""对局摘要（issue #98）：从事件流派生 finished / live / aborted 三态；坏文件跳过。"""

import asyncio
import logging

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import EventType
from app.runtime.history import is_finished, list_history, summarize_game
from app.runtime.registry import GameRegistry
from app.store.event_store import GameMeta, InMemoryEventStore, SeatName


def _finished_game(store: InMemoryEventStore, game_id: str, seed: int = 3) -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    _final, events = run_game(cfg, game_id=game_id)
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(GameMeta(game_id=game_id, config=cfg, roster=roster, agents={}))
    for i, e in enumerate(events):
        wall = f"2026-10-02T00:00:{i % 60:02d}+00:00"
        store.append(game_id, e.model_copy(update={"meta": {**e.meta, "wall_ts": wall}}))


def test_summarize_finished_game() -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_done")
    meta, events = store.load_meta("g_done"), store.load_events("g_done")
    s = summarize_game(meta, events, live=False)
    assert s.status == "finished" and is_finished(events)
    assert s.preset == "std_9_kill_side" and s.num_players == 9
    assert s.winner in ("GOOD", "WOLF")
    assert s.rounds == max(
        int(e.payload.round)  # type: ignore[attr-defined]
        for e in events
        if e.type == EventType.ROUND_STARTED
    )
    assert s.started_at == events[0].meta["wall_ts"] and s.ended_at == events[-1].meta["wall_ts"]
    assert s.seq == events[-1].seq
    assert [x.seat for x in s.seats] == list(range(9)) and not any(x.agent for x in s.seats)


def test_summarize_aborted_and_live() -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_cut")
    meta, events = store.load_meta("g_cut"), store.load_events("g_cut")
    partial = events[:40]  # 截断：没有 GAME_OVER
    assert not is_finished(partial)
    assert summarize_game(meta, partial, live=False).status == "aborted"
    assert summarize_game(meta, partial, live=True).status == "live"
    s = summarize_game(meta, partial, live=False)
    assert s.ended_at is None and s.winner is None and s.seq == partial[-1].seq


def test_seats_mark_agents_from_meta() -> None:
    from app.agent.profile import AgentProfile

    store = InMemoryEventStore()
    _finished_game(store, "g_a")
    meta = store.load_meta("g_a").model_copy(
        update={"agents": {"2": AgentProfile(name="夜枭", model="ollama/x")}}
    )
    s = summarize_game(meta, store.load_events("g_a"), live=False)
    assert s.seats[2].agent is True and s.seats[0].agent is False


async def test_list_history_sorts_desc_and_skips_corrupt(caplog) -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_old", seed=1)
    _finished_game(store, "g_new", seed=2)
    # 让 g_new 的首条事件更晚
    old = store.load_events("g_new")
    store._games["g_new"] = (  # noqa: SLF001 —— 测试直写内存实现
        store.load_meta("g_new"),
        [e.model_copy(update={"meta": {**e.meta, "wall_ts": "2026-10-03T00:00:00+00:00"}}) for e in old],
    )
    # 坏记录：有 meta 但事件为空也能列出（started_at None 排最后）；load 抛错的要跳过
    store._games["g_bad"] = (store.load_meta("g_old"), [])  # noqa: SLF001

    class _Boom(InMemoryEventStore):
        def load_events(self, game_id: str, from_seq: int = 0):  # type: ignore[override]
            if game_id == "g_bad":
                raise RuntimeError("坏文件")
            return super().load_events(game_id, from_seq)

    boom = _Boom()
    boom._games = store._games  # noqa: SLF001
    registry = GameRegistry(boom, None, None, None, None)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="app.runtime.history"):
        out = list_history(boom, registry)
    assert [s.game_id for s in out] == ["g_new", "g_old"]
    assert any("g_bad" in r.getMessage() for r in caplog.records)
    await asyncio.sleep(0)  # 保持 async 用例形态（asyncio_mode=auto）
```

> 若 `GameRegistry(...)` 的构造参数与此不符（看 `app/runtime/registry.py::GameRegistry.__init__`），按真实签名构造——只需要 `get()` 行为；`live` 判断在 `list_history` 内用 `registry.get(game_id)` 捕获 `LookupError`。

- [ ] **Step 2: 跑测试确认失败**：`uv run pytest -q tests/test_history.py` → `ModuleNotFoundError: app.runtime.history`。

- [ ] **Step 3: 实现** `backend/app/runtime/history.py`

```python
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
    # 新的在前；无时间戳的排最后；同值按 game_id 稳定
    out.sort(key=lambda s: (s.started_at is None, "" if s.started_at is None else s.started_at), reverse=False)
    out.sort(key=lambda s: s.started_at or "", reverse=True)
    return out
```

> 排序写成一次：`out.sort(key=lambda s: (s.started_at is not None, s.started_at or ""), reverse=True)`——有时间戳的在前且按时间倒序，无时间戳的在最后。实现时用这一行替换上面两行。
> `meta.config.config_id` 若在 `GameConfig` 上不叫这个名（看 `app/engine/config.py`），按真实字段取 preset 名；`meta.agents` 的类型是 `dict[str, AgentProfile]`。

- [ ] **Step 4: 跑测试确认通过 + 全量**（含 litellm 守卫：`history.py` 顶层只 import registry/store/events）。
- [ ] **Step 5: Commit** `feat(runtime): 历史对局摘要 history.py——finished/live/aborted 三态，坏文件跳过 (issue #98)`

---

### Task 2: `GET /games` + 已结束对局退回 store + `AGENTHOWL_PUBLIC_HISTORY`

**Files:**
- Modify: `backend/app/api/deps.py`（`optional_token`）、`backend/app/api/rest.py`（列表端点 + 三个端点回退）、`backend/app/main.py`（`public_history` 参数与 env）
- Test: `backend/tests/test_api_history.py`（新）

**Interfaces:**
- Consumes: Task 1 的 `list_history` / `is_finished`；`app.state.public_history: bool`。
- Produces: `GET /api/v1/games -> list[GameSummary]`；`optional_token(...) -> TokenInfo | None`；`create_app(public_history: bool | None = None)`。

- [ ] **Step 1: 写失败测试** `backend/tests/test_api_history.py`

```python
"""历史列表与无 token 回放（issue #98）：重启（换 registry、同一 store）后仍可回放；开关关则回到 401。"""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore


def _app(store: InMemoryEventStore, public_history: bool | None = None) -> TestClient:
    app = create_app(
        store=store,
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
        public_history=public_history,
    )
    return TestClient(app)


def _play_to_end(client: TestClient, seed: int) -> dict:
    body = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": seed}}
    ).json()
    client.post(
        f"/api/v1/games/{body['game_id']}/start",
        json={},
        headers={"Authorization": f"Bearer {body['host_token']}"},
    )
    handle = client.app.state.games.get(body["game_id"])  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    return body


@pytest.fixture
def store() -> Iterator[InMemoryEventStore]:
    yield InMemoryEventStore()


def test_list_games_mixes_finished_and_live(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=3)
        pending = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()  # 未开局
        rows = c.get("/api/v1/games").json()
    by_id = {r["game_id"]: r for r in rows}
    assert by_id[done["game_id"]]["status"] == "finished"
    assert by_id[done["game_id"]]["winner"] in ("GOOD", "WOLF")
    assert pending["game_id"] not in by_id  # 未开局没有事件文件，不在列表里
    assert all("token" not in r for r in rows)


def test_finished_game_replays_without_token_after_restart(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=5)
    gid = done["game_id"]
    with _app(store) as c2:  # 新进程：registry/token 全空，只有 store
        assert c2.get("/api/v1/games").json()[0]["game_id"] == gid
        replay = c2.get(f"/api/v1/games/{gid}/replay")
        meta = c2.get(f"/api/v1/games/{gid}/meta")
        speeches = c2.get(f"/api/v1/games/{gid}/speeches")
        assert replay.status_code == 200 and replay.json()[-1]["type"] == "GAME_OVER"
        assert meta.status_code == 200 and meta.json()["game_id"] == gid
        assert speeches.status_code == 200
        # 旧 token 失效也无妨
        assert c2.get(f"/api/v1/games/{gid}/replay", headers={"Authorization": "Bearer stale"}).status_code == 401
        # 进行中 / 不存在的对局不受影响
        assert c2.get("/api/v1/games/g_nope/replay").status_code == 404
        assert c2.get(f"/api/v1/games/{gid}/state").status_code == 401


def test_live_game_still_requires_token(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        assert c.get(f"/api/v1/games/{gid}/replay").status_code == 401
        assert (
            c.get(f"/api/v1/games/{gid}/replay", headers={"Authorization": f"Bearer {body['gm_token']}"}).status_code
            == 403
        )  # 未结束：与现状一致


def test_public_history_switch_off(store: InMemoryEventStore, monkeypatch) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=7)
    gid = done["game_id"]
    with _app(store, public_history=False) as c2:
        assert c2.get("/api/v1/games").status_code == 401
        assert c2.get(f"/api/v1/games/{gid}/replay").status_code == 401
    monkeypatch.setenv("AGENTHOWL_PUBLIC_HISTORY", "0")
    with _app(store) as c3:
        assert c3.get("/api/v1/games").status_code == 401
    monkeypatch.setenv("AGENTHOWL_PUBLIC_HISTORY", "1")
    with _app(store) as c4:
        assert c4.get("/api/v1/games").status_code == 200
```

> 注意：`stale` token 用例的预期——开关开时「带了无效 token」应视为无 token（200）还是 401？规格：有 token 则按原逻辑校验。无效 token → `tokens.resolve` 为 None → 401。保持该断言。若实现者认为 200 更合理，报告说明，不要擅改。

- [ ] **Step 2: 跑测试确认失败**（`create_app` 不认识 `public_history` → TypeError）。

- [ ] **Step 3: 实现**

`backend/app/api/deps.py` 追加：

```python
def optional_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    tokens: TokenRegistry = Depends(get_tokens),
) -> TokenInfo | None:
    """没带 token → None；带了就必须有效（无效仍 401），避免「坏 token 等于匿名」的歧义。"""
    if creds is None:
        return None
    info = tokens.resolve(creds.credentials)
    if info is None:
        raise HTTPException(status_code=401, detail="token 无效")
    return info
```

`backend/app/api/rest.py`：

```python
from app.runtime.history import GameSummary, is_finished, list_history


def _public_history(request: Request) -> bool:
    return bool(getattr(request.app.state, "public_history", True))


def _require_history_access(info: TokenInfo | None, public: bool) -> None:
    if info is None and not public:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")


@router.get("")
def list_games_endpoint(
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> list[GameSummary]:
    """历史对局列表（issue #98）：文件里的全部对局 + registry 的进行中状态。"""
    _require_history_access(info, _public_history(request))
    return list_history(games.store, games)


def _finished_from_store(games: GameRegistry, game_id: str) -> GameMeta:
    """registry 没有该局时退回事件文件：存在且已终局才开放，否则与现状同样的 404/403。"""
    try:
        meta = games.store.load_meta(game_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"对局不存在：{game_id}") from None
    if not is_finished(games.store.load_events(game_id)):
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")
    return meta


def _finished_or_handle(
    games: GameRegistry, game_id: str, info: TokenInfo | None, public: bool, *kinds: str
) -> None:
    """三个终局接口共用的门槛：有活 handle 走原逻辑（必须有 token）；无 handle 走 store 回退。"""
    try:
        handle = games.get(game_id)
    except LookupError:
        _require_history_access(info, public)
        if info is not None:
            require_kind(info, game_id, *kinds)
        _finished_from_store(games, game_id)
        return
    handle.ensure_healthy()
    if info is None:
        if not (public and handle.started and handle.live_state().phase == Phase.GAME_OVER):
            raise HTTPException(status_code=401, detail="缺少 Bearer token")
        return
    require_kind(info, game_id, *kinds)
    if not handle.started or handle.live_state().phase != Phase.GAME_OVER:
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")
```

然后把 `replay_endpoint`、`meta_endpoint`、`speeches_endpoint` 的签名改为 `request: Request, info: TokenInfo | None = Depends(optional_token)`，开头统一调用 `_finished_or_handle(games, game_id, info, _public_history(request), <原 kinds>)`，再用 `games.store.load_events / load_meta` 产出（它们本就从 store 读）。`speeches_endpoint` 原来对「未开局」返回 `[]`——改为：无 handle 时走回退（已终局必有事件）；有 handle 且未开局仍返回 `[]`，保持现状。`require_kind` 对 `/meta` `/replay` 的 kinds 含 `"HOST"`，`/speeches` 不含——照抄原值。`/meta` 的 403 文案原为「对局未结束，对局元数据未开放」，回退路径复用 `_finished_from_store` 的文案即可（测试只断言状态码）。

`backend/app/main.py`：`create_app(..., public_history: bool | None = None)`；

```python
    if public_history is None:
        raw = os.environ.get("AGENTHOWL_PUBLIC_HISTORY", "1").strip().lower()
        public_history = raw not in ("0", "false", "no", "off")
    app.state.public_history = public_history
```

- [ ] **Step 4: 跑测试确认通过 + 全量**（现有 `test_api_*` 全部不改）。
- [ ] **Step 5: Commit** `feat(api): GET /games 历史列表；已结束对局无 token 回放（退回 store）；AGENTHOWL_PUBLIC_HISTORY (issue #98)`

---

### Task 3: 前端——`#/history` 页、`?replay=1` 无 token 回放

**Files:**
- Modify: `frontend/src/api/tokens.ts`、`frontend/src/api/rest.ts`、`frontend/src/App.tsx`、`frontend/src/pages/GamePage.tsx`
- Create: `frontend/src/api/history.ts`、`frontend/src/store/history.ts`、`frontend/src/pages/History.tsx` + `History.module.css`、`frontend/src/components/HistoryTable/HistoryTable.tsx` + `.module.css`
- Test: `frontend/src/api/tokens.test.ts`（追加）、`frontend/src/store/history.test.ts`（新）、`frontend/src/components/HistoryTable/HistoryTable.test.tsx`（新）

**Interfaces:**
- Consumes: `GET /api/v1/games -> GameSummary[]`（Task 2 形状）；`getMeta/getReplay` token 可选；`useGameStore.load(meta, {gameId, token, viewer, mode})`。
- Produces: `parseHash` 新返回 `{route: "history"}` 与 `{route: "game", gameId, replay: true, viewer: "GM"}`；`useHistory`；`History` 页；`GamePage` 新 prop `replay?: boolean`。

- [ ] **Step 1: 写失败测试**

`src/api/tokens.test.ts` 追加：

```ts
it("history 路由与 replay=1 无 token 回放", () => {
  expect(parseHash("#/history")).toEqual({ route: "history" });
  expect(parseHash("#/g/g_abc?replay=1")).toEqual({ route: "game", gameId: "g_abc", replay: true, viewer: "GM" });
  // gm 与 replay 同时出现：有 token 走原路径
  expect(parseHash("#/g/g_abc?gm=T&replay=1")).toEqual({ route: "game", gameId: "g_abc", token: "T", viewer: "GM" });
});
```

`src/store/history.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useHistory } from "./history";

const rows = [
  { game_id: "g_new", preset: "std_9_kill_side", num_players: 9, status: "finished", started_at: "2026-10-02T03:00:00+00:00", ended_at: "2026-10-02T03:10:00+00:00", winner: "GOOD", rounds: 3, seats: [], seq: 120 },
  { game_id: "g_live", preset: "std_12_yn_hunter_guard", num_players: 12, status: "live", started_at: "2026-10-02T02:00:00+00:00", ended_at: null, winner: null, rounds: 1, seats: [], seq: 30 },
];

describe("useHistory", () => {
  beforeEach(() => {
    useHistory.setState({ items: [], loading: false, error: null });
  });
  it("refresh 拉取 /api/v1/games", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(rows), { status: 200, headers: { "content-type": "application/json" } })));
    await useHistory.getState().refresh();
    expect(useHistory.getState().items.map((r) => r.game_id)).toEqual(["g_new", "g_live"]);
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]?.[0]).toContain("/api/v1/games");
  });
  it("失败落 error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "缺少 Bearer token" }), { status: 401 })));
    await useHistory.getState().refresh();
    expect(useHistory.getState().error).toContain("缺少 Bearer token");
  });
});
```

`src/components/HistoryTable/HistoryTable.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HistoryTable from "./HistoryTable";

const base = { preset: "std_9_kill_side", num_players: 9, rounds: 2, seq: 50, seats: [{ seat: 0, display_name: "夜枭", agent: true }, { seat: 1, display_name: "Bot1", agent: false }] };

describe("HistoryTable", () => {
  it("三种状态的操作列", () => {
    render(
      <HistoryTable
        items={[
          { ...base, game_id: "g_f", status: "finished", started_at: "2026-10-02T03:00:00+00:00", ended_at: "2026-10-02T03:10:00+00:00", winner: "WOLF" },
          { ...base, game_id: "g_l", status: "live", started_at: "2026-10-02T02:00:00+00:00", ended_at: null, winner: null },
          { ...base, game_id: "g_a", status: "aborted", started_at: "2026-10-02T01:00:00+00:00", ended_at: null, winner: null },
        ]}
      />,
    );
    const replay = screen.getByRole("link", { name: /回放/ });
    expect(replay).toHaveAttribute("href", "#/g/g_f?replay=1");
    expect(screen.getByText(/狼人胜/)).toBeInTheDocument();
    expect(screen.getByText(/直播中/)).toBeInTheDocument();
    expect(screen.getByText(/中断/)).toBeInTheDocument();
    expect(screen.getByText(/夜枭/)).toBeInTheDocument();
  });
  it("空态", () => {
    render(<HistoryTable items={[]} />);
    expect(screen.getByText(/还没有对局/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**：`npm run test`。

- [ ] **Step 3: 实现**

`src/api/tokens.ts`：`Route` 加 `"history"`；`ParsedHash` 加 `replay?: boolean`；`/history` 分支与 `/agents` 同形；`/g/` 分支在 `gm`/`spec` 之后：`if (query.get("replay") === "1") return { route: "game", gameId, replay: true, viewer: "GM" };`。

`src/api/rest.ts`：`getMeta(gameId, token?)`、`getReplay(gameId, token?)`——`req` 已支持 `token` 为 `undefined` 时不加 `Authorization`（核对 `req` 实现，若不支持则补 `if (opts.token)`）。

`src/api/history.ts`：

```ts
import { req } from "./rest";

export type GameStatus = "finished" | "live" | "aborted";
export interface SeatSummary { seat: number; display_name: string; agent: boolean }
export interface GameSummary {
  game_id: string; preset: string; num_players: number; status: GameStatus;
  started_at: string | null; ended_at: string | null; winner: string | null;
  rounds: number; seats: SeatSummary[]; seq: number;
}
export function listGames(): Promise<GameSummary[]> {
  return req<GameSummary[]>("GET", "/games");
}
```

`src/store/history.ts`：照 `store/providers.ts` 的 `{items, loading, error, refresh}` 形态，`refresh` 用 `listGames()`，错误经同样的 `messageOf`。

`components/HistoryTable/HistoryTable.tsx`（props `{ items: GameSummary[] }`）：nocturne `.table`；列：开始时间（`new Date(started_at)` → `MM-DD HH:mm` 本地时区；null → `—`）、板子（`PRESET_LABEL[preset] ?? preset`，映射 4 个板子的中文名：`std_9_kill_side` 9 人屠边、`std_9_kill_all` 9 人屠城、`std_12_yn_hunter_idiot` 12 人预女猎白、`std_12_yn_hunter_guard` 12 人预女猎守）、人数、状态（已结束 / 直播中 / 中断于第 N 轮）、胜方（`GOOD` 好人胜、`WOLF` 狼人胜、null `—`）、轮数、座位（`seats.map(s => s.display_name).join("、")`，超过 6 个用 `title` 放全文、单元格截断）、操作：`finished` → `<a className="btn btn-primary" href={`#/g/${id}?replay=1`}>回放</a>`；`live` → 文字「直播中 · 用建局时的链接观看」；`aborted` → 文字「中断于第 N 轮」。空态：`还没有对局，<a href="#/">去建一局</a>`。

`pages/History.tsx`：挂载时 `refresh()`；标题「历史对局」+「刷新」按钮（loading 时禁用）+ `error` 行 + `<HistoryTable items={items} />`。样式照 `Providers.module.css` 的页面容器。

`App.tsx`：`NAV` 加 `{ href: "#/history", label: "历史对局", route: "history" }`（放在「新的一局」之后）；路由分支加 `hash.route === "history" ? <History /> : …`；`GamePage` 传 `replay={hash.replay}`，`key` 里带上 `replay`。

`pages/GamePage.tsx`：props 加 `replay?: boolean`。引导 effect 开头：

```ts
if (replay) {
  // 历史回放：无 token，直接装入（后端只对已结束对局开放）
  let cancelled = false;
  (async () => {
    try {
      const meta = await getMeta(gameId!);
      const events = await getReplay(gameId!);
      if (cancelled) return;
      const store = useGameStore.getState();
      store.load(meta, { gameId, token: "", viewer: "GM", mode: "replay" });
      store.appendEvents(events);
      setErrorKind(null); setReady(true);
    } catch (err) {
      if (cancelled) return;
      if (err instanceof ApiError && err.status === 404) { setErrorKind("4404"); setDetail(err.detail); return; }
      if (err instanceof ApiError && err.status === 403) { setErrorKind("error"); setDetail("对局未结束，暂不可回放"); return; }
      setErrorKind("error"); setDetail(err instanceof ApiError ? `${err.status} · ${err.detail}` : String(err));
    }
  })();
  return () => { cancelled = true; useGameStore.getState().reset(); setReady(false); };
}
```

并把原来 `if (!gameId || !token || !viewer)` 的 auth 判定改为 `if (!gameId || (!replay && (!token || !viewer)))`。`useLiveEvents` 的 `enabled` 已要求 `mode === "live"`，回放不会连 WS。PhaseBar 在 `mode === "replay"` 时显示「回放」——不改；若顶栏有「上帝 / 观众」切换按钮依赖 `token`，`replay` 模式下隐藏这两个按钮（无 token 可切）。

- [ ] **Step 4: `npm run check` + `npm run build` 全绿；手工验收**：`make serve`（或 docker）+ `make fe-dev`，`#/history` 列出 `backend/data/games/` 里的对局，点「回放」能拖到终局；重启后端再试一次仍可回放；建一局进行中的随机 bot 局显示「直播中」。
- [ ] **Step 5: Commit** `feat(frontend): 历史对局页 #/history 与 ?replay=1 无 token 回放 (issue #98)`

---

### Task 4: 文档

**Files:**
- Modify: `README.md`（「前端」小节加「历史对局」；「Docker 运行」把「文件里的事件流可回放」改为指向历史页；环境变量 `AGENTHOWL_PUBLIC_HISTORY` 说明）、`docs/specs/requirements.md`（§5.2 端点表加 `GET /games` 与已结束对局公开回放策略一行）、`.env.example`（加注释行 `#AGENTHOWL_PUBLIC_HISTORY=1`）。

- [ ] **Step 1: 改文档**；README 「历史对局」段落要点：入口 `#/history`、已结束对局无需 token 即可回放（本地单用户默认；多用户用 `AGENTHOWL_PUBLIC_HISTORY=0` 关闭后恢复 token 要求）、直播中与中断局的显示。
- [ ] **Step 2: `make check`**（含 fe-check）全绿。
- [ ] **Step 3: Commit** `docs: 历史对局页与 AGENTHOWL_PUBLIC_HISTORY 说明；PRD §5.2 加 GET /games (issue #98)`

---

## Self-Review

- **Spec 覆盖**：§2.1 → T1；§2.2/§2.3 → T2；§3 → T3；§4 → T4；§5 测试分布在 T1–T3。
- **类型一致性**：`GameSummary` 字段（后端 pydantic ↔ 前端 TS 接口）逐字相同：`game_id, preset, num_players, status, started_at, ended_at, winner, rounds, seats{seat, display_name, agent}, seq`；`optional_token` 名称在 T2 定义、仅 T2 使用；`parseHash` 的 `replay` 字段在 T3 内自洽。
- **import 方向**：`history.py` 只依赖 engine.events / store / registry；`rest.py` 新增 import 来自 `app.runtime.history`（不含 litellm）。
