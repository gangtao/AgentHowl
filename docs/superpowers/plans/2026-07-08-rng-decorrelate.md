# 随机抽取去相关（seq = state_version，删除 rng_state）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引擎两处随机抽取改用 `seq=state.state_version`（每次抽取唯一、事件推导、重放恒同），并删除死掉的 `rng_state` 机制全链路。

**Architecture:** 纯机械替换 + 删除：`_wolf_consensus`（RANDOM_PROPOSAL）与 `_tally_and_continue`（PK_THEN_RANDOM）的 `derive_int` 改 seq 来源；随后 `GameState.rng_state`、`RolesAssignedPayload.new_rng_state`、ROLES_ASSIGNED reduce 的 rng 写入、`create_game` 实参全部删除（切换后零读者）。bot 已用同一模式（state_version），发牌 shuffle 不涉 seq，均不动。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest；纯引擎（零 IO），从 `backend/` 运行所有命令。

**Spec:** `docs/superpowers/specs/2026-07-08-rng-decorrelate-design.md`（已批准，关联 issue #12）

## Global Constraints

- 引擎纯函数零 IO：只许 stdlib + Pydantic，不得引入任何网络/DB/LLM 依赖。
- 事实经 reduce；本变更不新增任何事件类型，不改 `EVENT_PAYLOAD_TYPES`。
- 文档与注释中文；标识符英文。
- 门禁（全部从 `backend/` 运行）：`uv run pytest -q`（现 189 通过，本任务新增 2）、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`。
- 完成后 `grep -rn "rng_state" backend/app backend/tests`（仓库根运行）必须零命中（含 docstring）。

---

### Task 1: seq 切换 + rng_state 全删 + 去相关测试

**Files:**
- Create: `backend/tests/test_rng_decorrelation.py`
- Modify: `backend/app/engine/engine.py`（149、729、1252 行）
- Modify: `backend/app/engine/events.py`（4、75、309 行）
- Modify: `backend/app/engine/state.py`（76 行）
- Modify: `backend/app/engine/rng.py`（4 行 docstring）
- Modify: `backend/tests/test_wolf_kill_rule.py`（81 行）

**Interfaces:**
- Consumes: `rng.derive_int(seed: int, purpose: str, seq: int, modulo: int) -> int`（不改）；`GameState.state_version: int`（每事件 +1，已存在）。
- Produces: 无新接口。`GameState` 不再有 `rng_state` 字段；`RolesAssignedPayload` 只剩 `assignments`。

- [ ] **Step 1: 写失败的去相关测试**

新建 `backend/tests/test_rng_decorrelation.py`（完整文件）：

```python
"""随机抽取去相关（issue #12）：同池不同 state_version → 抽取结果可不同，且恒可重放。"""

from app.engine import rng
from app.engine.config import Faction, RoleType, TieRule, WolfKillRule, build_preset
from app.engine.events import EventType, PlayerExiledPayload
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _wolf_state(state_version: int) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": 42, "wolf_kill_rule": WolfKillRule.RANDOM_PROPOSAL}
    )
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i < 3 else RoleType.VILLAGER,
            faction=Faction.WOLF if i < 3 else Faction.GOOD,
        )
        for i in range(9)
    )
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.NIGHT_WEREWOLF,
        round=1,
        players=players,
        wolf_proposals={0: 4, 1: 6, 2: 7},  # 池 [4, 6, 7]，无重复值：下标不同 ⇒ 座位不同
        state_version=state_version,
    )


def test_random_proposal_decorrelates_across_state_versions() -> None:
    from app.engine.engine import _wolf_consensus

    pool = [4, 6, 7]
    # 独立公式预算各 state_version 的下标，找一对不同者——证明差异非巧合而是派生契约
    picks = {sv: rng.derive_int(seed=42, purpose="wolf_kill", seq=sv, modulo=3) for sv in range(20)}
    sv_b = next(sv for sv in range(1, 20) if picks[sv] != picks[0])
    assert _wolf_consensus(_wolf_state(0)) == pool[picks[0]]
    assert _wolf_consensus(_wolf_state(sv_b)) == pool[picks[sv_b]]
    assert pool[picks[0]] != pool[picks[sv_b]]
    # 同状态重复调用恒同（可重放）
    assert _wolf_consensus(_wolf_state(sv_b)) == _wolf_consensus(_wolf_state(sv_b))


def _tie_state(state_version: int) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": 42, "tie_rule": TieRule.PK_THEN_RANDOM}
    )
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(9)
    )
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE_PK,
        round=1,
        players=players,
        votes={0: 3, 1: 3, 2: 4, 5: 4},  # 3、4 各两票：PK 轮再平票 → 随机放逐
        tie_round=1,
        state_version=state_version,
    )


def _exiled_of(state_version: int) -> int:
    from app.engine.engine import _tally_and_continue

    _, events = _tally_and_continue(_tie_state(state_version))
    exiled = [e for e in events if e.type == EventType.PLAYER_EXILED]
    assert len(exiled) == 1
    p = exiled[0].payload
    assert isinstance(p, PlayerExiledPayload)
    assert p.seat is not None  # mypy 收窄：随机放逐分支必有座位
    assert p.seat in (3, 4)
    return p.seat


def test_pk_then_random_decorrelates_across_state_versions() -> None:
    # 同一平票池、只有 state_version 不同：两个候选都应被抽中过（不再整局恒定同一下标）
    picks = {sv: _exiled_of(sv) for sv in range(20)}
    assert set(picks.values()) == {3, 4}
    # 同状态重复调用恒同（可重放）
    assert _exiled_of(0) == _exiled_of(0)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_rng_decorrelation.py -v`
Expected: 两条测试 FAIL——现状 `seq=state.rng_state` 恒为 1（wolf 单元态甚至为 0），抽取与 `state_version` 无关：第一条在 `_wolf_consensus(_wolf_state(sv_b)) == pool[picks[sv_b]]` 断言处失败，第二条在 `set(picks.values()) == {3, 4}` 处失败（恒中同一座位）。若碰巧某断言通过、另一条必失败；两条全过则说明实现已改，回查。

- [ ] **Step 3: 切换两处抽取的 seq 来源（engine.py）**

`backend/app/engine/engine.py` 729 行（`_wolf_consensus` 的 RANDOM_PROPOSAL 分支）：

```python
        idx = rng.derive_int(
            seed=seed, purpose="wolf_kill", seq=state.state_version, modulo=len(pool)
        )
```

（原为 `seq=state.rng_state`；改后超 100 列需按上式折行，ruff format 会强制。）

1252 行（`_tally_and_continue` 的 PK_THEN_RANDOM 再平票分支）：

```python
        idx = rng.derive_int(seed=seed, purpose="tie", seq=state.state_version, modulo=len(tie))
```

- [ ] **Step 4: 删除 rng_state 全链路**

四处删除 + 两处 docstring 改写：

1. `backend/app/engine/state.py` 76 行，删除整行：
```python
    rng_state: int = 0
```

2. `backend/app/engine/events.py` 75 行，`RolesAssignedPayload` 删除 `new_rng_state` 字段，变为：
```python
class RolesAssignedPayload(EventPayload):
    # 座位->角色（GM_ONLY）；用 list[tuple] 以便确定性序列化
    assignments: tuple[tuple[int, RoleType], ...]
```

3. `backend/app/engine/events.py` 309 行，ROLES_ASSIGNED reduce 返回值去掉 rng 写入：
```python
        return {"players": players}
```

4. `backend/app/engine/engine.py` 149 行，`create_game` 的 payload 构造：
```python
        RolesAssignedPayload(assignments=assignments),
```

5. `backend/app/engine/rng.py` 4 行 docstring，原「GameState.rng_state 只是一个递增计数器（seq 的来源），因此重放天然复现。」改为：
```python
引擎抽取以 GameState.state_version 为 seq（每事件 +1，事件推导），因此重放天然复现。
```

6. `backend/app/engine/events.py` 4 行 docstring，原「每个事件应用后 state_version += 1，rng_state 由使用随机的事件在 payload 里带出新值。」改为：
```python
每个事件应用后 state_version += 1（引擎随机抽取以它为 seq）。
```

- [ ] **Step 5: 迁移唯一契约测试引用**

`backend/tests/test_wolf_kill_rule.py` 81 行：

```python
    idx = rng.derive_int(seed=42, purpose="wolf_kill", seq=st.state_version, modulo=3)
```

（原为 `seq=st.rng_state`。该测试其余部分不动。）

- [ ] **Step 6: 运行新测试确认通过**

Run: `cd backend && uv run pytest tests/test_rng_decorrelation.py tests/test_wolf_kill_rule.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: 零残留 grep**

Run（仓库根）: `grep -rn "rng_state" backend/app backend/tests; echo "exit=$?"`
Expected: 无输出、`exit=1`（零命中，含 docstring）。

- [ ] **Step 8: 全量门禁**

Run: `cd backend && uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 191 passed（189 + 2 新增；确定性 test_determinism 与 500 局 test_sweep 含在套件内）；mypy 无错误；ruff 两项干净。

- [ ] **Step 9: Commit**

```bash
git add backend/app/engine/engine.py backend/app/engine/events.py backend/app/engine/state.py backend/app/engine/rng.py backend/tests/test_wolf_kill_rule.py backend/tests/test_rng_decorrelation.py
git commit -m "fix(engine): 随机抽取 seq 改用 state_version 去相关，删除死 rng_state 机制 (issue #12)"
```
