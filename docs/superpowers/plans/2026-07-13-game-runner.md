# GameRunner runtime 层实施计划（issue #29，M2.2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `backend/app/runtime/`：GameRunner 驱动纯引擎跑完整局，玩家经异步 `PlayerPort` 接入，超时/异常/拒绝一律兜底为默认行动，事件同序落 EventStore 并按视角广播；补齐引擎预留事件 `GAME_CREATED`/`GAME_STARTED`。

**Architecture:** 串行开窗严格跟随引擎阶段序（不改引擎的夜序模型）。四个小模块：`defaults.py`（§5.5 默认行动纯函数）、`player_port.py`（Protocol + Bot 实现）、`connection.py`（进程内订阅广播，复用引擎 `visible_events`）、`game_runner.py`（Lobby + Runner 主循环 + meta 充实）。引擎唯一改动：`create_game` 增 roster 参数并头部发射两预留事件。规格见 `docs/superpowers/specs/2026-07-13-game-runner-design.md`。

**Tech Stack:** Python 3.11 asyncio / Pydantic v2 / pytest + pytest-asyncio（新 dev 依赖）。生产依赖不新增。

## Global Constraints

- 所有命令在 `backend/` 下运行：`uv run pytest -q`、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`
- ruff line-length = 100；mypy strict 全量注解；注释/docstring 中文、标识符英文
- 分层：runtime 可 import engine 与 store；engine/store 禁止 import runtime；广播过滤只复用引擎 `observation.visible_events`（隔离单一实现点）
- runtime 对事件的唯一改写点是 `meta`（`wall_ts` ISO8601 墙钟；默认行动补 `timeout: "true"`）；payload/seq/type/visibility 不可动
- 事件先 `store.append` 后 `broadcast`，同序不可乱
- 超时字段：发言型窗口（DAY_SPEECH、LAST_WORDS、VOTE_PK/SHERIFF_PK 的 PK 发言期）用 `config.speech_timeout_sec`，其余用 `config.action_timeout_sec`
- 工作分支：`feat/game-runner`（叠于 feat/event-store，PR base 待 #33 合并后指 main）
- 本分支起点测试基线：230 passed

---

### Task 1: 引擎侧 —— GAME_CREATED/GAME_STARTED 契约 + create_game roster 参数

**Files:**
- Modify: `backend/app/engine/events.py`（payload 类、映射、reduce 分支）
- Modify: `backend/app/engine/engine.py`（RosterEntry、create_game 签名与头部发射）
- Modify: `backend/tests/test_fail_loud.py`（预留集合清空、reserved 测试改写）
- Modify: 全套受 seq 偏移影响的既有测试（见 Step 5 的机械规则）
- Test: `backend/tests/test_engine_core.py`（追加 3 个用例）

**Interfaces:**
- Consumes: 现有 `EventPayload`/`EVENT_PAYLOAD_TYPES`/`_reduce_dispatch`/`create_game`
- Produces（后续任务与 runtime 依赖）:
  - `GameCreatedPayload(EventPayload)`: `num_players: int`
  - `GameStartedPayload(EventPayload)`: 无字段（纯标记）
  - `RosterEntry(BaseModel, frozen)`: `display_name: str`, `player_type: Literal["HUMAN", "AGENT"] = "AGENT"`（定义在 `app/engine/engine.py`，engine 不得依赖 store）
  - `create_game(config: GameConfig, game_id: str, roster: Sequence[RosterEntry] | None = None) -> StepResult`；roster 为 None 时行为与今日一致（`P{seat}`/AGENT）；`len(roster) != config.num_players` → `ValueError`
  - 事件序列头部变为：`GAME_CREATED`(seq=1, PUBLIC) → `GAME_STARTED`(seq=2, PUBLIC) → `ROLES_ASSIGNED`(seq=3, GM_ONLY) → …（既有全部事件 seq +2）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_engine_core.py`（导入区按需补 `EventType`、`Visibility`；`RosterEntry` 在用例内局部导入）：

```python
def test_create_game_emits_lifecycle_head() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    res = create_game(cfg, game_id="g")
    head = [e.type for e in res.events[:3]]
    assert head == [EventType.GAME_CREATED, EventType.GAME_STARTED, EventType.ROLES_ASSIGNED]
    assert [e.seq for e in res.events[:3]] == [1, 2, 3]
    assert res.events[0].visibility == Visibility.PUBLIC
    assert res.events[1].visibility == Visibility.PUBLIC


def test_create_game_applies_roster() -> None:
    from app.engine.engine import RosterEntry

    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    roster = tuple(
        RosterEntry(display_name=f"玩家{i}", player_type="HUMAN" if i == 0 else "AGENT")
        for i in range(cfg.num_players)
    )
    res = create_game(cfg, game_id="g", roster=roster)
    assert res.state.players[0].display_name == "玩家0"
    assert res.state.players[0].player_type == "HUMAN"
    assert res.state.players[3].player_type == "AGENT"


def test_create_game_roster_length_mismatch_rejected() -> None:
    from app.engine.engine import RosterEntry

    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    with pytest.raises(ValueError):
        create_game(cfg, game_id="g", roster=(RosterEntry(display_name="独苗"),))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_engine_core.py -k "lifecycle or roster" -v`
Expected: FAIL —— `AttributeError`/`ImportError`（无 GAME_CREATED 映射、无 RosterEntry）

- [ ] **Step 3: 实现**

`backend/app/engine/events.py`：

（a）payload 类（放在其他 payload 类旁）：

```python
class GameCreatedPayload(EventPayload):
    """对局创建（生命周期标记；num_players 供日志/前端自述，状态不依赖它）。"""

    num_players: int


class GameStartedPayload(EventPayload):
    """对局开始（纯标记，无字段）。"""
```

（b）`EVENT_PAYLOAD_TYPES` 补两项（并更新其上方"预留类型有意缺席"的注释——不再有预留类型）：

```python
    EventType.GAME_CREATED: GameCreatedPayload,
    EventType.GAME_STARTED: GameStartedPayload,
```

（c）`_reduce_dispatch` 追加显式 no-op 分支（放在函数头部各分支之前即可）：

```python
    if t in (EventType.GAME_CREATED, EventType.GAME_STARTED):
        # 生命周期标记事件：状态无字段变化，仅 state_version 随 reduce 常规递增。
        # 显式空分支 =「已实现的 no-op」，与「未实现类型抛错」的 fail-loud 语义区分。
        return {}
```

`backend/app/engine/engine.py`：

（a）`RosterEntry`（放在 StepResult 附近；导入区补 `from collections.abc import Sequence` 与 `from typing import Literal`，events 导入补 `GameCreatedPayload, GameStartedPayload`）：

```python
class RosterEntry(BaseModel):
    """建局名册项（按座位序传入）。engine 内定义，不依赖 store。"""

    model_config = ConfigDict(frozen=True)

    display_name: str
    player_type: Literal["HUMAN", "AGENT"] = "AGENT"
```

（b）`create_game` 改造（签名 + 玩家构造 + 头部发射；其余保持原样）：

```python
def create_game(
    config: GameConfig, game_id: str, roster: Sequence[RosterEntry] | None = None
) -> StepResult:
    validate_config(config)
    if roster is not None and len(roster) != config.num_players:
        raise ValueError(f"roster 长度 {len(roster)} 与 num_players {config.num_players} 不符")
    players = tuple(
        Player(
            seat=seat,
            display_name=roster[seat].display_name if roster is not None else f"P{seat}",
            player_type=roster[seat].player_type if roster is not None else "AGENT",
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for seat in range(config.num_players)
    )
    state = GameState(
        game_id=game_id,
        config=config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )

    events: list[Event] = []
    state, e = _emit(
        state,
        EventType.GAME_CREATED,
        GameCreatedPayload(num_players=config.num_players),
        Visibility.PUBLIC,
    )
    events.append(e)
    state, e = _emit(state, EventType.GAME_STARTED, GameStartedPayload(), Visibility.PUBLIC)
    events.append(e)

    # ……以下为既有发牌与 ROLES_ASSIGNED 逻辑，唯一变化：events 列表已含头部两事件
```

（既有 `expanded`/`rng.shuffle`/`ROLES_ASSIGNED`/`_begin_night`/`advance` 代码不动，只是接在后面。）

`backend/tests/test_fail_loud.py`：

（a）`test_reserved_type_raises` 改写（不再存在预留类型；同名不变量改为验证已映射类型的 payload 错配仍抛错）：

```python
def test_lifecycle_event_with_wrong_payload_raises() -> None:
    # GAME_CREATED 已实现：错误 payload 类 -> 抛 payload 错配（预留集合已清空，issue #29）
    ev = _evt(EventType.GAME_CREATED, PhaseChangedPayload(to=Phase.DAY_SPEECH))
    with pytest.raises(EngineInvariantError, match="payload"):
        reduce(_state(), ev)
```

（b）`test_mapping_covers_exactly_implemented_types` 中 `reserved` 改为空集：

```python
    reserved: set[EventType] = set()
```

- [ ] **Step 4: 跑新测试确认通过**

Run: `uv run pytest tests/test_engine_core.py -k "lifecycle or roster" tests/test_fail_loud.py -v`
Expected: 新增 3 用例 + fail_loud 全部 PASS

- [ ] **Step 5: 全套迁移（seq 偏移 +2）**

Run: `uv run pytest -q` 并修复失败，机械规则：

- 断言 `create_game`/`run_game` 产物中**绝对事件下标或绝对 seq**（如 `events[0].type == ROLES_ASSIGNED`、`seq == 1`）的测试：下标/seq +2，或改为按类型查找首个匹配事件（更稳，优先）。
- 定位手段：`grep -rn "events\[0\]\|\.seq ==\|state_version ==" tests/`。
- **注意**：所有游戏内随机派生用 `seq=state.state_version`，整体 +2 意味着既有 seed 的对局轨迹会变。凡"扫描 seed 范围找覆盖"类测试（如 PK 时间线、警徽流声明命中）若失手，扩大扫描范围以恢复覆盖，**禁止削弱语义断言**；任何此类调整必须在任务报告中逐条列出。
- 确定性字节一致测试（run-vs-run 同偏移）应天然通过，不许改动。

Expected: 全套 233 passed 左右（230 + 3 新增）

- [ ] **Step 6: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿

```bash
git add backend/app/engine backend/tests
git commit -m "feat(engine): GAME_CREATED/GAME_STARTED 契约与 create_game roster 参数，预留集合清空 (issue #29)"
```

---

### Task 2: runtime 包 + defaults.py（§5.5 默认行动表）

**Files:**
- Create: `backend/app/runtime/__init__.py`
- Create: `backend/app/runtime/defaults.py`
- Test: `backend/tests/test_runtime_defaults.py`

**Interfaces:**
- Consumes: `app.engine.rng.derive_int`；`app.engine.actions.*`；`app.engine.phases.{ElectionStage, Phase}`；`app.engine.state.{GameState, living_seats, player_at}`；`app.engine.config.Faction`
- Produces:
  - `TIMEOUT_SPEECH: str = "（超时，未发言）"`
  - `default_action(state: GameState, seat: int) -> Action` —— 纯函数、确定性（随机分支走引擎 seeded RNG，purpose 前缀 `default:`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_runtime_defaults.py`：

```python
"""默认行动表测试：全对局扫描证明任意可达窗口的默认行动必被引擎接受（issue #29）。"""

import pytest

from app.cli.bot import RandomBot
from app.engine.actions import DayVote, NightAction, NightActionType, SheriffActionType, Speak
from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.phases import ElectionStage, Phase, expected_actors
from app.runtime.defaults import TIMEOUT_SPEECH, default_action

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


def _sweep(preset: str, seed: int, **cfg_override: object) -> set[Phase]:
    """bot 驱动整局；每个待行动座位先探测默认行动可被接受，再用 bot 行动推进。"""
    cfg = build_preset(preset).model_copy(update={"seed": seed, **cfg_override})
    state = create_game(cfg, game_id="g").state
    seen: set[Phase] = set()
    guard = 0
    while state.phase != Phase.GAME_OVER:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            seen.add(state.phase)
            d = default_action(state, seat)
            probe = step(state, d)
            assert probe.rejection is None, (
                f"默认行动被拒：{probe.rejection} @ {state.phase}/{state.election_stage}"
            )
            # 关键分支的内容断言（在真实可达状态上验证表格语义）
            if state.phase == Phase.NIGHT_WITCH:
                assert isinstance(d, NightAction) and d.action_type == NightActionType.SKIP
            if state.phase == Phase.VOTE and isinstance(d, DayVote):
                assert d.abstain
            if state.phase == Phase.DAY_SPEECH and isinstance(d, Speak):
                assert d.content == TIMEOUT_SPEECH
            if (
                state.phase == Phase.SHERIFF_ELECTION
                and state.election_stage == ElectionStage.CANDIDACY
            ):
                assert d.action_type == SheriffActionType.WITHDRAW  # type: ignore[union-attr]
            # 推进沿用 bot（保持既有对局形态的覆盖广度）
            res = step(state, RandomBot.choose_action(state, seat))
            assert res.rejection is None
            state = res.state
        guard += 1
        assert guard < 100_000, "对局未收敛"
    return seen


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [3, 42])
def test_default_action_accepted_at_every_window(preset: str, seed: int) -> None:
    seen = _sweep(preset, seed)
    assert {Phase.NIGHT_WEREWOLF, Phase.DAY_SPEECH, Phase.VOTE} <= seen


@pytest.mark.parametrize("seed", [3, 42])
def test_default_action_with_empty_knife_disabled(seed: int) -> None:
    # 空刀被禁时狼的默认行动是确定性刀非狼目标，仍必被接受
    seen = _sweep("std_9_kill_side", seed, allow_wolf_empty_knife=False)
    assert Phase.NIGHT_WEREWOLF in seen


def test_default_is_deterministic() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    seat = sorted(expected_actors(state))[0]
    assert default_action(state, seat) == default_action(state, seat)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_runtime_defaults.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.runtime'`

- [ ] **Step 3: 实现**

`backend/app/runtime/__init__.py`：

```python
# AgentHowl 包标记
```

`backend/app/runtime/defaults.py`：

```python
"""超时默认行动表（PRD §5.5）：纯函数、零 IO，保证对局永不因玩家挂起而停摆。

随机分支走引擎 seeded RNG（purpose 前缀 default:），与 bot 同口径，可复现。
"""

from __future__ import annotations

from app.engine import rng
from app.engine.actions import (
    Action,
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import Faction
from app.engine.phases import ElectionStage, Phase
from app.engine.state import GameState, living_seats, player_at

TIMEOUT_SPEECH = "（超时，未发言）"


def default_action(state: GameState, seat: int) -> Action:
    """座位 seat 在当前窗口的默认行动（PRD §5.5 表）。"""
    ph = state.phase
    pl = player_at(state, seat)
    seed = state.config.seed if state.config.seed is not None else 0

    def pick(items: list[int], salt: str) -> int:
        idx = rng.derive_int(
            seed=seed,
            purpose=f"default:{seat}:{salt}",
            seq=state.state_version,
            modulo=len(items),
        )
        return items[idx]

    # PK 发言期（VOTE_PK / SHERIFF_PK 的发言队列）：空发言跳过
    if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)

    if ph in (Phase.NIGHT_GUARD, Phase.NIGHT_WITCH):
        # 守卫=空守；女巫=不用药
        return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
    if ph == Phase.NIGHT_WEREWOLF:
        if state.config.allow_wolf_empty_knife:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        targets = [s for s in living_seats(state) if player_at(state, s).faction != Faction.WOLF]
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.KILL,
            target_seat=pick(targets, "kill"),
        )
    if ph == Phase.NIGHT_SEER:
        # 验一名未验过的存活他人（不浪费夜信息）；无可验者才 skip
        checked = {int(rec["seat"]) for rec in state.seer_log.get(seat, [])}
        targets = [s for s in living_seats(state) if s != seat and s not in checked]
        if not targets:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.CHECK,
            target_seat=pick(targets, "check"),
        )
    if ph == Phase.HUNTER_SHOOT:
        return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)

    if ph == Phase.DAY_SPEECH:
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)
    if ph == Phase.LAST_WORDS:
        if pl.is_sheriff:
            # 警长遗言窗口的期望行动是警徽处置：默认撕掉（警徽流失）
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.TEAR_BADGE)
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)

    if ph in (Phase.VOTE, Phase.VOTE_PK):
        return DayVote(actor_seat=seat, abstain=True)

    if ph == Phase.SHERIFF_ELECTION:
        stage = state.election_stage
        if stage == ElectionStage.CANDIDACY:
            # 不上警
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.WITHDRAW)
        if stage == ElectionStage.WITHDRAW:
            # 退水确认窗口：默认留任
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.RUN_FOR_SHERIFF)
        if stage == ElectionStage.DIRECTION:
            return SheriffAction(
                actor_seat=seat,
                action_type=SheriffActionType.SET_SPEECH_DIRECTION,
                direction=Direction.LEFT,
            )
        # vote 子阶段：引擎无警上弃票语义，确定性投最小座位号候选人
        cands = sorted(state.sheriff_candidates) or living_seats(state)
        return SheriffAction(
            actor_seat=seat,
            action_type=SheriffActionType.VOTE_SHERIFF,
            target_seat=cands[0],
        )
    if ph == Phase.SHERIFF_PK:
        cands = sorted(state.sheriff_candidates) or living_seats(state)
        return SheriffAction(
            actor_seat=seat,
            action_type=SheriffActionType.VOTE_SHERIFF,
            target_seat=cands[0],
        )

    # 兜底：一切发言型窗口空发言（与 bot 的兜底同构）
    return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_runtime_defaults.py -v`
Expected: 11 passed（8 + 2 + 1）

- [ ] **Step 5: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿（244 passed 左右）

```bash
git add backend/app/runtime backend/tests/test_runtime_defaults.py
git commit -m "feat(runtime): §5.5 默认行动表纯函数与全对局扫描验证 (issue #29)"
```

---

### Task 3: player_port.py + pytest-asyncio 基建

**Files:**
- Create: `backend/app/runtime/player_port.py`
- Modify: `backend/pyproject.toml`（dev 依赖 + asyncio 配置）
- Test: `backend/tests/test_player_port.py`

**Interfaces:**
- Consumes: `app.engine.actions.Action`；`app.engine.observation.PlayerObservation`；`app.engine.state.GameState`；`app.cli.bot.RandomBot`（cli.bot 为零 IO 纯模块，runtime 复用其 bot 作填充玩家）
- Produces:
  - `PlayerPort(Protocol)`: `async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action`
  - `BotPlayerPort`: `__init__(self, state_provider: Callable[[], GameState])`；act 以全知 state 调 `RandomBot.choose_action(state, observation.my_seat)`（内置 bot 属服务端，不越隔离边界；真人/Agent 端口只见 observation）

- [ ] **Step 1: 安装 dev 依赖并配置**

```bash
uv add --dev pytest-asyncio
```

`backend/pyproject.toml` 的 `[tool.pytest.ini_options]` 追加一行：

```toml
asyncio_mode = "auto"
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_player_port.py`：

```python
"""PlayerPort 协议与 BotPlayerPort（issue #29）。asyncio_mode=auto，无需逐个标记。"""

import time

from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.observation import build_observation
from app.engine.phases import expected_actors
from app.runtime.player_port import BotPlayerPort, PlayerPort


async def test_bot_port_action_accepted_by_engine() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    port = BotPlayerPort(state_provider=lambda: state)
    seat = sorted(expected_actors(state))[0]
    obs = build_observation(state, seat)
    action = await port.act(obs, deadline_ts=time.time() + 30)
    assert step(state, action).rejection is None


def test_bot_port_satisfies_protocol() -> None:
    port: PlayerPort = BotPlayerPort(state_provider=lambda: None)  # type: ignore[arg-type, return-value]
    assert hasattr(port, "act")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_player_port.py -v`
Expected: FAIL —— `ModuleNotFoundError`（app.runtime.player_port）

- [ ] **Step 4: 实现**

`backend/app/runtime/player_port.py`：

```python
"""玩家接入端口：runner 与玩家实现（bot/真人/Agent）之间的唯一缝（issue #29）。

M2.3 真人（WS/REST 桥接）与 M2.4 LLM Agent 实现同一 Protocol。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.cli.bot import RandomBot
from app.engine.actions import Action
from app.engine.observation import PlayerObservation
from app.engine.state import GameState


class PlayerPort(Protocol):
    """runner 询问玩家行动的异步端口；超时/异常兜底由 runner 持有。"""

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action: ...


class BotPlayerPort:
    """服务端内置填充 bot：以全知 state 复用 RandomBot。

    内置 bot 属服务端信任域，不越信息隔离边界；observation 仅用于取 my_seat。
    """

    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        return RandomBot.choose_action(self._state_provider(), observation.my_seat)
```

- [ ] **Step 5: 跑测试确认通过 + 质量门 + 提交**

Run: `uv run pytest tests/test_player_port.py -v && uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 2 passed；全套全绿

```bash
git add backend/app/runtime/player_port.py backend/tests/test_player_port.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(runtime): PlayerPort 协议与 BotPlayerPort，接入 pytest-asyncio (issue #29)"
```

---

### Task 4: connection.py —— ConnectionManager 订阅广播骨架

**Files:**
- Create: `backend/app/runtime/connection.py`
- Test: `backend/tests/test_connection.py`

**Interfaces:**
- Consumes: `app.engine.observation.{Viewer, visible_events}`；`app.engine.events.Event`；`app.engine.state.GameState`
- Produces:
  - `Subscriber = Callable[[list[Event]], Awaitable[None]]`
  - `ConnectionManager`: `__init__(state_provider: Callable[[], GameState])`；`subscribe(viewer: Viewer, callback: Subscriber) -> None`（同 viewer 可多订阅）；`unsubscribe(viewer: Viewer, callback: Subscriber) -> None`；`async broadcast(events: list[Event]) -> None`（每订阅者只收 `visible_events` 过滤后的子集，空子集不回调；回调按订阅顺序串行 await）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_connection.py`：

```python
"""ConnectionManager：按视角过滤广播，复用引擎 visible_events 口径（issue #29）。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    PhaseChangedPayload,
    Visibility,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player
from app.runtime.connection import ConnectionManager


def _state() -> GameState:
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
        )
        for i in range(4)
    )
    return GameState(
        game_id="g",
        config=build_preset("std_9_kill_side"),
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
    )


def _evt(seq: int, vis: Visibility, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g",
        ts=float(seq),
        type=EventType.PHASE_CHANGED,
        actor_seat=actor,
        payload=PhaseChangedPayload(to=Phase.VOTE),
        visibility=vis,
    )


async def test_broadcast_filters_per_viewer() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    got: dict[str, list[Event]] = {"gm": [], "spec": [], "wolf": [], "villager": []}

    async def _mk(key: str):  # type: ignore[no-untyped-def]
        async def cb(events: list[Event]) -> None:
            got[key].extend(events)

        return cb

    mgr.subscribe("GM", await _mk("gm"))
    mgr.subscribe("SPECTATOR", await _mk("spec"))
    mgr.subscribe(0, await _mk("wolf"))  # 座位 0 是狼
    mgr.subscribe(1, await _mk("villager"))

    events = [
        _evt(1, Visibility.PUBLIC),
        _evt(2, Visibility.WOLVES),
        _evt(3, Visibility.ROLE_SELF, actor=1),
        _evt(4, Visibility.GM_ONLY),
    ]
    await mgr.broadcast(events)

    assert [e.seq for e in got["gm"]] == [1, 2, 3, 4]
    assert [e.seq for e in got["spec"]] == [1]
    assert [e.seq for e in got["wolf"]] == [1, 2]
    assert [e.seq for e in got["villager"]] == [1, 3]


async def test_unsubscribe_stops_delivery() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    got: list[Event] = []

    async def cb(events: list[Event]) -> None:
        got.extend(events)

    mgr.subscribe("GM", cb)
    await mgr.broadcast([_evt(1, Visibility.PUBLIC)])
    mgr.unsubscribe("GM", cb)
    await mgr.broadcast([_evt(2, Visibility.PUBLIC)])
    assert [e.seq for e in got] == [1]


async def test_empty_subset_not_called() -> None:
    state = _state()
    mgr = ConnectionManager(state_provider=lambda: state)
    calls: list[int] = []

    async def cb(events: list[Event]) -> None:
        calls.append(len(events))

    mgr.subscribe("SPECTATOR", cb)
    await mgr.broadcast([_evt(1, Visibility.GM_ONLY)])
    assert calls == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_connection.py -v`
Expected: FAIL —— `ModuleNotFoundError`（app.runtime.connection）

- [ ] **Step 3: 实现**

`backend/app/runtime/connection.py`：

```python
"""ConnectionManager：进程内订阅者按视角接收过滤后的事件流（issue #29）。

过滤复用引擎 observation.visible_events —— 信息隔离的单一实现点；
本模块不自造任何过滤逻辑。M2.3 的 WS 端点将以订阅者身份接入。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.engine.events import Event
from app.engine.observation import Viewer, visible_events
from app.engine.state import GameState

Subscriber = Callable[[list[Event]], Awaitable[None]]


class ConnectionManager:
    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider
        self._subs: list[tuple[Viewer, Subscriber]] = []

    def subscribe(self, viewer: Viewer, callback: Subscriber) -> None:
        self._subs.append((viewer, callback))

    def unsubscribe(self, viewer: Viewer, callback: Subscriber) -> None:
        self._subs = [(v, cb) for v, cb in self._subs if not (v == viewer and cb is callback)]

    async def broadcast(self, events: list[Event]) -> None:
        """按订阅顺序串行投递；每订阅者只见其视角可见的子集，空子集不打扰。"""
        state = self._state_provider()
        for viewer, cb in list(self._subs):
            visible = visible_events(state, events, viewer)
            if visible:
                await cb(visible)
```

- [ ] **Step 4: 跑测试确认通过 + 质量门 + 提交**

Run: `uv run pytest tests/test_connection.py -v && uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 3 passed；全套全绿

```bash
git add backend/app/runtime/connection.py backend/tests/test_connection.py
git commit -m "feat(runtime): ConnectionManager 按视角过滤广播骨架 (issue #29)"
```

---

### Task 5: game_runner.py —— GameLobby + GameRunner 主循环（happy path）

**Files:**
- Create: `backend/app/runtime/game_runner.py`
- Test: `backend/tests/test_game_runner.py`

**Interfaces:**
- Consumes: Task 1 的 `create_game(config, game_id, roster)`/`RosterEntry`；Task 3 `PlayerPort`/`BotPlayerPort`；Task 4 `ConnectionManager`；store 的 `EventStore/GameMeta/SeatName/load_state`；引擎 `step/expected_actors/build_observation`
- Produces:
  - `LobbyError(RuntimeError)`
  - `RunnerTimeouts(BaseModel, frozen)`: `speech_sec: float`, `action_sec: float`；`@classmethod from_config(cfg: GameConfig) -> RunnerTimeouts`
  - `GameLobby`: `__init__(config: GameConfig, game_id: str)`；`join(display_name: str, player_type: Literal["HUMAN", "AGENT"] = "HUMAN") -> int`（返回座位；满员抛 LobbyError）；`fill_with_bots() -> None`（余座填 `Bot{seat}`/AGENT）；`is_full: bool` 属性；`roster() -> tuple[RosterEntry, ...]`（未满抛 LobbyError）；`game_meta() -> GameMeta`
  - `GameRunner`: `__init__(*, store: EventStore, config: GameConfig, game_id: str, roster: Sequence[RosterEntry], ports: Mapping[int, PlayerPort], connections: ConnectionManager | None = None, timeouts: RunnerTimeouts | None = None)`；`state: GameState` 属性（BotPlayerPort/ConnectionManager 的 state_provider 缝）；`async run() -> GameState`
  - meta 充实：落库/广播前每事件 `meta` 注入 `wall_ts`（ISO8601 UTC）；本任务 timeout 标记参数已预留（`_commit(events, timed_out=False)`），Task 6 启用
  - 本任务 runner 直接 `await port.act(...)`（无超时包装），拒绝即抛 `RuntimeError` —— 超时与拒绝重试是 Task 6 的增量

- [ ] **Step 1: 写失败测试**

`backend/tests/test_game_runner.py`：

```python
"""GameRunner 集成：12 bot 全自动经 runner + store 跑完整局（issue #29）。"""

from pathlib import Path

import pytest

from app.engine.config import build_preset
from app.engine.events import EventType
from app.engine.phases import Phase
from app.runtime.connection import ConnectionManager
from app.runtime.game_runner import GameLobby, GameRunner, LobbyError, RunnerTimeouts
from app.runtime.player_port import BotPlayerPort, PlayerPort
from app.store.event_store import (
    EventStore,
    InMemoryEventStore,
    JsonFileEventStore,
    load_state,
)


def _make_runner(store: EventStore, seed: int = 42, preset: str = "std_12_yn_hunter_idiot"):  # type: ignore[no-untyped-def]
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        connections=ConnectionManager(state_provider=lambda: runner.state),
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    return runner


class TestLobby:
    def test_join_assigns_seats_and_rejects_overflow(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        assert lobby.join("Alice") == 0
        assert lobby.join("Bob", player_type="AGENT") == 1
        lobby.fill_with_bots()
        assert lobby.is_full
        with pytest.raises(LobbyError):
            lobby.join("Carol")
        roster = lobby.roster()
        assert roster[0].display_name == "Alice"
        assert roster[0].player_type == "HUMAN"
        assert roster[2].display_name == "Bot2"

    def test_roster_requires_full(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        lobby.join("Alice")
        with pytest.raises(LobbyError):
            lobby.roster()

    def test_game_meta_matches_roster(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        lobby.fill_with_bots()
        meta = lobby.game_meta()
        assert meta.game_id == "g1"
        assert [s.display_name for s in meta.roster] == [f"Bot{i}" for i in range(9)]


class TestRunnerIntegration:
    async def test_full_game_memory_store(self) -> None:
        store = InMemoryEventStore()
        runner = _make_runner(store)
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        events = store.load_events("g1")
        # 生命周期头 + 落库回放一致
        assert [e.type for e in events[:2]] == [EventType.GAME_CREATED, EventType.GAME_STARTED]
        replayed = load_state(store, "g1")
        assert replayed.winner == final.winner
        assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
        # runtime meta 充实：每事件带墙钟
        assert all("wall_ts" in e.meta for e in events)

    async def test_full_game_jsonl_store_cold_reload(self, tmp_path: Path) -> None:
        store = JsonFileEventStore(tmp_path / "d")
        runner = _make_runner(store, seed=7)
        final = await runner.run()
        cold = JsonFileEventStore(tmp_path / "d")
        replayed = load_state(cold, "g1")
        assert replayed.phase == Phase.GAME_OVER
        assert replayed.winner == final.winner

    async def test_spectator_stream_is_public_only(self) -> None:
        store = InMemoryEventStore()
        runner = _make_runner(store, seed=9)
        got: list[EventType] = []

        async def spec_cb(events) -> None:  # type: ignore[no-untyped-def]
            got.extend(e.type for e in events)

        assert runner.connections is not None
        runner.connections.subscribe("SPECTATOR", spec_cb)
        await runner.run()
        assert EventType.GAME_CREATED in got
        assert EventType.ROLES_ASSIGNED not in got  # GM_ONLY 不得泄给观众


def test_runner_timeouts_from_config() -> None:
    cfg = build_preset("std_9_kill_side")
    t = RunnerTimeouts.from_config(cfg)
    assert t.speech_sec == float(cfg.speech_timeout_sec)
    assert t.action_sec == float(cfg.action_timeout_sec)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_game_runner.py -v`
Expected: FAIL —— `ModuleNotFoundError`（app.runtime.game_runner）

- [ ] **Step 3: 实现**

`backend/app/runtime/game_runner.py`：

```python
"""GameRunner：驱动纯引擎的编排层 —— 串行开窗、事件落库同序广播（issue #29）。

分层：runtime 只转发 intent，裁决全在 engine；本模块对事件的唯一改写点是 meta。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.engine.config import GameConfig
from app.engine.engine import RosterEntry, create_game, step
from app.engine.events import Event
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.player_port import PlayerPort
from app.store.event_store import EventStore, GameMeta, SeatName


class LobbyError(RuntimeError):
    """大厅规则违规（重复加入、未满员取名册等）。"""


class RunnerTimeouts(BaseModel):
    model_config = ConfigDict(frozen=True)

    speech_sec: float
    action_sec: float

    @classmethod
    def from_config(cls, cfg: GameConfig) -> RunnerTimeouts:
        return cls(
            speech_sec=float(cfg.speech_timeout_sec),
            action_sec=float(cfg.action_timeout_sec),
        )


class GameLobby:
    """建局前大厅：收集座位（真人 join / bot 填充），产出 roster 与 GameMeta。"""

    def __init__(self, config: GameConfig, game_id: str) -> None:
        self._config = config
        self._game_id = game_id
        self._entries: list[RosterEntry] = []

    @property
    def is_full(self) -> bool:
        return len(self._entries) >= self._config.num_players

    def join(
        self, display_name: str, player_type: Literal["HUMAN", "AGENT"] = "HUMAN"
    ) -> int:
        if self.is_full:
            raise LobbyError(f"对局已满员（{self._config.num_players} 座）")
        self._entries.append(RosterEntry(display_name=display_name, player_type=player_type))
        return len(self._entries) - 1

    def fill_with_bots(self) -> None:
        while not self.is_full:
            seat = len(self._entries)
            self._entries.append(RosterEntry(display_name=f"Bot{seat}", player_type="AGENT"))

    def roster(self) -> tuple[RosterEntry, ...]:
        if not self.is_full:
            raise LobbyError(f"未满员：{len(self._entries)}/{self._config.num_players}")
        return tuple(self._entries)

    def game_meta(self) -> GameMeta:
        return GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name)
                for i, e in enumerate(self.roster())
            ),
        )


def _speech_window(state: GameState) -> bool:
    """当前窗口是否发言型（超时取 speech_timeout_sec）。"""
    if state.phase in (Phase.DAY_SPEECH, Phase.LAST_WORDS):
        return True
    return state.phase in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(
        state.speech_order
    )


class GameRunner:
    def __init__(
        self,
        *,
        store: EventStore,
        config: GameConfig,
        game_id: str,
        roster: Sequence[RosterEntry],
        ports: Mapping[int, PlayerPort],
        connections: ConnectionManager | None = None,
        timeouts: RunnerTimeouts | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._game_id = game_id
        self._roster = tuple(roster)
        self._ports = ports
        self.connections = connections
        self._timeouts = timeouts or RunnerTimeouts.from_config(config)
        self._state: GameState | None = None

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("对局尚未开始")
        return self._state

    async def run(self) -> GameState:
        meta = GameMeta(
            game_id=self._game_id,
            config=self._config,
            roster=tuple(
                SeatName(seat=i, display_name=e.display_name)
                for i, e in enumerate(self._roster)
            ),
        )
        self._store.create_game(meta)
        res = create_game(self._config, self._game_id, roster=self._roster)
        self._state = res.state
        await self._commit(res.events)

        guard = 0
        while self.state.phase != Phase.GAME_OVER:
            actors = sorted(expected_actors(self.state))
            if not actors:
                raise RuntimeError(f"无人可行动但未终局：phase={self.state.phase}")
            for seat in actors:
                if seat not in expected_actors(self.state):
                    continue  # 前一行动已终结此窗口（如终局）
                await self._drive_seat(seat)
            guard += 1
            if guard > 100_000:
                raise RuntimeError("对局未收敛")
        return self.state

    # ---------- 内部 ----------

    def _window_timeout(self) -> float:
        return self._timeouts.speech_sec if _speech_window(self.state) else self._timeouts.action_sec

    async def _drive_seat(self, seat: int) -> None:
        obs = build_observation(self.state, seat)
        deadline_ts = time.time() + self._window_timeout()
        action = await self._ports[seat].act(obs, deadline_ts)
        res = step(self.state, action)
        if res.rejection is not None:
            raise RuntimeError(f"行动被拒：{res.rejection} @ {self.state.phase}")
        self._state = res.state
        await self._commit(res.events)

    async def _commit(self, events: list[Event], timed_out: bool = False) -> None:
        """meta 充实 → 落库 → 广播，同序。runtime 对事件的唯一合法改写点。"""
        wall_ts = datetime.now(UTC).isoformat()
        enriched = [
            e.model_copy(
                update={
                    "meta": {
                        **e.meta,
                        "wall_ts": wall_ts,
                        **({"timeout": "true"} if timed_out else {}),
                    }
                }
            )
            for e in events
        ]
        for e in enriched:
            self._store.append(self._game_id, e)
        if self.connections is not None:
            await self.connections.broadcast(enriched)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_game_runner.py -v`
Expected: 8 passed

- [ ] **Step 5: 质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿

```bash
git add backend/app/runtime/game_runner.py backend/tests/test_game_runner.py
git commit -m "feat(runtime): GameLobby 与 GameRunner 主循环，12 bot 全自动对局经 store 跑通 (issue #29)"
```

---

### Task 6: 超时代打 + 拒绝重试（runner 兜底路径）

**Files:**
- Modify: `backend/app/runtime/game_runner.py`（`_drive_seat` 增量）
- Test: `backend/tests/test_game_runner.py`（追加）

**Interfaces:**
- Consumes: Task 2 `default_action`；Task 5 `GameRunner._drive_seat/_commit`
- Produces（行为契约）:
  - 端口超时（`asyncio.wait_for`）、端口抛任意异常、或拒绝达 `MAX_REJECTIONS = 3` 次/超过截止 → 落 `default_action(state, seat)`，其事件 `meta.timeout == "true"`
  - 拒绝重试：截止前且次数未满 → 重新询问端口（剩余时间为新超时）
  - 默认行动被引擎拒绝 = 不变量破坏 → `RuntimeError`（fail-loud，不静默跳过）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_game_runner.py`（导入区补 `import asyncio`、`from app.engine.actions import Action, Speak`、`from app.engine.observation import PlayerObservation`）：

```python
class HangingPort:
    """永不返回的端口：模拟断线/挂起玩家。"""

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class AlwaysInvalidPort:
    """永远提交非法 intent（夜里发言必 WRONG_PHASE；白天发言合法，故包一层计数狼刀自己）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self.calls += 1
        # 对任意阶段都非法：actor 座位冒用他人（NOT_YOUR_TURN）
        other = (observation.my_seat + 1) % 9
        return Speak(actor_seat=other, content="(evil)")


class RetryOncePort:
    """每个窗口先交一次非法 intent，被拒后交出合法 bot 行动：验证重试成功路径。"""

    def __init__(self, inner: PlayerPort) -> None:
        self._inner = inner
        self.calls = 0

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self.calls += 1
        if self.calls % 2 == 1:
            other = (observation.my_seat + 1) % 9
            return Speak(actor_seat=other, content="(oops)")
        return await self._inner.act(observation, deadline_ts)


def _make_special_runner(
    store: EventStore, seed: int, timeouts: RunnerTimeouts
) -> tuple[GameRunner, dict[int, PlayerPort]]:
    """9 人局，全 bot；调用方把 seat 0 换成特殊端口后 run。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        timeouts=timeouts,
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    return runner, ports


class TestTimeoutAndRetry:
    async def test_hanging_port_replaced_by_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=0.02, action_sec=0.02)
        )
        ports[0] = HangingPort()
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        events = store.load_events("g1")
        timed_out = [e for e in events if e.meta.get("timeout") == "true"]
        assert timed_out, "挂起座位必须留下超时代打事件"
        replayed = load_state(store, "g1")
        assert replayed.winner == final.winner

    async def test_rejections_exhausted_falls_to_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5)
        )
        evil = AlwaysInvalidPort()
        ports[0] = evil
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        assert evil.calls >= 3  # 至少被重试到上限一次
        events = store.load_events("g1")
        assert any(e.meta.get("timeout") == "true" for e in events)

    async def test_retry_then_valid_needs_no_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
        )
        retry = RetryOncePort(BotPlayerPort(state_provider=lambda: runner.state))
        ports[0] = retry
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        assert retry.calls >= 2  # 至少发生过一次「拒绝 → 重试成功」
        events = store.load_events("g1")
        # 重试全部成功：全局不应出现任何超时代打事件（其余座位是即时 bot）
        assert not any(e.meta.get("timeout") == "true" for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_game_runner.py -k "rejections_exhausted or retry_then_valid" -v`
Expected: FAIL —— 现行 `_drive_seat` 对拒绝直抛 `RuntimeError("行动被拒…")`，两用例红灯。
（挂起用例在实现前会真挂而非快速失败，故红灯证据以这两例为准；实现后三例一起转绿。）

- [ ] **Step 3: 实现（_drive_seat 替换）**

`backend/app/runtime/game_runner.py`：导入区补 `import asyncio`，模块级补常量与导入
`from app.runtime.defaults import default_action`：

```python
MAX_REJECTIONS = 3  # 截止前允许的非法 intent 次数，超过即落默认行动
```

`_drive_seat` 整体替换为：

```python
    async def _drive_seat(self, seat: int) -> None:
        obs = build_observation(self.state, seat)
        deadline_ts = time.time() + self._window_timeout()
        rejections = 0
        while True:
            remaining = deadline_ts - time.time()
            if remaining <= 0 or rejections >= MAX_REJECTIONS:
                await self._apply_default(seat)
                return
            try:
                action = await asyncio.wait_for(
                    self._ports[seat].act(obs, deadline_ts), timeout=remaining
                )
            except TimeoutError:
                await self._apply_default(seat)
                return
            except Exception:
                # 端口实现抛错（Agent 崩溃等）：对局不陪葬，落默认行动
                await self._apply_default(seat)
                return
            res = step(self.state, action)
            if res.rejection is None:
                self._state = res.state
                await self._commit(res.events)
                return
            rejections += 1  # 非法 intent：截止前重试（M2.3 真人重试路径）

    async def _apply_default(self, seat: int) -> None:
        res = step(self.state, default_action(self.state, seat))
        if res.rejection is not None:
            raise RuntimeError(
                f"默认行动被拒（不变量破坏）：{res.rejection} @ {self.state.phase}"
            )
        self._state = res.state
        await self._commit(res.events, timed_out=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_game_runner.py -v`
Expected: 11 passed（8 + 3）

- [ ] **Step 5: 全量质量门 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check . && uv run ruff format --check .`
Expected: 全绿（Task 2 基线 + 本分支新增 ≈ 259 passed 左右）

```bash
git add backend/app/runtime/game_runner.py backend/tests/test_game_runner.py
git commit -m "feat(runtime): 超时代打与拒绝重试兜底，meta.timeout 标记，闭环 issue #29"
```

---

## 完成后

按 finishing-a-development-branch 流程：push `feat/game-runner`、开 PR 关联 issue #29
（用户在 GitHub 上自行合并；不在本地 merge main）。若 PR #33 已合并，先把 PR base
指向 main；否则以 stacked PR 说明依赖 #33。
