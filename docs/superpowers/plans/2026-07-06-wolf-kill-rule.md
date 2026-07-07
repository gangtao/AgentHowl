# 狼刀决策规则开关 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 issue #3：`wolf_kill_rule` GameConfig 开关（UNANIMOUS_OR_NO_KILL 默认 / MAJORITY / RANDOM_PROPOSAL），消除引擎最后一条硬编码规则。

**Architecture:** `config.py` 新增 `WolfKillRule` 枚举与字段（preset 继承默认，既有行为字节级不变）；`engine.py` 的 `_wolf_consensus` 改为按规则分派——一致制原样、相对多数（并列→空刀）、加权随机（既有 `rng.derive_int` 模式）。决策仍经 `WOLF_KILL_DECIDED` 事件流出，事件/reduce 零改动。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2）。命令在 `backend/` 下运行。

## Global Constraints

- 默认值下零行为变化：`test_determinism`（字节级）必须原样通过——这是本特性的核心回归门。
- 随机只走 `rng.derive_int(seed, purpose="wolf_kill", seq=state.rng_state, modulo=len(pool))`，池先排序（确定性）。
- MAJORITY：相对多数（唯一最高票）；None=空刀票同票计数；任何并列（含与空刀票并列）→ None。
- 引擎零 IO；注释中文/标识符英文；`uv run mypy app`（strict）+ `uv run ruff check .` + `uv run ruff format --check .` 全程干净。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/config.py` | +`WolfKillRule` 枚举、`GameConfig.wolf_kill_rule` 字段 |
| `backend/app/engine/engine.py` | `_wolf_consensus` 按规则分派（约 662 行；import 补 `WolfKillRule`） |
| `backend/tests/test_wolf_kill_rule.py` | 新测试文件（配置 + 三规则语义 + 集成） |

---

### Task 1: 配置 —— `WolfKillRule` 枚举与字段

**Files:**
- Modify: `backend/app/engine/config.py`
- Test: `backend/tests/test_wolf_kill_rule.py`（新建）

**Interfaces:**
- Produces: `WolfKillRule(StrEnum)` 三成员；`GameConfig.wolf_kill_rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL`。Task 2 经 `state.config.wolf_kill_rule` 消费。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_wolf_kill_rule.py`：
```python
"""狼刀决策规则开关（issue #3）：配置、三规则语义与集成。"""

from app.engine.config import GameConfig, WolfKillRule, build_preset


def test_wolf_kill_rule_enum_members() -> None:
    assert WolfKillRule.UNANIMOUS_OR_NO_KILL.value == "UNANIMOUS_OR_NO_KILL"
    assert WolfKillRule.MAJORITY.value == "MAJORITY"
    assert WolfKillRule.RANDOM_PROPOSAL.value == "RANDOM_PROPOSAL"


def test_default_is_unanimous_and_presets_inherit() -> None:
    assert GameConfig(config_id="x").wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
    for name in (
        "std_12_yn_hunter_idiot",
        "std_12_yn_hunter_guard",
        "std_9_kill_side",
        "std_9_kill_all",
    ):
        assert build_preset(name).wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_wolf_kill_rule.py -v`
Expected: FAIL（`ImportError: cannot import name 'WolfKillRule'`）。

- [ ] **Step 3: 实现**

`backend/app/engine/config.py` —— 在 `TieRule` 枚举之后追加：
```python
class WolfKillRule(StrEnum):
    UNANIMOUS_OR_NO_KILL = "UNANIMOUS_OR_NO_KILL"  # 全员一致才刀，否则空刀（默认）
    MAJORITY = "MAJORITY"  # 相对多数；并列（含与空刀票并列）→ 空刀
    RANDOM_PROPOSAL = "RANDOM_PROPOSAL"  # 非空提案多重集中加权随机
```
`GameConfig` 里，在 `allow_wolf_empty_knife` 与 `wolf_first_kill_priority` 之间插入字段：
```python
    wolf_kill_rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_wolf_kill_rule.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: 全量回归 + 门禁 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿（147 tests）。
```bash
git add backend/app/engine/config.py backend/tests/test_wolf_kill_rule.py
git commit -m "feat(engine): WolfKillRule 枚举与 wolf_kill_rule 配置字段"
```

### Task 2: 决策分派 —— `_wolf_consensus` 三规则 + 集成

**Files:**
- Modify: `backend/app/engine/engine.py`（`_wolf_consensus`，约 662 行；顶部 config import 补 `WolfKillRule`）
- Test: `backend/tests/test_wolf_kill_rule.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `WolfKillRule` / `wolf_kill_rule`；既有 `rng.derive_int`、`state.wolf_proposals`、`state.rng_state`。
- Produces: `_wolf_consensus(state) -> int | None` 语义扩展，签名与调用点（`WOLF_KILL_DECIDED` 发射处）不变。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_wolf_kill_rule.py`：
```python
from app.engine import rng
from app.engine.config import Faction, RoleType
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _wolf_state(proposals: dict[int, int | None], rule: WolfKillRule, seed: int = 1) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": seed, "wolf_kill_rule": rule}
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
        wolf_proposals=proposals,
    )


def test_unanimous_agree_kills_disagree_or_skip_no_kill() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.UNANIMOUS_OR_NO_KILL
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 5}, rule)) == 5
    assert _wolf_consensus(_wolf_state({0: 5, 1: 6, 2: 5}, rule)) is None
    assert _wolf_consensus(_wolf_state({0: 5, 1: None, 2: 5}, rule)) is None


def test_majority_plurality_wins_tie_no_kill() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.MAJORITY
    # 3-1（4 狼场景不必真实：直接构造 4 票提案）
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 5, 3: 6}, rule)) == 5
    # 2-2 并列 -> 空刀
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 6, 3: 6}, rule)) is None
    # 空刀票占多 -> 空刀
    assert _wolf_consensus(_wolf_state({0: None, 1: None, 2: 5}, rule)) is None
    # 2-1-1 -> 相对多数胜
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 6, 3: 7}, rule)) == 5
    # 目标票与空刀票并列 -> 空刀
    assert _wolf_consensus(_wolf_state({0: 5, 1: None}, rule)) is None


def test_random_proposal_weighted_and_deterministic() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.RANDOM_PROPOSAL
    st = _wolf_state({0: 4, 1: 4, 2: 7}, rule, seed=42)
    # 池 = sorted([4, 4, 7])；与实现同公式独立计算期望值，钉死派生契约
    pool = [4, 4, 7]
    idx = rng.derive_int(seed=42, purpose="wolf_kill", seq=st.rng_state, modulo=3)
    assert _wolf_consensus(st) == pool[idx]
    # 同 seed 可复现
    assert _wolf_consensus(st) == _wolf_consensus(st)
    # 全 skip -> 空刀
    assert _wolf_consensus(_wolf_state({0: None, 1: None, 2: None}, rule, seed=42)) is None


def test_nondefault_rules_full_games_terminate() -> None:
    from app.cli.bot import run_game

    for rule in (WolfKillRule.MAJORITY, WolfKillRule.RANDOM_PROPOSAL):
        for seed in (3, 11):
            cfg = build_preset("std_9_kill_side").model_copy(
                update={"seed": seed, "wolf_kill_rule": rule}
            )
            final, _events = run_game(cfg, game_id=f"wk-{rule.value}-{seed}")
            assert final.phase == Phase.GAME_OVER
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_wolf_kill_rule.py -v`
Expected: MAJORITY/RANDOM 用例 FAIL（现实现忽略规则、一律一致制）；UNANIMOUS 用例已通过。

- [ ] **Step 3: 实现分派**

`backend/app/engine/engine.py` —— 顶部 `from app.engine.config import ...` 增加 `WolfKillRule`；用下面整体替换 `_wolf_consensus`：
```python
def _wolf_consensus(state: GameState) -> int | None:
    """按 config.wolf_kill_rule 从狼队提案决定刀口（None=空刀）。"""
    proposals = state.wolf_proposals
    rule = state.config.wolf_kill_rule

    if rule == WolfKillRule.MAJORITY:
        # 相对多数；空刀票(None)同票计数；任何并列（含与空刀票并列）-> 空刀
        counts: dict[int | None, int] = {}
        for t in proposals.values():
            counts[t] = counts.get(t, 0) + 1
        if not counts:
            return None
        top = max(counts.values())
        leaders = [t for t in counts if counts[t] == top]
        if len(leaders) == 1 and leaders[0] is not None:
            return leaders[0]
        return None

    if rule == WolfKillRule.RANDOM_PROPOSAL:
        # 非 None 提案多重集（同目标多票权重更高），排序后确定性抽取
        pool = sorted(t for t in proposals.values() if t is not None)
        if not pool:
            return None
        seed = state.config.seed if state.config.seed is not None else 0
        idx = rng.derive_int(
            seed=seed, purpose="wolf_kill", seq=state.rng_state, modulo=len(pool)
        )
        return pool[idx]

    # UNANIMOUS_OR_NO_KILL（默认）：全员一致且非 None 才刀
    vals = set(proposals.values())
    if len(vals) == 1 and None not in vals:
        return next(iter(vals))
    return None
```
> 说明：MAJORITY 的 `leaders` 无需排序——只在 `len(leaders) == 1` 时使用其唯一元素，多元素一律返回 None，结果与迭代顺序无关（确定性由值而非顺序保证）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_wolf_kill_rule.py -v`
Expected: PASS（6 项，含 2 规则 × 2 seed 完整对局）。

- [ ] **Step 5: 全量回归（核心门：默认值字节级不变）+ 提交**

Run:
```bash
uv run pytest -q
uv run mypy app && uv run ruff check . && uv run ruff format --check .
```
Expected: 全绿（151 tests；`test_determinism` 字节级一致即证明默认行为零变化）。
```bash
git add backend/app/engine/engine.py backend/tests/test_wolf_kill_rule.py
git commit -m "feat(engine): _wolf_consensus 按 wolf_kill_rule 分派（一致/多数/加权随机），闭环 issue #3"
```

---

## Self-Review

**Spec 覆盖**：§2 配置→Task 1；§3 三规则语义（含并列→空刀、加权池、排序确定性）→Task 2 Step 3；§4 交互（不改校验层）→无需任务，Task 2 不触碰 `_validate_night`；§5 测试→两任务测试步骤（配置继承、三规则矩阵、随机契约、集成、回归）；§6 范围外无任务——正确。

**占位扫描**：无 TBD/TODO；每步含完整代码与期望输出。

**类型一致性**：`WolfKillRule` 名称/成员在 config、engine、测试三处一致；`_wolf_consensus(state) -> int | None` 签名不变；`rng.derive_int(seed, purpose, seq, modulo)` 与既有 `rng.py` 签名一致（关键字调用）。
