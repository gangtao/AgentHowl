# 警长竞选上警发言子阶段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在警长竞选中补齐 `speech` 子阶段（issue #47）：候选人按法官「单顺双逆」定序依次公开发言（可带警徽流），之后进入既有退水确认。

**Architecture:** 引擎新增 `ElectionStage.SPEECH`；发言队列经 `ELECTION_STAGE_CHANGED.speech_order` 入事件流、由既有 `PLAYER_SPOKE` reduce 推进游标——全程事件推导、不新增事件类型。任务顺序为「契约 → 内置驱动（bot/超时默认）→ 引擎」，保证引擎开始发射 `speech` 时全量套件已能走通；随后适配 agent 层与工具提示/CLI 渲染。

**Tech Stack:** Python 3.11、Pydantic v2、pytest；`uv` 管理。全部命令在 `backend/` 下执行。

**Spec:** `docs/superpowers/specs/2026-09-17-campaign-speech-design.md`（执行者须同时阅读）

## Global Constraints

- 引擎（`backend/app/engine/`）纯函数零 IO，不得 import 网络/DB/LLM/runtime/cli 代码。
- 一切状态变更经 append-only Event；`state = reduce(events)`。本期新增的发言游标**禁止**用 `model_copy` 直写（不给 issue #37 添新债）。
- 一切随机走 seeded RNG：`rng.derive_int(seed=..., purpose=..., seq=state.state_version, modulo=...)`。
- 无硬编码规则：行为差异一律是 `GameConfig` 开关。
- 文档与代码注释用中文；标识符、API 名、schema 用英文。注释密度与周边代码一致。
- 引擎测试零 IO、零 mock；确定性测试用固定 `seed`。
- 每个任务结束时：`uv run pytest -q -x --ignore=tests/test_api_e2e.py` 全绿、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app` 全过（E2E 套件约 2 分钟，留给 Task 3 与最终验收跑）。
- commit message 风格：`feat(engine): … (issue #47)`，结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `backend/app/engine/config.py` | `CampaignSpeechOrder` 枚举；`SheriffRule` 两个新开关 | 1 |
| `backend/app/engine/phases.py` | `ElectionStage.SPEECH`；`campaign_speaking()`；`expected_actors` speech 分支 | 1 |
| `backend/app/engine/events.py` | `ElectionStageChangedPayload.speech_order`；reduce 写队列 | 1 |
| `backend/app/cli/bot.py` | RandomBot 上警发言；警徽流生成抽 helper | 2 |
| `backend/app/runtime/defaults.py` | speech 超时 → 空发言 | 2 |
| `backend/app/engine/engine.py` | 顺序计算、子阶段转移、`Speak`/警徽流/`SheriffAction` 校验 | 3 |
| `backend/tests/factories.py` | `run_campaign_speeches()` 测试辅助 | 3 |
| `backend/app/agent/decisions.py`、`prompts.py` | speech 分派；警徽流开放条件；上警发言引导语 | 4 |
| `backend/app/schemas/actions.py`、`backend/app/cli/render.py` | 工具提示；竞选子阶段中文叙述 | 5 |
| `backend/tests/test_campaign_speech.py`（新建） | 本特性的引擎/bot 测试 | 1–3 |
| `docs/specs/requirements.md`、`README.md` | PRD §3.2 `SheriffRule`、README 规则描述 | 3 |

---

### Task 1: 契约层——配置、子阶段枚举、事件载荷（无行为变化）

**Files:**
- Modify: `backend/app/engine/config.py`（`SheriffRule`，约 line 78）
- Modify: `backend/app/engine/phases.py`（`ElectionStage` 约 line 34；`expected_actors` 的 `SHERIFF_ELECTION` 分支约 line 132）
- Modify: `backend/app/engine/events.py`（`ElectionStageChangedPayload` 约 line 209；reduce 分支约 line 489）
- Modify: `backend/tests/test_election_timeline.py`（`test_election_stage_enum_values`）
- Create: `backend/tests/test_campaign_speech.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `app.engine.config.CampaignSpeechOrder`（`StrEnum`：`JUDGE_ODD_EVEN`、`SEAT_ASC`）
  - `SheriffRule.campaign_speech_enabled: bool = True`、`SheriffRule.campaign_speech_order: CampaignSpeechOrder = JUDGE_ODD_EVEN`
  - `app.engine.phases.ElectionStage.SPEECH`（值 `"speech"`）
  - `app.engine.phases.campaign_speaking(state: GameState) -> bool`
  - `ElectionStageChangedPayload.speech_order: tuple[int, ...] | None = None`
  - `expected_actors(state)`：`SHERIFF_ELECTION` + stage `"speech"` → `{speech_order[speech_idx]}` 或空集

本任务后引擎尚不发射 `speech`，既有行为零变化。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_campaign_speech.py`：

```python
"""上警发言子阶段（issue #47）：配置、事件契约、发言流、拒绝矩阵、回放保真。"""

from app.engine.config import (
    CampaignSpeechOrder,
    Faction,
    RoleType,
    SheriffRule,
    build_preset,
)
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    Visibility,
    reduce,
)
from app.engine.phases import ElectionStage, Phase, campaign_speaking, expected_actors
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0,)) -> tuple[Player, ...]:
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
    n: int = 6,
    sheriff: SheriffRule | None = None,
    seed: int = 1,
    wolves: tuple[int, ...] = (0,),
    **kw: object,
) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": seed})
    if sheriff is not None:
        cfg = cfg.model_copy(update={"sheriff": sheriff})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n, wolves=wolves),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _stage_evt(stage: ElectionStage, order: tuple[int, ...] | None = None) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.ELECTION_STAGE_CHANGED,
        actor_seat=None,
        payload=ElectionStageChangedPayload(stage=stage, speech_order=order),
        visibility=Visibility.PUBLIC,
    )


# ---------- Task 1：契约 ----------


def test_config_defaults() -> None:
    sr = SheriffRule()
    assert sr.campaign_speech_enabled is True
    assert sr.campaign_speech_order == CampaignSpeechOrder.JUDGE_ODD_EVEN
    assert {o.value for o in CampaignSpeechOrder} == {"JUDGE_ODD_EVEN", "SEAT_ASC"}


def test_stage_enum_has_speech() -> None:
    assert ElectionStage.SPEECH.value == "speech"


def test_reduce_speech_stage_sets_queue_and_resets_cursor() -> None:
    st = _state(election_stage="candidacy", speech_order=(9, 9, 9), speech_idx=3)
    new = reduce(st, _stage_evt(ElectionStage.SPEECH, (3, 1)))
    assert new.election_stage == "speech"
    assert new.speech_order == (3, 1)
    assert new.speech_idx == 0
    assert st.speech_idx == 3  # 原状态不变（纯函数）


def test_reduce_stage_without_order_keeps_queue() -> None:
    st = _state(election_stage="speech", speech_order=(3, 1), speech_idx=2)
    new = reduce(st, _stage_evt(ElectionStage.WITHDRAW))
    assert new.election_stage == "withdraw"
    assert new.speech_order == (3, 1) and new.speech_idx == 2


def test_payload_backward_compatible_with_old_logs() -> None:
    # 旧持久化日志无 speech_order 键
    p = ElectionStageChangedPayload.model_validate({"stage": "vote"})
    assert p.speech_order is None


def test_expected_actors_in_speech_stage() -> None:
    st = _state(
        election_stage="speech", sheriff_candidates=(1, 3), speech_order=(3, 1), speech_idx=0
    )
    assert campaign_speaking(st)
    assert expected_actors(st) == {3}
    st2 = st.model_copy(update={"speech_idx": 1})
    assert expected_actors(st2) == {1}
    done = st.model_copy(update={"speech_idx": 2})
    assert not campaign_speaking(done)
    assert expected_actors(done) == set()


def test_campaign_speaking_false_outside_speech_stage() -> None:
    # PK 发言期与其他子阶段不算上警发言
    assert not campaign_speaking(
        _state(election_stage="withdraw", speech_order=(1, 2), speech_idx=0)
    )
    assert not campaign_speaking(
        _state(phase=Phase.SHERIFF_PK, speech_order=(1, 2), speech_idx=0)
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_campaign_speech.py -q`
Expected: 收集期 `ImportError: cannot import name 'CampaignSpeechOrder'`

- [ ] **Step 3: 实现**

`app/engine/config.py`——在 `class SheriffRule` 之前加枚举，并给 `SheriffRule` 加两个字段：

```python
class CampaignSpeechOrder(StrEnum):
    """上警发言顺序（issue #47）。"""

    JUDGE_ODD_EVEN = "JUDGE_ODD_EVEN"  # 法官「单顺双逆」：seeded RNG 抽奇偶，座号升序或降序
    SEAT_ASC = "SEAT_ASC"  # 固定座号升序（无随机对照）


class SheriffRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = True
    vote_weight: float = 1.5
    election_before_first_death_announce: bool = True
    badge_flow_enabled: bool = True
    badge_flow_max_length: int = 2  # 警徽流最多声明几夜（「一般留两夜」为约定，可配置）
    wolf_selfdestruct_eats_badge: bool = True
    campaign_speech_enabled: bool = True  # 上警发言子阶段（issue #47）；False = 上警后直接退水确认
    campaign_speech_order: CampaignSpeechOrder = CampaignSpeechOrder.JUDGE_ODD_EVEN
```

`app/engine/phases.py`——枚举加值（放在 `CANDIDACY` 与 `WITHDRAW` 之间）：

```python
    CANDIDACY = "candidacy"
    SPEECH = "speech"  # 上警发言（issue #47）：候选人按 speech_order 依次发言
    WITHDRAW = "withdraw"
```

同文件，在 `expected_actors` 定义之前加 helper：

```python
def campaign_speaking(state: GameState) -> bool:
    """上警发言回合进行中（issue #47）：竞选 speech 子阶段且发言队列未耗尽。"""
    return (
        state.phase == Phase.SHERIFF_ELECTION
        and state.election_stage == ElectionStage.SPEECH
        and state.speech_idx < len(state.speech_order)
    )
```

同文件，`expected_actors` 的 `SHERIFF_ELECTION` 分支里，在 `candidacy` 判断之后、`withdraw` 判断之前插入：

```python
        if state.election_stage == "speech":
            # 上警发言：仅当前发言者；队列耗尽后空集 -> advance 进入退水确认
            if state.speech_idx < len(state.speech_order):
                return {state.speech_order[state.speech_idx]}
            return set()
```

`app/engine/events.py`——载荷加字段：

```python
class ElectionStageChangedPayload(EventPayload):
    stage: ElectionStage  # 子阶段标记；reduce 据此写 election_stage（issue #17）
    # 进入 speech 子阶段时一并设定上警发言顺序（issue #47）；与 PhaseChangedPayload.speech_order 同语义
    speech_order: tuple[int, ...] | None = None
```

同文件 reduce 分支替换为：

```python
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        stage_upd: dict[str, object] = {"election_stage": p.stage.value}
        if p.speech_order is not None:
            stage_upd["speech_order"] = p.speech_order
            stage_upd["speech_idx"] = 0
        return stage_upd
```

`tests/test_election_timeline.py::test_election_stage_enum_values` 加一行：

```python
    assert ElectionStage.SPEECH.value == "speech"
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `uv run pytest tests/test_campaign_speech.py tests/test_election_timeline.py tests/test_event_store.py tests/test_determinism.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿（行为零变化）

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/config.py backend/app/engine/phases.py backend/app/engine/events.py backend/tests/test_campaign_speech.py backend/tests/test_election_timeline.py
git commit -m "feat(engine): 上警发言契约层——CampaignSpeechOrder、ElectionStage.SPEECH、speech_order 载荷 (issue #47)"
```

---

### Task 2: 内置驱动先行——RandomBot 与超时默认行动支持 speech 子阶段

引擎在 Task 3 才会发射 `speech`。先让两个内置驱动认识它，Task 3 落地时 `run_game` 扫描与 runner 超时路径才不会断。本任务用**直接构造**的 `speech` 状态测试。

**Files:**
- Modify: `backend/app/cli/bot.py`
- Modify: `backend/app/runtime/defaults.py`（PK 发言分支约 line 41）
- Test: `backend/tests/test_campaign_speech.py`、`backend/tests/test_runtime_defaults.py`

**Interfaces:**
- Consumes: `app.engine.phases.campaign_speaking(state) -> bool`（Task 1）
- Produces:
  - `RandomBot.choose_action` 在上警发言回合返回 `Speak(content="(bot-campaign)", badge_flow=…)`
  - `default_action` 在上警发言回合返回 `Speak(content=TIMEOUT_SPEECH)`
  - `app.cli.bot._bot_badge_flow(state: GameState, seat: int, seed: int) -> tuple[int, ...]`（模块私有）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_campaign_speech.py` 末尾：

```python
# ---------- Task 2：内置驱动 ----------


def test_bot_speaks_in_campaign_speech() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    st = _state(
        election_stage="speech", sheriff_candidates=(2, 3), speech_order=(3, 2), speech_idx=0
    )
    a = RandomBot.choose_action(st, 3)  # 3 号是好人：不会触发狼自爆掷骰
    assert isinstance(a, Speak)
    assert a.actor_seat == 3 and a.content == "(bot-campaign)"


def test_bot_campaign_badge_flow_sometimes_and_always_wellformed() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    seen_claim = False
    for seed in range(1, 41):
        st = _state(
            seed=seed,
            election_stage="speech",
            sheriff_candidates=(2, 3),
            speech_order=(3, 2),
            speech_idx=0,
        )
        a = RandomBot.choose_action(st, 3)
        assert isinstance(a, Speak)
        bf = a.badge_flow
        assert len(bf) <= st.config.sheriff.badge_flow_max_length
        assert len(set(bf)) == len(bf) and 3 not in bf
        seen_claim = seen_claim or bool(bf)
    assert seen_claim  # 1/4 概率，40 个 seed 内必现


def test_bot_no_badge_flow_when_disabled() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    for seed in range(1, 41):
        st = _state(
            seed=seed,
            sheriff=SheriffRule(badge_flow_enabled=False),
            election_stage="speech",
            sheriff_candidates=(2, 3),
            speech_order=(3, 2),
            speech_idx=0,
        )
        a = RandomBot.choose_action(st, 3)
        assert isinstance(a, Speak) and a.badge_flow == ()
```

追加到 `backend/tests/test_runtime_defaults.py` 末尾：

```python
def test_default_in_campaign_speech_is_empty_speech() -> None:
    # 上警发言回合超时：空发言跳过，不得落入 vote 分支（issue #47）
    from app.engine.state import GameState

    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 1})
    base = create_game(cfg, game_id="g").state
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.SHERIFF_ELECTION,
        round=1,
        players=base.players,
        election_stage="speech",
        sheriff_candidates=(1, 2),
        speech_order=(2, 1),
        speech_idx=0,
    )
    assert default_action(st, 2) == Speak(actor_seat=2, content=TIMEOUT_SPEECH)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_campaign_speech.py tests/test_runtime_defaults.py::test_default_in_campaign_speech_is_empty_speech -q`
Expected: bot 三例 FAIL（bot 返回 `SheriffAction(VOTE_SHERIFF)` 而非 `Speak`）；defaults 一例 FAIL（同因）

- [ ] **Step 3: 实现**

`app/cli/bot.py`——import 改为：

```python
from app.engine.phases import Phase, campaign_speaking, expected_actors
```

在 `_legal_night_targets` 之后加模块级 helper（**RNG purpose 串与原内联代码逐字一致**，保证 PK 路径字节级不变）：

```python
def _bot_badge_flow(state: GameState, seat: int, seed: int) -> tuple[int, ...]:
    """竞选语境发言以 1/4 概率附带一份结构合法的警徽流声明；警徽流关闭时恒空。"""
    if not state.config.sheriff.badge_flow_enabled:
        return ()
    if rng.derive_int(seed=seed, purpose=f"bot:{seat}:bf", seq=state.state_version, modulo=4) != 0:
        return ()
    targets = [s for s in living_seats(state) if s != seat]
    if not targets:
        return ()
    n_claim = 1 + rng.derive_int(
        seed=seed, purpose=f"bot:{seat}:bfn", seq=state.state_version, modulo=2
    )
    picks: list[int] = []
    for k in range(min(n_claim, len(targets))):
        idx = rng.derive_int(
            seed=seed, purpose=f"bot:{seat}:bf{k}", seq=state.state_version, modulo=len(targets)
        )
        if targets[idx] not in picks:
            picks.append(targets[idx])
    return tuple(picks)
```

`choose_action` 里，把现有「PK 发言期」整块（从 `if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):` 到 `return Speak(actor_seat=seat, content="(bot-pk)", badge_flow=bf)`）替换为：

```python
        if campaign_speaking(state):
            # 上警发言（issue #47）：轮到的候选人发言，1/4 概率附带合法警徽流声明
            return Speak(
                actor_seat=seat,
                content="(bot-campaign)",
                badge_flow=_bot_badge_flow(state, seat, seed),
            )

        if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):
            # PK 发言期：轮到的平票者发言；警上 PK 以 1/4 概率附带合法警徽流声明
            bf = _bot_badge_flow(state, seat, seed) if ph == Phase.SHERIFF_PK else ()
            return Speak(actor_seat=seat, content="(bot-pk)", badge_flow=bf)
```

`app/runtime/defaults.py`——import 改为 `from app.engine.phases import ElectionStage, Phase, campaign_speaking`，并把 PK 发言分支扩为：

```python
    # 发言队列型窗口（PK 发言 / 上警发言，issue #47）：空发言跳过
    if campaign_speaking(state) or (
        ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order)
    ):
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)
```

- [ ] **Step 4: 跑测试确认通过 + PK 路径字节级不变**

Run: `uv run pytest tests/test_campaign_speech.py tests/test_runtime_defaults.py tests/test_pk_speech.py tests/test_badge_flow.py tests/test_determinism.py tests/test_sweep.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/cli/bot.py backend/app/runtime/defaults.py backend/tests/test_campaign_speech.py backend/tests/test_runtime_defaults.py
git commit -m "feat(cli,runtime): RandomBot 与超时默认行动支持上警发言子阶段 (issue #47)"
```

---

### Task 3: 引擎——speech 子阶段转移、发言/警徽流校验、发言期 SheriffAction 守卫

**Files:**
- Modify: `backend/app/engine/engine.py`（import 块；`_validate` 的 `Speak` 门约 line 233；`_validate_sheriff` 约 line 394；`_advance_election` 约 line 1043）
- Modify: `backend/tests/factories.py`
- Modify: `backend/tests/test_election_timeline.py`（`_VALID_NEXT`）
- Modify: `backend/tests/test_runtime_defaults.py`（`_sweep` 内加 speech 断言）
- Modify: `backend/tests/test_pk_speech.py`（既有漏洞回归）
- Modify: `docs/specs/requirements.md`（§3.2 `SheriffRule`，约 line 139）、`README.md`（line 92、line 126）
- Test: `backend/tests/test_campaign_speech.py`

**Interfaces:**
- Consumes: Task 1 的 `CampaignSpeechOrder`、`SheriffRule.campaign_speech_*`、`ElectionStage.SPEECH`、`campaign_speaking`、`ElectionStageChangedPayload.speech_order`；Task 2 的 bot/默认行动（全局扫描依赖）。
- Produces:
  - 引擎行为：`candidacy` 收尾 →（开关开）`ELECTION_STAGE_CHANGED(stage=SPEECH, speech_order=…)`；队列耗尽 → `ELECTION_STAGE_CHANGED(stage=WITHDRAW)`。
  - `tests.factories.run_campaign_speeches(state: GameState, content: str = "竞选发言") -> tuple[GameState, list[Event]]`

- [ ] **Step 1: 写测试辅助**

`backend/tests/factories.py` 末尾追加（并在文件头补 import）：

```python
from app.engine.actions import Speak
from app.engine.engine import step
from app.engine.events import Event
from app.engine.phases import campaign_speaking
from app.engine.state import GameState


def run_campaign_speeches(
    state: GameState, content: str = "竞选发言"
) -> tuple[GameState, list[Event]]:
    """让上警发言队列里的候选人依次发言，直到离开 speech 子阶段（issue #47）。"""
    events: list[Event] = []
    while campaign_speaking(state):
        seat = state.speech_order[state.speech_idx]
        res = step(state, Speak(actor_seat=seat, content=content))
        assert res.rejection is None, res.rejection
        state = res.state
        events.extend(res.events)
    return state, events
```

- [ ] **Step 2: 写失败测试**

追加到 `backend/tests/test_campaign_speech.py` 末尾：

```python
# ---------- Task 3：引擎 ----------


def _finish_candidacy(
    sheriff: SheriffRule | None = None,
    seed: int = 1,
    cands: tuple[int, ...] = (1, 2, 3),
    wolves: tuple[int, ...] = (0,),
):
    """6 人局 candidacy 收尾：0-4 已声明，5 号最后声明不上警 -> 引擎推进子阶段。"""
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.engine import step

    st = _state(
        sheriff=sheriff,
        seed=seed,
        wolves=wolves,
        election_stage="candidacy",
        sheriff_declared=frozenset({0, 1, 2, 3, 4}),
        sheriff_candidates=cands,
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    return res


def _stage_events(events: list[Event]) -> list[ElectionStageChangedPayload]:
    out = []
    for e in events:
        if e.type == EventType.ELECTION_STAGE_CHANGED:
            assert isinstance(e.payload, ElectionStageChangedPayload)
            out.append(e.payload)
    return out


def test_candidacy_flows_into_speech_with_order_in_event() -> None:
    res = _finish_candidacy()
    st = res.state
    assert st.election_stage == "speech"
    assert sorted(st.speech_order) == [1, 2, 3] and st.speech_idx == 0
    assert expected_actors(st) == {st.speech_order[0]}
    stages = _stage_events(res.events)
    assert [p.stage.value for p in stages] == ["speech"]
    assert stages[0].speech_order == st.speech_order  # 顺序随事件入流，回放不重算 RNG


def test_seat_asc_order() -> None:
    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    for seed in range(1, 11):
        assert _finish_candidacy(sheriff=sr, seed=seed, cands=(3, 1, 2)).state.speech_order == (
            1,
            2,
            3,
        )


def test_judge_odd_even_both_directions_and_deterministic() -> None:
    orders = {seed: _finish_candidacy(seed=seed).state.speech_order for seed in range(1, 21)}
    assert set(orders.values()) == {(1, 2, 3), (3, 2, 1)}  # 单顺双逆：只有升序/降序两种
    again = {seed: _finish_candidacy(seed=seed).state.speech_order for seed in range(1, 21)}
    assert again == orders  # 同 seed 可复现


def test_speech_flow_then_withdraw_stage() -> None:
    from tests.factories import run_campaign_speeches

    st = _finish_candidacy().state
    order = st.speech_order
    st2, events = run_campaign_speeches(st)
    spoke = [e.actor_seat for e in events if e.type == EventType.PLAYER_SPOKE]
    assert tuple(spoke) == order
    assert st2.election_stage == "withdraw"
    assert st2.sheriff_confirmed == frozenset()
    assert expected_actors(st2) == {1, 2, 3}  # 既有退水确认照旧


def test_no_candidates_skips_speech() -> None:
    res = _finish_candidacy(cands=())
    assert res.state.election_stage == ""
    assert all(p.stage != ElectionStage.SPEECH for p in _stage_events(res.events))


def test_disabled_toggle_goes_straight_to_withdraw() -> None:
    res = _finish_candidacy(sheriff=SheriffRule(campaign_speech_enabled=False))
    assert res.state.election_stage == "withdraw"
    assert [p.stage.value for p in _stage_events(res.events)] == ["withdraw"]


def test_rejection_matrix() -> None:
    from app.engine.actions import RejectedReason, SheriffAction, SheriffActionType, Speak
    from app.engine.engine import step
    from tests.factories import run_campaign_speeches

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr).state  # 顺序 (1,2,3)，轮到 1

    # 非当前发言者 / 警下玩家发言
    assert step(st, Speak(actor_seat=2, content="x")).rejection == RejectedReason.NOT_YOUR_TURN
    assert step(st, Speak(actor_seat=4, content="x")).rejection == RejectedReason.NOT_YOUR_TURN
    # 当前发言者在发言期提交任何警长行动 -> WRONG_PHASE（含投票：堵住兜底分支）
    for at, tgt in (
        (SheriffActionType.RUN_FOR_SHERIFF, None),
        (SheriffActionType.WITHDRAW, None),
        (SheriffActionType.VOTE_SHERIFF, 2),
    ):
        r = step(st, SheriffAction(actor_seat=1, action_type=at, target_seat=tgt))
        assert r.rejection == RejectedReason.WRONG_PHASE, at
        assert r.state.sheriff_votes == {}
    # 其他人提交警长行动 -> NOT_YOUR_TURN
    r = step(
        st, SheriffAction(actor_seat=4, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    )
    assert r.rejection == RejectedReason.NOT_YOUR_TURN

    # 发言结束后（withdraw 子阶段）候选人再 Speak -> WRONG_PHASE
    st_w, _ = run_campaign_speeches(st)
    assert step(st_w, Speak(actor_seat=1, content="x")).rejection == RejectedReason.WRONG_PHASE


def test_badge_flow_in_campaign_speech() -> None:
    from app.engine.actions import RejectedReason, Speak
    from app.engine.engine import step

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr).state
    ok = step(st, Speak(actor_seat=1, content="我是预言家", badge_flow=(4, 5)))
    assert ok.rejection is None
    assert ok.state.badge_flow_claims == {1: (4, 5)}

    for bad in ((4, 5, 0), (4, 4)):  # 超长 / 重复
        r = step(st, Speak(actor_seat=1, content="x", badge_flow=bad))
        assert r.rejection == RejectedReason.BADGE_FLOW_INVALID, bad

    off = SheriffRule(
        campaign_speech_order=CampaignSpeechOrder.SEAT_ASC, badge_flow_enabled=False
    )
    st_off = _finish_candidacy(sheriff=off).state
    r = step(st_off, Speak(actor_seat=1, content="x", badge_flow=(4,)))
    assert r.rejection == RejectedReason.BADGE_FLOW_INVALID


def test_self_destruct_mid_speech_eats_badge_and_skips_day() -> None:
    from app.engine.actions import SelfDestruct, Speak
    from app.engine.engine import step
    from app.engine.events import PhaseChangedPayload, SheriffBadgeLostPayload

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr, wolves=(0, 4)).state
    st = step(st, Speak(actor_seat=1, content="first")).state  # 发言进行到一半
    res = step(st, SelfDestruct(actor_seat=0))  # 警下狼自爆，不受发言轮次限制
    assert res.rejection is None
    assert res.state.sheriff_seat is None and res.state.election_stage == ""
    assert any(
        isinstance(e.payload, SheriffBadgeLostPayload) and e.payload.reason == "SELF_DESTRUCT"
        for e in res.events
    )
    assert not any(
        isinstance(e.payload, PhaseChangedPayload) and e.payload.to == Phase.DAY_SPEECH
        for e in res.events
    )  # 立即天黑：当天无发言


def test_stepwise_replay_equals_live_during_campaign_speech() -> None:
    # 回放保真（不给 issue #37 添新债）：发言中途任意前缀重放与 live 逐字段相等
    from app.cli.bot import RandomBot
    from app.engine.engine import create_game, step
    from app.engine.events import reduce_all

    mid_speech_points = 0
    for seed in (7, 8, 9):
        cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": seed})
        res = create_game(cfg, "g")
        state, events = res.state, list(res.events)
        blank = GameState(
            game_id=state.game_id,
            config=state.config,
            phase=Phase.LOBBY,
            round=0,
            players=tuple(
                Player(
                    seat=p.seat,
                    display_name=p.display_name,
                    role=RoleType.VILLAGER,
                    faction=Faction.GOOD,
                )
                for p in state.players
            ),
        )
        guard = 0
        while state.phase not in (Phase.GAME_OVER, Phase.DAY_SPEECH):
            for seat in sorted(expected_actors(state)):
                if seat not in expected_actors(state):
                    continue
                r = step(state, RandomBot.choose_action(state, seat))
                assert r.rejection is None
                state, events = r.state, [*events, *r.events]
                if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "speech":
                    replayed = reduce_all(blank, events)
                    assert replayed.election_stage == state.election_stage
                    assert replayed.speech_order == state.speech_order
                    assert replayed.speech_idx == state.speech_idx
                    assert replayed.badge_flow_claims == state.badge_flow_claims
                    mid_speech_points += 1
            guard += 1
            assert guard < 10_000
    assert mid_speech_points > 0  # 样本里确实走到了上警发言


def test_full_games_with_campaign_speech_terminate() -> None:
    from app.cli.bot import run_game

    saw_speech = False
    for preset in ("std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side"):
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            final, events = run_game(cfg, "g")
            assert final.phase == Phase.GAME_OVER
            saw_speech = saw_speech or any(
                p.stage == ElectionStage.SPEECH for p in _stage_events(events)
            )
    assert saw_speech
```

追加到 `backend/tests/test_pk_speech.py` 末尾（既有漏洞回归）：

```python
def test_pk_speaker_cannot_vote_during_pk_speech() -> None:
    # issue #47 顺带修复：SHERIFF_PK 发言期，当前发言者（平票候选人）曾可经
    # _validate_sheriff 兜底分支投票并计入票型。
    from app.engine.actions import RejectedReason, SheriffAction, SheriffActionType

    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 6, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.SHERIFF_PK,
        round=1,
        players=_players(6, wolves=(1,)),
        sheriff_candidates=(1, 2),
        speech_order=(1, 2),
        speech_idx=0,
        night_deaths=(),
        resolved_first_night=True,
    )
    res = step(
        st, SheriffAction(actor_seat=1, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    )
    assert res.rejection == RejectedReason.WRONG_PHASE
    assert res.state.sheriff_votes == {}
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_campaign_speech.py tests/test_pk_speech.py -q`
Expected: Task 3 段新测试 FAIL（`election_stage == "withdraw"` 而非 `"speech"` 等）；`test_pk_speaker_cannot_vote_during_pk_speech` FAIL（`rejection is None`）；`test_disabled_toggle_*`、`test_no_candidates_*` 可能已 PASS（现行为即如此）

- [ ] **Step 4: 实现引擎**

`app/engine/engine.py` import：`from app.engine.config import (...)` 块加入 `CampaignSpeechOrder`；phases 的 import 加入 `campaign_speaking`（与现有 `ElectionStage`/`Phase`/`expected_actors` 同一条 import）。

**(a) `_validate` 的 `Speak` 门**——替换为：

```python
    if isinstance(action, Speak):
        # 发言合法阶段：白天发言、遗言、PK 发言期、上警发言期（队列未耗尽）
        pk_speaking = state.phase in (Phase.VOTE_PK, Phase.SHERIFF_PK) and (
            state.speech_idx < len(state.speech_order)
        )
        campaigning = campaign_speaking(state)
        if (
            state.phase not in (Phase.DAY_SPEECH, Phase.LAST_WORDS)
            and not pk_speaking
            and not campaigning
        ):
            return RejectedReason.WRONG_PHASE
        if (
            state.phase == Phase.DAY_SPEECH or pk_speaking
        ) and state.config.speech_order_rule == SpeechOrderRule.BIDDING:
            return RejectedReason.BIDDING_NOT_IMPLEMENTED
        if action.badge_flow:
            # 警徽流：仅竞选语境发言（SHERIFF_PK 发言回合 / 上警发言）接受；
            # 只验结构，不验真实性/角色（悍跳合法）
            sr = state.config.sheriff
            if (
                not ((state.phase == Phase.SHERIFF_PK and pk_speaking) or campaigning)
                or not sr.badge_flow_enabled
                or len(action.badge_flow) > sr.badge_flow_max_length
                or len(set(action.badge_flow)) != len(action.badge_flow)
                or not all(_alive_target(state, s) for s in action.badge_flow)
            ):
                return RejectedReason.BADGE_FLOW_INVALID
        return None
```

（BIDDING 拒绝不镜像到上警发言：其顺序由 `campaign_speech_order` 独立决定。）

**(b) `_validate_sheriff` 的发言期守卫**——紧跟在 `if a.actor_seat not in expected_actors(state): return RejectedReason.NOT_YOUR_TURN` 之后、`at = a.action_type` 之前插入：

```python
    # 发言期守卫（issue #47）：竞选语境下发言队列未耗尽时不接受任何警长行动。
    # 当前发言者恰在 expected_actors 内，不设此守卫则 VOTE_SHERIFF 会落入末尾兜底分支被接受
    # （SHERIFF_PK 发言期的同一口子为既有漏洞，一并堵上）。
    if campaign_speaking(state) or (
        state.phase == Phase.SHERIFF_PK and state.speech_idx < len(state.speech_order)
    ):
        return RejectedReason.WRONG_PHASE
```

**(c) 顺序计算与子阶段转移**——在 `_advance_election` 之前加两个函数：

```python
def _campaign_speech_order(state: GameState) -> tuple[int, ...]:
    """上警发言顺序（issue #47）。JUDGE_ODD_EVEN = 法官「看时间单顺双逆」：
    引擎无钟表，以 seeded RNG 抽奇偶位，在座号升序/降序间二选一。"""
    asc = tuple(sorted(state.sheriff_candidates))
    if state.config.sheriff.campaign_speech_order == CampaignSpeechOrder.SEAT_ASC:
        return asc
    seed = state.config.seed if state.config.seed is not None else 0
    flip = rng.derive_int(
        seed=seed, purpose="campaign_speech_dir", seq=state.state_version, modulo=2
    )
    return asc if flip == 0 else tuple(reversed(asc))


def _enter_withdraw(state: GameState, events: list[Event]) -> tuple[GameState, list[Event]]:
    """进入退水确认子阶段（confirmed 是游标，保持 model_copy）。"""
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

`_advance_election` 的 `candidacy` 分支替换为（并新增 `speech` 分支）：

```python
    if state.election_stage == "candidacy":
        # 全员声明完毕
        if not state.sheriff_candidates:
            return _lose_badge(state, BadgeLostReason.NO_CANDIDATES, events)
        if state.config.sheriff.campaign_speech_enabled:
            # 上警发言（issue #47）：顺序一次算定并随事件入流，回放不重算 RNG
            state, e = _emit(
                state,
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(
                    stage=ElectionStage.SPEECH, speech_order=_campaign_speech_order(state)
                ),
                Visibility.PUBLIC,
            )
            events.append(e)
            return state, events
        return _enter_withdraw(state, events)
    if state.election_stage == "speech":
        # 上警发言队列耗尽 -> 退水确认
        return _enter_withdraw(state, events)
```

- [ ] **Step 5: 适配既有测试的时间线语法与扫描断言**

`tests/test_election_timeline.py` 的 `_VALID_NEXT` 改为：

```python
_VALID_NEXT: dict[str, set[str]] = {
    "candidacy": {"speech", "withdraw", ""},  # withdraw 直达 = campaign_speech_enabled=False
    "speech": {"withdraw", ""},
    "withdraw": {"vote", ""},
    "vote": {"direction", ""},
    "direction": {"announce", ""},
    "announce": {""},
}
```

`tests/test_runtime_defaults.py::_sweep` 内，在 `CANDIDACY` 断言块之后加：

```python
            if (
                state.phase == Phase.SHERIFF_ELECTION
                and state.election_stage == ElectionStage.SPEECH
            ):
                # 上警发言超时默认空发言，不得落投票分支
                assert isinstance(d, Speak)
                assert d.content == TIMEOUT_SPEECH
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_campaign_speech.py tests/test_pk_speech.py tests/test_election_timeline.py tests/test_runtime_defaults.py -q`
Expected: 全部 PASS

- [ ] **Step 7: 全量回归（含 E2E）**

Run: `uv run pytest -q`
Expected: 全绿（4 个 `AGENTHOWL_SMOKE_MODEL` 门控 skip 属正常）。

若有既有用例因「candidacy 之后多出 speech」失败：该用例必是**逐步驱动穿过 candidacy** 的（直接构造 `withdraw`/`vote` 状态的用例不受影响）。修法统一为在其 candidacy 收尾后插入 `state, _ = run_campaign_speeches(state)`（`from tests.factories import run_campaign_speeches`），**不得**用 `campaign_speech_enabled=False` 回避。

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全过

- [ ] **Step 8: 文档同步**

`docs/specs/requirements.md` §3.2 的 `SheriffRule`（约 line 139）改为：

```python
class CampaignSpeechOrder(str, Enum):
    JUDGE_ODD_EVEN = "JUDGE_ODD_EVEN"   # 法官「单顺双逆」：seeded RNG 抽奇偶，座号升序或降序（默认）
    SEAT_ASC       = "SEAT_ASC"         # 固定座号升序

class SheriffRule(BaseModel):
    enabled: bool = True
    vote_weight: float = 1.5
    election_before_first_death_announce: bool = True    # 竞选在公布死讯前
    badge_flow_enabled: bool = True                      # 警徽流
    wolf_selfdestruct_eats_badge: bool = True            # 自爆吞警徽
    campaign_speech_enabled: bool = True                 # 上警发言子阶段（候选人依次发言后再退水）
    campaign_speech_order: CampaignSpeechOrder = CampaignSpeechOrder.JUDGE_ODD_EVEN
```

`README.md` line 92 的「警长竞选（退水、警徽流、…）」改为「警长竞选（上警发言及其顺序、退水、警徽流、…）」；line 126 改为：

```markdown
- 警长竞选完整子阶段机（上警 → 上警发言 → 退水确认 → 投票 → 方向决策 → 公布），上警发言顺序按法官「单顺双逆」经 seeded RNG 决定；全部子阶段边界经 `ELECTION_STAGE_CHANGED` 事件可从日志重建
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/engine/engine.py backend/tests/ docs/specs/requirements.md README.md
git commit -m "feat(engine): 警长竞选上警发言子阶段——单顺双逆定序、警徽流放宽、发言期警长行动守卫 (issue #47)"
```

---

### Task 4: Agent 层——speech 分派、警徽流开放条件、上警发言引导语

**Files:**
- Modify: `backend/app/agent/decisions.py`（`decision_kind_for` 的 `SHERIFF_ELECTION` 分支，约 line 107）
- Modify: `backend/app/agent/prompts.py`（`_BADGE_FLOW_PHASES` 约 line 34-38；`_speech_instruction` 约 line 92）
- Test: `backend/tests/test_agent_decisions.py`、`backend/tests/test_agent_prompts.py`

**Interfaces:**
- Consumes: `PlayerObservation.phase: str`、`PlayerObservation.election_stage: str`（既有字段）；`ElectionStage.SPEECH`（Task 1）。
- Produces: `decision_kind_for(obs)` 在 `SHERIFF_ELECTION`+`speech` 返回 `DecisionKind.SPEECH`；`build_prompt(DecisionKind.SPEECH, …)` 在该回合含 `badge_flow` 与上警发言引导语。

狼人的上警发言因 kind=`SPEECH` 自动走既有昼间装配路径——`build_prompt` 签名拿不到 `night_private` 分区（`test_day_prompt_builder_has_no_private_param` 已钉死），公私隔离无需新代码。

- [ ] **Step 1: 写失败测试**

`tests/test_agent_decisions.py` 的 `test_dispatch` 参数表里，在 `("SHERIFF_ELECTION", {"election_stage": "vote"}, DecisionKind.SHERIFF),` 之后加：

```python
        # 上警发言子阶段（issue #47）走发言决策
        ("SHERIFF_ELECTION", {"election_stage": "speech"}, DecisionKind.SPEECH),
        ("SHERIFF_ELECTION", {"election_stage": "withdraw"}, DecisionKind.SHERIFF),
```

`tests/test_agent_prompts.py`：把 `test_badge_flow_mentioned_only_in_sheriff_pk` 整体替换为：

```python
def test_badge_flow_mentioned_only_in_election_speech_contexts() -> None:
    # badge_flow 仅在竞选语境发言引擎合法：SHERIFF_PK 发言回合 / 上警发言（issue #47）
    obs_pk = _obs("SHERIFF_PK", pk_speech_pending=True)
    assert "badge_flow" in build_prompt(DecisionKind.SPEECH, obs_pk, "", agent_seed=1)

    obs_campaign = _obs("SHERIFF_ELECTION", election_stage="speech")
    assert "badge_flow" in build_prompt(DecisionKind.SPEECH, obs_campaign, "", agent_seed=1)

    obs_day = _obs("DAY_SPEECH")
    assert "badge_flow" not in build_prompt(DecisionKind.SPEECH, obs_day, "", agent_seed=1)


def test_campaign_speech_guidance_only_in_campaign_speech() -> None:
    obs_campaign = _obs("SHERIFF_ELECTION", election_stage="speech")
    up = build_prompt(DecisionKind.SPEECH, obs_campaign, "", agent_seed=1)
    assert "上警发言" in up and "self_destruct" in up

    for obs in (_obs("DAY_SPEECH"), _obs("SHERIFF_PK", pk_speech_pending=True)):
        assert "上警发言" not in build_prompt(DecisionKind.SPEECH, obs, "", agent_seed=1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_decisions.py tests/test_agent_prompts.py -q`
Expected: 新增 dispatch 参数例 FAIL（得到 `SHERIFF`）；两个 prompt 测试 FAIL（无 `badge_flow` / 无「上警发言」）

- [ ] **Step 3: 实现**

`app/agent/decisions.py`：

```python
    if ph == Phase.SHERIFF_ELECTION:
        # 上警发言子阶段（issue #47）走发言决策；其余子阶段为警长行动
        if obs.election_stage == ElectionStage.SPEECH:
            return DecisionKind.SPEECH
        return DecisionKind.SHERIFF
```

`app/agent/prompts.py`——把注释块与 `_BADGE_FLOW_PHASES` 常量替换为：

```python
# 评审修正（Task 2 review 摘要）：badge_flow 仅在竞选语境发言引擎合法
# （SHERIFF_PK 发言回合 / 上警发言，issue #47），
# self_destruct 仅在 DAY_SPEECH/SHERIFF_ELECTION/SHERIFF_PK 引擎合法，
# 其它阶段提交会被引擎拒绝（BADGE_FLOW_INVALID 等）——指令段按阶段裁剪提示，
# 避免诱导 agent 提交必然非法的字段。
_SELF_DESTRUCT_PHASES = frozenset({"DAY_SPEECH", "SHERIFF_ELECTION", "SHERIFF_PK"})

_CAMPAIGN_SPEECH_GUIDE = (
    "你正在警长竞选的上警发言：说明为什么应由你当警长，可声称身份。"
    "若你是（或要悍跳）预言家，报出查验结果，并用 badge_flow 给出警徽流（未来两夜的验人顺序）。"
    "全部候选人发言结束后你还有一次退水机会"
)


def _is_campaign_speech(obs: PlayerObservation) -> bool:
    return obs.phase == "SHERIFF_ELECTION" and obs.election_stage == "speech"
```

`_speech_instruction` 替换为：

```python
def _speech_instruction(obs: PlayerObservation) -> str:
    parts = ["给出你的发言 content；可选声称身份 claim_role"]
    campaign = _is_campaign_speech(obs)
    if campaign:
        parts.insert(0, _CAMPAIGN_SPEECH_GUIDE)
    if campaign or obs.phase == "SHERIFF_PK":
        parts.append("可报警徽流 badge_flow")
    if obs.phase in _SELF_DESTRUCT_PHASES:
        parts.append("狼人可选 self_destruct 自爆")
    return "；".join(parts) + "。"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_agent_decisions.py tests/test_agent_prompts.py tests/test_agent_player.py tests/test_agent_integration.py tests/test_acceptance_m25.py -q`
Expected: 全部 PASS（集成/验收用例经 `ScriptedLLMClient` 把 bot 行动映射成决策；上警发言回合 bot 给 `Speak` → `SpeechDecision`，与新分派一致）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/decisions.py backend/app/agent/prompts.py backend/tests/test_agent_decisions.py backend/tests/test_agent_prompts.py
git commit -m "feat(agent): 上警发言分派为 SPEECH；警徽流提示放宽至上警发言 + 竞选引导语 (issue #47)"
```

---

### Task 5: 工具提示与 CLI 叙述

**Files:**
- Modify: `backend/app/schemas/actions.py`（`available_tools_for`，约 line 108）
- Modify: `backend/app/cli/render.py`（import 块；`render_event` 的 `SHERIFF_CANDIDACY` 分支之前）
- Test: `backend/tests/test_schemas.py`、`backend/tests/test_cli_render.py`

**Interfaces:**
- Consumes: `PlayerObservation.election_stage`；`ElectionStageChangedPayload.speech_order`、`ElectionStage`（Task 1）。
- Produces: speech 子阶段工具提示 `("speak", "self_destruct", "get_game_state", "get_speeches")`；`ELECTION_STAGE_CHANGED` 的中文叙述行。

加 `speech_order` 字段后，`ELECTION_STAGE_CHANGED` 的通用回退渲染会变成 `stage=withdraw，speech_order=None`，故为该事件补专用叙述。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_schemas.py` 末尾：

```python
def test_available_tools_in_campaign_speech() -> None:
    # 上警发言子阶段（issue #47）：只提示发言/自爆，不提示 sheriff_action
    from app.engine.config import RoleType
    from app.engine.observation import PlayerObservation
    from app.schemas.actions import available_tools_for

    def obs(stage: str) -> PlayerObservation:
        return PlayerObservation(
            game_id="g",
            state_version=1,
            my_seat=0,
            my_role=RoleType.VILLAGER,
            my_status="ALIVE",
            phase="SHERIFF_ELECTION",
            round=1,
            seats=[{"seat": 0, "alive": True, "is_sheriff": False}],
            sheriff_seat=None,
            badge_flow_claims={},
            private={},
            available_actions=[0],
            election_stage=stage,
        )

    assert available_tools_for(obs("speech")) == (
        "speak",
        "self_destruct",
        "get_game_state",
        "get_speeches",
    )
    assert "sheriff_action" in available_tools_for(obs("vote"))
```

追加到 `backend/tests/test_cli_render.py` 末尾：

```python
def test_render_election_stage_changes() -> None:
    from app.engine.events import ElectionStageChangedPayload
    from app.engine.phases import ElectionStage

    speech = render_event(
        _ev(
            EventType.ELECTION_STAGE_CHANGED,
            ElectionStageChangedPayload(stage=ElectionStage.SPEECH, speech_order=(8, 5, 4)),
        )
    )
    assert "上警发言" in speech and "8号、5号、4号" in speech

    for stage in ElectionStage:
        out = render_event(
            _ev(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=stage))
        )
        assert out.strip() and "speech_order" not in out and "None" not in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_schemas.py::test_available_tools_in_campaign_speech tests/test_cli_render.py::test_render_election_stage_changes -q`
Expected: 两例 FAIL（工具提示含 `sheriff_action`；渲染输出含 `speech_order=`）

- [ ] **Step 3: 实现**

`app/schemas/actions.py`——在 `if ph in ("SHERIFF_ELECTION", "SHERIFF_PK"):` 之前插入：

```python
    if ph == "SHERIFF_ELECTION" and obs.election_stage == "speech":
        # 上警发言子阶段（issue #47）：发言期不接受任何警长行动
        return ("speak", "self_destruct", *_READONLY)
```

`app/cli/render.py`——`from app.engine.events import (...)` 块加入 `ElectionStageChangedPayload`，并新增 `from app.engine.phases import ElectionStage`；在 `_seats` 之后加映射：

```python
_ELECTION_STAGE_ZH = {
    ElectionStage.CANDIDACY: "上警报名",
    ElectionStage.SPEECH: "上警发言",
    ElectionStage.WITHDRAW: "退水确认",
    ElectionStage.VOTE: "警下投票",
    ElectionStage.DIRECTION: "警长决定发言方向",
    ElectionStage.ANNOUNCE: "公布结果",
    ElectionStage.NONE: "竞选环节结束",
}
```

`render_event` 里在 `SHERIFF_CANDIDACY` 分支之前插入：

```python
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        order = f"，顺序：{_seats(p.speech_order)}" if p.speech_order is not None else ""
        return f"【竞选】{_ELECTION_STAGE_ZH[p.stage]}{order}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_schemas.py tests/test_cli_render.py tests/test_cli_play_watch.py tests/test_cli_play_human.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全量（含 E2E）全绿；lint/type 全过

- [ ] **Step 5: 真机看一眼终端叙述**

Run（`backend/` 下；不带 `--ai-model` 即全随机 bot，无需 LLM）:
`uv run python -m app.cli.play --preset std_12_yn_hunter_idiot --seed 7 --view gm --delay 0 --no-color | grep -n -m 12 -E "【竞选】|bot-campaign"`
Expected: 输出里依次出现 `【竞选】上警报名` → `【竞选】上警发言，顺序：…` → 各候选人 `N号发言…：(bot-campaign)` → `【竞选】退水确认` → `【竞选】警下投票`。

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/actions.py backend/app/cli/render.py backend/tests/test_schemas.py backend/tests/test_cli_render.py
git commit -m "feat(cli,schemas): 上警发言工具提示收窄 + 竞选子阶段中文叙述 (issue #47)"
```

---

## Self-Review

- **Spec 覆盖**：§3 配置→Task 1；§4.1 子阶段转移/§4.2 事件→Task 1（载荷/reduce）+ Task 3（发射）；§5 `expected_actors`→Task 1，`Speak` 门/警徽流/发言期守卫（含既有 PK 漏洞）/自爆测试→Task 3；§6 表：defaults、bot→Task 2，decisions、prompts→Task 4，actions、render→Task 5，play_human 无改动；§7 测试清单逐条落在 Task 1–5 的测试代码中（`run_campaign_speeches` 在 Task 3 定义并被新用例使用）；PRD/README→Task 3 Step 8；§8 不在范围项无对应任务（符合预期）。
- **与规格的一处细化**：规格 §7 预期多个既有竞选用例需插入 `run_campaign_speeches`；读码确认这些用例几乎都**直接构造** `withdraw`/`vote` 状态、不穿过 candidacy，实际需改的只有 `test_election_timeline._VALID_NEXT` 与 `_sweep` 断言。Task 3 Step 7 保留了统一修法指令以覆盖遗漏。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码与期望输出。
- **类型一致性**：`campaign_speaking(state) -> bool`、`CampaignSpeechOrder.{JUDGE_ODD_EVEN,SEAT_ASC}`、`ElectionStageChangedPayload.speech_order`、`run_campaign_speeches(state, content) -> tuple[GameState, list[Event]]`、`_bot_badge_flow(state, seat, seed)` 在各任务间名称与签名一致。
