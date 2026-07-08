# SHERIFF_ELECTED reduce 剥离在任者 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 issue #19：`SHERIFF_ELECTED` reduce 全化——先剥离在任者 `is_sheriff` 再授予新任者，消除方向阶段自爆吞警徽后死者持徽的事实不一致。

**Architecture:** 单点修复 `events.py` 的 `SHERIFF_ELECTED` 分支（发射方不改、事件日志不变）；恢复不变量「`sheriff_seat` 与 `is_sheriff` 不经此事件分叉」，对所有现在/未来发射方成立。正常竞选路径零影响（当选时无在任者）。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2）。命令在 `backend/` 下运行。

## Global Constraints

- 只改 reduce，不改发射方；事件日志不变，确定性（同代码两次运行）不受影响。
- 修复前端到端复现测试必须先 FAIL（证明捕获了原缺陷）。
- 注释中文/标识符英文；`uv run mypy app`（strict）+ `uv run ruff check .` + `uv run ruff format --check .` 干净。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/events.py` | `SHERIFF_ELECTED` reduce 分支全化 |
| `backend/tests/test_self_destruct_skip.py` | +3 测试（端到端复现、reduce 单元、正常当选回归） |

---

### Task 1: reduce 全化 + 三测试

**Files:**
- Modify: `backend/app/engine/events.py`（`SHERIFF_ELECTED` 分支，约 436-440 行）
- Test: `backend/tests/test_self_destruct_skip.py`（追加；复用既有 `_election_state`/`_mk_player` helper）

**Interfaces:**
- Consumes: 既有 `SheriffElectedPayload(seat: int | None)`、`_replace_player`、测试文件 helper。
- Produces: 全化后的 reduce 语义（strip-then-grant）。无新接口。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_self_destruct_skip.py`：
```python
def test_sheriff_wolf_direction_stage_selfdestruct_strips_badge() -> None:
    # issue #19 端到端复现：方向阶段的狼警长自爆吞警徽后，死者不得残留 is_sheriff
    st = _election_state(election_stage="direction", sheriff_seat=0)
    players = tuple(
        p.model_copy(update={"is_sheriff": True}) if p.seat == 0 else p for p in st.players
    )
    st = st.model_copy(update={"players": players})

    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    final = res.state
    assert final.sheriff_seat is None
    # 修复前失败点：死者 seat 0 的 is_sheriff 残留为 True
    assert not any((not p.alive) and p.is_sheriff for p in final.players)


def test_sheriff_elected_none_strips_incumbent_reduce_unit() -> None:
    from app.engine.events import Event, EventType, SheriffElectedPayload, Visibility, reduce

    st = _election_state(sheriff_seat=2)
    players = tuple(
        p.model_copy(update={"is_sheriff": True}) if p.seat == 2 else p for p in st.players
    )
    st = st.model_copy(update={"players": players})
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_ELECTED,
        actor_seat=None,
        payload=SheriffElectedPayload(seat=None),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_seat is None
    assert not any(p.is_sheriff for p in new.players)


def test_sheriff_elected_normal_grant_regression() -> None:
    from app.engine.events import Event, EventType, SheriffElectedPayload, Visibility, reduce

    st = _election_state()  # 无在任者
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_ELECTED,
        actor_seat=None,
        payload=SheriffElectedPayload(seat=3),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_seat == 3
    assert [p.seat for p in new.players if p.is_sheriff] == [3]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_self_destruct_skip.py -v -k "strips or grant"`
Expected: `test_sheriff_wolf_direction_stage_selfdestruct_strips_badge` 与 `test_sheriff_elected_none_strips_incumbent_reduce_unit` FAIL（残留 `is_sheriff=True`）；`test_sheriff_elected_normal_grant_regression` PASS（现状已正确）。

- [ ] **Step 3: 全化 reduce**

`backend/app/engine/events.py` —— 把 `SHERIFF_ELECTED` 分支整体替换为：
```python
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        # 全化：先剥离在任者（吞警徽等带在任者路径），再授予新任者——
        # 保证 sheriff_seat 与 is_sheriff 不经此事件分叉（issue #19）。
        players = state.players
        if state.sheriff_seat is not None:
            players = _replace_player(players, state.sheriff_seat, is_sheriff=False)
        if p.seat is not None:
            players = _replace_player(players, p.seat, is_sheriff=True)
        return {"sheriff_seat": p.seat, "players": players}
```

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_self_destruct_skip.py -v && uv run pytest -q`
Expected: 全绿（183 tests；确定性、500 局扫描不受影响——事件日志不变，仅原缺陷路径的 reduce 结果被修正）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine/events.py backend/tests/test_self_destruct_skip.py
git commit -m "fix(engine): SHERIFF_ELECTED reduce 全化剥离在任者，闭环 issue #19"
```

---

## Self-Review

**Spec 覆盖**：§2 全化 reduce→Step 3（逐字对应）；§3 三测试→Step 1；§4 范围外无任务——正确。

**占位扫描**：无 TBD/TODO。

**类型一致性**：`SheriffElectedPayload(seat)`/`_replace_player`/`_election_state` 均既有名字；`step`/`SelfDestruct` 已在测试文件顶部 import（Task 1/M1 时引入）。
