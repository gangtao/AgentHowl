# 狼队刀口收敛（可见提案 + 收敛轮）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复狼队频繁空刀（issue #46）：让狼在夜间看到队友本轮提案，不一致时引擎再开一轮（最多 `wolf_consensus_rounds` 轮），末轮按 `wolf_kill_rule` 兜底；prompt 引导跟刀；CLI 提供规则旋钮。

**Architecture:** 引擎新增 `WOLF_KILL_REVOTE`（WOLVES 可见）事件与两个事件推导的状态字段（`wolf_kill_round`、`wolf_proposal_history`）；`_system_transition` 的狼收尾在「裁决为空刀 ∧ 有非空提案 ∧ 轮次未用尽」时发 REVOTE 而非 DECIDED。observation 给存活狼暴露本轮提案/历史/轮次；agent prompt、记忆渲染、CLI 渲染与旋钮随之适配。任务顺序：契约（配置+状态+事件）→ 引擎转移 → observation → agent → CLI。

**Tech Stack:** Python 3.11、Pydantic v2、pytest；`uv` 管理。全部命令在 `backend/` 下执行。

**Spec:** `docs/superpowers/specs/2026-09-18-wolf-consensus-design.md`（执行者须同时阅读）

## Global Constraints

- 引擎（`backend/app/engine/`）纯函数零 IO，不得 import 网络/DB/LLM/runtime/cli/agent 代码。
- 一切状态变更经 append-only Event；`state = reduce(events)`。新增字段 `wolf_kill_round` / `wolf_proposal_history` **只能**由 reduce 写入（`ROUND_STARTED` 重置、`WOLF_KILL_REVOTE` 推进），禁止 `model_copy` 直写。
- 一切随机走 seeded RNG；`_wolf_consensus` 的 `RANDOM_PROPOSAL` 分支 RNG purpose `"wolf_kill"`、`seq=state.state_version` 不得改动。
- 无硬编码规则：`wolf_consensus_rounds`（默认 2，≥1）、`wolf_kill_rule`（默认不变 `UNANIMOUS_OR_NO_KILL`）均为 `GameConfig` 开关；`wolf_consensus_rounds=1` 时事件序列与改动前逐字节一致。
- 信息隔离是服务端边界：新 observation 字段只给**存活狼**；`WOLF_KILL_REVOTE` 可见性 `WOLVES`。
- 狼夜私有推理与公开发言分开调用：`build_wolf_night_prompt` 仍是唯一接收 `night_private` 的装配函数，`build_prompt` 签名不变。
- 文档与代码注释用中文；标识符、API 名、schema 用英文。注释密度与周边代码一致。ruff 行宽 100 且中文按宽 2 计。
- 引擎测试零 IO、零 mock；确定性测试用固定 `seed`。
- 每个任务结束时：`uv run pytest -q -x --ignore=tests/test_api_e2e.py` 全绿、`uv run ruff check .`（须为 All checks passed!）、`uv run ruff format --check .`、`uv run mypy app` 全过（最后一个任务跑含 E2E 的 `uv run pytest -q`）。
- commit message 风格 `feat(engine): … (issue #46)`，结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `backend/app/engine/config.py` | `wolf_consensus_rounds` 字段 + 校验 | 1 |
| `backend/app/engine/state.py` | `wolf_kill_round`、`wolf_proposal_history` | 1 |
| `backend/app/engine/events.py` | `WOLF_KILL_REVOTE` 枚举/载荷/映射；reduce（REVOTE 推进、ROUND_STARTED 重置） | 1 |
| `backend/app/engine/engine.py` | `_system_transition` 狼收尾的重提分支 | 2 |
| `backend/app/engine/observation.py` | 狼夜 private 新字段 | 3 |
| `backend/app/agent/prompts.py`、`memory.py` | 狼夜 prompt 改读新字段 + 跟刀/重提引导；REVOTE 渲染与打分 | 4 |
| `backend/app/cli/render.py`、`play.py`、`Makefile`、`README.md` | REVOTE/观察渲染；`--wolf-rule` `--wolf-rounds`；文档 | 5 |
| `docs/specs/requirements.md` | §3.2 `wolf_consensus_rounds`、§4.2 狼夜可见字段、§6.4 事件清单 | 3（§3.2/§4.2）、1（§6.4） |
| `backend/tests/test_wolf_consensus.py`（新建） | 本特性引擎测试 | 1–3 |

---

### Task 1: 契约层——配置、状态字段、`WOLF_KILL_REVOTE` 事件与 reduce（引擎尚不发射）

**Files:**
- Modify: `backend/app/engine/config.py`（`GameConfig` 约 line 141 `wolf_kill_rule` 之后；`validate_config` 约 line 229）
- Modify: `backend/app/engine/state.py`（约 line 66 `wolf_proposals` 之后）
- Modify: `backend/app/engine/events.py`（`EventType` 枚举末尾约 line 66；`WolfKillDecidedPayload` 之后约 line 113；`EVENT_PAYLOAD_TYPES` 约 line 245；reduce 的 `ROUND_STARTED` 分支约 line 336、`WOLF_KILL_DECIDED` 分支之后约 line 377）
- Modify: `docs/specs/requirements.md`（§6.4 事件清单，约 line 713）
- Create: `backend/tests/test_wolf_consensus.py`

**Interfaces:**
- Produces:
  - `GameConfig.wolf_consensus_rounds: int = 2`；`validate_config` 对 `< 1` 抛 `ConfigError`
  - `GameState.wolf_kill_round: int = 1`、`GameState.wolf_proposal_history: tuple[tuple[tuple[int, int | None], ...], ...] = ()`
  - `EventType.WOLF_KILL_REVOTE`；`WolfKillRevotePayload(round_no: int, proposals: tuple[tuple[int, int | None], ...])`
  - reduce：REVOTE → `wolf_proposals={}`、`wolf_kill_round+1`、`history+(proposals,)`；ROUND_STARTED → `wolf_kill_round=1`、`wolf_proposal_history=()`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_wolf_consensus.py`：

```python
"""狼队刀口收敛（issue #46）：可见提案、收敛轮、末轮兜底、回放保真。"""

import pytest

from app.engine.config import (
    ConfigError,
    Faction,
    GameConfig,
    RoleType,
    WolfKillRule,
    build_preset,
    validate_config,
)
from app.engine.events import (
    Event,
    EventType,
    RoundStartedPayload,
    Visibility,
    WolfKillRevotePayload,
    reduce,
)
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player

WOLVES = (0, 1, 2)


def _players(n: int = 9, wolves: tuple[int, ...] = WOLVES) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(
    proposals: dict[int, int | None] | None = None,
    rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL,
    rounds: int = 2,
    seed: int = 1,
    **kw: object,
) -> GameState:
    """夜间狼阶段状态：3 狼 6 民；proposals 为本轮已提交的提案。"""
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"seed": seed, "wolf_kill_rule": rule, "wolf_consensus_rounds": rounds}
    )
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.NIGHT_WEREWOLF,
        "round": 1,
        "players": _players(),
        "wolf_proposals": dict(proposals or {}),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _evt(etype: EventType, payload: object, vis: Visibility = Visibility.WOLVES) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=etype,
        actor_seat=None,
        payload=payload,  # type: ignore[arg-type]
        visibility=vis,
    )


# ---------- Task 1：契约 ----------


def test_config_default_and_validation() -> None:
    assert GameConfig(config_id="x").wolf_consensus_rounds == 2
    for name in ("std_12_yn_hunter_idiot", "std_9_kill_side"):
        assert build_preset(name).wolf_consensus_rounds == 2
    with pytest.raises(ConfigError, match="wolf_consensus_rounds"):
        validate_config(build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 0}))
    validate_config(build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 1}))


def test_state_defaults() -> None:
    st = _state()
    assert st.wolf_kill_round == 1
    assert st.wolf_proposal_history == ()


def test_reduce_revote_clears_proposals_and_records_history() -> None:
    st = _state({0: 8, 1: 3, 2: 8})
    snapshot = ((0, 8), (1, 3), (2, 8))
    new = reduce(st, _evt(EventType.WOLF_KILL_REVOTE, WolfKillRevotePayload(round_no=1, proposals=snapshot)))
    assert new.wolf_proposals == {}
    assert new.wolf_kill_round == 2
    assert new.wolf_proposal_history == (snapshot,)
    assert new.acted_seats == st.acted_seats  # 其他角色的已行动记录不受影响
    assert st.wolf_proposals == {0: 8, 1: 3, 2: 8}  # 纯函数：原状态不变
    # 狼重新成为行动者
    assert expected_actors(new) == set(WOLVES)


def test_reduce_round_started_resets_round_and_history() -> None:
    st = _state(wolf_kill_round=3, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    new = reduce(st, _evt(EventType.ROUND_STARTED, RoundStartedPayload(round=2), Visibility.PUBLIC))
    assert new.wolf_kill_round == 1
    assert new.wolf_proposal_history == ()
    assert new.wolf_proposals == {}


def test_revote_payload_is_mapped_for_fail_loud_reduce() -> None:
    from app.engine.events import EVENT_PAYLOAD_TYPES

    assert EVENT_PAYLOAD_TYPES[EventType.WOLF_KILL_REVOTE] is WolfKillRevotePayload
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_wolf_consensus.py -q`
Expected: 收集期 `ImportError: cannot import name 'WolfKillRevotePayload'`

- [ ] **Step 3: 实现**

`app/engine/config.py`——`GameConfig` 里 `wolf_kill_rule` 之后加：

```python
    wolf_consensus_rounds: int = 2  # 狼队提案最多几轮（issue #46）；不一致则重提；1 = 一轮定夺
```

`validate_config` 末尾（`night_order 必须包含狼人` 校验之后）加：

```python
    if config.wolf_consensus_rounds < 1:
        raise ConfigError(f"wolf_consensus_rounds 须 ≥ 1，收到 {config.wolf_consensus_rounds}")
```

`app/engine/state.py`——`wolf_proposals` 之后加：

```python
    wolf_kill_round: int = 1  # 本夜第几轮狼队提案（issue #46；WOLF_KILL_REVOTE 推进，ROUND_STARTED 重置）
    # 之前各轮的提案快照（每轮为按座位升序的 (seat, target) 元组）
    wolf_proposal_history: tuple[tuple[tuple[int, int | None], ...], ...] = ()
```

`app/engine/events.py`——`EventType` 末尾加 `WOLF_KILL_REVOTE = "WOLF_KILL_REVOTE"`；`WolfKillDecidedPayload` 之后加：

```python
class WolfKillRevotePayload(EventPayload):
    """狼队本轮意见不一致、再开一轮（issue #46）。快照随事件入流，回放不必重建。"""

    round_no: int  # 刚结束的那一轮（从 1 起）
    proposals: tuple[tuple[int, int | None], ...]  # 该轮提案快照，按座位升序
```

`EVENT_PAYLOAD_TYPES` 里 `WOLF_KILL_DECIDED` 之后加 `EventType.WOLF_KILL_REVOTE: WolfKillRevotePayload,`。

reduce：`ROUND_STARTED` 分支的返回 dict 里，`"wolf_proposals": {},` 之后加两行：

```python
            "wolf_kill_round": 1,
            "wolf_proposal_history": (),
```

`WOLF_KILL_DECIDED` 分支之后加：

```python
    if t == EventType.WOLF_KILL_REVOTE and isinstance(p, WolfKillRevotePayload):
        return {
            "wolf_proposals": {},
            "wolf_kill_round": state.wolf_kill_round + 1,
            "wolf_proposal_history": (*state.wolf_proposal_history, p.proposals),
        }
```

`docs/specs/requirements.md` §6.4 事件清单里，在 `WOLF_KILL_DECIDED(GM_ONLY)` 之后插入 `WOLF_KILL_REVOTE(WOLVES)`。

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `uv run pytest tests/test_wolf_consensus.py tests/test_wolf_kill_rule.py tests/test_fail_loud.py tests/test_event_store.py tests/test_determinism.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿（引擎尚不发射 REVOTE，行为零变化）

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/config.py backend/app/engine/state.py backend/app/engine/events.py backend/tests/test_wolf_consensus.py docs/specs/requirements.md
git commit -m "feat(engine): 狼队收敛轮契约层——wolf_consensus_rounds、WOLF_KILL_REVOTE 事件与状态字段 (issue #46)"
```

---

### Task 2: 引擎——狼收尾的重提分支

**Files:**
- Modify: `backend/app/engine/engine.py`（`_system_transition` 的 `NIGHT_WEREWOLF` 收尾，约 line 833-840；`_wolf_consensus` 附近加 helper）
- Test: `backend/tests/test_wolf_consensus.py`

**Interfaces:**
- Consumes: Task 1 全部。
- Produces: 引擎行为——全部狼提完后，`_wolf_consensus` 为 `None` ∧ 存在非 `None` 提案 ∧ `wolf_kill_round < wolf_consensus_rounds` → 发 `WOLF_KILL_REVOTE`（WOLVES）并停在狼阶段；否则发 `WOLF_KILL_DECIDED` 照旧。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_wolf_consensus.py` 末尾：

```python
# ---------- Task 2：引擎重提 ----------


def _propose(st: GameState, seat: int, target: int | None):
    from app.engine.actions import NightAction, NightActionType
    from app.engine.engine import step

    if target is None:
        a = NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
    else:
        a = NightAction(actor_seat=seat, action_type=NightActionType.KILL, target_seat=target)
    res = step(st, a)
    assert res.rejection is None, res.rejection
    return res


def _types(events: list[Event]) -> list[EventType]:
    return [e.type for e in events]


def test_unanimous_first_round_decides_without_revote() -> None:
    st = _state({0: 8, 1: 8})
    res = _propose(st, 2, 8)
    types = _types(res.events)
    assert EventType.WOLF_KILL_REVOTE not in types
    assert EventType.WOLF_KILL_DECIDED in types
    assert res.state.pending_night.wolf_target == 8
    assert res.state.phase != Phase.NIGHT_WEREWOLF


def test_disagreement_triggers_revote_then_second_round_decides() -> None:
    st = _state({0: 8, 1: 3})
    res = _propose(st, 2, 8)  # 8,3,8 -> UNANIMOUS 不一致
    revotes = [e for e in res.events if e.type == EventType.WOLF_KILL_REVOTE]
    assert len(revotes) == 1
    p = revotes[0].payload
    assert isinstance(p, WolfKillRevotePayload)
    assert p.round_no == 1 and p.proposals == ((0, 8), (1, 3), (2, 8))
    assert revotes[0].visibility == Visibility.WOLVES
    assert EventType.WOLF_KILL_DECIDED not in _types(res.events)
    st2 = res.state
    assert st2.phase == Phase.NIGHT_WEREWOLF
    assert st2.wolf_proposals == {} and st2.wolf_kill_round == 2
    assert st2.wolf_proposal_history == (((0, 8), (1, 3), (2, 8)),)
    assert expected_actors(st2) == set(WOLVES)
    # 第二轮统一 -> 出刀
    st2 = _propose(st2, 0, 8).state
    st2 = _propose(st2, 1, 8).state
    res2 = _propose(st2, 2, 8)
    assert EventType.WOLF_KILL_DECIDED in _types(res2.events)
    assert res2.state.pending_night.wolf_target == 8


def test_last_round_disagreement_falls_back_to_rule() -> None:
    # rounds=2：第二轮仍不一致 -> 空刀，不再重提
    st = _state({0: 8, 1: 3}, wolf_kill_round=2, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    res = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    decided = [e for e in res.events if e.type == EventType.WOLF_KILL_DECIDED]
    assert len(decided) == 1 and decided[0].payload.target is None  # type: ignore[attr-defined]


def test_three_rounds_allow_two_revotes() -> None:
    st = _state({0: 8, 1: 3}, rounds=3)
    r1 = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE in _types(r1.events)
    s = r1.state
    s = _propose(s, 0, 8).state
    s = _propose(s, 1, 3).state
    r2 = _propose(s, 2, 8)
    assert EventType.WOLF_KILL_REVOTE in _types(r2.events)
    assert r2.state.wolf_kill_round == 3
    assert len(r2.state.wolf_proposal_history) == 2
    s = r2.state
    s = _propose(s, 0, 8).state
    s = _propose(s, 1, 3).state
    r3 = _propose(s, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(r3.events)
    assert EventType.WOLF_KILL_DECIDED in _types(r3.events)


def test_all_skip_is_not_disagreement() -> None:
    st = _state({0: None, 1: None})
    res = _propose(st, 2, None)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target is None


def test_rounds_one_matches_legacy_behavior() -> None:
    st = _state({0: 8, 1: 3}, rounds=1)
    res = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target is None


def test_random_rule_never_revotes_and_majority_only_on_tie() -> None:
    res = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.RANDOM_PROPOSAL), 2, 5)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target in (3, 5, 8)

    clear = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.MAJORITY), 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(clear.events)
    assert clear.state.pending_night.wolf_target == 8

    tie = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.MAJORITY), 2, 5)  # 8,3,5 三方并列
    assert EventType.WOLF_KILL_REVOTE in _types(tie.events)


def test_stepwise_replay_equals_live_across_revote() -> None:
    from app.engine.events import reduce_all

    st = _state({0: 8, 1: 3})
    blank = st.model_copy(update={"wolf_proposals": {}})
    events: list[Event] = []
    # 让 blank 与 st 起点一致：先把 0/1 的提案作为事件重放进 blank
    from app.engine.events import WolfKillProposedPayload

    for seat, tgt in ((0, 8), (1, 3)):
        e = Event(
            seq=len(events) + 1,
            game_id="g",
            ts=1.0,
            type=EventType.WOLF_KILL_PROPOSED,
            actor_seat=seat,
            payload=WolfKillProposedPayload(wolf_seat=seat, target=tgt),
            visibility=Visibility.WOLVES,
        )
        events.append(e)
    live = reduce_all(blank, events)
    assert live.wolf_proposals == st.wolf_proposals
    for seat, tgt in ((2, 8), (0, 8), (1, 8), (2, 8)):
        r = _propose(live, seat, tgt)
        live, events = r.state, [*events, *r.events]
        replayed = reduce_all(blank, events)
        assert replayed.wolf_proposals == live.wolf_proposals
        assert replayed.wolf_kill_round == live.wolf_kill_round
        assert replayed.wolf_proposal_history == live.wolf_proposal_history
        assert replayed.pending_night.wolf_target == live.pending_night.wolf_target


def test_full_games_terminate_and_revote_occurs() -> None:
    from app.cli.bot import run_game

    saw_revote = False
    for preset in ("std_12_yn_hunter_idiot", "std_9_kill_side", "std_9_kill_all"):
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            final, events = run_game(cfg, "g")
            assert final.phase == Phase.GAME_OVER
            saw_revote = saw_revote or any(e.type == EventType.WOLF_KILL_REVOTE for e in events)
    assert saw_revote  # 随机 bot 几乎必然出现分歧
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_wolf_consensus.py -q`
Expected: Task 2 段中 `test_disagreement_*`、`test_three_rounds_*`、`test_random_rule_*`（MAJORITY 并列分支）、`test_stepwise_replay_*`、`test_full_games_*` FAIL（无 REVOTE 事件）；其余（一致/全空刀/rounds=1/末轮）已 PASS

- [ ] **Step 3: 实现**

`app/engine/engine.py` import 块加入 `WolfKillRevotePayload`（`WolfKillProposedPayload` 旁）。

在 `_wolf_consensus` 之后加：

```python
def _wolf_revote_pending(state: GameState) -> bool:
    """狼队本轮裁决为空刀但存在非空提案且轮次未用尽 -> 再开一轮（issue #46）。
    全员主动空刀不算分歧；RANDOM_PROPOSAL 有非空提案必出结果、天然不重提。"""
    if state.wolf_kill_round >= state.config.wolf_consensus_rounds:
        return False
    if not any(t is not None for t in state.wolf_proposals.values()):
        return False
    return _wolf_consensus(state) is None
```

`_system_transition` 的狼收尾替换为：

```python
        if ph == Phase.NIGHT_WEREWOLF:
            if _wolf_revote_pending(state):
                # 意见不一致：清空提案再开一轮，狼重新成为行动者，advance 循环在此停下
                state, e = _emit(
                    state,
                    EventType.WOLF_KILL_REVOTE,
                    WolfKillRevotePayload(
                        round_no=state.wolf_kill_round,
                        proposals=tuple(sorted(state.wolf_proposals.items())),
                    ),
                    Visibility.WOLVES,
                )
                return state, [e]
            state, e = _emit(
                state,
                EventType.WOLF_KILL_DECIDED,
                WolfKillDecidedPayload(target=_wolf_consensus(state)),
                Visibility.GM_ONLY,
            )
            events.append(e)
```

（`return state, [e]` 早退：`advance` 循环下一次检查 `expected_actors` 非空即停止，不会误入 `next_night_phase`。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_wolf_consensus.py tests/test_wolf_kill_rule.py tests/test_night_resolution.py tests/test_wolf_first.py tests/test_determinism.py tests/test_sweep.py tests/test_runtime_defaults.py tests/test_game_runner.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿。若 `test_isolation.py::test_every_visibility_class_filtered_correctly` 之类按事件类型枚举可见性的用例因新类型失败，把 `WOLF_Kill_REVOTE` 归入 `WOLVES` 可见性组即可（与 `WOLF_KILL_PROPOSED` 同组）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/engine.py backend/tests/
git commit -m "feat(engine): 狼队意见不一致时再开一轮提案，末轮按 wolf_kill_rule 兜底 (issue #46)"
```

---

### Task 3: observation——狼夜可见本轮提案、历史与轮次

**Files:**
- Modify: `backend/app/engine/observation.py`（`build_observation` 狼分支，约 line 59-63）
- Modify: `docs/specs/requirements.md`（§3.2 `GameConfig` 加 `wolf_consensus_rounds`，约 line 186 `allow_wolf_empty_knife` 之后；§4.2 line 450 狼可见字段）
- Test: `backend/tests/test_wolf_consensus.py`、`backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: Task 1 的状态字段。
- Produces: 存活狼的 `obs.private` 含 `tonight_kill_proposals: dict[int, int | None]`、`kill_proposal_history: list[dict[int, int | None]]`、`kill_vote_round: int`、`kill_vote_rounds_max: int`；非狼/死狼不含。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_wolf_consensus.py` 末尾：

```python
# ---------- Task 3：observation ----------


def test_wolf_sees_current_round_proposals_history_and_round() -> None:
    from app.engine.observation import build_observation

    st = _state({0: 8}, wolf_kill_round=2, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    obs = build_observation(st, 1)
    priv = obs.private
    assert priv["tonight_kill_proposals"] == {0: 8}
    assert priv["kill_proposal_history"] == [{0: 8, 1: 3, 2: 8}]
    assert priv["kill_vote_round"] == 2 and priv["kill_vote_rounds_max"] == 2
    assert "tonight_kill_proposal" not in priv  # 裁决前无刀口


def test_wolf_fields_present_even_when_no_proposal_yet() -> None:
    from app.engine.observation import build_observation

    priv = build_observation(_state(), 0).private
    assert priv["tonight_kill_proposals"] == {}
    assert priv["kill_proposal_history"] == []
    assert priv["kill_vote_round"] == 1


def test_non_wolf_and_dead_wolf_do_not_see_proposals() -> None:
    from app.engine.observation import build_observation

    st = _state({0: 8, 1: 3})
    for seat in (3, 4, 8):
        priv = build_observation(st, seat).private
        for key in ("tonight_kill_proposals", "kill_proposal_history", "kill_vote_round"):
            assert key not in priv
    dead = st.model_copy(
        update={"players": tuple(p.model_copy(update={"alive": False}) if p.seat == 2 else p for p in st.players)}
    )
    priv = build_observation(dead, 2).private
    assert "tonight_kill_proposals" not in priv and "teammates" not in priv
```

追加到 `backend/tests/test_isolation.py` 的 `test_non_wolf_has_no_teammates_or_chat`（约 line 23-30）循环体内，紧跟现有两条断言：

```python
            assert "tonight_kill_proposals" not in obs.private
            assert "kill_proposal_history" not in obs.private
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_wolf_consensus.py -k "sees_current_round or no_proposal_yet" -q`
Expected: FAIL（`KeyError: 'tonight_kill_proposals'`）；`test_non_wolf_*` 与 isolation 用例已 PASS

- [ ] **Step 3: 实现**

`app/engine/observation.py` 狼分支替换为：

```python
        if me.faction == Faction.WOLF:
            private["teammates"] = sorted(w.seat for w in living_wolves(state) if w.seat != seat)
            private["wolf_chat"] = []  # M1 无私聊内容；结构预留
            # 狼队本轮提案与收敛轮信息（issue #46）：后手狼据此跟刀，重提轮据此看分歧
            private["tonight_kill_proposals"] = dict(sorted(state.wolf_proposals.items()))
            private["kill_proposal_history"] = [dict(r) for r in state.wolf_proposal_history]
            private["kill_vote_round"] = state.wolf_kill_round
            private["kill_vote_rounds_max"] = state.config.wolf_consensus_rounds
            if state.pending_night.wolf_target is not None:
                private["tonight_kill_proposal"] = state.pending_night.wolf_target
```

`docs/specs/requirements.md`：
- §3.2 `GameConfig` 的 `allow_wolf_empty_knife: bool = True      # 允许空刀` 之后加一行 `wolf_consensus_rounds: int = 2           # 狼队提案最多几轮，不一致则重提（1=一轮定夺）`。
- §4.2 line 450 改为：`` - **狼人**：`private.teammates = [座号...]`；`private.wolf_chat = [...]`（狼队夜间私聊，预留）；夜晚可见 `private.tonight_kill_proposals`（本轮队友已提案 `{seat: target|null}`）、`kill_proposal_history`（之前各轮快照）、`kill_vote_round` / `kill_vote_rounds_max`；裁决后可见 `private.tonight_kill_proposal`（刀口）。 ``

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_wolf_consensus.py tests/test_isolation.py tests/test_observation_fields.py tests/test_api_ws.py tests/test_acceptance_m25.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/observation.py backend/tests/test_wolf_consensus.py backend/tests/test_isolation.py docs/specs/requirements.md
git commit -m "feat(engine): 狼夜 observation 暴露本轮队友提案、历史与收敛轮次 (issue #46)"
```

---

### Task 4: Agent 层——狼夜 prompt 跟刀/重提引导、记忆渲染与打分

**Files:**
- Modify: `backend/app/agent/prompts.py`（`build_wolf_night_prompt`，约 line 158-182）
- Modify: `backend/app/agent/memory.py`（`_SCORE_2` 约 line 67；`_render` 约 line 96-109）
- Test: `backend/tests/test_agent_prompts.py`、`backend/tests/test_agent_memory.py`

**Interfaces:**
- Consumes: Task 3 的 `obs.private` 字段（缺失时按空处理，prompt 装配不得因旧观察缺键而崩）；Task 1 的 `WolfKillRevotePayload`。
- Produces: `build_wolf_night_prompt` 输出含队友提案行与跟刀引导；重提轮含轮次与上一轮分歧；`memory._render` 对 REVOTE 输出可读中文；REVOTE 打 2 分。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_agent_prompts.py` 末尾（复用文件里的 `_obs`，其 `private` 可经 kw 覆盖）：

```python
def test_wolf_prompt_lists_teammate_proposals_and_follow_guidance() -> None:
    obs = _obs(
        "NIGHT_WEREWOLF",
        private={
            "teammates": [4, 7],
            "tonight_kill_proposals": {4: 8, 7: None},
            "kill_proposal_history": [],
            "kill_vote_round": 1,
            "kill_vote_rounds_max": 2,
        },
    )
    up = build_wolf_night_prompt(obs, "", "", agent_seed=1)
    assert "4 号提议刀 8 号" in up and "7 号提议空刀" in up
    assert "跟刀" in up and "全员一致" in up
    assert "上一轮" not in up


def test_wolf_prompt_revote_round_shows_disagreement() -> None:
    obs = _obs(
        "NIGHT_WEREWOLF",
        private={
            "teammates": [4, 7],
            "tonight_kill_proposals": {},
            "kill_proposal_history": [{0: 8, 4: 3, 7: 8}],
            "kill_vote_round": 2,
            "kill_vote_rounds_max": 2,
        },
    )
    up = build_wolf_night_prompt(obs, "", "", agent_seed=1)
    assert "第 2/2 轮" in up and "上一轮" in up
    assert "0 号→8 号" in up and "4 号→3 号" in up
    assert "末轮" in up


def test_wolf_prompt_tolerates_missing_new_fields() -> None:
    up = build_wolf_night_prompt(_obs("NIGHT_WEREWOLF"), "", "", agent_seed=1)
    assert "队友" in up and "提议" not in up
```

追加到 `backend/tests/test_agent_memory.py` 末尾（照该文件里构造 `Event` 与调用 `_render` 的既有写法；若无 `_render` 直测先例则 `from app.agent.memory import _render, _score`）：

```python
def test_render_and_score_wolf_kill_revote() -> None:
    from app.agent.memory import _render, _score
    from app.engine.events import Event, EventType, Visibility, WolfKillRevotePayload

    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.WOLF_KILL_REVOTE,
        actor_seat=None,
        payload=WolfKillRevotePayload(round_no=1, proposals=((0, 8), (1, None), (2, 8))),
        visibility=Visibility.WOLVES,
    )
    out = _render(ev)
    assert "第 1 轮" in out and "0 号→8 号" in out and "1 号→空刀" in out
    assert "None" not in out and "proposals" not in out
    assert _score(ev, seat=0) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_prompts.py -k wolf_prompt tests/test_agent_memory.py -k revote -q`
Expected: 三个 prompt 用例中前两个 FAIL（无「提议刀」/「上一轮」）；memory 用例 FAIL（通用渲染含 `proposals`，分数 1）

- [ ] **Step 3: 实现**

`app/agent/prompts.py`——在 `build_wolf_night_prompt` 之前加两个 helper，并重写该函数的「狼队私有」段：

```python
def _fmt_target(t: object) -> str:
    return "空刀" if t is None else f"{t} 号"


def _wolf_consensus_section(obs: PlayerObservation) -> str:
    """狼队本轮提案 + 跟刀/重提引导（issue #46）。旧观察缺键时按空处理。"""
    priv = obs.private
    proposals: dict[Any, Any] = priv.get("tonight_kill_proposals") or {}
    history: list[dict[Any, Any]] = priv.get("kill_proposal_history") or []
    rnd = int(priv.get("kill_vote_round", 1))
    rnd_max = int(priv.get("kill_vote_rounds_max", 1))
    lines: list[str] = []
    others = {int(s): t for s, t in proposals.items() if int(s) != obs.my_seat}
    if others:
        lines.append("本轮队友已提案：" + "；".join(f"{s} 号提议{_fmt_target(t)}" for s, t in sorted(others.items())) + "。")
    lines.append("狼队须全员一致才能出刀，否则空刀。若队友已有提案且你没有强理由反对，请跟刀（proposed_target 与之一致）。")
    if rnd > 1 and history:
        prev = history[-1]
        lines.append(
            f"第 {rnd}/{rnd_max} 轮：上一轮意见不一致（"
            + "、".join(f"{int(s)} 号→{_fmt_target(t)}" for s, t in sorted(prev.items(), key=lambda kv: int(kv[0])))
            + "），请统一意见。"
            + ("末轮仍不一致将按规则兜底（默认空刀）。" if rnd >= rnd_max else "")
        )
    return "\n".join(lines)
```

`build_wolf_night_prompt` 里删除 `proposal = obs.private.get("tonight_kill_proposal")` 与 `proposal_line` 两行（该字段在狼行动时恒空，是既有缺陷），「狼队私有」段改为：

```python
        f"== 狼队私有 ==\n你的队友座位：{teammates}。\n{_wolf_consensus_section(obs)}\n"
```

（其余段落与 `cands`/`_SELF_CHECK` 保持不变。注意 ruff 行宽：长字符串按现有写法拆行。）

`app/agent/memory.py`——import `WolfKillRevotePayload`；`_SCORE_2` 加入 `EventType.WOLF_KILL_REVOTE`；`_render` 在 `SEER_CHECKED` 分支之后、通用回退之前加：

```python
    if t == EventType.WOLF_KILL_REVOTE and isinstance(p, WolfKillRevotePayload):
        body = "、".join(f"{s} 号→{'空刀' if tgt is None else f'{tgt} 号'}" for s, tgt in p.proposals)
        return f"狼队第 {p.round_no} 轮意见不一致（{body}），重新提案"
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_memory.py tests/test_agent_player.py tests/test_agent_integration.py -q`
Expected: 全部 PASS（`test_prompts_carry_memory_and_self_check` 里 `"队友" in wolf and "4" in wolf` 仍成立）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts.py backend/app/agent/memory.py backend/tests/test_agent_prompts.py backend/tests/test_agent_memory.py
git commit -m "feat(agent): 狼夜 prompt 读取队友本轮提案并引导跟刀；重提轮呈现分歧；记忆渲染 REVOTE (issue #46)"
```

---

### Task 5: CLI——渲染、`--wolf-rule` / `--wolf-rounds` 旋钮、Makefile、README

**Files:**
- Modify: `backend/app/cli/render.py`（import；`render_event` 的 `WOLF_KILL_DECIDED` 分支之后；`render_observation` 狼提案行）
- Modify: `backend/app/cli/play.py`（`main` 参数与 config 组装，约 line 146-173）
- Modify: `Makefile`（变量块 line 16-26；`watch`/`play` 目标 help 文案）
- Modify: `README.md`（§「板子」line 92 规则清单；§「终端对局」约 line 199-213 加旋钮示例）
- Test: `backend/tests/test_cli_render.py`、`backend/tests/test_cli_play_watch.py`

**Interfaces:**
- Consumes: Task 1 的 `WolfKillRevotePayload`；Task 3 的 observation 字段。
- Produces: `app.cli.play._apply_wolf_knobs(config: GameConfig, wolf_rule: str | None, wolf_rounds: int | None) -> GameConfig`；CLI 参数 `--wolf-rule {unanimous,majority,random}`、`--wolf-rounds N`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_cli_render.py` 末尾：

```python
def test_render_wolf_kill_revote_and_wolf_observation() -> None:
    from app.engine.events import WolfKillRevotePayload

    out = render_event(
        _ev(EventType.WOLF_KILL_REVOTE, WolfKillRevotePayload(round_no=1, proposals=((0, 8), (1, None))))
    )
    assert "[GM]" in out and "第 1 轮" in out and "0号→8号" in out and "1号→空刀" in out
    assert "None" not in out and "proposals" not in out

    obs = _obs("NIGHT_WEREWOLF")
    obs = obs.model_copy(
        update={
            "private": {
                "teammates": [4],
                "tonight_kill_proposals": {4: 8},
                "kill_proposal_history": [],
                "kill_vote_round": 2,
                "kill_vote_rounds_max": 2,
            }
        }
    )
    text = render_observation(obs)
    assert "队友提案" in text and "4号→8号" in text and "第 2/2 轮" in text
```

追加到 `backend/tests/test_cli_play_watch.py` 末尾：

```python
def test_apply_wolf_knobs() -> None:
    from app.cli.play import _apply_wolf_knobs
    from app.engine.config import WolfKillRule, build_preset

    base = build_preset("std_9_kill_side")
    assert _apply_wolf_knobs(base, None, None) == base
    cfg = _apply_wolf_knobs(base, "majority", 3)
    assert cfg.wolf_kill_rule == WolfKillRule.MAJORITY and cfg.wolf_consensus_rounds == 3
    assert _apply_wolf_knobs(base, "random", None).wolf_kill_rule == WolfKillRule.RANDOM_PROPOSAL
    assert _apply_wolf_knobs(base, "unanimous", 1).wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_render.py::test_render_wolf_kill_revote_and_wolf_observation tests/test_cli_play_watch.py::test_apply_wolf_knobs -q`
Expected: 两例 FAIL（渲染含 `proposals=`；`ImportError: _apply_wolf_knobs`）

- [ ] **Step 3: 实现**

`app/cli/render.py`——import 加 `WolfKillRevotePayload`；`render_event` 在 `WOLF_KILL_DECIDED` 分支之后加：

```python
    if t == EventType.WOLF_KILL_REVOTE and isinstance(p, WolfKillRevotePayload):
        body = "、".join(f"{s}号→{'空刀' if tgt is None else f'{tgt}号'}" for s, tgt in p.proposals)
        return f"[GM] 狼队第 {p.round_no} 轮意见不一致（{body}），重新提案"
```

`render_observation` 在「你的私有信息」行之前加狼提案行（并把这几个键从 `priv` 通用行里排除）：

```python
    priv = {k: v for k, v in obs.private.items() if k != "wolf_chat"}
    proposals = priv.pop("tonight_kill_proposals", None)
    history = priv.pop("kill_proposal_history", None)
    rnd = priv.pop("kill_vote_round", None)
    rnd_max = priv.pop("kill_vote_rounds_max", None)
    if proposals is not None:
        body = "、".join(f"{s}号→{'空刀' if t is None else f'{t}号'}" for s, t in sorted(proposals.items())) or "暂无"
        lines.append(f"狼队第 {rnd}/{rnd_max} 轮 · 队友提案：{body}")
        if history:
            prev = "、".join(f"{s}号→{'空刀' if t is None else f'{t}号'}" for s, t in sorted(history[-1].items()))
            lines.append(f"上一轮分歧：{prev}")
    if priv:
        lines.append(f"你的私有信息：{priv}")
```

`app/cli/play.py`——`_parse_view` 之后加：

```python
_WOLF_RULES = {
    "unanimous": WolfKillRule.UNANIMOUS_OR_NO_KILL,
    "majority": WolfKillRule.MAJORITY,
    "random": WolfKillRule.RANDOM_PROPOSAL,
}


def _apply_wolf_knobs(
    config: GameConfig, wolf_rule: str | None, wolf_rounds: int | None
) -> GameConfig:
    """狼刀规则旋钮（issue #46）：只覆盖显式给出的项。"""
    update: dict[str, object] = {}
    if wolf_rule is not None:
        update["wolf_kill_rule"] = _WOLF_RULES[wolf_rule]
    if wolf_rounds is not None:
        update["wolf_consensus_rounds"] = wolf_rounds
    return config.model_copy(update=update) if update else config
```

（import `GameConfig`、`WolfKillRule` 自 `app.engine.config`。）`main` 里加参数：

```python
    parser.add_argument(
        "--wolf-rule",
        choices=sorted(_WOLF_RULES),
        default=None,
        help="狼刀裁决规则：unanimous（全员一致，默认）|majority（相对多数）|random（加权随机）",
    )
    parser.add_argument(
        "--wolf-rounds", type=int, default=None, help="狼队提案最多几轮，不一致则重提（默认 2）"
    )
```

config 组装改为：

```python
    config = build_preset(args.preset).model_copy(update={"seed": args.seed})
    config = _apply_wolf_knobs(config, args.wolf_rule, args.wolf_rounds)
```

`Makefile`——变量块加：

```make
WOLF_RULE       ?=     # 狼刀裁决规则 unanimous|majority|random（缺省=预设默认 unanimous）
WOLF_ROUNDS     ?=     # 狼队提案最多几轮，不一致则重提（缺省 2）
```

`_AIFLAGS` 之后加并入 `watch`/`play` 命令（两处 `$(_AIFLAGS)` 后各加 `$(_WOLFFLAGS)`）：

```make
_WOLFFLAGS := $(if $(WOLF_RULE),--wolf-rule $(WOLF_RULE),) \
	$(if $(WOLF_ROUNDS),--wolf-rounds $(WOLF_ROUNDS),)
```

`watch` 目标的 help 注释补 `WOLF_RULE= WOLF_ROUNDS=`。

`README.md`：
- line 92 规则清单中「狼刀决策（全员一致/相对多数/加权随机）」改为「狼刀决策（全员一致/相对多数/加权随机；意见不一致时可再开 `wolf_consensus_rounds` 轮统一意见）」。
- §「终端对局」示例块（约 line 208 `make watch AI_MODEL=…` 之后）加两行：

```bash
make watch AI_MODEL=ollama/qwen2.5-coder:7b WOLF_RULE=majority   # 狼刀相对多数即可
make watch WOLF_ROUNDS=3                                        # 狼队最多三轮统一意见
```

- [ ] **Step 4: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_cli_render.py tests/test_cli_play_watch.py tests/test_cli_play_human.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全量（含 E2E）全绿；lint/type 全过

- [ ] **Step 5: 真机看一眼**

Run（`backend/` 下，全随机 bot）:
`uv run python -m app.cli.play --preset std_12_yn_hunter_idiot --seed 3 --view gm --delay 0 --no-color | grep -n -E "狼提议|狼队" | head -30`
Expected: 出现 `[GM] N号狼提议刀 …` 若干行后，某夜有 `[GM] 狼队第 1 轮意见不一致（…），重新提案`，随后再一组提议与 `[GM] 狼队决定刀 …` 或 `[GM] 狼队空刀`。若该 seed 恰无分歧，换 seed（42、256）并在报告注明。

Run: `uv run python -m app.cli.play --preset std_9_kill_side --seed 3 --view gm --delay 0 --no-color --wolf-rule majority --wolf-rounds 1 | grep -c "狼队第"`
Expected: `0`（rounds=1 不重提）

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli/render.py backend/app/cli/play.py backend/tests/test_cli_render.py backend/tests/test_cli_play_watch.py Makefile README.md
git commit -m "feat(cli): 狼队收敛轮渲染 + --wolf-rule/--wolf-rounds 旋钮；Makefile/README 同步 (issue #46)"
```

---

## Self-Review

- **Spec 覆盖**：§3 配置→T1；§4.1 状态→T1；§4.2 事件/reduce→T1；§4.3 转移→T2；§5 observation + PRD §3.2/§4.2→T3；§6 表：prompts/memory→T4，render/play/Makefile/README→T5，decisions/bot/defaults/api/schemas 无改动（T2 Step 4 的回归跑 defaults/runner 验证「无需改动」成立）；§7 测试逐条落在 T1–T5；PRD §6.4→T1。§8 不在范围无任务。
- **占位符扫描**：无 TBD/TODO；T5 Step 5 的换 seed 指引是明确执行指令。
- **类型一致性**：`WolfKillRevotePayload(round_no, proposals)`、`GameState.wolf_kill_round` / `wolf_proposal_history`、observation 键名 `tonight_kill_proposals` / `kill_proposal_history` / `kill_vote_round` / `kill_vote_rounds_max`、`_apply_wolf_knobs(config, wolf_rule, wolf_rounds)` 在各任务间一致；`_state(..., **kw)` 在 T2/T3 传 `wolf_kill_round` / `wolf_proposal_history` 依赖 T1 的字段名。
- **已知细节**：T2 `test_random_rule_*` 的 MAJORITY 并列例用三方各一票（8,3,5）触发重提；T4 prompt 测试的 `_obs(private=…)` 依赖 `test_agent_prompts._obs` 用 `kw.pop("private", …)` 取私有段（已核对）。
