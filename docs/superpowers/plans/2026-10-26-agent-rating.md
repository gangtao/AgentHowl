# Agent 积分与战绩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每局终局后按胜负给参局的库内 Agent 档案累计 Elo 积分与战绩，在 `/agents` 带积分摘要、Agent 库按积分排序、Lobby 建局时把座位归因到档案（issue #123）。

**Architecture:** 建局请求新增 `agent_ids`，`registry.start` 展开成座位 → `agent_id` 写进 `GameMeta.agent_ids`（只在 meta 首行，不进任何 Event）。积分不落盘：`app/runtime/rating.py` 是零 IO 纯函数（`compute_ratings = fold(settle_game)`），`app/runtime/rating_index.py` 持有 `EventStore`，把每个已结束且带 `agent_ids` 的对局 reduce 成 `FinishedGame` 并进程内缓存，每次 `snapshot()` 重算。API 把 `snapshot()` 合并进 `/agents` 响应；前端只渲染服务端数字。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / pytest（uv）；React 18 / TypeScript / Zustand / Vitest。

**Spec:** `docs/superpowers/specs/2026-10-26-agent-rating-design.md`

## Global Constraints

- 引擎目录零改动：完成后 `git diff --stat main -- backend/app/engine frontend/src/engine/__fixtures__` 必须为空；不跑 `make fixtures`。
- `app/runtime`、`app/api`、`app/cli` 不在模块级 import litellm / `app.agent.agent_player` / `app.agent.llm_client`；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫（本计划把 `app.cli.rating`、`app.runtime.rating_index` 加进参数化）。
- `GameMeta.agent_ids` 只在 meta 里，不进任何 Event；`GET /games/{id}/meta` 响应剔除 `agent_ids`；`visible_events` / `/events` / `/replay` / WS `game_event` 不含它（分享链接匿名可见）。
- 可见性：普通用户只能看自己档案的积分，admin 全部；`/agents/{id}/rating` 不存在与无权一律 404（沿用 `_get_owned_agent`）。
- 数值常量：`INITIAL_RATING = 1000.0`、`K_FACTOR = 32.0`、`HISTORY_LIMIT = 200`；`rating` / `delta` 保留 float 不四舍五入，展示层取整。
- 建局 400 文案（逐字）：`agent_ids 非法：座位 X 没有对应的 agents 档案`、`agent_ids 非法：档案不存在：<id>`。
- 前端文案（逐字）：战绩行 `1024 分 · 12 局 · 胜率 58%`，无战绩 `尚无战绩`；排序切换按钮 `最近更新` / `积分`；CLI 已删除档案名显示 `(已删除)`。
- 后端门禁（在 `backend/` 下）：`uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q --ignore=tests/test_api_e2e.py`。已知基线失败（与本计划无关，忽略）：`tests/test_api_admin.py::test_list_patch_verify`、`tests/test_api_admin.py::test_concurrent_cross_demotion_keeps_one_admin`（issue #124）。
- 前端门禁（在 `frontend/` 下）：`npm run check`。
- ruff：行宽 100，`select = E,F,W,I,UP,B,SIM`；mypy strict（只查 `app`）。ruff 也检查 `tests/`；跑 `--check` 门禁前先 `uv run ruff format . && uv run ruff check --fix .`（格式器会重排测试里的长字面量，E501 需手工折行）。文档与注释中文，标识符英文。
- 提交信息末尾加 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`；每个任务一次提交；分支 `feat/agent-rating`（已存在，spec 已提交）。
- 前端 / 后端目录不同，每条命令都用绝对路径 `cd /Users/gangtao/Code/gang/AgentHowl/backend` 或 `.../frontend`（会话 cwd 会漂移）。

## Review Focus

spec 隐含但未逐条点名的输入，各自的测试已塞进拥有该代码的任务：

1. 同一 `agent_id` 被两个座位引用（`agent_ids = {"0": "a_x", "1": "a_x"}`）：建局允许；同阵营只记一局、Δ 只加一次，跨阵营记两条且相抵 → Task 1 `test_same_agent_multiple_seats_same_camp_counts_once` / `test_same_agent_in_both_camps_gets_two_entries_that_cancel`。
2. `agent_ids` 指到的座位在开局时被真人占了，或座位专属档案是内联无 id 而 `"*"` 有 id：真人座位不记；内联座位不得错拿 `"*"` 的 id → Task 2 `test_start_expands_agent_ids_per_effective_agent_seat`。
3. 两局 `ended_at` 同秒：按 `game_id` 决胜，输入乱序结果不变 → Task 1 `test_order_by_ended_at_then_game_id_regardless_of_input_order`。
4. 坏 JSONL / 单阵营坏数据：`snapshot()` 跳过并 warning，其它对局照常；`settle_game` 对全员同阵营的对局原样返回而不是除零 → Task 4 `test_corrupt_game_is_skipped_with_warning`、Task 1 `test_single_faction_game_is_ignored`。
5. 档案被删除后：`snapshot()` 仍含其积分，`/agents/{id}/rating` 404，CLI 打印 `(已删除)` → Task 5 `test_rating_accumulates_after_finished_game_and_is_owner_scoped`、Task 6 `test_rating_cli_prints_table_sorted_by_rating`。
6. 前端非整数积分（1015.6）与胜率四舍五入（7/12 → 58%）→ Task 8 `src/lib/rating.test.ts`。

---

### Task 1: 计分纯函数 `app/runtime/rating.py`

**Files:**
- Create: `backend/app/runtime/rating.py`
- Test: `backend/tests/test_rating.py`

**Interfaces:**
- Consumes: `app.engine.config.Faction`（`StrEnum`，`GOOD` / `WOLF`）。
- Produces（后续任务依赖的精确签名）:
  - `INITIAL_RATING: float = 1000.0`、`K_FACTOR: float = 32.0`、`HISTORY_LIMIT: int = 200`
  - `class FinishedGame(BaseModel)`：`game_id: str`、`ended_at: str`、`winner: str | None`、`seat_factions: dict[int, Faction]`、`agent_ids: dict[int, str]`
  - `class CampRecord(BaseModel)`：`games/wins/losses/draws: int = 0`
  - `class RatingEntry(BaseModel)`：`game_id: str`、`ended_at: str`、`camp: Faction`、`result: Literal["WIN","LOSS","DRAW"]`、`delta: float`
  - `class AgentRating(BaseModel)`：`rating: float = 1000.0`、`games/wins/losses/draws: int = 0`、`by_camp: dict[Faction, CampRecord]`（两阵营键都在）、`history: list[RatingEntry]`
  - `expected_score(own: float, other: float) -> float`
  - `settle_game(ratings: Mapping[str, AgentRating], game: FinishedGame) -> dict[str, AgentRating]`
  - `compute_ratings(games: Iterable[FinishedGame]) -> dict[str, AgentRating]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_rating.py`：

```python
"""积分纯函数（issue #123）：Elo 阵营评分 + 胜/负/平战绩；零 IO、零 mock。"""

from __future__ import annotations

import pytest

from app.engine.config import Faction
from app.runtime.rating import (
    INITIAL_RATING,
    K_FACTOR,
    AgentRating,
    FinishedGame,
    compute_ratings,
    expected_score,
    settle_game,
)

W, G = Faction.WOLF, Faction.GOOD
# 9 人局：0-2 狼，3-8 好人
FACTIONS = {s: (W if s < 3 else G) for s in range(9)}
T0 = "2026-10-26T10:00:00+00:00"


def _game(
    game_id: str, winner: str | None, agent_ids: dict[int, str], ended_at: str = T0
) -> FinishedGame:
    return FinishedGame(
        game_id=game_id,
        ended_at=ended_at,
        winner=winner,
        seat_factions=FACTIONS,
        agent_ids=agent_ids,
    )


def test_expected_score_symmetry_and_known_values() -> None:
    assert expected_score(1000.0, 1000.0) == 0.5
    assert expected_score(1100.0, 1000.0) == pytest.approx(0.640065, abs=1e-6)
    assert expected_score(1000.0, 1100.0) + expected_score(1100.0, 1000.0) == pytest.approx(1.0)


def test_wolf_win_from_equal_ratings_gives_plus_minus_16() -> None:
    out = compute_ratings([_game("g1", "WOLF", {0: "wolf_a", 3: "good_a"})])
    wolf, good = out["wolf_a"], out["good_a"]
    assert wolf.rating == pytest.approx(INITIAL_RATING + 16.0)
    assert good.rating == pytest.approx(INITIAL_RATING - 16.0)
    assert (wolf.games, wolf.wins, wolf.losses, wolf.draws) == (1, 1, 0, 0)
    assert (good.games, good.wins, good.losses, good.draws) == (1, 0, 1, 0)
    assert wolf.by_camp[W].wins == 1 and wolf.by_camp[G].games == 0
    assert good.by_camp[G].losses == 1 and good.by_camp[W].games == 0
    entry = wolf.history[0]
    assert (entry.game_id, entry.camp, entry.result, entry.ended_at) == ("g1", W, "WIN", T0)
    assert entry.delta == pytest.approx(16.0)


def test_good_win_and_draw() -> None:
    good = compute_ratings([_game("g1", "GOOD", {0: "w", 3: "g"})])
    assert good["w"].rating == pytest.approx(984.0) and good["g"].rating == pytest.approx(1016.0)
    assert good["w"].losses == 1 and good["g"].wins == 1
    draw = compute_ratings([_game("g1", None, {0: "w", 3: "g"})])
    assert draw["w"].rating == pytest.approx(1000.0) and draw["g"].rating == pytest.approx(1000.0)
    assert draw["w"].draws == 1 and draw["g"].draws == 1
    assert draw["w"].history[0].result == "DRAW" and draw["w"].history[0].delta == 0.0


def test_team_average_uses_seats_and_initial_for_seats_without_id() -> None:
    # 狼队：座位 0 档案 1300 分，座位 1、2 无 id（按 1000 代入）→ Rw = 1100；好人全 1000
    prior = {"strong": AgentRating(rating=1300.0)}
    after = settle_game(prior, _game("g1", "WOLF", {0: "strong", 3: "g"}))
    e_w = expected_score(1100.0, 1000.0)
    assert after["strong"].rating == pytest.approx(1300.0 + K_FACTOR * (1.0 - e_w))
    assert after["g"].rating == pytest.approx(1000.0 - K_FACTOR * (1.0 - e_w))
    # 平局对强队是负增量（刻意：Elo 平局语义）
    drawn = settle_game(prior, _game("g1", None, {0: "strong", 3: "g"}))
    assert drawn["strong"].rating == pytest.approx(1300.0 + K_FACTOR * (0.5 - e_w))
    assert drawn["strong"].rating < 1300.0 and drawn["strong"].draws == 1


def test_same_camp_delta_shared_and_opposite_camps_negate() -> None:
    out = compute_ratings([_game("g1", "GOOD", {0: "w1", 1: "w2", 3: "g1", 4: "g2"})])
    assert out["w1"].history[0].delta == out["w2"].history[0].delta
    assert out["g1"].history[0].delta == out["g2"].history[0].delta
    assert out["w1"].history[0].delta == pytest.approx(-out["g1"].history[0].delta)


def test_same_agent_multiple_seats_same_camp_counts_once() -> None:
    # 同档案占 3 个狼座：均分里权重 3（全 1000 时仍是 1000），但 games / Δ 只记一次
    out = compute_ratings([_game("g1", "WOLF", {0: "a", 1: "a", 2: "a"})])
    assert out["a"].games == 1 and out["a"].wins == 1 and len(out["a"].history) == 1
    assert out["a"].rating == pytest.approx(1016.0)


def test_same_agent_in_both_camps_gets_two_entries_that_cancel() -> None:
    out = compute_ratings([_game("g1", "WOLF", {0: "a", 3: "a"})])
    a = out["a"]
    assert a.games == 2 and a.wins == 1 and a.losses == 1
    assert [e.camp for e in a.history] == [W, G]
    assert [e.result for e in a.history] == ["WIN", "LOSS"]
    assert a.rating == pytest.approx(INITIAL_RATING)
    assert a.by_camp[W].wins == 1 and a.by_camp[G].losses == 1


def test_order_by_ended_at_then_game_id_regardless_of_input_order() -> None:
    t1 = "2026-10-26T11:00:00+00:00"
    g1 = _game("g1", "WOLF", {0: "a", 3: "b"}, ended_at=T0)
    g2 = _game("g2", "GOOD", {0: "a", 3: "b"}, ended_at=t1)
    g0 = _game("g0", "GOOD", {0: "a", 3: "b"}, ended_at=t1)  # 同时刻：按 game_id 决胜
    forward = compute_ratings([g1, g2, g0])
    backward = compute_ratings([g0, g2, g1])
    assert forward == backward
    assert [e.game_id for e in forward["a"].history] == ["g1", "g0", "g2"]


def test_games_without_agent_ids_are_skipped() -> None:
    assert compute_ratings([_game("g1", "WOLF", {})]) == {}


def test_settle_game_does_not_mutate_input() -> None:
    prior = {"a": AgentRating(rating=1200.0)}
    snapshot = prior["a"].model_copy(deep=True)
    settle_game(prior, _game("g1", "WOLF", {0: "a", 3: "b"}))
    assert prior == {"a": snapshot} and "b" not in prior


def test_single_faction_game_is_ignored() -> None:
    # 坏数据兜底：全员同阵营（均分无法计算）→ 原样返回，不除零
    g = FinishedGame(
        game_id="g", ended_at=T0, winner="WOLF", seat_factions={0: W, 1: W}, agent_ids={0: "a"}
    )
    assert settle_game({}, g) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_rating.py -q`
Expected: 收集阶段 `ModuleNotFoundError: No module named 'app.runtime.rating'`。

- [ ] **Step 3: 实现 `app/runtime/rating.py`**

```python
"""Agent 积分与战绩纯函数（issue #123）：Elo 风格阵营评分 + 胜/负/平，零 IO。

规则见 docs/superpowers/specs/2026-10-26-agent-rating-design.md §3.2。积分完全由已结束
对局推导（与 state = reduce(events) 同一思路），本模块不持有任何状态；只依赖 pydantic 与
app.engine.config.Faction。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.config import Faction

INITIAL_RATING = 1000.0
K_FACTOR = 32.0
HISTORY_LIMIT = 200  # API 输出截取最近 N 条；内存里全量

Result = Literal["WIN", "LOSS", "DRAW"]


class FinishedGame(BaseModel):
    """一局已结束对局的计分输入（RatingIndex 从事件日志提取）。"""

    model_config = ConfigDict(frozen=True)

    game_id: str
    ended_at: str  # GAME_OVER 事件的 meta.wall_ts（ISO 8601），缺失时退回事件 ts
    winner: str | None  # "GOOD" | "WOLF" | None（平局）
    seat_factions: dict[int, Faction]
    agent_ids: dict[int, str]  # 已展开：座位 → agent_id（只含库内档案座位）


class CampRecord(BaseModel):
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


class RatingEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    ended_at: str
    camp: Faction
    result: Result
    delta: float


def _empty_camps() -> dict[Faction, CampRecord]:
    return {Faction.GOOD: CampRecord(), Faction.WOLF: CampRecord()}


class AgentRating(BaseModel):
    rating: float = INITIAL_RATING
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    by_camp: dict[Faction, CampRecord] = Field(default_factory=_empty_camps)
    history: list[RatingEntry] = Field(default_factory=list)  # 时间顺序，全量


def expected_score(own: float, other: float) -> float:
    """Elo 期望得分：own 对 other 的期望胜率。"""
    return 1.0 / (1.0 + 10 ** ((other - own) / 400.0))


def _result_for(camp: Faction, winner: str | None) -> Result:
    if winner is None:
        return "DRAW"
    return "WIN" if winner == camp else "LOSS"


def settle_game(ratings: Mapping[str, AgentRating], game: FinishedGame) -> dict[str, AgentRating]:
    """把一局结果记到各档案上，返回新 dict（不改入参）。

    队伍均分按座位算（无 id 的座位按 INITIAL_RATING 代入，参与均值但不落账）；记账粒度是
    「档案 × 阵营」：同阵营多座位只记一条，两个阵营都占则记两条（Δ 相抵）。全员同阵营的
    坏数据对局原样返回。
    """
    out: dict[str, AgentRating] = dict(ratings)

    def rating_of(seat: int) -> float:
        aid = game.agent_ids.get(seat)
        return out[aid].rating if aid is not None and aid in out else INITIAL_RATING

    seats = sorted(game.seat_factions)
    wolves = [s for s in seats if game.seat_factions[s] == Faction.WOLF]
    goods = [s for s in seats if game.seat_factions[s] == Faction.GOOD]
    if not wolves or not goods:
        return out
    r_wolf = fmean(rating_of(s) for s in wolves)
    r_good = fmean(rating_of(s) for s in goods)
    s_wolf = 0.5 if game.winner is None else (1.0 if game.winner == Faction.WOLF else 0.0)
    delta_wolf = K_FACTOR * (s_wolf - expected_score(r_wolf, r_good))
    deltas = {Faction.WOLF: delta_wolf, Faction.GOOD: -delta_wolf}

    touched: list[tuple[str, Faction]] = []  # 按座位顺序去重，保证 history 顺序确定
    for seat in seats:
        aid = game.agent_ids.get(seat)
        if aid is None:
            continue
        key = (aid, game.seat_factions[seat])
        if key not in touched:
            touched.append(key)

    for aid, camp in touched:
        old = out.get(aid, AgentRating())
        result = _result_for(camp, game.winner)
        delta = deltas[camp]
        won, lost, drew = result == "WIN", result == "LOSS", result == "DRAW"
        rec = old.by_camp[camp]
        new_rec = rec.model_copy(
            update={
                "games": rec.games + 1,
                "wins": rec.wins + int(won),
                "losses": rec.losses + int(lost),
                "draws": rec.draws + int(drew),
            }
        )
        entry = RatingEntry(
            game_id=game.game_id, ended_at=game.ended_at, camp=camp, result=result, delta=delta
        )
        out[aid] = old.model_copy(
            update={
                "rating": old.rating + delta,
                "games": old.games + 1,
                "wins": old.wins + int(won),
                "losses": old.losses + int(lost),
                "draws": old.draws + int(drew),
                "by_camp": {**old.by_camp, camp: new_rec},
                "history": [*old.history, entry],
            }
        )
    return out


def compute_ratings(games: Iterable[FinishedGame]) -> dict[str, AgentRating]:
    """按 (ended_at, game_id) 升序逐局 fold；输入顺序不影响结果；无 agent_ids 的对局跳过。"""
    ratings: dict[str, AgentRating] = {}
    for game in sorted(games, key=lambda g: (g.ended_at, g.game_id)):
        if not game.agent_ids:
            continue
        ratings = settle_game(ratings, game)
    return ratings
```

- [ ] **Step 4: 跑测试确认通过 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_rating.py -q && uv run ruff check app/runtime/rating.py tests/test_rating.py && uv run ruff format --check app/runtime/rating.py tests/test_rating.py && uv run mypy app`
Expected: 11 passed；ruff / mypy 无报错。

- [ ] **Step 5: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/runtime/rating.py backend/tests/test_rating.py && git commit -m "feat(rating): Elo 阵营评分与战绩纯函数 settle_game / compute_ratings (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 归因——`agent_ids` 从建局请求落到 `GameMeta`

**Files:**
- Modify: `backend/app/schemas/games.py`（`CreateGameRequest`）
- Modify: `backend/app/store/event_store.py`（`GameMeta`，约第 50-66 行）
- Modify: `backend/app/runtime/registry.py`（`GameHandle.__init__`、`GameRegistry.create`、`GameRegistry.start`）
- Modify: `backend/app/runtime/game_runner.py`（`GameRunner.__init__` 与 `run()` 里的 `GameMeta(...)`）
- Test: `backend/tests/test_registry.py`、`backend/tests/test_event_store.py`

**Interfaces:**
- Consumes: 无（Task 1 独立）。
- Produces:
  - `CreateGameRequest.agent_ids: dict[str, str]`（默认 `{}`；键为座位号字符串或 `"*"`）
  - `GameMeta.agent_ids: dict[str, str]`（默认 `{}`；键为座位号字符串，已展开）
  - `GameHandle.agent_ids: dict[str, str]`（请求原值）
  - `GameRegistry.create(..., agent_ids: dict[str, str] | None = None)`
  - `GameRunner(..., agent_ids: dict[str, str] | None = None)`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registry.py` 末尾：

```python
async def test_start_expands_agent_ids_per_effective_agent_seat() -> None:
    """issue #123：agent_ids 只对实际建成 Agent 端口的座位展开；真人座位不记；
    座位专属内联档案（无 id）不得错拿 "*" 的 id。"""
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort

    store = InMemoryEventStore()
    reg = GameRegistry(
        store=store,
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    agents = {
        "0": AgentProfile(model="a"),
        "2": AgentProfile(model="inline"),
        "*": AgentProfile(model="b"),
    }
    handle = reg.create(
        cfg, allow_spectators=False, agents=agents, agent_ids={"0": "a_zero", "*": "a_star"}
    )
    assert handle.agent_ids == {"0": "a_zero", "*": "a_star"}
    reg.join(handle, "Alice", "HUMAN", seat=1)  # 真人占 1 号
    reg.start(handle, fill_with_bots=True)
    await asyncio.sleep(0)  # runner.run() 开头同步写 meta 首行
    meta = store.load_meta(handle.game_id)
    assert meta.agent_ids == {"0": "a_zero", **{str(s): "a_star" for s in range(3, 9)}}
    assert "1" not in meta.agent_ids and "2" not in meta.agent_ids
    assert handle.task is not None
    handle.task.cancel()


def test_create_without_agent_ids_defaults_empty() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    assert reg.create(cfg, allow_spectators=False).agent_ids == {}
```

追加到 `backend/tests/test_event_store.py` 末尾：

```python
def test_meta_agent_ids_roundtrip_and_default(tmp_path: Path) -> None:
    """issue #123：agent_ids 随 meta 首行落盘；旧文件缺省 {}。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 1})
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store = JsonFileEventStore(tmp_path)
    store.create_game(
        GameMeta(game_id="g_ids", config=cfg, roster=roster, agent_ids={"0": "a_x"})
    )
    store.create_game(GameMeta(game_id="g_none", config=cfg, roster=roster))
    reopened = JsonFileEventStore(tmp_path)
    assert reopened.load_meta("g_ids").agent_ids == {"0": "a_x"}
    assert reopened.load_meta("g_none").agent_ids == {}
    # 旧文件：meta 记录里根本没有 agent_ids 键
    raw = json.loads((tmp_path / "g_none.jsonl").read_text(encoding="utf-8").splitlines()[0])
    del raw["data"]["agent_ids"]
    (tmp_path / "g_old.jsonl").write_text(
        json.dumps({**raw, "data": {**raw["data"], "game_id": "g_old"}}) + "\n", encoding="utf-8"
    )
    assert JsonFileEventStore(tmp_path).load_meta("g_old").agent_ids == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_registry.py::test_start_expands_agent_ids_per_effective_agent_seat tests/test_registry.py::test_create_without_agent_ids_defaults_empty tests/test_event_store.py::test_meta_agent_ids_roundtrip_and_default -q`
Expected: 3 failed（`TypeError: ... unexpected keyword argument 'agent_ids'` / `ValidationError`）。

- [ ] **Step 3: 改 `CreateGameRequest`**

`backend/app/schemas/games.py`，在 `agents` 字段后加一行：

```python
    agents: dict[str, AgentProfile] = Field(default_factory=dict)  # 档案：座位号或 "*"（issue #56）
    # 座位号或 "*" → 库内档案 agent_id（issue #123）：键须同时出现在 agents 里；只用于归因计分
    agent_ids: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: 改 `GameMeta`**

`backend/app/store/event_store.py`，`GameMeta`：

```python
class GameMeta(BaseModel):
    """JSONL 首行头记录：冷装载 reduce 所需的全部初始信息。

    agents（issue #64）：实际建成 Agent 端口的座位 → 档案（键为座位号字符串；真人 / 随机 bot
    不记；"*" 已展开）。只供回放 / 档案评估（#60）使用，不经 observation 暴露；缺省 {} 兼容旧文件。
    owner_id（issue #114）：建局者 user_id；旧文件缺省 None = 无主，仅 admin 可见。
    agent_ids（issue #123）：实际建成 Agent 端口且来自库内档案的座位 → agent_id（已展开）。只在
    meta 里，不进任何 Event；/meta 端点回传前剔除；缺省 {} = 不计分。
    """

    model_config = ConfigDict(frozen=True)

    game_id: str
    config: GameConfig
    roster: tuple[SeatName, ...]
    agents: dict[str, AgentProfile] = {}
    owner_id: str | None = None
    agent_ids: dict[str, str] = {}
```

- [ ] **Step 5: 改 `GameRunner`**

`backend/app/runtime/game_runner.py`，`GameRunner.__init__` 签名加参数并保存；`run()` 的 `GameMeta(...)` 带上：

```python
        narration_enabled: bool = False,
        owner_id: str | None = None,
        agent_ids: dict[str, str] | None = None,
    ) -> None:
        ...
        self._owner_id = owner_id
        # 座位 → 库内档案 id（issue #123）；只写进 meta，运行时不读
        self._agent_ids: dict[str, str] = dict(agent_ids or {})
```

```python
        meta = GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name) for i, e in enumerate(self._roster)
            ),
            agents=self._agents,
            owner_id=self._owner_id,
            agent_ids=self._agent_ids,
        )
```

- [ ] **Step 6: 改 `GameRegistry`**

`backend/app/runtime/registry.py`：

`GameHandle.__init__` 加参数 `agent_ids: dict[str, str] | None = None`（放在 `owner_id` 之后），并在 `self.owner_id = owner_id` 后加：

```python
        # 座位号或 "*" → 库内档案 id（issue #123）；start() 按实际建成的 Agent 端口展开进 meta
        self.agent_ids: dict[str, str] = dict(agent_ids or {})
```

`GameRegistry.create` 签名在 `require_provider: bool = False,` 后加 `agent_ids: dict[str, str] | None = None,`；构造 `GameHandle(...)` 时传 `agent_ids=agent_ids,`（与 `owner_id=owner_id,` 相邻）。

`GameRegistry.start` 的端口装配循环改为：

```python
        effective: AgentProfiles = {}  # 实际建成 Agent 端口的座位 → 档案，写进 meta（issue #64）
        effective_ids: dict[str, str] = {}  # 同上，座位 → 库内档案 id（issue #123）
        for seat in range(handle.config.num_players):
            if seat not in handle.ports:
                profile = handle.profile_for(seat)
                if profile is None:
                    handle.ports[seat] = BotPlayerPort(state_provider=_state_of)
                else:
                    handle.ports[seat] = self._build_agent_port(seat, handle)
                    effective[str(seat)] = profile
                    # 与 profile_for 同一优先级：座位专属档案只认座位专属 id，否则取 "*" 的 id
                    key = str(seat) if str(seat) in handle.agents else "*"
                    aid = handle.agent_ids.get(key)
                    if aid is not None:
                        effective_ids[str(seat)] = aid
```

`GameRunner(...)` 构造加 `agent_ids=effective_ids,`（放在 `owner_id=handle.owner_id,` 后）。

- [ ] **Step 7: 跑测试 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_registry.py tests/test_event_store.py tests/test_game_runner.py tests/test_history.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部通过；ruff / mypy 无报错。

- [ ] **Step 8: 确认引擎零 diff 并提交**

Run: `cd /Users/gangtao/Code/gang/AgentHowl && git diff --stat main -- backend/app/engine frontend/src/engine/__fixtures__`
Expected: 无输出。

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/schemas/games.py backend/app/store/event_store.py backend/app/runtime/registry.py backend/app/runtime/game_runner.py backend/tests/test_registry.py backend/tests/test_event_store.py && git commit -m "feat(registry,store): 建局 agent_ids 归因，按实际 Agent 座位展开写进 GameMeta.agent_ids (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: API——建局校验 `agent_ids`，`/meta` 剔除，事件流不含

**Files:**
- Modify: `backend/app/api/rest.py`（`create_game_endpoint` 约第 70-135 行；`meta_endpoint` 约第 495-507 行）
- Test: `backend/tests/test_api_lobby.py`、`backend/tests/test_api_ws.py`

**Interfaces:**
- Consumes: Task 2 的 `CreateGameRequest.agent_ids`、`GameRegistry.create(agent_ids=...)`、`GameMeta.agent_ids`；现有 `can_access(user, owner_id)`、`AgentLibraryStore.get(agent_id) -> StoredAgent | None`、`ToolCallError`（映射 400）、`request.app.state.agent_library`。
- Produces: `POST /games` 接受 `agent_ids`；`GET /games/{id}/meta` 响应无 `agent_ids` 键。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_api_lobby.py` 末尾：

```python
def test_create_agent_ids_validated_and_never_leave_meta_or_events() -> None:
    """issue #123：agent_ids 键须在 agents 里、id 须当前用户可见（不存在与无权同文案）；
    服务端 meta 记下展开后的 id，但 /meta、/replay、/events 都不回传 agent_ids。"""
    import time as _t

    from app.runtime.player_port import BotPlayerPort

    app = make_app(
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    with TestClient(app) as client, TestClient(app) as other:
        login_as(client, "host", role="admin")
        login_as(other, "bob")
        created_agent = client.post("/api/v1/agents", json={"name": "夜枭", "model": "m"}).json()
        mine = created_agent["agent_id"]
        base = {"preset": "std_9_kill_side", "config_override": {"seed": 11}}
        agents = {"1": {"model": "m"}}

        r = client.post("/api/v1/games", json={**base, "agents": agents, "agent_ids": {"2": mine}})
        assert r.status_code == 400
        assert r.json()["detail"] == "agent_ids 非法：座位 2 没有对应的 agents 档案"
        r = client.post(
            "/api/v1/games", json={**base, "agents": agents, "agent_ids": {"1": "a_nope"}}
        )
        assert r.status_code == 400 and r.json()["detail"] == "agent_ids 非法：档案不存在：a_nope"
        # bob 看不到 host 的档案：与不存在同文案（不泄露存在性）
        r = other.post("/api/v1/games", json={**base, "agents": agents, "agent_ids": {"1": mine}})
        assert r.status_code == 400 and r.json()["detail"] == f"agent_ids 非法：档案不存在：{mine}"

        created = client.post(
            "/api/v1/games", json={**base, "agents": agents, "agent_ids": {"1": mine}}
        ).json()
        gid, host, spec = created["game_id"], created["host_token"], created["share_token"]
        assert "agent_ids" not in created
        assert (
            client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host)).status_code
            == 200
        )
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
        deadline = _t.time() + 30
        while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
            _t.sleep(0.05)
        assert handle.task is not None and handle.task.done()
        store = client.app.state.games.store  # type: ignore[attr-defined]
        assert store.load_meta(gid).agent_ids == {"1": mine}  # 服务端真相：meta 首行记了展开后的 id
        meta = client.get(f"/api/v1/games/{gid}/meta", params={"share": spec}).json()
        assert set(meta["agents"]) == {"1"} and "agent_ids" not in meta
        replay = client.get(f"/api/v1/games/{gid}/replay", params={"share": spec}).json()
        events = client.get(f"/api/v1/games/{gid}/events", params={"share": spec}).json()
        for e in [*replay, *events]:
            assert "agent_ids" not in e and "agent_ids" not in e["meta"]
            assert mine not in json.dumps(e, ensure_ascii=False)
```

文件顶部若没有 `import json`，加上。

在 `backend/tests/test_api_ws.py::test_spectator_stream_public_only_until_game_over` 的 `events = [...]` 行后加一行：

```python
    assert all("agent_ids" not in f["event"] for f in events)  # issue #123：归因只在 meta
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_api_lobby.py::test_create_agent_ids_validated_and_never_leave_meta_or_events -q`
Expected: FAIL——首个 `assert r.status_code == 400` 失败（当前 `agent_ids` 被接受，返回 200）。

- [ ] **Step 3: 实现校验与剔除**

`backend/app/api/rest.py`，在 `create_game_endpoint` 之前加：

```python
def _check_agent_ids(req: CreateGameRequest, lib: AgentLibraryStore, user: User) -> None:
    """agent_ids（issue #123）：键须在 agents 里（有 id 必有档案）；id 须是当前用户可见的档案
    （不存在与无权一律「档案不存在」，不泄露存在性）。不校验内联 profile 与库里是否一致。"""
    for key, agent_id in req.agent_ids.items():
        if key not in req.agents:
            raise ToolCallError(f"agent_ids 非法：座位 {key} 没有对应的 agents 档案")
        stored = lib.get(agent_id)
        if stored is None or not can_access(user, stored.owner_id):
            raise ToolCallError(f"agent_ids 非法：档案不存在：{agent_id}")
```

在 `create_game_endpoint` 里、`allowed: set[str] | None = (...)` 之前插入：

```python
    _check_agent_ids(req, request.app.state.agent_library, user)
```

`games.create(...)` 调用加 `agent_ids=req.agent_ids,`（放在 `require_provider=...` 之后）。

`meta_endpoint` 改为：

```python
    _require_finished(games, game_id)
    meta = games.store.load_meta(game_id)
    data = meta.model_dump(mode="json")
    data.pop("agent_ids", None)  # 归因 id 不随分享链接外泄（issue #123）
    return {**data, "viewer": viewer_of(info)}
```

- [ ] **Step 4: 跑测试 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_api_lobby.py tests/test_api_ws.py tests/test_api_share.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部通过。

- [ ] **Step 5: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/api/rest.py backend/tests/test_api_lobby.py backend/tests/test_api_ws.py && git commit -m "feat(api): 建局校验 agent_ids（键在 agents 里、档案可见），/meta 剔除 agent_ids (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `RatingIndex`——从事件日志推导并缓存 `FinishedGame`

**Files:**
- Create: `backend/app/runtime/rating_index.py`
- Modify: `backend/app/api/deps.py`（加 `get_rating_index`）
- Modify: `backend/app/main.py`（`app.state.rating_index`）
- Test: `backend/tests/test_rating_index.py`

**Interfaces:**
- Consumes: Task 1 的 `FinishedGame`、`AgentRating`、`compute_ratings`；Task 2 的 `GameMeta.agent_ids`；现有 `EventStore`（`list_games/load_meta/load_events`）、`initial_state(meta)`、`app.engine.events.reduce_all`、`EventType.GAME_OVER`。
- Produces:
  - `class RatingIndex: __init__(self, store: EventStore)`；`snapshot(self) -> dict[str, AgentRating]`；`extract_finished(self, game_id: str) -> FinishedGame | None`
  - `app.api.deps.get_rating_index(request) -> RatingIndex`
  - `app.state.rating_index`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_rating_index.py`：

```python
"""RatingIndex（issue #123）：从事件日志推导 FinishedGame；只计已结束且带 agent_ids 的对局；
已结束对局只读一次（缓存）；坏文件跳过。"""

from __future__ import annotations

import logging
from typing import Any

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.state import GameState
from app.runtime.rating_index import RatingIndex
from app.store.event_store import GameMeta, InMemoryEventStore, SeatName, StoreCorruptionError


class _CountingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.event_loads: dict[str, int] = {}

    def load_events(self, game_id: str, from_seq: int = 0) -> list[Any]:
        self.event_loads[game_id] = self.event_loads.get(game_id, 0) + 1
        return super().load_events(game_id, from_seq)


def _finished(
    store: InMemoryEventStore,
    game_id: str,
    *,
    seed: int = 3,
    agent_ids: dict[str, str] | None = None,
    truncate: int | None = None,
    wall: bool = True,
) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id=game_id)
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(
        GameMeta(game_id=game_id, config=cfg, roster=roster, agent_ids=agent_ids or {})
    )
    kept = events if truncate is None else events[:truncate]
    for i, e in enumerate(kept):
        meta = {**e.meta, "wall_ts": f"2026-10-26T00:{i // 60:02d}:{i % 60:02d}+00:00"}
        store.append(game_id, e.model_copy(update={"meta": meta if wall else e.meta}))
    return final


def test_extract_finished_reads_factions_winner_and_ended_at() -> None:
    store = InMemoryEventStore()
    final = _finished(store, "g_a", agent_ids={"0": "a_x", "5": "a_y"})
    fg = RatingIndex(store).extract_finished("g_a")
    assert fg is not None and fg.game_id == "g_a"
    assert fg.winner == final.winner
    assert fg.seat_factions == {p.seat: p.faction for p in final.players}
    assert fg.agent_ids == {0: "a_x", 5: "a_y"}
    assert fg.ended_at == store.load_events("g_a")[-1].meta["wall_ts"]


def test_snapshot_only_counts_finished_games_with_ids() -> None:
    store = InMemoryEventStore()
    final = _finished(store, "g_ids", agent_ids={"0": "a_x", "5": "a_y"})
    _finished(store, "g_noids", seed=4)
    _finished(store, "g_cut", seed=5, agent_ids={"0": "a_z"}, truncate=40)
    index = RatingIndex(store)
    assert index.extract_finished("g_noids") is None
    assert index.extract_finished("g_cut") is None
    snap = index.snapshot()
    assert set(snap) == {"a_x", "a_y"}
    assert snap["a_x"].games == 1 and snap["a_y"].games == 1
    seat0 = final.players[0].faction
    if final.winner is None:
        assert snap["a_x"].draws == 1
    else:
        assert snap["a_x"].wins == (1 if seat0 == final.winner else 0)
    assert snap["a_x"].history[0].camp == seat0


def test_snapshot_caches_finished_games_only() -> None:
    store = _CountingStore()
    _finished(store, "g_ids", agent_ids={"0": "a_x"})
    _finished(store, "g_noids", seed=4)
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    _final, events = run_game(cfg, game_id="g_cut")
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(GameMeta(game_id="g_cut", config=cfg, roster=roster, agent_ids={"3": "a_z"}))
    for e in events[:40]:
        store.append("g_cut", e)
    index = RatingIndex(store)
    first = index.snapshot()
    second = index.snapshot()
    assert first == second and set(first) == {"a_x"}
    assert store.event_loads["g_ids"] == 1  # 已结束：缓存，只读一次
    assert "g_noids" not in store.event_loads  # 无 id：meta 判空即短路，不读事件也不缓存
    assert store.event_loads["g_cut"] == 2  # 未结束：不缓存
    for e in events[40:]:  # 补完 → 下次 snapshot 计入
        store.append("g_cut", e)
    third = index.snapshot()
    assert set(third) == {"a_x", "a_z"} and store.event_loads["g_cut"] == 3
    index.snapshot()
    assert store.event_loads["g_cut"] == 3 and store.event_loads["g_ids"] == 1


def test_ended_at_falls_back_to_ts_when_wall_ts_missing() -> None:
    store = InMemoryEventStore()
    _finished(store, "g_old", agent_ids={"0": "a_x"}, wall=False)
    fg = RatingIndex(store).extract_finished("g_old")
    assert fg is not None and fg.ended_at == str(store.load_events("g_old")[-1].ts)


def test_corrupt_game_is_skipped_with_warning(caplog) -> None:
    class _Boom(InMemoryEventStore):
        def load_meta(self, game_id: str) -> GameMeta:
            if game_id == "g_bad":
                raise StoreCorruptionError("g_bad.jsonl：meta 记录损坏")
            return super().load_meta(game_id)

    store = _Boom()
    _finished(store, "g_ok", agent_ids={"0": "a_x"})
    store._games["g_bad"] = store._games["g_ok"]  # noqa: SLF001 —— 让 list_games 列出它
    with caplog.at_level(logging.WARNING):
        snap = RatingIndex(store).snapshot()
    assert set(snap) == {"a_x"} and snap["a_x"].games == 1
    assert any("g_bad" in rec.getMessage() for rec in caplog.records)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_rating_index.py -q`
Expected: `ModuleNotFoundError: No module named 'app.runtime.rating_index'`。

- [ ] **Step 3: 实现 `app/runtime/rating_index.py`**

```python
"""RatingIndex（issue #123）：从事件日志推导各档案积分，进程内缓存，不落盘。

IO 层，持有 EventStore。不依赖终局钩子：snapshot() 每次遍历 list_games()，已结束且带
agent_ids 的对局只 reduce 一次（结果不可变），其余不缓存。坏文件跳过 + warning，与 list_history
一致。单进程 asyncio，snapshot() 同步、不 await，无竞态。
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
        except Exception as exc:  # noqa: BLE001 —— 坏文件不拖垮积分表
            logger.warning("对局 %s 读取失败，积分已跳过：%s", game_id, exc)
            return None
        last = events[-1]
        winner = getattr(last.payload, "winner", None)
        finished = FinishedGame(
            game_id=game_id,
            ended_at=last.meta.get("wall_ts") or str(last.ts),
            winner=None if winner is None else str(winner),
            seat_factions={p.seat: p.faction for p in final.players},
            agent_ids={int(seat): aid for seat, aid in meta.agent_ids.items()},
        )
        self._cache[game_id] = finished
        return finished

    def snapshot(self) -> dict[str, AgentRating]:
        """当前全部档案的积分（纯函数重算，线性）。"""
        games = [
            fg for gid in self._store.list_games() if (fg := self.extract_finished(gid)) is not None
        ]
        return compute_ratings(games)
```

- [ ] **Step 4: 依赖注入与装配**

`backend/app/api/deps.py`：在 `from fastapi.security import ...` 后加 `from app.runtime.rating_index import RatingIndex`（rating_index 不 import api 层，不成环），文件末尾加：

```python
def get_rating_index(request: Request) -> RatingIndex:
    """积分推导索引（issue #123），运行时取自 app.state。"""
    index = request.app.state.rating_index
    assert isinstance(index, RatingIndex)
    return index
```

`backend/app/main.py`：import 区加 `from app.runtime.rating_index import RatingIndex`（按字母序放在 `from app.runtime.ratelimit import ...` 之后）；在 `app.state.tokens = TokenRegistry()` 之前加：

```python
    # Agent 积分（issue #123）：由事件日志推导，进程内缓存，不落盘
    app.state.rating_index = RatingIndex(app.state.games.store)
```

- [ ] **Step 5: 跑测试 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_rating_index.py tests/test_agent_profile.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部通过（`test_importing_registry_does_not_load_litellm` 仍绿）。

- [ ] **Step 6: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/runtime/rating_index.py backend/app/api/deps.py backend/app/main.py backend/tests/test_rating_index.py && git commit -m "feat(runtime): RatingIndex 从事件日志推导 FinishedGame 并缓存，挂到 app.state (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Agents API——`/agents` 带积分摘要、`/agents/{id}/rating`

**Files:**
- Create: `backend/app/schemas/agents.py`
- Modify: `backend/app/api/agents.py`（`list_agents`、`get_agent`，新增 `get_agent_rating`）
- Test: `backend/tests/test_api_agents.py`

**Interfaces:**
- Consumes: Task 1 `AgentRating`、`HISTORY_LIMIT`、`INITIAL_RATING`；Task 4 `get_rating_index` / `RatingIndex.snapshot()`；现有 `StoredAgent`、`_visible_agents`、`_get_owned_agent`。
- Produces:
  - `app.schemas.agents.RatingSummary{rating: float, games, wins, losses, draws: int}`
  - `app.schemas.agents.StoredAgentWithRating(StoredAgent) + rating: RatingSummary`
  - `app.schemas.agents.with_rating(stored, ratings) -> StoredAgentWithRating`
  - `GET /agents` → `list[StoredAgentWithRating]`；`GET /agents/{id}` → `StoredAgentWithRating`；`GET /agents/{id}/rating` → `AgentRating`（history 最近 200 条）。`POST` / `PUT` 响应不变（`StoredAgent`）。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_api_agents.py` 末尾：

```python
def test_rating_accumulates_after_finished_game_and_is_owner_scoped() -> None:
    """issue #123：建局带 agent_ids → 终局后 /agents 两条档案 games=1、胜负与 winner 一致；
    /agents/{id}/rating 一条 history；他人 404；删除档案后 404 但索引仍有其积分。"""
    import time as _t

    from app.runtime.game_runner import RunnerTimeouts
    from app.runtime.player_port import BotPlayerPort
    from tests.conftest import bearer

    app = make_app(
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    with TestClient(app) as c, TestClient(app) as bob:
        login_as(c, "host", role="admin")
        login_as(bob, "bob")
        a = c.post("/api/v1/agents", json={"name": "甲", "model": "m"}).json()
        b = c.post("/api/v1/agents", json={"name": "乙", "model": "m"}).json()
        assert "rating" not in a  # POST 响应保持 StoredAgent
        fresh = {x["agent_id"]: x for x in c.get("/api/v1/agents").json()}
        assert fresh[a["agent_id"]]["rating"] == {
            "rating": 1000.0, "games": 0, "wins": 0, "losses": 0, "draws": 0
        }
        assert c.get(f"/api/v1/agents/{a['agent_id']}").json()["rating"]["games"] == 0

        created = c.post(
            "/api/v1/games",
            json={
                "preset": "std_9_kill_side",
                "config_override": {"seed": 11},
                "agents": {"0": {"model": "m"}, "5": {"model": "m"}},
                "agent_ids": {"0": a["agent_id"], "5": b["agent_id"]},
            },
        ).json()
        gid, host = created["game_id"], created["host_token"]
        assert (
            c.post(f"/api/v1/games/{gid}/start", json={}, headers=bearer(host)).status_code == 200
        )
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        deadline = _t.time() + 30
        while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
            _t.sleep(0.05)
        final = handle.task.result()

        by_id = {x["agent_id"]: x["rating"] for x in c.get("/api/v1/agents").json()}
        for aid, seat in ((a["agent_id"], 0), (b["agent_id"], 5)):
            r = by_id[aid]
            assert r["games"] == 1
            if final.winner is None:
                assert r["draws"] == 1 and r["rating"] == 1000.0
            elif final.players[seat].faction == final.winner:
                assert r["wins"] == 1 and r["rating"] > 1000.0
            else:
                assert r["losses"] == 1 and r["rating"] < 1000.0
        full = c.get(f"/api/v1/agents/{a['agent_id']}/rating").json()
        assert full["games"] == 1 and len(full["history"]) == 1
        assert full["history"][0]["game_id"] == gid
        assert full["history"][0]["camp"] == final.players[0].faction.value
        assert set(full["by_camp"]) == {"GOOD", "WOLF"}

        # 可见性：bob 看不到 host 的档案与积分
        assert bob.get(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert bob.get(f"/api/v1/agents/{a['agent_id']}/rating").status_code == 404
        assert bob.get("/api/v1/agents").json() == []
        # 删除档案：API 404，索引里的积分仍由历史对局推导得出（CLI 仍能打印）
        assert c.delete(f"/api/v1/agents/{b['agent_id']}").status_code == 204
        assert c.get(f"/api/v1/agents/{b['agent_id']}/rating").status_code == 404
        index = c.app.state.rating_index  # type: ignore[attr-defined]
        assert index.snapshot()[b["agent_id"]].games == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_api_agents.py::test_rating_accumulates_after_finished_game_and_is_owner_scoped -q`
Expected: FAIL——`KeyError: 'rating'`（`/agents` 尚无该字段）。

- [ ] **Step 3: 新建 `app/schemas/agents.py`**

```python
"""Agent 档案 API 的响应模型（issue #123）：档案 + 积分摘要。"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from app.runtime.agent_library import StoredAgent
from app.runtime.rating import INITIAL_RATING, AgentRating


class RatingSummary(BaseModel):
    """档案卡片用的积分摘要；没打过 = 1000 / 0。"""

    rating: float = INITIAL_RATING
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


class StoredAgentWithRating(StoredAgent):
    rating: RatingSummary = RatingSummary()


def with_rating(stored: StoredAgent, ratings: Mapping[str, AgentRating]) -> StoredAgentWithRating:
    r = ratings.get(stored.agent_id)
    summary = (
        RatingSummary()
        if r is None
        else RatingSummary(
            rating=r.rating, games=r.games, wins=r.wins, losses=r.losses, draws=r.draws
        )
    )
    return StoredAgentWithRating(**stored.model_dump(), rating=summary)
```

- [ ] **Step 4: 改 `app/api/agents.py`**

import 区加：

```python
from app.api.deps import get_rating_index
from app.runtime.rating import HISTORY_LIMIT, AgentRating
from app.runtime.rating_index import RatingIndex
from app.schemas.agents import StoredAgentWithRating, with_rating
```

替换 `list_agents` 与 `get_agent`，并在 `get_agent` 后新增 `get_agent_rating`：

```python
@router.get("/agents")
def list_agents(
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
    index: RatingIndex = Depends(get_rating_index),
) -> list[StoredAgentWithRating]:
    ratings = index.snapshot()
    return [with_rating(s, ratings) for s in _visible_agents(lib, user)]
```

```python
@router.get("/agents/{agent_id}")
def get_agent(
    agent_id: str,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
    index: RatingIndex = Depends(get_rating_index),
) -> StoredAgentWithRating:
    return with_rating(_get_owned_agent(lib, user, agent_id), index.snapshot())


@router.get("/agents/{agent_id}/rating")
def get_agent_rating(
    agent_id: str,
    user: User = Depends(require_user),
    lib: AgentLibraryStore = Depends(get_library),
    index: RatingIndex = Depends(get_rating_index),
) -> AgentRating:
    """完整积分对象（issue #123）；history 只回最近 HISTORY_LIMIT 条。可见性同档案本身。"""
    _get_owned_agent(lib, user, agent_id)
    full = index.snapshot().get(agent_id, AgentRating())
    return full.model_copy(update={"history": full.history[-HISTORY_LIMIT:]})
```

- [ ] **Step 5: 跑测试 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_api_agents.py tests/test_api_ownership.py tests/test_api_lobby.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/schemas/agents.py backend/app/api/agents.py backend/tests/test_api_agents.py && git commit -m "feat(api): /agents 带积分摘要，新增 GET /agents/{id}/rating (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: CLI `app/cli/rating.py` + litellm 守卫参数化 + README

**Files:**
- Create: `backend/app/cli/rating.py`
- Modify: `backend/tests/test_agent_profile.py`（`test_importing_registry_does_not_load_litellm` 参数化）
- Modify: `README.md`（cli 目录树 + 命令示例）
- Test: `backend/tests/test_cli_rating.py`

**Interfaces:**
- Consumes: Task 4 `RatingIndex`；Task 1 `AgentRating`、`Faction`；现有 `JsonFileEventStore(Path)`、`JsonFileAgentLibrary(Path).list()`。
- Produces: `python -m app.cli.rating [--data-dir data]`；`app.cli.rating.main(argv: list[str] | None = None, out: Callable[[str], None] = print)`；`render_table(ratings, names) -> list[str]`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli_rating.py`：

```python
"""app.cli.rating（issue #123）：从 data/games 推导积分表，按积分降序；已删除档案名显示 (已删除)。"""

from __future__ import annotations

from pathlib import Path

from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.cli.rating import main
from app.engine.config import build_preset
from app.runtime.agent_library import JsonFileAgentLibrary, StoredAgent
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName


def test_rating_cli_prints_table_sorted_by_rating(tmp_path: Path) -> None:
    store = JsonFileEventStore(tmp_path / "games")
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, game_id="g_1")
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    ids = {"0": "a_kept", "4": "a_gone"}
    store.create_game(GameMeta(game_id="g_1", config=cfg, roster=roster, agent_ids=ids))
    for i, e in enumerate(events):
        wall = f"2026-10-26T00:00:{i % 60:02d}+00:00"
        store.append("g_1", e.model_copy(update={"meta": {**e.meta, "wall_ts": wall}}))
    JsonFileAgentLibrary(tmp_path / "agents").put(
        StoredAgent(
            agent_id="a_kept",
            profile=AgentProfile(name="夜枭", model="m"),
            created_at="t",
            updated_at="t",
        )
    )
    lines: list[str] = []
    main(["--data-dir", str(tmp_path)], out=lines.append)
    text = "\n".join(lines)
    assert "夜枭" in text and "(已删除)" in text and "a_gone" in text and "a_kept" in text
    # 顺序：积分降序；同分按场次再按 id（两者都 1 局，于是按 id：a_gone < a_kept）
    f0, f4 = final.players[0].faction, final.players[4].faction
    if final.winner is None or f0 == f4:
        expected = ["a_gone", "a_kept"]
    else:
        expected = ["a_kept", "a_gone"] if f0 == final.winner else ["a_gone", "a_kept"]
    idx = {aid: next(i for i, line in enumerate(lines) if aid in line) for aid in expected}
    assert idx[expected[0]] < idx[expected[1]]
    assert lines[0].startswith("档案")  # 表头


def test_rating_cli_empty_data_dir(tmp_path: Path) -> None:
    lines: list[str] = []
    main(["--data-dir", str(tmp_path / "empty")], out=lines.append)
    assert lines == ["没有带 agent_ids 的已结束对局；积分表为空"]
```

把 `backend/tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 改为参数化（保留函数名——CLAUDE.md 引用它）：

```python
@pytest.mark.parametrize(
    "modules",
    [
        "app.runtime.registry, app.agent.profile",
        "app.runtime.rating_index",
        "app.cli.rating",
    ],
)
def test_importing_registry_does_not_load_litellm(modules: str) -> None:
    """档案模块进 registry 的 import 图后，服务启动不得连带加载 litellm（惰性加载设计）；
    积分索引与积分 CLI（issue #123）同样不得。"""
    import subprocess
    import sys
    from pathlib import Path

    code = f"import sys, {modules}; print('litellm' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    ).stdout.strip()
    assert out == "False"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_cli_rating.py tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm -q`
Expected: `test_cli_rating.py` 收集失败（`No module named 'app.cli.rating'`）；守卫的 `app.cli.rating` 参数因 `CalledProcessError` 失败。

- [ ] **Step 3: 实现 `app/cli/rating.py`**

```python
"""CLI：uv run python -m app.cli.rating [--data-dir data] —— 打印 Agent 积分表（issue #123）。

只读核对工具：从 data/games 的事件日志推导（与 API 同一条 RatingIndex 路径），不落盘；
模块级不加载 litellm。库里已删除但历史对局仍有 id 的档案照样打印，名字显示 (已删除)。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from app.engine.config import Faction
from app.runtime.agent_library import JsonFileAgentLibrary
from app.runtime.rating import AgentRating
from app.runtime.rating_index import RatingIndex
from app.store.event_store import JsonFileEventStore

Printer = Callable[[str], None]
DELETED_LABEL = "(已删除)"
EMPTY_MSG = "没有带 agent_ids 的已结束对局；积分表为空"


def render_table(ratings: Mapping[str, AgentRating], names: Mapping[str, str]) -> list[str]:
    """积分降序，同分按场次降序，再按 agent_id；列：档案 / id / 积分 / 场次 / 胜负平 / 狼 / 好人。"""
    header = (
        f"{'档案':<12}{'id':<12}{'积分':>6}{'场次':>6}"
        f"{'胜/负/平':>10}{'狼 场/胜':>10}{'好人 场/胜':>12}"
    )
    rows = [header]
    ordered = sorted(ratings.items(), key=lambda kv: (-kv[1].rating, -kv[1].games, kv[0]))
    for aid, r in ordered:
        wolf, good = r.by_camp[Faction.WOLF], r.by_camp[Faction.GOOD]
        name = names.get(aid, DELETED_LABEL)
        record = f"{r.wins}/{r.losses}/{r.draws}"
        as_wolf = f"{wolf.games}/{wolf.wins}"
        as_good = f"{good.games}/{good.wins}"
        rows.append(
            f"{name:<12}{aid[:8]:<12}{round(r.rating):>6}{r.games:>6}"
            f"{record:>10}{as_wolf:>10}{as_good:>12}"
        )
    return rows


def main(argv: list[str] | None = None, out: Printer = print) -> None:
    parser = argparse.ArgumentParser(description="AgentHowl Agent 积分表（由已结束对局推导，只读）")
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="数据目录（含 games/ 与 agents/）"
    )
    args = parser.parse_args(argv)
    ratings = RatingIndex(JsonFileEventStore(args.data_dir / "games")).snapshot()
    if not ratings:
        out(EMPTY_MSG)
        return
    library = JsonFileAgentLibrary(args.data_dir / "agents")
    names = {s.agent_id: (s.profile.name or s.agent_id) for s in library.list()}
    for line in render_table(ratings, names):
        out(line)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: README**

`README.md` 目录树 `play_human.py` 一行之前插入（保持树形符号）：

```
│       ├── rating.py      # Agent 积分表核对（python -m app.cli.rating，issue #123）
```

在 `uv run python -m app.cli.simulate --games 100                 # 纯引擎胜负统计` 一行后加：

```
uv run python -m app.cli.rating                               # Agent 积分表（由已结束对局推导）
```

- [ ] **Step 5: 跑测试 + 门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run pytest tests/test_cli_rating.py tests/test_agent_profile.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部通过（守卫 3 个参数全绿）。

- [ ] **Step 6: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add backend/app/cli/rating.py backend/tests/test_cli_rating.py backend/tests/test_agent_profile.py README.md && git commit -m "feat(cli): app.cli.rating 打印积分表；litellm 守卫覆盖 rating_index / cli.rating (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 前端类型、store 与测试夹具

**Files:**
- Modify: `frontend/src/api/agents.ts`
- Modify: `frontend/src/api/rest.ts`（`CreateGameRequest`，约第 87-99 行）
- Modify: `frontend/src/store/agents.ts`（`create` / `update`）
- Modify: `frontend/src/lib/seats.test.ts`、`frontend/src/components/SeatAssignment/SeatAssignment.test.tsx`、`frontend/src/components/AgentEditor/AgentEditor.test.tsx`（夹具补 `rating`）
- Test: `frontend/src/store/agents.test.ts`

**Interfaces:**
- Produces:
  - `RatingSummary { rating: number; games: number; wins: number; losses: number; draws: number }`
  - `EMPTY_RATING: RatingSummary`
  - `StoredAgentBase { agent_id; profile; created_at; updated_at }`（POST / PUT 响应）
  - `StoredAgent extends StoredAgentBase { rating: RatingSummary }`（GET 响应）
  - `createAgent/updateAgent(): Promise<StoredAgentBase>`
  - `CreateGameRequest.agent_ids?: Record<string, string>`
  - store 的 `create` / `update` 仍返回 `StoredAgent`（新建 → `EMPTY_RATING`；更新 → 沿用原积分）

- [ ] **Step 1: 写失败测试**

追加到 `frontend/src/store/agents.test.ts` 的 `describe` 块内：

```ts
  it("create() 给新档案补 EMPTY_RATING；update() 沿用原积分（积分只由终局推导，POST/PUT 响应不带）", async () => {
    const base = {
      agent_id: "a_new",
      profile: { name: "新", model: "m" },
      created_at: "t",
      updated_at: "t",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(201, base)),
    );
    const created = await useAgentLibrary.getState().create({ name: "新", model: "m" });
    expect(created.rating).toEqual({ rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 });
    expect(useAgentLibrary.getState().items[0]?.rating.games).toBe(0);

    const played = { rating: 1016, games: 1, wins: 1, losses: 0, draws: 0 };
    useAgentLibrary.setState({ items: [{ ...base, rating: played }] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { ...base, updated_at: "t2" })),
    );
    const updated = await useAgentLibrary.getState().update("a_new", { name: "新", model: "m2" });
    expect(updated.rating).toEqual(played);
    expect(useAgentLibrary.getState().items[0]).toEqual({ ...base, updated_at: "t2", rating: played });
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npx vitest run src/store/agents.test.ts`
Expected: FAIL——`created.rating` 为 `undefined`。

- [ ] **Step 3: 改 `api/agents.ts`**

把 `StoredAgent` 接口替换为：

```ts
/** 与 app/schemas/agents.py::RatingSummary 对应（issue #123）；没打过 = 1000 / 0。 */
export interface RatingSummary {
  rating: number;
  games: number;
  wins: number;
  losses: number;
  draws: number;
}

export const EMPTY_RATING: RatingSummary = { rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 };

/** POST / PUT /agents 的响应（后端 StoredAgent）：不带积分。 */
export interface StoredAgentBase {
  agent_id: string;
  profile: AgentProfile;
  created_at: string;
  updated_at: string;
}

/** GET /agents 与 GET /agents/{id} 的响应：档案 + 积分摘要。只渲染，前端不算 Elo。 */
export interface StoredAgent extends StoredAgentBase {
  rating: RatingSummary;
}
```

`createAgent` / `updateAgent` 的返回类型与泛型改为 `StoredAgentBase`：

```ts
export function createAgent(profile: AgentProfile): Promise<StoredAgentBase> {
  return req<StoredAgentBase>("POST", "/agents", { body: profile });
}

export function updateAgent(agentId: string, profile: AgentProfile): Promise<StoredAgentBase> {
  return req<StoredAgentBase>("PUT", `/agents/${agentId}`, { body: profile });
}
```

- [ ] **Step 4: 改 `api/rest.ts`**

`CreateGameRequest` 在 `agents?: Record<string, unknown>;` 后加：

```ts
  /** 座位号或 "*" → 库内档案 agent_id（issue #123）；键须同时在 agents 里，只用于归因计分。 */
  agent_ids?: Record<string, string>;
```

- [ ] **Step 5: 改 `store/agents.ts`**

import 加 `EMPTY_RATING`（放进现有的 `from "../api/agents"` 列表）；`create` / `update` 改为：

```ts
  async create(profile) {
    try {
      // POST 响应不带积分；新档案尚无战绩，补 EMPTY_RATING 即是真值
      const stored: StoredAgent = { ...(await createAgent(profile)), rating: EMPTY_RATING };
      set({ items: [stored, ...get().items] });
      return stored;
    } catch (err) {
      set({ error: messageOf(err) });
      throw err; // 页面可能想自己 catch 再弹提示，这里只负责落 error，不吞异常
    }
  },

  async update(agentId, profile) {
    try {
      const base = await updateAgent(agentId, profile);
      // 积分只由终局推导，编辑档案不改变它：沿用列表里的原值
      const prev = get().items.find((a) => a.agent_id === agentId);
      const stored: StoredAgent = { ...base, rating: prev?.rating ?? EMPTY_RATING };
      set({ items: get().items.map((a) => (a.agent_id === agentId ? stored : a)) });
      return stored;
    } catch (err) {
      set({ error: messageOf(err) });
      throw err;
    }
  },
```

- [ ] **Step 6: 测试夹具补 `rating`**

三处构造 `StoredAgent` 字面量的 helper，各在 `updated_at: ...,` 后加一行 `rating: EMPTY_RATING,`，并补 import：

- `frontend/src/lib/seats.test.ts`：`import { EMPTY_RATING, type StoredAgent } from "../api/agents";`（替换原 `import type { StoredAgent } ...`）。
- `frontend/src/components/SeatAssignment/SeatAssignment.test.tsx`：`import { EMPTY_RATING, type StoredAgent } from "../../api/agents";`。
- `frontend/src/components/AgentEditor/AgentEditor.test.tsx`：`import { EMPTY_RATING, type AgentProfile, type SkillInfo, type StoredAgent } from "../../api/agents";`。

- [ ] **Step 7: 跑门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npm run check`
Expected: lint / tsc / vitest 全绿（tsc 会把任何漏补 `rating` 的字面量揪出来）。

- [ ] **Step 8: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add frontend/src/api/agents.ts frontend/src/api/rest.ts frontend/src/store/agents.ts frontend/src/store/agents.test.ts frontend/src/lib/seats.test.ts frontend/src/components/SeatAssignment/SeatAssignment.test.tsx frontend/src/components/AgentEditor/AgentEditor.test.tsx && git commit -m "feat(frontend): StoredAgent.rating 类型、CreateGameRequest.agent_ids，store 为新建/更新档案补积分 (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 战绩行纯函数 + AgentCard

**Files:**
- Create: `frontend/src/lib/rating.ts`（纯函数；页面 / 组件文件只导出组件——ESLint `react-refresh/only-export-components` 在 `--max-warnings 0` 下会把非组件导出当错误）
- Modify: `frontend/src/components/AgentCard/AgentCard.tsx`
- Modify: `frontend/src/components/AgentCard/AgentCard.module.css`
- Test: `frontend/src/lib/rating.test.ts`（新建）、`frontend/src/components/AgentCard/AgentCard.test.tsx`（新建）

**Interfaces:**
- Consumes: Task 7 `StoredAgent.rating`、`RatingSummary`、`EMPTY_RATING`。
- Produces: `src/lib/rating.ts` 导出 `ratingLine(r: RatingSummary): string`（Task 9 往同一文件追加 `sortAgents`）。

- [ ] **Step 1: 写失败测试**

`frontend/src/lib/rating.test.ts`：

```ts
// 积分展示纯函数（issue #123）：只排版服务端数字，不在前端算 Elo。

import { describe, expect, it } from "vitest";
import { EMPTY_RATING } from "../api/agents";
import { ratingLine } from "./rating";

describe("ratingLine", () => {
  it("取整积分、四舍五入胜率；0 局为「尚无战绩」", () => {
    expect(ratingLine({ rating: 1015.6, games: 12, wins: 7, losses: 4, draws: 1 })).toBe(
      "1016 分 · 12 局 · 胜率 58%",
    );
    expect(ratingLine({ rating: 1024, games: 12, wins: 7, losses: 5, draws: 0 })).toBe(
      "1024 分 · 12 局 · 胜率 58%",
    );
    expect(ratingLine(EMPTY_RATING)).toBe("尚无战绩");
  });
});
```

`frontend/src/components/AgentCard/AgentCard.test.tsx`：

```tsx
// AgentCard 战绩行（issue #123）：完整卡与精简卡都渲染 ratingLine 的文案。

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EMPTY_RATING, type RatingSummary, type StoredAgent } from "../../api/agents";
import AgentCard from "./AgentCard";

function agent(rating: RatingSummary): StoredAgent {
  return {
    agent_id: "a_owl",
    profile: { name: "夜枭", model: "qwen2.5:14b", skills: [] },
    created_at: "2026-09-20T00:00:00+00:00",
    updated_at: "2026-09-20T00:00:00+00:00",
    rating,
  };
}

describe("AgentCard 战绩行", () => {
  it("完整卡与精简卡都渲染战绩行", () => {
    const played: RatingSummary = { rating: 1015.6, games: 12, wins: 7, losses: 4, draws: 1 };
    const { unmount } = render(<AgentCard stored={agent(played)} />);
    expect(screen.getByText("1016 分 · 12 局 · 胜率 58%")).toBeInTheDocument();
    unmount();
    render(<AgentCard stored={agent(EMPTY_RATING)} compact />);
    expect(screen.getByText("尚无战绩")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npx vitest run src/lib/rating.test.ts src/components/AgentCard`
Expected: `rating.test.ts` 因找不到 `./rating` 模块失败；AgentCard 用例找不到战绩文案失败。

- [ ] **Step 3: 实现**

`frontend/src/lib/rating.ts`：

```ts
// Agent 积分展示的纯函数（issue #123）。零 IO、零 React；只排版服务端给的数字，不在前端算 Elo。

import type { RatingSummary } from "../api/agents";

/** 卡片战绩行：`1024 分 · 12 局 · 胜率 58%`；没打过 → `尚无战绩`。积分取整，胜率四舍五入。 */
export function ratingLine(r: RatingSummary): string {
  if (r.games === 0) return "尚无战绩";
  const winRate = Math.round((r.wins / r.games) * 100);
  return `${Math.round(r.rating)} 分 · ${r.games} 局 · 胜率 ${winRate}%`;
}
```

`AgentCard.tsx`：import 区加 `import { ratingLine } from "../../lib/rating";`（放在 `personality` 那行 import 之后）。

精简卡：在 `<div className={styles.compactFoot}>…</div>` 之后、外层 `</div>` 之前加：

```tsx
        <div className={styles.rating}>{ratingLine(stored.rating)}</div>
```

完整卡：在 `<div className={styles.body}>…</div>` 之后、`<div className="card-meta" …>` 之前加：

```tsx
      <div className={styles.rating}>{ratingLine(stored.rating)}</div>
```

`AgentCard.module.css` 在 `.memory {…}` 之后加：

```css
.rating {
  font-size: 11.5px;
  color: var(--color-neutral-400);
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 4: 跑门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npm run check`
Expected: 全绿（含 lint：AgentCard.tsx 仍只导出组件）。

- [ ] **Step 5: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add frontend/src/lib/rating.ts frontend/src/lib/rating.test.ts frontend/src/components/AgentCard && git commit -m "feat(frontend): AgentCard 显示积分 / 场次 / 胜率战绩行 (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Agent 库按积分排序

**Files:**
- Modify: `frontend/src/lib/rating.ts`（追加 `sortAgents`）
- Modify: `frontend/src/pages/AgentLibrary.tsx`
- Modify: `frontend/src/pages/AgentLibrary.module.css`
- Test: `frontend/src/lib/rating.test.ts`（追加）、`frontend/src/pages/AgentLibrary.test.tsx`（新建）

**Interfaces:**
- Consumes: Task 7 `StoredAgent.rating`；Task 8 的 `src/lib/rating.ts`。
- Produces: `src/lib/rating.ts` 导出 `type AgentSort = "updated" | "rating"` 与 `sortAgents(items: StoredAgent[], sort: AgentSort): StoredAgent[]`。

- [ ] **Step 1: 写失败测试**

追加到 `frontend/src/lib/rating.test.ts`（import 行改为 `import { ratingLine, sortAgents } from "./rating";`，并加 `import type { StoredAgent } from "../api/agents";`）：

```ts
function agent(id: string, name: string, rating: number, games: number, updated: string): StoredAgent {
  return {
    agent_id: id,
    profile: { name, model: "m", skills: [] },
    created_at: updated,
    updated_at: updated,
    rating: { rating, games, wins: games, losses: 0, draws: 0 },
  };
}

// 服务端按 updated_at 倒序返回
const ITEMS: StoredAgent[] = [
  agent("a_new", "新人", 1000, 0, "2026-10-26T00:00:00+00:00"),
  agent("a_mid", "中坚", 1016, 1, "2026-10-25T00:00:00+00:00"),
  agent("a_vet", "老将", 1016, 5, "2026-10-24T00:00:00+00:00"),
  agent("a_top", "顶尖", 1100, 3, "2026-10-23T00:00:00+00:00"),
];

describe("sortAgents", () => {
  it("积分降序 → 场次降序 → 名字；最近更新保持服务端顺序且不改入参", () => {
    const before = ITEMS.map((a) => a.agent_id);
    expect(sortAgents(ITEMS, "rating").map((a) => a.agent_id)).toEqual(["a_top", "a_vet", "a_mid", "a_new"]);
    expect(sortAgents(ITEMS, "updated").map((a) => a.agent_id)).toEqual(before);
    expect(ITEMS.map((a) => a.agent_id)).toEqual(before);
  });
});
```

`frontend/src/pages/AgentLibrary.test.tsx`：

```tsx
// Agent 库排序切换（issue #123）：默认最近更新（服务端顺序）；点「积分」按积分排，再点「最近更新」恢复。

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StoredAgent } from "../api/agents";
import { useAgentLibrary } from "../store/agents";
import { useProviders } from "../store/providers";
import AgentLibrary from "./AgentLibrary";

function agent(id: string, name: string, rating: number, games: number, updated: string): StoredAgent {
  return {
    agent_id: id,
    profile: { name, model: "m", skills: [] },
    created_at: updated,
    updated_at: updated,
    rating: { rating, games, wins: games, losses: 0, draws: 0 },
  };
}

const ITEMS: StoredAgent[] = [
  agent("a_new", "新人", 1000, 0, "2026-10-26T00:00:00+00:00"),
  agent("a_mid", "中坚", 1016, 1, "2026-10-25T00:00:00+00:00"),
  agent("a_vet", "老将", 1016, 5, "2026-10-24T00:00:00+00:00"),
  agent("a_top", "顶尖", 1100, 3, "2026-10-23T00:00:00+00:00"),
];

function stubFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/agents") ? ITEMS : [];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function cardNames(): string[] {
  return screen.getAllByText(/^(新人|中坚|老将|顶尖)$/).map((el) => el.textContent ?? "");
}

describe("AgentLibrary 排序", () => {
  beforeEach(() => {
    useAgentLibrary.setState({ items: [], skills: [], presets: [], loading: false, error: null });
    useProviders.setState({ items: [], loading: false, error: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("默认最近更新；点「积分」后按积分排，再点「最近更新」恢复", async () => {
    stubFetch();
    render(<AgentLibrary />);
    await screen.findByText("顶尖");
    expect(cardNames()).toEqual(["新人", "中坚", "老将", "顶尖"]);
    const byRating = screen.getByRole("button", { name: "积分" });
    expect(screen.getByRole("button", { name: "最近更新" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(byRating);
    expect(cardNames()).toEqual(["顶尖", "老将", "中坚", "新人"]);
    expect(byRating).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "最近更新" }));
    expect(cardNames()).toEqual(["新人", "中坚", "老将", "顶尖"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npx vitest run src/lib/rating.test.ts src/pages/AgentLibrary.test.tsx`
Expected: `sortAgents` 未导出；页面用例找不到「积分」按钮。

- [ ] **Step 3: 实现 `sortAgents`**

追加到 `frontend/src/lib/rating.ts`（import 行改为 `import type { RatingSummary, StoredAgent } from "../api/agents";`）：

```ts
export type AgentSort = "updated" | "rating";

/** 「最近更新」= 服务端顺序（updated_at 倒序）；「积分」= rating 降序 → games 降序 → 名字。不改入参。 */
export function sortAgents(items: StoredAgent[], sort: AgentSort): StoredAgent[] {
  if (sort === "updated") return items;
  return [...items].sort(
    (a, b) =>
      b.rating.rating - a.rating.rating ||
      b.rating.games - a.rating.games ||
      (a.profile.name ?? "").localeCompare(b.profile.name ?? "", "zh-Hans-CN"),
  );
}
```

- [ ] **Step 4: 页面接线**

`AgentLibrary.tsx`：import 区加 `import { sortAgents, type AgentSort } from "../lib/rating";`（放在 `toProfilePayload` 那行 import 之后）。

组件内，在 `const [notice, setNotice] = useState<string | null>(null);` 之后加：

```ts
  const [sort, setSort] = useState<AgentSort>("updated"); // 只在页面内存里，不持久化
  const shown = sortAgents(items, sort);
```

页头 `<div className={styles.headActions}>` 的第一个子元素之前插入排序切换：

```tsx
          <div className={styles.sortGroup} role="group" aria-label="排序">
            <button
              type="button"
              className={`btn btn-ghost ${sort === "updated" ? styles.sortOn : ""}`}
              aria-pressed={sort === "updated"}
              onClick={() => setSort("updated")}
            >
              最近更新
            </button>
            <button
              type="button"
              className={`btn btn-ghost ${sort === "rating" ? styles.sortOn : ""}`}
              aria-pressed={sort === "rating"}
              onClick={() => setSort("rating")}
            >
              积分
            </button>
          </div>
```

网格渲染把 `items.map((a) => (` 改为 `shown.map((a) => (`（其它 `items` 用法——计数、空态、导出、`others`——保持不变）。

`AgentLibrary.module.css` 在 `.headActions {…}` 之后加：

```css
.sortGroup {
  display: inline-flex;
  gap: 2px;
  margin-right: 8px;
}

.sortOn {
  color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent-700);
}
```

- [ ] **Step 5: 跑门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npm run check`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add frontend/src/lib/rating.ts frontend/src/lib/rating.test.ts frontend/src/pages/AgentLibrary.tsx frontend/src/pages/AgentLibrary.module.css frontend/src/pages/AgentLibrary.test.tsx && git commit -m "feat(frontend): Agent 库排序切换 最近更新 / 积分 (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Lobby 补发 `agent_ids`

**Files:**
- Modify: `frontend/src/lib/seats.ts`（新增 `buildAgentIdsPayload`）
- Modify: `frontend/src/pages/Lobby.tsx`（请求体 + 回显）
- Test: `frontend/src/lib/seats.test.ts`、`frontend/src/pages/Lobby.test.tsx`

**Interfaces:**
- Consumes: Task 7 `CreateGameRequest.agent_ids`；现有 `SeatSlot`、`ME`、`buildAgentsPayload(assignment, fill, library)`。
- Produces: `buildAgentIdsPayload(assignment: SeatSlot[], fill: string | null, library: StoredAgent[]): Record<string, string>`。

- [ ] **Step 1: 写失败测试**

追加到 `frontend/src/lib/seats.test.ts` 末尾（import 列表加 `buildAgentIdsPayload`）：

```ts
describe("buildAgentIdsPayload（issue #123）", () => {
  it("座位档案写座位键，fill 写 \"*\"；随机 bot / 我自己 / 库里查不到的 id 不写", () => {
    const assignment: SeatSlot[] = [
      { seat: 0, agentId: "a_owl" },
      { seat: 1, agentId: null },
      { seat: 2, agentId: ME },
      { seat: 3, agentId: "a_ghost" },
    ];
    expect(buildAgentIdsPayload(assignment, "a_nice", LIBRARY)).toEqual({ "0": "a_owl", "*": "a_nice" });
    expect(buildAgentIdsPayload(assignment, null, LIBRARY)).toEqual({ "0": "a_owl" });
    expect(buildAgentIdsPayload([], null, LIBRARY)).toEqual({});
  });

  it("键集合与 buildAgentsPayload 一致（后端要求有 id 必有档案）", () => {
    const ids = buildAgentIdsPayload(MOCKUP_ASSIGNMENT, "a_nice", LIBRARY);
    expect(Object.keys(ids).sort()).toEqual(Object.keys(buildAgentsPayload(MOCKUP_ASSIGNMENT, "a_nice", LIBRARY)).sort());
  });
});
```

`MOCKUP_ASSIGNMENT` 已在该文件里定义（设计稿 2a 分配）。

追加到 `frontend/src/pages/Lobby.test.tsx` 末尾：

```tsx
const LIBRARY_ROWS = [
  {
    agent_id: "a_owl",
    profile: { name: "夜枭", model: "m", skills: [] },
    created_at: "t",
    updated_at: "t",
    rating: { rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 },
  },
  {
    agent_id: "a_nice",
    profile: { name: "老好人", model: "m", skills: [] },
    created_at: "t",
    updated_at: "t",
    rating: { rating: 1000, games: 0, wins: 0, losses: 0, draws: 0 },
  },
];

describe("Lobby 建局归因（issue #123）", () => {
  it("座位选库内档案 + 填满档案 → 请求体 agent_ids 含座位键与 \"*\"，与 agents 键一致", async () => {
    const fetchMock = stubLobbyFetch();
    const inner = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (rawUrl: string, init?: RequestInit) => {
      const url = rawUrl.split("?")[0] as string;
      if (url.endsWith("/agents") && (init?.method ?? "GET") === "GET")
        return new Response(JSON.stringify(LIBRARY_ROWS), { status: 200, headers: { "Content-Type": "application/json" } });
      return inner(rawUrl, init);
    });
    useAuth.setState({ status: "authed", user: { username: "alice" } as never });
    window.location.hash = "#/";
    render(<Lobby />);
    await screen.findByText("标准 9 人局");
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 分配座位/ }));
    fireEvent.change(await screen.findByLabelText("3号 座位"), { target: { value: "a_owl" } });
    fireEvent.change(screen.getByLabelText("填满其余座位"), { target: { value: "a_nice" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步 · 汇总/ }));
    expect(screen.getByText(/agent_ids: \{"\*", "3"\}/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "创建并开始" })[0] as HTMLElement);
    await vi.waitFor(() => expect(bodyOf(fetchMock, "/games").agent_ids).toBeDefined());
    const create = bodyOf(fetchMock, "/games");
    expect(create.agent_ids).toEqual({ "3": "a_owl", "*": "a_nice" });
    expect(Object.keys(create.agents as object).sort()).toEqual(["*", "3"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npx vitest run src/lib/seats.test.ts src/pages/Lobby.test.tsx`
Expected: `seats.test.ts` 因 `buildAgentIdsPayload` 未导出失败；Lobby 新用例在 `agent_ids` 断言处失败。

- [ ] **Step 3: 实现 `buildAgentIdsPayload`**

`frontend/src/lib/seats.ts`，在 `buildAgentsPayload` 之后加：

```ts
/**
 * 座位选择 → `POST /games` 的 `agent_ids`（issue #123）：凡座位档案来自库里的写 `"{seat}": agent_id`，
 * 填满档案写 `"*"`。键集合与 buildAgentsPayload 一致（后端要求有 id 必有档案）；
 * 随机 bot / 我自己 / 库里查不到的 id 不写。不校验 memory_id——那是 buildAgentsPayload 的事。
 */
export function buildAgentIdsPayload(
  assignment: SeatSlot[],
  fill: string | null,
  library: StoredAgent[],
): Record<string, string> {
  const byId = indexById(library);
  const out: Record<string, string> = {};
  for (const slot of assignment) {
    if (slot.agentId === null || slot.agentId === ME) continue;
    if (byId.has(slot.agentId)) out[String(slot.seat)] = slot.agentId;
  }
  if (fill !== null && byId.has(fill)) out["*"] = fill;
  return out;
}
```

- [ ] **Step 4: Lobby 接线**

`frontend/src/pages/Lobby.tsx`：

- 文件头注释第 4 行末尾补 `, agent_ids: {"0": agent_id, "*": agent_id}`（说明请求体形状）。
- `import { ..., buildAgentsPayload, ... } from "../lib/seats";` 里加 `buildAgentIdsPayload`。
- `agentsPayload` 的 `useMemo` 之后加：

```ts
  const agentIdsPayload = useMemo(
    () => buildAgentIdsPayload(assignment, fillBlocked ? null : fill, items),
    [assignment, fill, fillBlocked, items],
  );
```

- `createAndStart` 里的 `const body: CreateGameRequest = { preset: preset.name, agents: agentsPayload, voice, narration: voice && narration };` 改为：

```ts
      const body: CreateGameRequest = {
        preset: preset.name,
        agents: agentsPayload,
        agent_ids: agentIdsPayload,
        voice,
        narration: voice && narration,
      };
```

- `const payloadKeys = Object.keys(agentsPayload).sort();` 之后加 `const idKeys = Object.keys(agentIdsPayload).sort();`。
- 侧栏回显 `<span className={styles.payload}>agents: …</span>` 之后加一行：

```tsx
          <span className={styles.payload}>
            agent_ids: {idKeys.length === 0 ? "{}" : `{${idKeys.map((k) => `"${k}"`).join(", ")}}`}
          </span>
```

- 汇总区 `agents` 的 `reviewRow` 之后加：

```tsx
              <div className={styles.reviewRow}>
                <span className={styles.reviewKey}>agent_ids</span>
                <pre className={styles.json}>{JSON.stringify(agentIdsPayload, null, 2)}</pre>
              </div>
```

- [ ] **Step 5: 跑门禁**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npm run check`
Expected: 全绿。若 Lobby 用例里 `screen.getByText(/agent_ids: \{"\*", "3"\}/)` 因侧栏与汇总区同时出现而报多个匹配，改用 `screen.getAllByText(...)[0]`。

- [ ] **Step 6: 提交**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git add frontend/src/lib/seats.ts frontend/src/lib/seats.test.ts frontend/src/pages/Lobby.tsx frontend/src/pages/Lobby.test.tsx && git commit -m "feat(frontend): Lobby 建局补发 agent_ids（座位键与 \"*\"）并回显 (issue #123)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: 全量门禁与验收核对

**Files:**
- 无新文件；只在发现问题时修改并单独提交。

- [ ] **Step 1: 后端全量**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q --ignore=tests/test_api_e2e.py`
Expected: 除已知基线失败 `tests/test_api_admin.py::test_list_patch_verify`、`::test_concurrent_cross_demotion_keeps_one_admin`（issue #124）外全部通过。

- [ ] **Step 2: 前端全量**

Run: `cd /Users/gangtao/Code/gang/AgentHowl/frontend && npm run check`
Expected: 全绿。

- [ ] **Step 3: 引擎零 diff**

Run: `cd /Users/gangtao/Code/gang/AgentHowl && git diff --stat main -- backend/app/engine frontend/src/engine/__fixtures__`
Expected: 无输出。

- [ ] **Step 4: 验收脚本（spec §1 成功判据，真实文件存储）**

Run:

```bash
cd /Users/gangtao/Code/gang/AgentHowl/backend && uv run python - <<'EOF'
from pathlib import Path
import tempfile
from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.cli.rating import main
from app.engine.config import build_preset
from app.runtime.agent_library import JsonFileAgentLibrary, StoredAgent
from app.runtime.rating_index import RatingIndex
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName

d = Path(tempfile.mkdtemp())
store = JsonFileEventStore(d / "games")
cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
final, events = run_game(cfg, game_id="g_acc")
roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
store.create_game(GameMeta(game_id="g_acc", config=cfg, roster=roster, agent_ids={"0": "a_a", "4": "a_b"}))
for i, e in enumerate(events):
    store.append("g_acc", e.model_copy(update={"meta": {**e.meta, "wall_ts": f"2026-10-26T00:00:{i % 60:02d}+00:00"}}))
lib = JsonFileAgentLibrary(d / "agents")
lib.put(StoredAgent(agent_id="a_a", profile=AgentProfile(name="甲", model="m"), created_at="t", updated_at="t"))
lib.put(StoredAgent(agent_id="a_b", profile=AgentProfile(name="乙", model="m"), created_at="t", updated_at="t"))
s1 = RatingIndex(JsonFileEventStore(d / "games")).snapshot()
s2 = RatingIndex(JsonFileEventStore(d / "games")).snapshot()  # “重启”
assert s1 == s2, "重启后结果不一致"
print("winner:", final.winner, {aid: (round(r.rating, 2), r.games, r.wins, r.losses, r.draws) for aid, r in s1.items()})
main(["--data-dir", str(d)])
EOF
```

Expected: 打印 `winner` 与两条档案 `games=1`，胜方 `rating>1000` 败方 `<1000`（平局则两边 `draws=1`、积分 1000），之后 CLI 表与之一致。

- [ ] **Step 5: 推送**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && git push -u origin feat/agent-rating
```

然后交给 `superpowers:finishing-a-development-branch`（用户在 GitHub 合并；PR 引用 issue #123，正文末尾 `🤖 Generated with [Claude Code](https://claude.com/claude-code)`）。
