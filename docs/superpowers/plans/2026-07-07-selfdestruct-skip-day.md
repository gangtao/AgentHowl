# 竞选期自爆「立即天黑」精确化 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 issue #8（+ 并入 issue #15 的 bot 覆盖）：竞选期自爆后即使死讯经猎人开枪/遗言绕行，处理完结算权利后仍严格跳过当天直接入夜。

**Architecture:** 新增流程游标 `GameState.skip_day: bool`（`model_copy`，与 `resume_token` 同类）。竞选自爆分支置位；`_enter_day_speech`（所有直达/绕行路径的唯一漏斗，仅两个调用点）首行消费——置位则清零并委托 `_after_day_death`（其内已含胜负判定/max_rounds/入夜）。删除 `_after_self_destruct` 尾部只覆盖同步路径的 `if phase == DAY_SPEECH` hack（被漏斗完全取代）。Bot 在竞选/警上 PK 阶段以 1/24 概率自爆使扫描真实触达。

**Tech Stack:** 既有 M1 引擎（Python 3.11 + Pydantic v2）。命令在 `backend/` 下运行。

## Global Constraints

- 语义边界：自爆只跳过当天讨论/投票；猎人开枪与遗言照常处理。
- `skip_day` 是游标（文档化例外，不参与 `reduce==live` 事实断言）；白天自爆路径不置位、行为不变。
- 全量回归（确定性、500 局扫描）必须通过；引擎零 IO；注释中文/标识符英文；mypy strict + ruff check + ruff format 干净。
- 提交信息以 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 结尾。

## File Structure

| 文件 | 改动 |
|---|---|
| `backend/app/engine/state.py` | +`skip_day: bool = False` 游标 |
| `backend/app/engine/engine.py` | `_after_self_destruct` 置位+删 hack；`_enter_day_speech` 消费 |
| `backend/app/cli/bot.py` | 竞选/警上 PK 阶段 1/24 概率自爆 |
| `backend/tests/test_self_destruct_skip.py` | 新测试文件（含 issue #15 的 direction 锁定测试） |

---

### Task 1: skip_day 机制 —— 置位/漏斗消费/删 hack

**Files:**
- Modify: `backend/app/engine/state.py`（`resume_token` 附近）
- Modify: `backend/app/engine/engine.py`（`_after_self_destruct`、`_enter_day_speech`）
- Test: `backend/tests/test_self_destruct_skip.py`（新建）

**Interfaces:**
- Produces: `GameState.skip_day: bool = False`；`_enter_day_speech` 消费语义（置位 → 清零 + `_after_day_death`）。Task 2 依赖该语义做集成覆盖。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_self_destruct_skip.py`：
```python
"""竞选期自爆「立即天黑」（issue #8）：死讯绕行猎人/遗言后仍跳过当天。"""

from app.engine.actions import NightAction, NightActionType, SelfDestruct, Speak
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
from app.engine.events import Event, EventType, PhaseChangedPayload
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player


def _mk_player(seat: int, role: RoleType, alive: bool = True) -> Player:
    return Player(
        seat=seat,
        display_name=f"P{seat}",
        role=role,
        faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
        alive=alive,
    )


def _election_state(night_deaths: tuple[int, ...] = (), **kw: object) -> GameState:
    """竞选期（死讯未公布）：7 人，狼 0/1，猎人 5。"""
    roles = [
        RoleType.WEREWOLF,
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.WITCH,
    ]
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 7, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": tuple(_mk_player(i, r) for i, r in enumerate(roles)),
        "election_stage": "candidacy",
        "night_deaths": night_deaths,
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _no_day_speech(events: list[Event]) -> bool:
    return not any(
        e.type == EventType.PHASE_CHANGED
        and isinstance(e.payload, PhaseChangedPayload)
        and e.payload.to == Phase.DAY_SPEECH
        for e in events
    )


def test_selfdestruct_with_hunter_detour_skips_day() -> None:
    # 首夜刀死猎人(5)，死讯被竞选推迟；狼 0 自爆
    st = _election_state(night_deaths=(5,))
    all_events: list[Event] = []

    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    all_events += res.events
    st = res.state
    # 死讯公布后猎人可开枪 -> 绕行 HUNTER_SHOOT
    assert st.phase == Phase.HUNTER_SHOOT
    assert expected_actors(st) == {5}

    res = step(st, NightAction(actor_seat=5, action_type=NightActionType.SHOOT, target_seat=3))
    assert res.rejection is None
    all_events += res.events
    st = res.state
    # 首夜死者遗言（FIRST_NIGHT_ONLY，round 1）
    assert st.phase == Phase.LAST_WORDS
    while st.phase == Phase.LAST_WORDS:
        speaker = next(iter(expected_actors(st)))
        res = step(st, Speak(actor_seat=speaker, content="遗言"))
        assert res.rejection is None
        all_events += res.events
        st = res.state

    # 核心断言：处理完枪与遗言后直接入夜（round 2），全程无 DAY_SPEECH
    assert st.round == 2
    assert st.phase in (Phase.NIGHT_WEREWOLF, Phase.NIGHT_GUARD, Phase.NIGHT_WITCH, Phase.NIGHT_SEER)
    assert _no_day_speech(all_events)
    assert st.skip_day is False  # 游标已消费


def test_selfdestruct_peaceful_night_synchronous_skip() -> None:
    # 平安夜（空死讯）：无绕行，同步直接入夜（原 hack 语义保留）
    st = _election_state(night_deaths=())
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert res.state.round == 2
    assert res.state.phase in (
        Phase.NIGHT_WEREWOLF,
        Phase.NIGHT_GUARD,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
    )
    assert _no_day_speech(res.events)
    assert res.state.skip_day is False


def test_day_selfdestruct_unchanged_and_flag_untouched() -> None:
    # 白天自爆路径不使用 skip_day（恒 False），行为照旧直接入夜
    roles = [RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER, RoleType.WITCH]
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=2,
        players=tuple(_mk_player(i, r) for i, r in enumerate(roles)),
        speech_order=(0, 1, 2, 3, 4),
        speech_idx=0,
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert res.state.round == 3
    assert res.state.skip_day is False
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_self_destruct_skip.py -v`
Expected: `test_selfdestruct_with_hunter_detour_skips_day` FAIL（绕行后落入 DAY_SPEECH：`st.round == 2` 或 `_no_day_speech` 断言失败）；`skip_day` 字段不存在也会先报错。

- [ ] **Step 3: 实现**

`backend/app/engine/state.py` —— `resume_token` 字段旁追加：
```python
    skip_day: bool = False  # 竞选期自爆置位：死讯（含枪/遗言绕行）处理完后跳过当天直接入夜（游标）
```

`backend/app/engine/engine.py`：

(a) `_after_self_destruct` 竞选分支——把
```python
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言）
    state = state.model_copy(update={"election_stage": ""})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    # _announce_and_continue_night 会进入 DAY_SPEECH；自爆要求跳过白天 -> 强制推进到入夜
    if state.phase == Phase.DAY_SPEECH:
        winner = check_win(state)
        if winner is not None:
            state, e = _emit(
                state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC
            )
            return state, [*ev, e]
        state, ev2 = _after_day_death(state)
        return state, [*ev, *ev2]
    return state, ev
```
整体替换为：
```python
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言绕行）；skip_day 游标保证
    # 无论同步还是绕行续接，最终都在 _enter_day_speech 漏斗处跳过当天直接入夜。
    state = state.model_copy(update={"election_stage": "", "skip_day": True})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    return state, ev
```

(b) `_enter_day_speech` 首行加消费：
```python
def _enter_day_speech(state: GameState) -> tuple[GameState, list[Event]]:
    if state.skip_day:
        # 竞选期自爆的「立即天黑」：跳过当天发言/投票（胜负判定与入夜由 _after_day_death 处理）
        state = state.model_copy(update={"skip_day": False})
        return _after_day_death(state)
    order = _speech_order(state)
    ...（其余不变）
```

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_self_destruct_skip.py -v && uv run pytest -q`
Expected: 新测试 PASS（3 项）；全量 178 tests 全绿（skip_day 默认 False，非自爆路径零变化——确定性字节级不变；既有 test_sheriff 的自爆用例仍过）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine backend/tests/test_self_destruct_skip.py
git commit -m "feat(engine): skip_day 游标使竞选期自爆经绕行后仍严格跳过当天（issue #8）"
```

### Task 2: bot 竞选期自爆 + 集成 + direction 锁定测试（issue #15）

**Files:**
- Modify: `backend/app/cli/bot.py`
- Test: `backend/tests/test_self_destruct_skip.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 skip_day 语义；既有 `SelfDestruct` 校验（存活狼、DAY_SPEECH/SHERIFF_ELECTION/SHERIFF_PK）。
- Produces: bot 在竞选/警上 PK 阶段 1/24 概率自爆；issue #15 的两项覆盖（bot 路径 + direction 忽略残留 speech_order 锁定）。

- [ ] **Step 1: 写失败测试**

Append 到 `backend/tests/test_self_destruct_skip.py`：
```python
def test_direction_stage_ignores_stale_speech_order() -> None:
    # issue #15 锁定：方向决策子阶段不消费残留发言队列
    st = _election_state(
        election_stage="direction",
        sheriff_seat=2,
        speech_order=(1, 2),
        speech_idx=0,
    )
    assert expected_actors(st) == {2}


def test_full_games_bot_election_selfdestruct_occurs() -> None:
    from app.cli.bot import run_game

    saw_election_sd = False
    for seed in range(30):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"sd{seed}")
        assert final.phase == Phase.GAME_OVER
        # 自爆事件出现且其时点在首个 DAY_SPEECH 之前 => 竞选期自爆被真实触达
        first_day = next(
            (
                e.seq
                for e in events
                if e.type == EventType.PHASE_CHANGED
                and isinstance(e.payload, PhaseChangedPayload)
                and e.payload.to == Phase.DAY_SPEECH
            ),
            None,
        )
        for e in events:
            if e.type == EventType.WOLF_SELF_DESTRUCT and (first_day is None or e.seq < first_day):
                saw_election_sd = True
    assert saw_election_sd
```

> 概率兜底：若 30 个 seed 未命中竞选期自爆（1/24 × 每局竞选行动点数，命中概率高），把 range 扩到 60 并在报告注明——断言意图是路径真实触达，seed 数量可调；不得删除断言。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_self_destruct_skip.py::test_full_games_bot_election_selfdestruct_occurs -v`
Expected: FAIL（bot 从不在竞选期自爆，`saw_election_sd` 为 False）。`test_direction_stage_ignores_stale_speech_order` 应已 PASS（现状正确，纯锁定）。

- [ ] **Step 3: bot 分支**

`backend/app/cli/bot.py` —— 在 `pl = player_at(state, seat)` 之后、PK 发言分支（`if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and ...`）**之前**插入：
```python
        if (
            ph in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK)
            and pl.alive
            and pl.faction == Faction.WOLF
            and rng.derive_int(
                seed=seed, purpose=f"bot:{seat}:sd_elec", seq=state.state_version, modulo=24
            )
            == 0
        ):
            # 竞选/警上 PK 阶段偶发自爆（issue #15 覆盖；issue #8 的 skip_day 路径被扫描真实触达）
            return SelfDestruct(actor_seat=seat)
```
（`Faction`、`SelfDestruct` 已在 bot.py import。）

- [ ] **Step 4: 运行确认通过 + 全量回归**

Run: `uv run pytest tests/test_self_destruct_skip.py -v && uv run pytest -q`
Expected: 全绿（180 tests；确定性、500 局扫描——扫描中竞选期自爆将真实发生并走 skip_day 路径；若扫描出现 NOT_SELF_DESTRUCTABLE 拒绝说明分支的 alive/faction 守卫有误）。
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 干净。

- [ ] **Step 5: 提交**

```bash
git add backend/app/cli/bot.py backend/tests/test_self_destruct_skip.py
git commit -m "test(engine): bot 竞选期自爆覆盖与 direction 残留队列锁定，闭环 issue #8/#15"
```

---

## Self-Review

**Spec 覆盖**：§2 缺陷机理→Task 1 detour 测试复现；§3 机制四点（游标/置位/消费/删 hack）→Task 1 Step 3；§4 bot→Task 2 Step 3；§5 测试五类→Task 1（绕行/同步/白天）+ Task 2（bot 覆盖/锁定）+ 回归；§6 范围外无任务——正确。

**占位扫描**：无 TBD/TODO；概率兜底为明确执行指令。

**类型一致性**：`skip_day` 在 state/engine/tests 一致；`_election_state`/`_mk_player` 为本文件自足 helper；`PhaseChangedPayload`/`EventType`/`expected_actors` 均既有名字；bot 分支引用的 `Faction`/`SelfDestruct` 已在 bot.py import（Task 15/M1 时引入）。
