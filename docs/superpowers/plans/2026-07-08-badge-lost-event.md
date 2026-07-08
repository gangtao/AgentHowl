# 全员上警裁决 + SHERIFF_BADGE_LOST 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 issue #9：全员上警（无警下投票人）→ 警徽立即流失且不进入空投票阶段；实现最后一个引擎侧预留事件 `SHERIFF_BADGE_LOST(reason)` 替换全部 `SHERIFF_ELECTED(seat=None)` 用法，`SHERIFF_ELECTED.seat` 收紧为 `int`。

**Architecture:** Task 1 纯增量：`BadgeLostReason` 枚举 + `SheriffBadgeLostPayload` + reduce（#19 全化语义：剥离在任者 + 置空 sheriff_seat）+ 映射 + fail-loud 预留集合缩至 `{GAME_CREATED, GAME_STARTED}`。Task 2 原子迁移：新 `_lose_badge(state, reason, events)` helper 接管五个流失点（含新增 NO_VOTERS 裁决），`_finish_election` 只留真实当选路径，自爆吞警徽原地换发射，`SheriffElectedPayload.seat` 收紧，既有五处测试断言迁移 + 新行为测试。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2）。命令在 `backend/` 下运行。

## Global Constraints

- 五条流失路径 reason 对应：candidacy 空→`NO_CANDIDATES`；withdraw 后候选空→`ALL_WITHDREW`；withdraw 后警下空→`NO_VOTERS`（新裁决，`election_stage` 不得进入 `"vote"`）；PK 再平票→`TIE_AGAIN`；自爆吞警徽→`SELF_DESTRUCT`。
- `SHERIFF_ELECTED` 收紧后恒携带 `int` 座位；完整对局事件流中不得再出现 None。
- 全量回归（确定性、500 局扫描）必须通过；引擎零 IO；注释中文/标识符英文；mypy strict + ruff check + ruff format 干净。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/events.py` | +`BadgeLostReason`、`SheriffBadgeLostPayload`、reduce 分支、映射条目；`SheriffElectedPayload.seat: int` 收紧 + 其 reduce 简化（Task 2） |
| `backend/app/engine/engine.py` | +`_lose_badge`；`_finish_election` 只留当选路径；`_advance_election` 三处 + 自爆一处改接；NO_VOTERS 裁决 |
| `backend/tests/test_fail_loud.py` | 预留集合 → `{GAME_CREATED, GAME_STARTED}` |
| `backend/tests/test_badge_lost.py` | 新测试文件 |
| `backend/tests/test_withdraw.py` `test_sheriff.py` `test_self_destruct_skip.py` `test_speech_direction.py` | 既有断言迁移（见 Task 2 Step 4 清单） |

---

### Task 1: 事件契约（纯增量）—— BadgeLostReason + payload + reduce + 映射

**Files:**
- Modify: `backend/app/engine/events.py`
- Modify: `backend/tests/test_fail_loud.py`
- Test: `backend/tests/test_badge_lost.py`（新建）

**Interfaces:**
- Produces: `BadgeLostReason(StrEnum)` 五成员；`SheriffBadgeLostPayload(reason: str)`；`EventType.SHERIFF_BADGE_LOST` 的 reduce（剥离在任者 + `sheriff_seat=None`）与映射条目。Task 2 经 `_emit(..., SheriffBadgeLostPayload(reason=reason.value), ...)` 消费。
- 无发射方 → 本任务单独合入行为零变化（确定性字节级不变）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_badge_lost.py`：
```python
"""全员上警裁决 + SHERIFF_BADGE_LOST（issue #9）。"""

from app.engine.actions import SheriffAction, SheriffActionType
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
from app.engine.events import (
    BadgeLostReason,
    Event,
    EventType,
    SheriffBadgeLostPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0, 1)) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(n: int = 6, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _badge_lost_events(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.SHERIFF_BADGE_LOST]


def test_badge_lost_reduce_strips_incumbent() -> None:
    # 移植 issue #19 的全化语义到新事件
    st = _state(sheriff_seat=2)
    players = tuple(
        p.model_copy(update={"is_sheriff": True}) if p.seat == 2 else p for p in st.players
    )
    st = st.model_copy(update={"players": players})
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_BADGE_LOST,
        actor_seat=None,
        payload=SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_seat is None
    assert not any(p.is_sheriff for p in new.players)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_badge_lost.py -v`
Expected: FAIL（`ImportError: cannot import name 'BadgeLostReason'`）。

- [ ] **Step 3: 实现**

`backend/app/engine/events.py`：

(a) `SheriffElectedPayload` 附近追加：
```python
class BadgeLostReason(StrEnum):
    NO_CANDIDATES = "NO_CANDIDATES"  # 无人上警
    ALL_WITHDREW = "ALL_WITHDREW"  # 候选人全员退水
    NO_VOTERS = "NO_VOTERS"  # 全员上警，无警下投票人（issue #9 裁决）
    TIE_AGAIN = "TIE_AGAIN"  # PK 再平票
    SELF_DESTRUCT = "SELF_DESTRUCT"  # 竞选期狼人自爆吞警徽


class SheriffBadgeLostPayload(EventPayload):
    reason: str  # BadgeLostReason 的 .value
```

(b) reduce 分支（SHERIFF_ELECTED 分支之后）：
```python
    if t == EventType.SHERIFF_BADGE_LOST and isinstance(p, SheriffBadgeLostPayload):
        # 警徽流失：剥离在任者（若有）并置空（issue #19 全化语义）
        players = state.players
        if state.sheriff_seat is not None:
            players = _replace_player(players, state.sheriff_seat, is_sheriff=False)
        return {"sheriff_seat": None, "players": players}
```

(c) `EVENT_PAYLOAD_TYPES` 加 `EventType.SHERIFF_BADGE_LOST: SheriffBadgeLostPayload,`；顶部映射注释的预留清单同步改为「GAME_CREATED/GAME_STARTED」。

`backend/tests/test_fail_loud.py` —— 完整性测试的 `reserved` 集合改为 `{EventType.GAME_CREATED, EventType.GAME_STARTED}`。

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_badge_lost.py tests/test_fail_loud.py -v && uv run pytest -q`
Expected: 全绿（184 tests；无发射方，行为零变化）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine/events.py backend/tests/test_badge_lost.py backend/tests/test_fail_loud.py
git commit -m "feat(engine): SHERIFF_BADGE_LOST 事件契约（实现最后一个引擎侧预留类型）"
```

### Task 2: 原子迁移 —— _lose_badge、五流失点、NO_VOTERS 裁决、SHERIFF_ELECTED 收紧、断言迁移

**Files:**
- Modify: `backend/app/engine/engine.py`（`_finish_election`、`_advance_election`、`_apply_self_destruct`）
- Modify: `backend/app/engine/events.py`（`SheriffElectedPayload.seat` 收紧 + 其 reduce 简化）
- Modify: `backend/tests/test_withdraw.py`、`backend/tests/test_sheriff.py`、`backend/tests/test_self_destruct_skip.py`、`backend/tests/test_speech_direction.py`（断言迁移）
- Test: `backend/tests/test_badge_lost.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `BadgeLostReason`/`SheriffBadgeLostPayload`/reduce。
- Produces: `_lose_badge(state: GameState, reason: BadgeLostReason, events: list[Event]) -> tuple[GameState, list[Event]]`；`_finish_election(state, elected: int, events)`（只留当选路径）；`SheriffElectedPayload.seat: int`。

- [ ] **Step 1: 写失败测试（行为矩阵）**

Append 到 `backend/tests/test_badge_lost.py`：
```python
def _reason_of(events: list[Event]) -> str:
    lost = _badge_lost_events(events)
    assert len(lost) == 1
    return lost[0].payload.reason  # type: ignore[attr-defined]


def test_no_voters_all_run_skips_vote_stage() -> None:
    # 全员上警：withdraw 确认完毕后无警下 -> NO_VOTERS，且不进入 vote 阶段
    st = _state(
        election_stage="withdraw",
        sheriff_candidates=(0, 1, 2, 3, 4, 5),
        sheriff_confirmed=frozenset({0, 1, 2, 3, 4}),
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.RUN_FOR_SHERIFF))
    assert res.rejection is None
    assert _reason_of(res.events) == "NO_VOTERS"
    assert res.state.sheriff_seat is None
    # 从未进入投票子阶段
    assert res.state.election_stage != "vote"


def test_no_candidates_reason() -> None:
    # candidacy 全员声明完毕且无人上警 -> NO_CANDIDATES
    st = _state(
        election_stage="candidacy",
        sheriff_declared=frozenset({0, 1, 2, 3, 4}),
        sheriff_candidates=(),
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    assert _reason_of(res.events) == "NO_CANDIDATES"


def test_all_withdrew_reason() -> None:
    st = _state(election_stage="withdraw", sheriff_candidates=(1, 2))
    st = step(st, SheriffAction(actor_seat=1, action_type=SheriffActionType.WITHDRAW)).state
    res = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    assert _reason_of(res.events) == "ALL_WITHDREW"


def test_tie_again_reason() -> None:
    # SHERIFF_PK 发言已尽、警下 {0,3} 再度 1-1 -> TIE_AGAIN
    st = _state(
        phase=Phase.SHERIFF_PK,
        sheriff_candidates=(1, 2),
        speech_order=(1, 2),
        speech_idx=2,
        sheriff_votes={0: 1},
    )
    res = step(st, SheriffAction(actor_seat=3, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=2))
    # 4、5 号也是警下：先补投使全员投完并保持平票
    st = res.state
    if res.rejection is None and st.phase == Phase.SHERIFF_PK:
        st = step(st, SheriffAction(actor_seat=4, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)).state
        res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=2))
    assert res.rejection is None
    assert _reason_of(res.events) == "TIE_AGAIN"


def test_self_destruct_reason() -> None:
    from app.engine.actions import SelfDestruct

    st = _state(election_stage="candidacy")
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert _reason_of(res.events) == "SELF_DESTRUCT"


def test_sheriff_elected_always_has_seat_in_full_games() -> None:
    from app.cli.bot import run_game

    for seed in range(12):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"bl{seed}")
        assert final.phase == Phase.GAME_OVER
        for e in events:
            if e.type == EventType.SHERIFF_ELECTED:
                assert isinstance(e.payload.seat, int)  # type: ignore[attr-defined]
```


- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_badge_lost.py -v`
Expected: 新增行为测试全部 FAIL（`SHERIFF_BADGE_LOST` 无发射方；NO_VOTERS 路径进了空 vote 阶段）。

- [ ] **Step 3: 引擎迁移**

`backend/app/engine/engine.py`（import 块补 `BadgeLostReason`、`SheriffBadgeLostPayload`）：

(a) 新 helper（放在 `_finish_election` 之前）：
```python
def _lose_badge(
    state: GameState, reason: BadgeLostReason, events: list[Event]
) -> tuple[GameState, list[Event]]:
    """警徽流失：发 SHERIFF_BADGE_LOST(reason) 并续接「公布死讯并继续」。"""
    state, e = _emit(
        state,
        EventType.SHERIFF_BADGE_LOST,
        SheriffBadgeLostPayload(reason=reason.value),
        Visibility.PUBLIC,
    )
    events.append(e)
    state = state.model_copy(update={"election_stage": ""})
    return _announce_and_continue_night(state, state.night_deaths, events)
```

(b) `_finish_election` 整体替换（只留当选路径；方向子阶段与 PK 相位回切逻辑原样保留）：
```python
def _finish_election(
    state: GameState, elected: int, events: list[Event]
) -> tuple[GameState, list[Event]]:
    state, e = _emit(
        state, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=elected), Visibility.PUBLIC
    )
    events.append(e)
    if state.config.speech_order_rule == SpeechOrderRule.SHERIFF_DECIDES:
        # 警长先定发言方向，再公布死讯；PK 当选时相位先切回 SHERIFF_ELECTION
        if state.phase != Phase.SHERIFF_ELECTION:
            state, e2 = _emit(
                state,
                EventType.PHASE_CHANGED,
                PhaseChangedPayload(to=Phase.SHERIFF_ELECTION),
                Visibility.PUBLIC,
            )
            events.append(e2)
        state = state.model_copy(update={"election_stage": "direction"})
        return state, events
    state = state.model_copy(update={"election_stage": ""})
    return _announce_and_continue_night(state, state.night_deaths, events)
```

(c) `_advance_election` 四处改接：
- candidacy 空：`return _lose_badge(state, BadgeLostReason.NO_CANDIDATES, events)`
- withdraw 分支整体替换为：
```python
    if state.election_stage == "withdraw":
        if not state.sheriff_candidates:
            return _lose_badge(state, BadgeLostReason.ALL_WITHDREW, events)
        voters = {
            p.seat
            for p in living(state)
            if p.can_vote
            and p.seat not in state.sheriff_candidates
            and p.seat not in state.sheriff_withdrawn
        }
        if not voters:
            # 全员上警：无警下投票人 -> 警徽流失，不进入空投票阶段（issue #9 裁决）
            return _lose_badge(state, BadgeLostReason.NO_VOTERS, events)
        state = state.model_copy(update={"election_stage": "vote", "sheriff_votes": {}})
        return state, events
```
- PK 再平票（函数末行）：`return _lose_badge(state, BadgeLostReason.TIE_AGAIN, events)`

(d) `_apply_self_destruct` 吞警徽分支：`SheriffElectedPayload(seat=None)` 的 `_emit` 改为
```python
        s, e2 = _emit(
            s,
            EventType.SHERIFF_BADGE_LOST,
            SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
            Visibility.PUBLIC,
        )
```

`backend/app/engine/events.py`：

(e) `SheriffElectedPayload` 收紧：
```python
class SheriffElectedPayload(EventPayload):
    seat: int  # 恒为真实当选座位；流失走 SHERIFF_BADGE_LOST
```
(f) `SHERIFF_ELECTED` reduce 简化（保留 strip-then-grant 不变量防御）：
```python
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        players = state.players
        if state.sheriff_seat is not None:
            players = _replace_player(players, state.sheriff_seat, is_sheriff=False)
        players = _replace_player(players, p.seat, is_sheriff=True)
        return {"sheriff_seat": p.seat, "players": players}
```

- [ ] **Step 4: 既有断言迁移（精确清单）**

- `tests/test_withdraw.py::test_all_withdraw_badge_lost`（~102 行）：`SHERIFF_ELECTED` 事件断言改为 `SHERIFF_BADGE_LOST` 且 `payload.reason == "ALL_WITHDREW"`；`sheriff_seat is None` 断言保留。
- `tests/test_sheriff.py::test_full_game_with_sheriff_terminates`（~15-18 行）：`any(SHERIFF_ELECTED)` 改为 `any(e.type in (EventType.SHERIFF_ELECTED, EventType.SHERIFF_BADGE_LOST))`（竞选必有其一），注释同步。
- `tests/test_sheriff.py` 自爆吞警徽用例（~131、169-170 行）：`SHERIFF_ELECTED`+`SheriffElectedPayload` 断言改为 `SHERIFF_BADGE_LOST`（reason `"SELF_DESTRUCT"`）。
- `tests/test_self_destruct_skip.py::test_sheriff_elected_none_strips_incumbent_reduce_unit`（~182-201 行）：**删除**（已由 `test_badge_lost.py::test_badge_lost_reduce_strips_incumbent` 取代，避免重复）；`test_sheriff_elected_normal_grant_regression`（seat=3）保留不动；端到端 strips 测试（纯状态断言）保留不动。
- `tests/test_speech_direction.py`（~173 行）：过滤器 `e.payload.seat is not None` 在收紧后恒真——简化为 `e for e in events if e.type == EventType.SHERIFF_ELECTED`。
- 执行 `grep -rn "SheriffElectedPayload(seat=None)\|payload.seat is None" tests/` 确认零残留。

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_badge_lost.py -v && uv run pytest -q`
Expected: 全绿（约 190 tests：184 + 6 新行为 − 1 删除 + 迁移不改数量；以实际为准）。确定性、500 局扫描——事件日志形态改变（流失事件换类型）但同代码两次运行一致；扫描中五条流失路径均真实发生（bot 已覆盖竞选自爆/退水/全员上警概率路径）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 6: 提交**

```bash
git add backend/app/engine backend/tests
git commit -m "feat(engine): 警徽流失改发 SHERIFF_BADGE_LOST(reason)，全员上警判 NO_VOTERS，SHERIFF_ELECTED 收紧，闭环 issue #9"
```

---

## Self-Review

**Spec 覆盖**：§2 裁决→Task 2(c) withdraw 分支 + `test_no_voters_all_run_skips_vote_stage`；§3 契约四点→Task 1 + Task 2(e)(f) + fail_loud 更新；§4 五发射点→Task 2(a)-(d)；§5 测试（迁移清单 + 新文件）→Task 2 Step 4 精确清单 + Step 1；§6 范围外无任务——正确。

**占位扫描**：无 TBD/TODO；测试代码均为干净最终版。

**类型一致性**：`BadgeLostReason`/`SheriffBadgeLostPayload(reason: str)` 在 events/engine/tests 一致（emit 传 `.value`，断言比对字符串）；`_lose_badge`/`_finish_election(elected: int)` 签名与调用点一致；`living` 已在 engine.py import。
