# 竞选子阶段游标事件化（ELECTION_STAGE_CHANGED）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 PUBLIC 事件 `ELECTION_STAGE_CHANGED(stage)`，`election_stage` 从 model_copy 游标升格为事件推导事实——竞选子阶段时间线可从纯 `reduce(events)` 重建。

**Architecture:** 两层：先在 events/phases 落契约（`ElectionStage` 枚举、payload、`EVENT_PAYLOAD_TYPES`、reduce 写入），再把 `engine.py` 全部 `election_stage` 的 model_copy 写入改为 `_emit`（其中自爆路径的一处冗余清空直接删除）。同一 model_copy 里的其他游标字段（`sheriff_confirmed`/`sheriff_votes`/`night_deaths`/`skip_day`）保持 model_copy。

**Tech Stack:** Python 3.11+、Pydantic v2、pytest；纯引擎（零 IO），后端命令全部从 `backend/` 用 `uv run` 执行。

**Spec:** `docs/superpowers/specs/2026-07-08-election-stage-events-design.md`（已批准，关联 issue #17）

## Global Constraints

- 引擎纯函数零 IO：只许 stdlib + Pydantic。
- 事实经 reduce 写入；`_emit` 即时 reduce，事件后 `state.election_stage` 已更新（与原 model_copy 时序等价）。
- 新事件必须入 `EVENT_PAYLOAD_TYPES`（fail-loud tripwire `test_fail_loud.py` 会强制）。
- 文档与注释中文；标识符英文。
- 行为影响（预期）：事件流插入新事件 → `state_version` 位移 → 同 seed 抽取结果相对旧代码改变；确定性测试比较同代码两次运行，不受影响。
- 门禁（从 `backend/` 运行）：`uv run pytest -q`、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .` 全绿。

---

### Task 1: 契约层 — ElectionStage 枚举、事件类型、payload、reduce

**Files:**
- Modify: `backend/app/engine/phases.py`（`Phase` 类之后加 `ElectionStage`）
- Modify: `backend/app/engine/events.py`（EventType 成员、payload、`EVENT_PAYLOAD_TYPES`、reduce 分支、import）
- Create: `backend/tests/test_election_timeline.py`（本任务只写契约单元测试；时间线测试在 Task 2 追加）

**Interfaces:**
- Consumes: `reduce(state, event)`、`EventPayload`、`EVENT_PAYLOAD_TYPES`（events.py 既有）。
- Produces（Task 2 依赖）: `phases.ElectionStage(StrEnum)`，成员 `NONE=""/CANDIDACY="candidacy"/WITHDRAW="withdraw"/VOTE="vote"/DIRECTION="direction"/ANNOUNCE="announce"`；`EventType.ELECTION_STAGE_CHANGED`；`ElectionStageChangedPayload(stage: ElectionStage)`；reduce 将 `election_stage` 置为 `p.stage.value`。

- [ ] **Step 1: 写失败的契约单元测试**

新建 `backend/tests/test_election_timeline.py`（完整文件）：

```python
"""竞选子阶段事件化（issue #17）：ELECTION_STAGE_CHANGED 契约与时间线重建。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    Visibility,
    reduce,
)
from app.engine.phases import ElectionStage, Phase
from app.engine.state import GameState, Player


def _base_state() -> GameState:
    players = tuple(
        Player(seat=s, display_name=f"P{s}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for s in range(4)
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.SHERIFF_ELECTION,
        players=players,
    )


def _stage_evt(stage: ElectionStage) -> Event:
    return Event(
        seq=1,
        game_id="g1",
        ts=1.0,
        type=EventType.ELECTION_STAGE_CHANGED,
        payload=ElectionStageChangedPayload(stage=stage),
        visibility=Visibility.PUBLIC,
    )


def test_election_stage_enum_values() -> None:
    assert ElectionStage.NONE.value == ""
    assert ElectionStage.CANDIDACY.value == "candidacy"
    assert ElectionStage.WITHDRAW.value == "withdraw"
    assert ElectionStage.VOTE.value == "vote"
    assert ElectionStage.DIRECTION.value == "direction"
    assert ElectionStage.ANNOUNCE.value == "announce"


def test_reduce_writes_election_stage() -> None:
    state = _base_state()
    new = reduce(state, _stage_evt(ElectionStage.WITHDRAW))
    assert new.election_stage == "withdraw"
    assert new.state_version == state.state_version + 1
    assert state.election_stage == ""  # 原状态不变（纯函数）
    back = reduce(new, _stage_evt(ElectionStage.NONE))
    assert back.election_stage == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_election_timeline.py -v`
Expected: 收集即失败——`ImportError: cannot import name 'ElectionStageChangedPayload'`（或 `ElectionStage`）。

- [ ] **Step 3: phases.py 加枚举**

`backend/app/engine/phases.py`，紧跟 `Phase` 类定义之后（`GAME_OVER = "GAME_OVER"` 行与底部 `from app.engine.config import ...` 之间）插入：

```python
class ElectionStage(StrEnum):
    """警长竞选子阶段（issue #17：经 ELECTION_STAGE_CHANGED 事件写入 state.election_stage）。"""

    NONE = ""  # 竞选机器未启动/已结束（显式收尾标记）
    CANDIDACY = "candidacy"
    WITHDRAW = "withdraw"
    VOTE = "vote"
    DIRECTION = "direction"
    ANNOUNCE = "announce"
```

- [ ] **Step 4: events.py 落契约**

四处修改：

1. import 行 `from app.engine.phases import Phase` 改为：
```python
from app.engine.phases import ElectionStage, Phase
```

2. `EventType` 枚举，`SHERIFF_BADGE_LOST = "SHERIFF_BADGE_LOST"` 行之后插入：
```python
    ELECTION_STAGE_CHANGED = "ELECTION_STAGE_CHANGED"
```

3. payload 定义，`SheriffBadgeLostPayload` 类之后插入：
```python
class ElectionStageChangedPayload(EventPayload):
    stage: ElectionStage  # 子阶段标记；reduce 据此写 election_stage（issue #17）
```

4. `EVENT_PAYLOAD_TYPES` 映射，`EventType.SHERIFF_DIRECTION_SET: SheriffDirectionSetPayload,` 行之后插入：
```python
    EventType.ELECTION_STAGE_CHANGED: ElectionStageChangedPayload,
```

5. reduce：`SHERIFF_DIRECTION_SET` 分支（`return {"sheriff_speech_direction": p.direction}`）之后插入：
```python
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        return {"election_stage": p.stage.value}
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && uv run pytest tests/test_election_timeline.py tests/test_fail_loud.py -v`
Expected: 全部 PASS（fail_loud 的 tripwire 因新成员已入映射而满足）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/phases.py backend/app/engine/events.py backend/tests/test_election_timeline.py
git commit -m "feat(engine): ELECTION_STAGE_CHANGED 事件契约与 reduce 写入 (issue #17)"
```

---

### Task 2: 发射方切换、文档同步、时间线测试

**Files:**
- Modify: `backend/app/engine/engine.py`（`_apply_self_destruct`、`_after_self_destruct`、`_apply_sheriff`、首日竞选入口、`_advance_election`、`_lose_badge`、`_finish_election`、import）
- Modify: `backend/app/engine/state.py`（`election_stage` 注释）
- Modify: `docs/specs/requirements.md`（§6.4 事件清单行）
- Modify: `backend/tests/test_determinism.py`（reduce==live 增加 election_stage 断言）
- Test: `backend/tests/test_election_timeline.py`（追加时间线/逐步重放/消歧测试）

**Interfaces:**
- Consumes: Task 1 的 `phases.ElectionStage`、`EventType.ELECTION_STAGE_CHANGED`、`ElectionStageChangedPayload(stage: ElectionStage)`；engine.py 既有 `_emit(state, EventType, payload, Visibility, actor=None) -> tuple[GameState, Event]`（即时 reduce）。
- Produces: 完整对局事件流含子阶段标记序列；`election_stage` 全程 reduce==live。

- [ ] **Step 1: 追加失败的时间线测试**

在 `backend/tests/test_election_timeline.py` 末尾追加（import 区同步补 `SheriffCandidacyPayload` 与 `reduce_all` 到 `from app.engine.events import (...)`，并在文件顶部 import 区之后加 `PRESETS` 常量）：

```python
PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]

# 合法子阶段转移（时间线语法）：任何阶段都可经流失/自爆直接收尾到 ""
_VALID_NEXT: dict[str, set[str]] = {
    "candidacy": {"withdraw", ""},
    "withdraw": {"vote", ""},
    "vote": {"direction", ""},
    "direction": {"announce", ""},
    "announce": {""},
}


def _blank(like: GameState) -> GameState:
    players = tuple(
        Player(seat=p.seat, display_name=p.display_name, role=RoleType.VILLAGER, faction=Faction.GOOD)
        for p in like.players
    )
    return GameState(
        game_id=like.game_id,
        config=like.config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )


def _stage_sequence(events: list[Event]) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.type == EventType.ELECTION_STAGE_CHANGED:
            assert isinstance(e.payload, ElectionStageChangedPayload)
            out.append(e.payload.stage.value)
    return out


def test_stage_timeline_reconstructible_and_wellformed() -> None:
    from app.cli.bot import run_game

    for preset in PRESETS:
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            _, events = run_game(cfg, "g")
            seq = _stage_sequence(events)
            if not (cfg.sheriff.enabled and cfg.sheriff.election_before_first_death_announce):
                assert seq == []
                continue
            assert seq, f"{preset}/{seed}: 竞选开启但无子阶段标记"
            assert seq[0] == "candidacy" and seq[-1] == ""
            assert seq.count("candidacy") == 1  # 竞选只在首日发生一次
            for a, b in zip(seq, seq[1:]):
                assert b in _VALID_NEXT[a], f"{preset}/{seed}: {a}→{b} 非法（seq={seq}）"


def test_stepwise_replay_equals_live_election_stage() -> None:
    from app.cli.bot import RandomBot
    from app.engine.engine import create_game, step
    from app.engine.phases import expected_actors

    cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": 7})
    res = create_game(cfg, "g")
    state, events = res.state, list(res.events)
    blank = _blank(state)
    guard = 0
    while state.phase != Phase.GAME_OVER:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            r = step(state, RandomBot.choose_action(state, seat))
            assert r.rejection is None
            state, events = r.state, [*events, *r.events]
            # 中局强等价：任意前缀重放的 election_stage 与 live 一致
            assert reduce_all(blank, events).election_stage == state.election_stage
        guard += 1
        assert guard < 100_000


def test_reaffirm_disambiguated_by_stage_markers() -> None:
    from app.cli.bot import run_game

    # 标记把每个 SHERIFF_CANDIDACY(running=True) 分类到 candidacy/withdraw 窗口；
    # 断言分类恒可判定，且样本里确有退水期再确认（issue #17 的歧义场景）。
    found_reaffirm = False
    for seed in range(1, 30):
        cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": seed})
        _, events = run_game(cfg, "g")
        stage = ""
        for e in events:
            if e.type == EventType.ELECTION_STAGE_CHANGED:
                assert isinstance(e.payload, ElectionStageChangedPayload)
                stage = e.payload.stage.value
            elif e.type == EventType.SHERIFF_CANDIDACY:
                assert isinstance(e.payload, SheriffCandidacyPayload)
                if e.payload.running:
                    assert stage in ("candidacy", "withdraw")
                    if stage == "withdraw":
                        found_reaffirm = True
    assert found_reaffirm
```

（`SheriffCandidacyPayload` 字段已核实为 `seat: int` + `running: bool`。）若 `found_reaffirm` 在 seed 1..29 内未出现，扩大 seed 范围直至出现（确定性搜索，不改断言语义）。

再追加流失路径的标记闭合测试（spec §5 显式要求）：

```python
def test_badge_lost_closes_stage_marker() -> None:
    from app.engine.engine import _advance_election

    # 退水后候选清空 -> ALL_WITHDREW 流失；断言 SHERIFF_BADGE_LOST 之后紧跟收尾标记 ""
    st = _base_state().model_copy(
        update={
            "round": 1,
            "election_stage": "withdraw",
            "sheriff_candidates": (),
            "sheriff_withdrawn": frozenset({1}),
        }
    )
    _, events = _advance_election(st)
    types = [e.type for e in events]
    i = types.index(EventType.SHERIFF_BADGE_LOST)
    assert types[i + 1] == EventType.ELECTION_STAGE_CHANGED
    p = events[i + 1].payload
    assert isinstance(p, ElectionStageChangedPayload)
    assert p.stage == ElectionStage.NONE
```

（若 `_base_state` 的 4 村民构造在 `_lose_badge` 续接处触发无关不变量/终局分支干扰断言，参照 `tests/test_badge_lost.py` 既有的竞选状态构造替代——断言语义不变。）

同时修改 `backend/tests/test_determinism.py::test_reduce_events_equals_live_state`，在 `assert replayed.sheriff_seat == final.sheriff_seat` 之后追加一行：

```python
    assert replayed.election_stage == final.election_stage
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/test_election_timeline.py -v`
Expected: Task 1 的两条契约测试 PASS；新增三条 FAIL——`test_stage_timeline_reconstructible_and_wellformed` 在 `assert seq`（竞选开启但引擎尚未发标记）；`test_stepwise_replay_equals_live_election_stage` 在中局等价断言（live 经 model_copy 有值、重放恒 ""）；`test_reaffirm_disambiguated_by_stage_markers` 在 `assert found_reaffirm`（无标记则 stage 恒 ""，re-affirm 落入 `assert stage in (...)` 失败或计不上）。

- [ ] **Step 3: engine.py 发射方切换（9 处发射 + 1 处删除）**

先补 import：engine.py 的 `from app.engine.phases import ...` 增加 `ElectionStage`；`from app.engine.events import (...)` 增加 `ElectionStageChangedPayload`。

以下每处给出「现状 → 改后」。发射位置与原 model_copy 一致（`_emit` 即时 reduce，后续读值时序不变）。

**(1) `_apply_self_destruct` 吞警徽分支 —— 删除冗余清空**（该流程随后必经 `_after_self_destruct` 的竞选收尾，两处清空只保留后者；中间无任何 `election_stage` 读者）：

现状：
```python
        s = s.model_copy(update={"election_stage": ""})
        s, e2 = _emit(
            s,
            EventType.SHERIFF_BADGE_LOST,
            SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
            Visibility.PUBLIC,
        )
        events = [e, e2]
```
改后（仅删首行）：
```python
        s, e2 = _emit(
            s,
            EventType.SHERIFF_BADGE_LOST,
            SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
            Visibility.PUBLIC,
        )
        events = [e, e2]
```

**(2) `_after_self_destruct` 竞选收尾**：

现状：
```python
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言绕行）；skip_day 游标保证
    # 无论同步还是绕行续接，最终都在 _enter_day_speech 漏斗处跳过当天直接入夜。
    state = state.model_copy(update={"election_stage": "", "skip_day": True})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    return state, ev
```
改后：
```python
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言绕行）；skip_day 游标保证
    # 无论同步还是绕行续接，最终都在 _enter_day_speech 漏斗处跳过当天直接入夜。
    state, e = _emit(
        state,
        EventType.ELECTION_STAGE_CHANGED,
        ElectionStageChangedPayload(stage=ElectionStage.NONE),
        Visibility.PUBLIC,
    )
    events.append(e)
    state = state.model_copy(update={"skip_day": True})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    return state, ev
```

**(3) `_apply_sheriff` 方向已定 → announce**：

现状：
```python
        # 方向已定 -> 游标推进到 announce，由 _advance_election 续接死讯公布
        s = s.model_copy(update={"election_stage": "announce"})
        return s, [e]
```
改后：
```python
        # 方向已定 -> 子阶段推进到 announce（经事件），由 _advance_election 续接死讯公布
        s, e2 = _emit(
            s,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.ANNOUNCE),
            Visibility.PUBLIC,
        )
        return s, [e, e2]
```

**(4) 首日竞选入口（`night_deaths` 暂存处）**：

现状：
```python
        state = state.model_copy(update={"night_deaths": ordered, "election_stage": "candidacy"})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.SHERIFF_ELECTION),
            Visibility.PUBLIC,
        )
        return state, [*events, e]
```
改后（先相位、后子阶段，时间线阅读顺序自然）：
```python
        state = state.model_copy(update={"night_deaths": ordered})
        state, e = _emit(
            state,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.SHERIFF_ELECTION),
            Visibility.PUBLIC,
        )
        state, e2 = _emit(
            state,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.CANDIDACY),
            Visibility.PUBLIC,
        )
        return state, [*events, e, e2]
```

**(5) `_advance_election` announce 消费**：

现状：
```python
    if state.election_stage == "announce":
        state = state.model_copy(update={"election_stage": ""})
        return _announce_and_continue_night(state, state.night_deaths, events)
```
改后：
```python
    if state.election_stage == "announce":
        state, e = _emit(
            state,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.NONE),
            Visibility.PUBLIC,
        )
        events.append(e)
        return _announce_and_continue_night(state, state.night_deaths, events)
```

**(6) `_advance_election` candidacy → withdraw**：

现状：
```python
        # 进入退水确认子阶段
        state = state.model_copy(
            update={"election_stage": "withdraw", "sheriff_confirmed": frozenset()}
        )
        return state, events
```
改后：
```python
        # 进入退水确认子阶段（confirmed 是游标，保持 model_copy）
        state, e = _emit(
            state,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.WITHDRAW),
            Visibility.PUBLIC,
        )
        events.append(e)
        state = state.model_copy(update={"sheriff_confirmed": frozenset()})
        return state, events
```

**(7) `_advance_election` withdraw → vote**：

现状：
```python
        state = state.model_copy(update={"election_stage": "vote", "sheriff_votes": {}})
        return state, events
```
改后：
```python
        state, e = _emit(
            state,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.VOTE),
            Visibility.PUBLIC,
        )
        events.append(e)
        state = state.model_copy(update={"sheriff_votes": {}})
        return state, events
```

**(8) `_lose_badge` 收尾**：

现状：
```python
    events.append(e)
    state = state.model_copy(update={"election_stage": ""})
    return _announce_and_continue_night(state, state.night_deaths, events)
```
改后：
```python
    events.append(e)
    state, e2 = _emit(
        state,
        EventType.ELECTION_STAGE_CHANGED,
        ElectionStageChangedPayload(stage=ElectionStage.NONE),
        Visibility.PUBLIC,
    )
    events.append(e2)
    return _announce_and_continue_night(state, state.night_deaths, events)
```

**(9) `_finish_election` SHERIFF_DECIDES → direction**：

现状：
```python
        state = state.model_copy(update={"election_stage": "direction"})
        return state, events
```
改后：
```python
        state, e3 = _emit(
            state,
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.DIRECTION),
            Visibility.PUBLIC,
        )
        events.append(e3)
        return state, events
```

**(10) `_finish_election` 非方向路径收尾**：

现状：
```python
    state = state.model_copy(update={"election_stage": ""})
    return _announce_and_continue_night(state, state.night_deaths, events)
```
改后：
```python
    state, e3 = _emit(
        state,
        EventType.ELECTION_STAGE_CHANGED,
        ElectionStageChangedPayload(stage=ElectionStage.NONE),
        Visibility.PUBLIC,
    )
    events.append(e3)
    return _announce_and_continue_night(state, state.night_deaths, events)
```

完成后自查：`grep -n 'model_copy' backend/app/engine/engine.py | grep election_stage` 应零命中。

- [ ] **Step 4: 文档同步**

1. `backend/app/engine/state.py`，`election_stage` 字段注释：

现状：
```python
    election_stage: str = (
        ""  # ""/"candidacy"/"withdraw"/"vote"/"direction"/"announce"
        # （PK 由 phase==SHERIFF_PK 区分）
    )
```
改后：
```python
    election_stage: str = (
        ""  # 事实：经 ELECTION_STAGE_CHANGED 事件写入（issue #17）；
        # 值域见 phases.ElectionStage（PK 由 phase==SHERIFF_PK 区分）
    )
```

2. `docs/specs/requirements.md` 事件清单（§6.4，`SHERIFF_WITHDREW(PUBLIC), SHERIFF_ELECTED(PUBLIC),` 所在行）：把
`SHERIFF_WITHDREW(PUBLIC), SHERIFF_ELECTED(PUBLIC), BADGE_PASSED(PUBLIC),`
改为
`SHERIFF_WITHDREW(PUBLIC), SHERIFF_VOTE_CAST(PUBLIC), SHERIFF_ELECTED(PUBLIC), SHERIFF_DIRECTION_SET(PUBLIC), SHERIFF_BADGE_LOST(PUBLIC), ELECTION_STAGE_CHANGED(PUBLIC), BADGE_PASSED(PUBLIC),`
（顺带补齐三个已实现但清单漏记的警长事件——同一行的文档同步）。

- [ ] **Step 5: 运行新测试确认通过**

Run: `cd backend && uv run pytest tests/test_election_timeline.py tests/test_determinism.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 全量套件与既有断言迁移**

Run: `cd backend && uv run pytest -q`
Expected: 若有既有测试因事件流插入标记而失败，逐一修复——只允许把断言更新到新日志（补上标记事件的存在/位置），不得弱化断言（精确序列断言不得降级为 `in` 包含）。已知排查点：`tests/test_speech_direction.py`、`tests/test_withdraw.py`、`tests/test_badge_lost.py`、`tests/test_self_destruct_skip.py`、`tests/test_sheriff.py`（多为 `any(...)` 式断言，预期多数不受影响；`tests/test_fail_loud.py:98` 是投票中途，无标记插入，应不受影响）。修完后全套件绿（预期 197 = 191 + 6 新增：Task 1 两条契约 + Task 2 四条时间线；若迁移中增删测试以实际为准）。

- [ ] **Step 7: 全量门禁**

Run: `cd backend && uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿。

- [ ] **Step 8: Commit**

```bash
git add backend/app/engine/engine.py backend/app/engine/state.py backend/tests/test_election_timeline.py backend/tests/test_determinism.py docs/specs/requirements.md
git commit -m "feat(engine): 竞选子阶段发射 ELECTION_STAGE_CHANGED，election_stage 升格事件推导 (issue #17)"
```

（若 Step 6 迁移改了其他测试文件，一并 `git add`。）
