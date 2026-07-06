# 警长发言方向 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 issue #2：`SHERIFF_DECIDES` 下警长通过 `set_speech_direction` 选定警左/警右，第二天起自动换手；无警长退回 death-next。

**Architecture:** 在 `SHERIFF_ELECTION` 阶段新增 `"direction"` 子阶段（竞选出警长后、公布死讯前），警长提交方向 → `SHERIFF_DIRECTION_SET` 事件写入 `GameState.sheriff_speech_direction`（事实经 reduce）→ 游标推进到 `"announce"` → `_advance_election` 续接死讯公布。`_speech_order` 的 SHERIFF_DECIDES 分支按「基准方向 + round 奇偶换手」计算顺/逆时针顺序。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2，frozen 模型，事件溯源）。命令在 `backend/` 下运行。

## Global Constraints

- 引擎零 IO；**游戏事实只经 `reduce` 写入**（`sheriff_speech_direction` 是事实，必须走事件）；游标（`election_stage`）可 `model_copy`。
- 方向以字符串存储（`Direction` 枚举的 `.value`，`"LEFT"`/`"RIGHT"`），`state.py` 不得 import `actions.py`。
- 确定性：bot 的方向选择经 `(seed, seat, state_version)` 派生。
- 注释中文/标识符英文；`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .` 全程干净。
- 所有既有测试（含确定性、四 preset、500 局扫描）必须保持通过——本特性使默认 preset 的方向路径变为**必经**，扫描即真实覆盖。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/state.py` | +`sheriff_speech_direction: str \| None = None` |
| `backend/app/engine/events.py` | +`SHERIFF_DIRECTION_SET` 枚举、`SheriffDirectionSetPayload`、reduce 分支 |
| `backend/app/engine/engine.py` | `_finish_election`/`_advance_election` 方向子阶段；`_validate_sheriff`/`_apply_sheriff` 的 `SET_SPEECH_DIRECTION`；`_speech_order` 重写 |
| `backend/app/engine/phases.py` | `expected_actors` 的 `"direction"` 分支 |
| `backend/app/cli/bot.py` | 方向子阶段随机选 LEFT/RIGHT |
| `backend/tests/test_speech_direction.py` | 新测试文件 |

---

### Task 1: 方向事实 —— state 字段 + 事件 + reduce

**Files:**
- Modify: `backend/app/engine/state.py`（`GameState` 警长字段区）
- Modify: `backend/app/engine/events.py`
- Test: `backend/tests/test_speech_direction.py`（新建）

**Interfaces:**
- Produces: `GameState.sheriff_speech_direction: str | None`（默认 None）；`EventType.SHERIFF_DIRECTION_SET`；`SheriffDirectionSetPayload(direction: str)`；reduce 分支设置该字段。后续任务经 `_emit(state, EventType.SHERIFF_DIRECTION_SET, SheriffDirectionSetPayload(direction=...), Visibility.PUBLIC, actor=...)` 使用。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_speech_direction.py`：
```python
"""警长发言方向（issue #2）：方向事实、顺序计算与竞选后决策点。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    SheriffDirectionSetPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, sheriff: int | None = None, dead: tuple[int, ...] = ()) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
            alive=(i not in dead),
            is_sheriff=(i == sheriff),
        )
        for i in range(n)
    )


def _state(n: int = 5, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_direction_set_event_reduces_into_state() -> None:
    st = _state()
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_DIRECTION_SET,
        actor_seat=2,
        payload=SheriffDirectionSetPayload(direction="LEFT"),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_speech_direction == "LEFT"
    assert st.sheriff_speech_direction is None  # 原状态不变
    assert new.state_version == st.state_version + 1
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_speech_direction.py -v`
Expected: FAIL（`SheriffDirectionSetPayload` 不存在 / `sheriff_speech_direction` 字段不存在）。

- [ ] **Step 3: 实现**

`backend/app/engine/state.py` —— 在 `GameState` 的警长竞选字段区（`election_stage` 附近）追加：
```python
    sheriff_speech_direction: str | None = None  # 警长首日选定的基准方向 "LEFT"/"RIGHT"（事实，经事件写入）
```

`backend/app/engine/events.py` —— `EventType` 追加成员（放在 SHERIFF_ELECTED 附近）：
```python
    SHERIFF_DIRECTION_SET = "SHERIFF_DIRECTION_SET"
```
payload（放在 `SheriffElectedPayload` 之后）：
```python
class SheriffDirectionSetPayload(EventPayload):
    direction: str  # "LEFT" / "RIGHT"
```
reduce 分支（放在 SHERIFF_ELECTED 分支之后）：
```python
    if t == EventType.SHERIFF_DIRECTION_SET and isinstance(p, SheriffDirectionSetPayload):
        return {"sheriff_speech_direction": p.direction}
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_speech_direction.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: 全量回归 + 门禁 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿（138 tests）。
```bash
git add backend/app/engine/state.py backend/app/engine/events.py backend/tests/test_speech_direction.py
git commit -m "feat(engine): SHERIFF_DIRECTION_SET 事件与 sheriff_speech_direction 事实字段"
```

### Task 2: 顺序计算 —— `_speech_order` 重写

**Files:**
- Modify: `backend/app/engine/engine.py`（`_speech_order`，当前约 977 行起）
- Test: `backend/tests/test_speech_direction.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `sheriff_speech_direction`。
- Produces: `_speech_order(state) -> tuple[int, ...]` —— SHERIFF_DECIDES 下按方向+奇偶换手排序；无警长/未定向退回 death-next。签名不变，`_enter_day_speech` 等调用方无需改动。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_speech_direction.py`：
```python
def _day_state(
    sheriff: int | None,
    direction: str | None,
    round_: int,
    dead: tuple[int, ...] = (),
    night_deaths: tuple[int, ...] = (),
) -> GameState:
    return _state(
        n=5,
        phase=Phase.DAY_SPEECH,
        round=round_,
        players=_players(5, sheriff=sheriff, dead=dead),
        sheriff_seat=sheriff,
        sheriff_speech_direction=direction,
        night_deaths=night_deaths,
    )


def test_right_is_clockwise_from_sheriff_next() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警右：3,4,0,1,2
    assert _speech_order(_day_state(2, "RIGHT", 1)) == (3, 4, 0, 1, 2)


def test_left_is_counterclockwise_from_sheriff_prev() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警左：1,0,4,3,2
    assert _speech_order(_day_state(2, "LEFT", 1)) == (1, 0, 4, 3, 2)


def test_alternates_from_day_two() -> None:
    from app.engine.engine import _speech_order

    # 基准 RIGHT：round 2 换手 -> 实际 LEFT
    assert _speech_order(_day_state(2, "RIGHT", 2)) == (1, 0, 4, 3, 2)
    # round 3 换回 RIGHT
    assert _speech_order(_day_state(2, "RIGHT", 3)) == (3, 4, 0, 1, 2)


def test_dead_seats_skipped() -> None:
    from app.engine.engine import _speech_order

    # 警长=2，警右，座3已死：4,0,1,2
    assert _speech_order(_day_state(2, "RIGHT", 1, dead=(3,))) == (4, 0, 1, 2)


def test_no_sheriff_falls_back_to_death_next() -> None:
    from app.engine.engine import _speech_order

    # 无警长 + SHERIFF_DECIDES：退回死者下家顺时针（死者=2 -> 3,4,0,1）
    st = _day_state(None, None, 1, dead=(2,), night_deaths=(2,))
    assert _speech_order(st) == (3, 4, 0, 1)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_speech_direction.py -v`
Expected: 新增 5 项 FAIL（现实现固定顺时针、无换手、无 death-next 退回）。

- [ ] **Step 3: 重写 `_speech_order`**

用下面整体替换 `backend/app/engine/engine.py` 的 `_speech_order`：
```python
def _speech_order(state: GameState) -> tuple[int, ...]:
    alive = living_seats(state)
    if not alive:
        return ()
    rule = state.config.speech_order_rule
    n = state.config.num_players

    def _clockwise_from(start: int) -> tuple[int, ...]:
        seq = [(start + i) % n for i in range(n)]
        return tuple(s for s in seq if s in alive)

    def _counterclockwise_from(start: int) -> tuple[int, ...]:
        seq = [(start - i) % n for i in range(n)]
        return tuple(s for s in seq if s in alive)

    def _death_next_order() -> tuple[int, ...]:
        last_death = (
            max(state.night_deaths)
            if state.night_deaths
            else (state.day_exiled if state.day_exiled is not None else -1)
        )
        return _clockwise_from((last_death + 1) % n) if last_death >= 0 else tuple(alive)

    if rule == SpeechOrderRule.FIXED_CLOCKWISE or rule == SpeechOrderRule.BIDDING:
        return tuple(alive)  # BIDDING 下顺序仅占位；Speak 会被拒
    if rule == SpeechOrderRule.DEATH_NEXT:
        return _death_next_order()
    if rule == SpeechOrderRule.ODD_EVEN_CLOCK:
        base = _clockwise_from(alive[0])
        return base if state.round % 2 == 1 else tuple(reversed(base))
    # SHERIFF_DECIDES：警长在场且已定向 -> 按基准方向 + 奇偶换手；否则退回 death-next
    if state.sheriff_seat is not None and state.sheriff_speech_direction is not None:
        base_dir = state.sheriff_speech_direction
        # 竞选在 round 1：奇数天用基准方向，偶数天换手
        effective = base_dir if state.round % 2 == 1 else ("LEFT" if base_dir == "RIGHT" else "RIGHT")
        if effective == "RIGHT":
            return _clockwise_from((state.sheriff_seat + 1) % n)
        return _counterclockwise_from((state.sheriff_seat - 1) % n)
    return _death_next_order()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_speech_direction.py -v`
Expected: PASS（6 项）。

- [ ] **Step 5: 全量回归 + 门禁 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿。注意：既有 `test_speech_order_rules_return_living_only`（test_sheriff.py）对 SHERIFF_DECIDES 用 `sheriff_seat=None` 构造 —— 新退回是 death-next（该测试用 `night_deaths=(2,)`，退回后仍满足「死者不在序、覆盖所有存活者」断言，应保持通过；若失败按新语义修断言并在报告说明）。
```bash
git add backend/app/engine/engine.py backend/tests/test_speech_direction.py
git commit -m "feat(engine): _speech_order 按警长方向与奇偶换手排序，无警长退回 death-next"
```

### Task 3: 方向决策点 —— 竞选子阶段 + 校验/应用 + bot

**Files:**
- Modify: `backend/app/engine/engine.py`（`_finish_election`、`_advance_election`、`_validate_sheriff`、`_apply_sheriff`）
- Modify: `backend/app/engine/phases.py`（`expected_actors` 的 SHERIFF_ELECTION 分支）
- Modify: `backend/app/cli/bot.py`
- Test: `backend/tests/test_speech_direction.py`（追加）

**Interfaces:**
- Consumes: Task 1 事件、Task 2 顺序。
- Produces: `election_stage` 取值扩展为 `""/"candidacy"/"vote"/"direction"/"announce"`；`SET_SPEECH_DIRECTION` 在 direction 子阶段合法。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_speech_direction.py`：
```python
def test_direction_stage_flow() -> None:
    from app.engine.actions import Direction, SheriffAction, SheriffActionType
    from app.engine.engine import step
    from app.engine.phases import expected_actors

    # 构造「刚当选、进入 direction 子阶段」的态（SHERIFF_DECIDES 为 preset 默认）
    st = _state(
        n=5,
        players=_players(5, sheriff=2),
        sheriff_seat=2,
        election_stage="direction",
        night_deaths=(),
        resolved_first_night=True,
    )
    assert expected_actors(st) == {2}

    # 非警长提交 -> NOT_YOUR_TURN
    r_bad = step(st, SheriffAction(actor_seat=1, action_type=SheriffActionType.SET_SPEECH_DIRECTION, direction=Direction.LEFT))
    assert r_bad.rejection is not None

    # 警长提交错误行动类型 -> WRONG_PHASE
    r_wrong = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1))
    assert r_wrong.rejection is not None

    # 警长提交方向 -> 事实写入、事件发出、流程续接（离开 direction 子阶段）
    res = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.SET_SPEECH_DIRECTION, direction=Direction.LEFT))
    assert res.rejection is None
    assert res.state.sheriff_speech_direction == "LEFT"
    assert any(e.type == EventType.SHERIFF_DIRECTION_SET for e in res.events)
    assert res.state.election_stage == ""  # announce 已被消费
    assert res.state.phase != Phase.SHERIFF_ELECTION  # 已续接死讯公布及之后


def test_full_game_with_direction_still_terminates() -> None:
    from app.cli.bot import run_game

    for seed in (1, 7, 42):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"d{seed}")
        assert final.phase == Phase.GAME_OVER
        # 若有警长当选，必有方向事件
        elected = [e for e in events if e.type == EventType.SHERIFF_ELECTED and e.payload.seat is not None]  # type: ignore[attr-defined]
        if elected:
            assert any(e.type == EventType.SHERIFF_DIRECTION_SET for e in events)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_speech_direction.py::test_direction_stage_flow -v`
Expected: FAIL（direction 子阶段不存在，`expected_actors` 返回空集）。

- [ ] **Step 3: 实现流程**

`backend/app/engine/phases.py` —— `expected_actors` 的 SHERIFF_ELECTION 分支加（放在 `"vote"` 分支之后、`return set()` 之前）：
```python
        if state.election_stage == "direction":
            return {state.sheriff_seat} if state.sheriff_seat is not None else set()
```

`backend/app/engine/engine.py` —— `_finish_election` 改为（有警长且 SHERIFF_DECIDES 时进入方向子阶段）：
```python
def _finish_election(
    state: GameState, elected: int | None, events: list[Event]
) -> tuple[GameState, list[Event]]:
    state, e = _emit(
        state, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=elected), Visibility.PUBLIC
    )
    events.append(e)
    if elected is not None and state.config.speech_order_rule == SpeechOrderRule.SHERIFF_DECIDES:
        # 警长先定发言方向，再公布死讯
        state = state.model_copy(update={"election_stage": "direction"})
        return state, events
    state = state.model_copy(update={"election_stage": ""})
    # 竞选结束 -> 回到「公布死讯并继续」
    return _announce_and_continue_night(state, state.night_deaths, events)
```

`_advance_election` 开头加两个分支（放在 `"candidacy"` 分支之前）：
```python
    if state.election_stage == "direction":
        # 方向子阶段必有存活警长为行动者；到达此处说明不变量被破坏
        raise EngineInvariantError("方向决策阶段不应无行动者")
    if state.election_stage == "announce":
        state = state.model_copy(update={"election_stage": ""})
        return _announce_and_continue_night(state, state.night_deaths, events)
```

`_validate_sheriff` —— 在 `"candidacy"` 分支之后、通用 `SHERIFF_ELECTION/SHERIFF_PK` 投票分支**之前**插入：
```python
    if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "direction":
        if at != SheriffActionType.SET_SPEECH_DIRECTION:
            return RejectedReason.WRONG_PHASE
        if a.direction is None:
            return RejectedReason.INVALID_TARGET
        if a.actor_seat != state.sheriff_seat:
            return RejectedReason.NOT_YOUR_TURN
        return None
```

`_apply_sheriff` —— 在 badge 分支之后、`# vote_sheriff` 注释之前插入：
```python
    if at == SheriffActionType.SET_SPEECH_DIRECTION:
        assert a.direction is not None  # 校验已保证
        s, e = _emit(
            state,
            EventType.SHERIFF_DIRECTION_SET,
            SheriffDirectionSetPayload(direction=a.direction.value),
            Visibility.PUBLIC,
            actor=a.actor_seat,
        )
        # 方向已定 -> 游标推进到 announce，由 _advance_election 续接死讯公布
        s = s.model_copy(update={"election_stage": "announce"})
        return s, [e]
```
（engine.py 顶部 import 补 `SheriffDirectionSetPayload`；`SpeechOrderRule` 已 import。）

- [ ] **Step 4: bot 支持方向子阶段**

`backend/app/cli/bot.py` —— 在 `election_stage == "candidacy"` 分支**之前**插入：
```python
        if ph == Phase.SHERIFF_ELECTION and state.election_stage == "direction":
            from app.engine.actions import Direction, SheriffAction, SheriffActionType

            left = (
                rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:dir", seq=state.state_version, modulo=2
                )
                == 0
            )
            return SheriffAction(
                actor_seat=seat,
                action_type=SheriffActionType.SET_SPEECH_DIRECTION,
                direction=Direction.LEFT if left else Direction.RIGHT,
            )
```

- [ ] **Step 5: 运行新测试**

Run: `uv run pytest tests/test_speech_direction.py -v`
Expected: PASS（8 项，含 flow 与 3-seed 完整对局）。

- [ ] **Step 6: 全量回归（关键：确定性与扫描必须仍绿）**

Run:
```bash
uv run pytest -q
uv run mypy app && uv run ruff check . && uv run ruff format --check .
```
Expected: 全绿（默认 preset 现在必经方向子阶段：`test_determinism`、`test_sweep`、`test_config::test_all_presets_run_to_completion` 都会重新覆盖）。若扫描某 seed 卡死在 SHERIFF_ELECTION/direction，检查 `expected_actors` 与 bot 分支的 stage 判断。

- [ ] **Step 7: 提交**

```bash
git add backend/app/engine backend/app/cli/bot.py backend/tests/test_speech_direction.py
git commit -m "feat(engine): 警长竞选后选定发言方向（set_speech_direction），闭环 issue #2"
```

---

## Self-Review

**Spec 覆盖**：§2 数据模型→Task 1；§4 顺序计算（含换手/逆时针/death-next 抽取）→Task 2；§3 决策点流程 + §5 校验与 bot→Task 3；§6 测试→三任务的测试步骤 + 全量回归；§7 范围外（死左死右/归票）无任务——正确。

**占位扫描**：无 TBD/TODO；每步含完整代码。

**类型一致性**：`SheriffDirectionSetPayload(direction: str)` 与 `a.direction.value`（`Direction.LEFT.value == "LEFT"`）一致；`election_stage` 新值 `"direction"/"announce"` 在 phases/engine/bot 三处拼写一致；`_speech_order` 签名未变。
