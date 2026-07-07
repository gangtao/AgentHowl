# 警徽流结构校验 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 issue #7：`badge_flow` 仅在 `SHERIFF_PK` 发言回合接受、结构校验（激活死配置 `badge_flow_enabled` + 新 `badge_flow_max_length`）、记录为事实 `badge_flow_claims` 并在 observation 公开。

**Architecture:** 校验在 `_validate` 的 Speak 门内追加（非空 `badge_flow` → 语境 + 五项结构检查，违者 `BADGE_FLOW_INVALID`）；记录经既有 `PLAYER_SPOKE` reduce 扩展（payload 已携带，零新事件）；observation 加公开字段；bot 在 SHERIFF_PK 发言回合 1/4 概率附带合法声明使扫描覆盖。引擎只验结构、不验真实性/角色（悍跳合法）。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2）。命令在 `backend/` 下运行。

## Global Constraints

- **只验结构，绝不验真实性或真实角色**（悍跳是合法伪装）。
- 语境：M1 仅 `SHERIFF_PK` 发言回合可携带非空 `badge_flow`（`VOTE_PK`/`DAY_SPEECH`/`LAST_WORDS` 均拒）。
- 结构五检：`badge_flow_enabled`、`len <= badge_flow_max_length`（新配置，默认 2）、座位存在、座位存活、无重复。违者整条 Speak 拒绝（`BADGE_FLOW_INVALID`）。
- `badge_flow=()` 默认路径零行为变化；事实经既有事件 reduce（零新事件类型）。
- 全量回归（确定性、500 局扫描）必须通过；引擎零 IO；注释中文/标识符英文；mypy strict + ruff check + ruff format 干净。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/config.py` | `SheriffRule` +`badge_flow_max_length: int = 2` |
| `backend/app/engine/actions.py` | `RejectedReason` +`BADGE_FLOW_INVALID` |
| `backend/app/engine/state.py` | +`badge_flow_claims: dict[int, tuple[int, ...]]`（事实） |
| `backend/app/engine/events.py` | `PLAYER_SPOKE` reduce 扩展记录声明 |
| `backend/app/engine/engine.py` | Speak 门追加校验块 |
| `backend/app/engine/observation.py` | `PlayerObservation` +公开 `badge_flow_claims` |
| `backend/app/cli/bot.py` | SHERIFF_PK 发言 1/4 概率附带声明 |
| `backend/tests/test_badge_flow.py` | 新测试文件 |

---

### Task 1: 校验 + 记录（config/actions/state/events/engine）

**Files:**
- Modify: `backend/app/engine/config.py`（`SheriffRule`）
- Modify: `backend/app/engine/actions.py`（`RejectedReason`）
- Modify: `backend/app/engine/state.py`（`GameState` 事实字段）
- Modify: `backend/app/engine/events.py`（`PLAYER_SPOKE` reduce 分支）
- Modify: `backend/app/engine/engine.py`（`_validate` Speak 门）
- Test: `backend/tests/test_badge_flow.py`（新建）

**Interfaces:**
- Produces: `SheriffRule.badge_flow_max_length: int = 2`；`RejectedReason.BADGE_FLOW_INVALID`；`GameState.badge_flow_claims: dict[int, tuple[int, ...]] = {}`；`PLAYER_SPOKE` reduce 非空声明写 `{actor: badge_flow}`；Speak 门校验块。Task 2 依赖 `badge_flow_claims`。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_badge_flow.py`：
```python
"""警徽流（issue #7）：结构校验、事实记录与公开暴露。只验结构，不验真实性。"""

from app.engine.actions import RejectedReason, Speak
from app.engine.config import Faction, RoleType, SheriffRule, build_preset
from app.engine.engine import step
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, dead: tuple[int, ...] = ()) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
            alive=(i not in dead),
        )
        for i in range(n)
    )


def _pk_state(n: int = 6, dead: tuple[int, ...] = (), **kw: object) -> GameState:
    """SHERIFF_PK 发言回合：候选 (1,2)，轮到 1 发言。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_PK,
        "round": 1,
        "players": _players(n, dead=dead),
        "sheriff_candidates": (1, 2),
        "speech_order": (1, 2),
        "speech_idx": 0,
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_valid_claim_accepted_and_recorded() -> None:
    st = _pk_state()
    res = step(st, Speak(actor_seat=1, content="我是预言家", badge_flow=(3, 4)))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {1: (3, 4)}


def test_claim_overwritten_by_latest() -> None:
    st = _pk_state(badge_flow_claims={1: (5,)})
    res = step(st, Speak(actor_seat=1, content="改口", badge_flow=(3,)))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {1: (3,)}


def test_claim_rejected_outside_sheriff_pk() -> None:
    # DAY_SPEECH 携带非空声明 -> 拒
    st = _pk_state(phase=Phase.DAY_SPEECH, speech_order=(1, 2, 3), speech_idx=0)
    res = step(st, Speak(actor_seat=1, content="x", badge_flow=(3,)))
    assert res.rejection == RejectedReason.BADGE_FLOW_INVALID
    # 放逐 VOTE_PK 发言回合亦拒
    st2 = _pk_state(phase=Phase.VOTE_PK, vote_candidates=(1, 2), tie_round=1)
    res2 = step(st2, Speak(actor_seat=1, content="x", badge_flow=(3,)))
    assert res2.rejection == RejectedReason.BADGE_FLOW_INVALID


def test_structural_rejection_matrix() -> None:
    # 配置关闭
    cfg_off = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 6, "seed": 1, "sheriff": SheriffRule(badge_flow_enabled=False)}
    )
    st = _pk_state(config=cfg_off)
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 超长（默认 max=2）
    st = _pk_state()
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3, 4, 5))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 座位越界
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(99,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 座位已死
    st_dead = _pk_state(dead=(4,))
    assert (
        step(st_dead, Speak(actor_seat=1, content="x", badge_flow=(4,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 重复座位
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3, 3))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )


def test_empty_claim_unchanged() -> None:
    st = _pk_state()
    res = step(st, Speak(actor_seat=1, content="普通发言"))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_badge_flow.py -v`
Expected: FAIL（`badge_flow_claims` 字段不存在 / `BADGE_FLOW_INVALID` 不存在 / 校验缺失导致断言失败）。

- [ ] **Step 3: 实现**

`backend/app/engine/config.py` —— `SheriffRule` 追加字段（`badge_flow_enabled` 之后）：
```python
    badge_flow_max_length: int = 2  # 警徽流最多声明几夜（「一般留两夜」为约定，可配置）
```

`backend/app/engine/actions.py` —— `RejectedReason` 追加成员（`BIDDING_NOT_IMPLEMENTED` 附近）：
```python
    BADGE_FLOW_INVALID = "BADGE_FLOW_INVALID"
```

`backend/app/engine/state.py` —— `GameState` 追加事实字段（竞选字段区之后）：
```python
    badge_flow_claims: dict[int, tuple[int, ...]] = Field(default_factory=dict)
    # speaker -> 最新警徽流声明（事实；结构已校验，真实性不校验）
```

`backend/app/engine/events.py` —— `PLAYER_SPOKE` reduce 分支整体替换为：
```python
    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        spoke_upd: dict[str, object] = {"speech_idx": state.speech_idx + 1}
        if p.badge_flow:
            claims = dict(state.badge_flow_claims)
            claims[_actor(event)] = p.badge_flow
            spoke_upd["badge_flow_claims"] = claims
        return spoke_upd
```

`backend/app/engine/engine.py` —— `_validate` 的 Speak 门，在 BIDDING 检查之后、`return None` 之前插入：
```python
        if action.badge_flow:
            # 警徽流：仅 SHERIFF_PK 发言回合接受；只验结构，不验真实性/角色（悍跳合法）
            sr = state.config.sheriff
            if (
                not (state.phase == Phase.SHERIFF_PK and pk_speaking)
                or not sr.badge_flow_enabled
                or len(action.badge_flow) > sr.badge_flow_max_length
                or len(set(action.badge_flow)) != len(action.badge_flow)
                or not all(_alive_target(state, s) for s in action.badge_flow)
            ):
                return RejectedReason.BADGE_FLOW_INVALID
```
（`_alive_target` 对不存在座位返回 False，同时覆盖「越界」与「已死」。）

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_badge_flow.py -v && uv run pytest -q`
Expected: 新测试 PASS（5 项）；全量 173 tests 全绿（空声明路径零变化，确定性字节级不变——bot 尚未发声明）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine backend/tests/test_badge_flow.py
git commit -m "feat(engine): 警徽流结构校验与 badge_flow_claims 事实记录"
```

### Task 2: 暴露 + bot 覆盖

**Files:**
- Modify: `backend/app/engine/observation.py`（`PlayerObservation` + `build_observation`）
- Modify: `backend/app/cli/bot.py`（SHERIFF_PK 发言分支）
- Test: `backend/tests/test_badge_flow.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `badge_flow_claims` 事实与校验语义。
- Produces: `PlayerObservation.badge_flow_claims: dict[int, tuple[int, ...]]`（公开）；bot 在 SHERIFF_PK 发言回合 1/4 概率附带合法声明。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_badge_flow.py`：
```python
def test_claims_exposed_publicly_in_observation() -> None:
    from app.engine.observation import build_observation

    st = _pk_state(badge_flow_claims={1: (3, 4)})
    # 所有视角（含普通村民）都能看到公开声明
    obs = build_observation(st, 5)
    assert obs.badge_flow_claims == {1: (3, 4)}


def test_full_games_with_claims_terminate() -> None:
    from app.cli.bot import run_game
    from app.engine.events import EventType

    saw_claim = False
    for seed in range(12):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"bf{seed}")
        assert final.phase == Phase.GAME_OVER
        if any(
            e.type == EventType.PLAYER_SPOKE and getattr(e.payload, "badge_flow", ())
            for e in events
        ):
            saw_claim = True
    # 12 个 seed 中至少一次真实报出警徽流（SHERIFF_PK 发生且 1/4 概率命中）
    assert saw_claim
```

> 若 12 个 seed 恰好无一进入 SHERIFF_PK 或概率未命中导致 `saw_claim` 断言失败，把 range 扩到 20 并在报告注明（断言意图是「路径被真实覆盖」，seed 数量可调）。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_badge_flow.py::test_claims_exposed_publicly_in_observation -v`
Expected: FAIL（`PlayerObservation` 无 `badge_flow_claims` 字段）。

- [ ] **Step 3: 实现暴露**

`backend/app/engine/observation.py`：

(a) `PlayerObservation` 追加字段（`sheriff_seat` 之后）：
```python
    badge_flow_claims: dict[int, tuple[int, ...]]  # 公开的警徽流声明（speaker -> 座位序列）
```

(b) `build_observation` 的构造调用追加：
```python
        badge_flow_claims=dict(state.badge_flow_claims),
```

- [ ] **Step 4: bot 声明分支**

`backend/app/cli/bot.py` —— 把 PK 发言分支整体替换为：
```python
        if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):
            # PK 发言期：轮到的平票者发言；警上 PK 以 1/4 概率附带合法警徽流声明
            bf: tuple[int, ...] = ()
            if (
                ph == Phase.SHERIFF_PK
                and rng.derive_int(
                    seed=seed, purpose=f"bot:{seat}:bf", seq=state.state_version, modulo=4
                )
                == 0
            ):
                targets = [s for s in living_seats(state) if s != seat]
                if targets:
                    n_claim = 1 + rng.derive_int(
                        seed=seed, purpose=f"bot:{seat}:bfn", seq=state.state_version, modulo=2
                    )
                    picks: list[int] = []
                    for k in range(min(n_claim, len(targets))):
                        idx = rng.derive_int(
                            seed=seed,
                            purpose=f"bot:{seat}:bf{k}",
                            seq=state.state_version,
                            modulo=len(targets),
                        )
                        if targets[idx] not in picks:
                            picks.append(targets[idx])
                    bf = tuple(picks)
            return Speak(actor_seat=seat, content="(bot-pk)", badge_flow=bf)
```

- [ ] **Step 5: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_badge_flow.py -v && uv run pytest -q`
Expected: 全绿（175 tests；确定性、500 局扫描——bot 现在偶发报警徽流，若某 seed 因非法声明被拒说明 bot 生成器有 bug，检查 targets 均存活且去重、长度 ≤2）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 6: 提交**

```bash
git add backend/app/engine/observation.py backend/app/cli/bot.py backend/tests/test_badge_flow.py
git commit -m "feat(engine): 警徽流 observation 公开暴露与 bot 覆盖，闭环 issue #7"
```

---

## Self-Review

**Spec 覆盖**：§2 配置→Task 1（config）；§3 校验五检+语境+新枚举→Task 1（engine/actions + 拒绝矩阵测试）；§4 记录→Task 1（state/events + 记录/覆盖测试）；§5 暴露→Task 2（observation + 测试）；§6 bot→Task 2；§7 测试→两任务测试步骤 + 回归；§8 范围外无任务——正确。

**占位扫描**：无 TBD/TODO；`test_full_games_with_claims_terminate` 的 seed 数量调整指引是明确的执行指令而非占位。

**类型一致性**：`badge_flow_claims: dict[int, tuple[int, ...]]` 在 state/observation/tests 一致；`BADGE_FLOW_INVALID` 在 actions/engine/tests 一致；`badge_flow_max_length` 在 config/engine/tests 一致；Speak 门插入点引用的 `pk_speaking`/`_alive_target` 为 engine.py 既有名字。
