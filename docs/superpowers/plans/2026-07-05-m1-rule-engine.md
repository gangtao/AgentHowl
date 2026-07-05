# M1 规则引擎核心 实施计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AgentHowl 的纯函数规则引擎（M1）：`GameConfig`/presets、阶段状态机、事件溯源 + `reduce`、夜晚/白天结算、信息隔离 observation，以及用随机 bot 跑完整对局的 CLI。

**Architecture:** 事件是唯一写路径 —— `step(state, action)` 固定为「校验 → 决定事件 → `reduce` 应用」，状态只经 `reduce` 变更。阶段机是普通 `Phase` 枚举 + 纯函数转移；`step` 内的 `advance()` 循环持续产出系统事件直到抵达需要玩家输入的阶段。随机性走无隐藏状态的 `(seed, purpose, seq)` 哈希派生。所有模型是 frozen Pydantic v2，纯度由类型系统强制。

**Tech Stack:** Python 3.11+，Pydantic v2（引擎唯一第三方依赖），pytest，mypy strict，ruff。用 **uv** 管理（`uv add`、`uv run pytest`）。

## Global Constraints

以下约束来自 `CLAUDE.md` 与设计文档 §2/§11，**每个任务都隐含包含**：

- 引擎包 `backend/app/engine/` **零 IO**：只 import 标准库与 Pydantic，绝不 import 网络/DB/LLM/asyncio。
- **事件是唯一写路径（游戏事实）**：所有**游戏事实**（玩家生死/身份/票数/警长归属/药态等）只能经 `reduce(state, event)` 变更；`step` 不得直接 `model_copy` 这些字段。**唯一例外**是流程游标字段（`resume_token`/`pending_hunter`/`election_stage`/`sheriff_candidates`/`sheriff_votes`/`night_deaths`），允许 `step`/系统推进直接 `model_copy` 更新——它们不参与 `reduce(events)==live` 的终态断言（见文末「M1 内进一步简化」）。`state_version`/`rng_state` 由事件应用时统一推进。
- 所有随机走 `rng.py` 的 `(seed, purpose, seq)` 派生；`GameState.rng_state` 只是计数器。
- 所有 Pydantic 模型 **frozen**（`model_config = ConfigDict(frozen=True)`）；`reduce` 用 `model_copy(update=...)` 返回新副本，绝不原地改 list/dict。
- 无规则硬编码：每个规则变体都是 `GameConfig` 开关。
- 文档/注释用中文；代码标识符、schema、API 名用英文。
- 引擎测试 **零 IO、零 mock**；确定性测试用固定 `GameConfig.seed`。
- 命令一律在 `backend/` 目录下运行：`uv run pytest`、`uv run ruff check .`、`uv run ruff format .`、`uv run mypy app`（strict）。
- 交付判据：§8.4 规则单测全绿；固定 seed 两次运行事件日志逐字节一致且 `reduce(events)` == 实时终态；CLI 多 seed 跑完 500 局，每局必终局且有结果。

## File Structure

引擎为纯包，模块职责单一：

| 文件 | 职责 |
|---|---|
| `backend/app/engine/__init__.py` | 空包标记 |
| `backend/app/engine/rng.py` | `derive_int` / `shuffle` 确定性随机派生 |
| `backend/app/engine/config.py` | `RoleType`/`Faction` 等枚举、子规则模型、`GameConfig`、`build_preset`、`validate_config` |
| `backend/app/engine/state.py` | `Player`、`NightActions`、`GameState`（frozen）+ 查询 helper |
| `backend/app/engine/events.py` | `Visibility`/`EventType` 枚举、类型化 payload、`Event`、`reduce`、`reduce_all` |
| `backend/app/engine/actions.py` | 行动意图模型（`NightAction`/`DayVote`/`Speak`/`SheriffAction`/`SelfDestruct`）、`RejectedReason` |
| `backend/app/engine/phases.py` | `Phase` 枚举、`expected_actors`、夜序 helper |
| `backend/app/engine/resolver.py` | `resolve_night`/`count_votes`/`check_win` 纯函数 |
| `backend/app/engine/engine.py` | `create_game`、`step`、`advance`、`StepResult` |
| `backend/app/engine/observation.py` | `PlayerObservation`、`build_observation`、`visible_events` |
| `backend/app/cli/__init__.py` | 空包标记 |
| `backend/app/cli/bot.py` | `RandomBot.choose_action(state, seat)` |
| `backend/app/cli/simulate.py` | `python -m app.cli.simulate` 主循环 |
| `backend/tests/…` | §9 测试表逐文件对应 |

每个模块「改动时同时改动」的东西住在一起：payload 模型与 `reduce` 同在 `events.py`；阶段转移的「谁行动」与阶段枚举同在 `phases.py`；结算算法独立在 `resolver.py` 便于矩阵测试。

---

## Stage 0 — 项目脚手架

本期只做依赖与包骨架，让后续每个 TDD 任务能立即 `uv run pytest`。

### Task 0: 引擎依赖与包骨架

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/engine/__init__.py`
- Create: `backend/app/cli/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

**Interfaces:**
- Produces: 可 `from app.engine import ...`、`from app.cli import ...`；`uv run pytest` 从 `backend/tests/` 收集用例。

- [ ] **Step 1: 加 pydantic 运行时依赖**

Run（在 `backend/`）：
```bash
uv add "pydantic>=2.6"
```
Expected: `pyproject.toml` 的 `[project].dependencies` 出现 `pydantic>=2.6`，`uv.lock` 更新。

- [ ] **Step 2: 修正 pytest 配置到 `tests/` 并加 pythonpath**

把 `backend/pyproject.toml` 里 `[tool.pytest.ini_options]` 段整体替换为：
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```
理由：设计文档与规格 §6.2 都把测试放在 `backend/tests/`；`pythonpath = ["."]` 让 `from app.engine... import` 在 `backend/` 根下可解析。

- [ ] **Step 3: 建包标记文件**

四个 `__init__.py` 均写入一行注释即可（保持包为空）：
```python
# AgentHowl 包标记
```
分别写到：`backend/app/__init__.py`、`backend/app/engine/__init__.py`、`backend/app/cli/__init__.py`、`backend/tests/__init__.py`。

- [ ] **Step 4: 写冒烟测试确认工具链**

Create `backend/tests/conftest.py`：
```python
"""pytest 共享夹具（M1 引擎测试；零 IO、零 mock）。"""
```

Create `backend/tests/test_smoke.py`：
```python
def test_app_package_importable() -> None:
    import app.engine  # noqa: F401

    assert app.engine is not None
```

- [ ] **Step 5: 运行冒烟测试**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 6: 确认 lint / 类型链路干净**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```
Expected: 三条命令都通过（`app` 目前只有空 `__init__.py`）。

- [ ] **Step 7: 删除冒烟测试并提交骨架**

删除 `backend/tests/test_smoke.py`（它只验证工具链，不属于交付面）。
Run:
```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "chore(engine): M1 依赖与包骨架"
```

---

## Stage 1 — 核心循环

交付：config/state/events/reduce + 夜晚（守/狼/女巫/预言家）+ 白天发言/投票/放逐/平票 + 胜负判定 + RandomBot + CLI。本期用 **9 人测试板**（3 狼 + 3 民 + 预言家 + 女巫 + 守卫，**无猎人/白痴/警长**）跑通完整对局；猎人/白痴/警长留到 Stage 2/3。

> 本期所有测试板由 `tests/factories.py` 的 `stage1_config(seed=...)` 提供（见 Task 5），避免每个测试重复拼 config。

### Task 1: 确定性随机派生 `rng.py`

**Files:**
- Create: `backend/app/engine/rng.py`
- Test: `backend/tests/test_rng.py`

**Interfaces:**
- Produces:
  - `derive_int(seed: int, purpose: str, seq: int, modulo: int) -> int` —— 返回 `[0, modulo)` 的确定性整数。
  - `shuffle(seed: int, purpose: str, items: list[T]) -> list[T]` —— 返回洗牌后的**新** list，不改入参。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_rng.py`：
```python
from app.engine.rng import derive_int, shuffle


def test_derive_int_in_range() -> None:
    for seq in range(100):
        v = derive_int(seed=42, purpose="deal", seq=seq, modulo=12)
        assert 0 <= v < 12


def test_derive_int_is_deterministic() -> None:
    a = derive_int(seed=7, purpose="tie", seq=3, modulo=5)
    b = derive_int(seed=7, purpose="tie", seq=3, modulo=5)
    assert a == b


def test_derive_int_varies_by_inputs() -> None:
    base = derive_int(seed=1, purpose="deal", seq=0, modulo=1000)
    assert derive_int(seed=2, purpose="deal", seq=0, modulo=1000) != base
    assert derive_int(seed=1, purpose="x", seq=0, modulo=1000) != base
    assert derive_int(seed=1, purpose="deal", seq=1, modulo=1000) != base


def test_derive_int_rejects_bad_modulo() -> None:
    import pytest

    with pytest.raises(ValueError):
        derive_int(seed=1, purpose="p", seq=0, modulo=0)


def test_shuffle_is_permutation_and_pure() -> None:
    items = list(range(12))
    out = shuffle(seed=99, purpose="deal", items=items)
    assert sorted(out) == items          # 是一个排列
    assert items == list(range(12))      # 未改入参
    assert out != items                  # 对该 seed 确实打乱（12! 下几乎必然）


def test_shuffle_is_deterministic() -> None:
    a = shuffle(seed=5, purpose="deal", items=list(range(9)))
    b = shuffle(seed=5, purpose="deal", items=list(range(9)))
    assert a == b
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_rng.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.engine.rng'`）。

- [ ] **Step 3: 实现 `rng.py`**

Create `backend/app/engine/rng.py`：
```python
"""确定性随机派生。

引擎不持有随机对象；每次抽取都是 (seed, purpose, seq) 的纯函数（哈希派生）。
GameState.rng_state 只是一个递增计数器（seq 的来源），因此重放天然复现。
"""

from __future__ import annotations

import hashlib
from typing import TypeVar

T = TypeVar("T")


def derive_int(seed: int, purpose: str, seq: int, modulo: int) -> int:
    """由 (seed, purpose, seq) 派生一个 [0, modulo) 的确定性整数。"""
    if modulo <= 0:
        raise ValueError(f"modulo 必须为正数，收到 {modulo}")
    raw = f"{seed}:{purpose}:{seq}".encode()
    digest = hashlib.sha256(raw).digest()
    value = int.from_bytes(digest[:8], "big")
    return value % modulo


def shuffle(seed: int, purpose: str, items: list[T]) -> list[T]:
    """确定性 Fisher-Yates 洗牌，返回新列表，不修改入参。"""
    result = list(items)
    n = len(result)
    for i in range(n - 1, 0, -1):
        j = derive_int(seed=seed, purpose=purpose, seq=n - 1 - i, modulo=i + 1)
        result[i], result[j] = result[j], result[i]
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_rng.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/engine/rng.py backend/tests/test_rng.py
git commit -m "feat(engine): 确定性随机派生 rng"
```

### Task 2: `GameConfig`、presets 与 `validate_config`

**Files:**
- Create: `backend/app/engine/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces（后续任务全部依赖这些名字）：
  - 枚举：`RoleType`（WEREWOLF/VILLAGER/SEER/WITCH/HUNTER/GUARD/IDIOT）、`Faction`（GOOD/WOLF）、`WinCondition`（KILL_SIDE/KILL_ALL）、`SpeechOrderRule`、`TieRule`、`LastWordsRule`。
  - 子规则模型：`WitchRule`、`GuardRule`、`SheriffRule`、`RoleSlot`。
  - `GameConfig`（frozen）。
  - `faction_of(role: RoleType) -> Faction`。
  - `build_preset(name: str) -> GameConfig`，支持 `std_12_yn_hunter_idiot`、`std_12_yn_hunter_guard`、`std_9_kill_side`、`std_9_kill_all`。
  - `validate_config(config: GameConfig) -> None`，失败抛 `ConfigError`。
  - `ConfigError(ValueError)`。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_config.py`：
```python
import pytest

from app.engine.config import (
    ConfigError,
    Faction,
    GameConfig,
    RoleSlot,
    RoleType,
    WinCondition,
    build_preset,
    faction_of,
    validate_config,
)

ALL_PRESETS = [
    "std_12_yn_hunter_idiot",
    "std_12_yn_hunter_guard",
    "std_9_kill_side",
    "std_9_kill_all",
]


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_presets_are_valid(name: str) -> None:
    config = build_preset(name)
    validate_config(config)  # 不抛异常即通过
    assert sum(slot.count for slot in config.roles) == config.num_players


def test_preset_12_yn_hunter_idiot_composition() -> None:
    config = build_preset("std_12_yn_hunter_idiot")
    counts = {slot.role: slot.count for slot in config.roles}
    assert counts[RoleType.WEREWOLF] == 4
    assert counts[RoleType.VILLAGER] == 4
    assert counts[RoleType.SEER] == 1
    assert counts[RoleType.WITCH] == 1
    assert counts[RoleType.HUNTER] == 1
    assert counts[RoleType.IDIOT] == 1


def test_preset_9_kill_side_witch_self_rescue_first_night() -> None:
    config = build_preset("std_9_kill_side")
    assert config.num_players == 9
    assert config.witch.self_rescue_first_night is True


def test_build_preset_unknown_name_raises() -> None:
    with pytest.raises(ConfigError):
        build_preset("does_not_exist")


def test_faction_of() -> None:
    assert faction_of(RoleType.WEREWOLF) == Faction.WOLF
    for role in (
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.WITCH,
        RoleType.HUNTER,
        RoleType.GUARD,
        RoleType.IDIOT,
    ):
        assert faction_of(role) == Faction.GOOD


def test_validate_config_rejects_count_mismatch() -> None:
    config = GameConfig(
        config_id="bad",
        num_players=12,
        roles=[RoleSlot(role=RoleType.WEREWOLF, count=3)],
    )
    with pytest.raises(ConfigError, match="num_players"):
        validate_config(config)


def test_validate_config_rejects_night_order_role_not_in_setup() -> None:
    config = GameConfig(
        config_id="bad2",
        num_players=4,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=1),
            RoleSlot(role=RoleType.VILLAGER, count=3),
        ],
        night_order=[RoleType.WEREWOLF, RoleType.SEER],  # SEER 不在板子里
    )
    with pytest.raises(ConfigError, match="night_order"):
        validate_config(config)


def test_validate_config_rejects_no_wolves() -> None:
    config = GameConfig(
        config_id="bad3",
        num_players=3,
        roles=[RoleSlot(role=RoleType.VILLAGER, count=3)],
        night_order=[],
    )
    with pytest.raises(ConfigError, match="狼"):
        validate_config(config)


def test_gameconfig_is_frozen() -> None:
    config = build_preset("std_9_kill_all")
    with pytest.raises(Exception):
        config.num_players = 8  # type: ignore[misc]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.engine.config'`）。

- [ ] **Step 3: 实现 `config.py`**

Create `backend/app/engine/config.py`：
```python
"""GameConfig、内置 preset 与校验。

严格按规格 §3.2 实现；所有规则默认值都暴露为可配置项，不硬编码。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RoleType(str, Enum):
    WEREWOLF = "WEREWOLF"
    VILLAGER = "VILLAGER"
    SEER = "SEER"
    WITCH = "WITCH"
    HUNTER = "HUNTER"
    GUARD = "GUARD"
    IDIOT = "IDIOT"


class Faction(str, Enum):
    GOOD = "GOOD"
    WOLF = "WOLF"


def faction_of(role: RoleType) -> Faction:
    return Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD


class WinCondition(str, Enum):
    KILL_SIDE = "KILL_SIDE"  # 屠边：杀光村民或杀光神职
    KILL_ALL = "KILL_ALL"  # 屠城：杀光所有好人


class SpeechOrderRule(str, Enum):
    SHERIFF_DECIDES = "SHERIFF_DECIDES"
    DEATH_NEXT = "DEATH_NEXT"
    FIXED_CLOCKWISE = "FIXED_CLOCKWISE"
    ODD_EVEN_CLOCK = "ODD_EVEN_CLOCK"
    BIDDING = "BIDDING"


class TieRule(str, Enum):
    PK_THEN_NO_EXILE = "PK_THEN_NO_EXILE"
    PK_THEN_RANDOM = "PK_THEN_RANDOM"
    NO_EXILE = "NO_EXILE"


class LastWordsRule(str, Enum):
    FIRST_NIGHT_ONLY = "FIRST_NIGHT_ONLY"
    ALWAYS_NIGHT = "ALWAYS_NIGHT"
    N_EQUALS_WOLVES = "N_EQUALS_WOLVES"


class WitchRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    self_rescue_first_night: bool = False
    self_rescue_always: bool = False
    two_potions_same_night: bool = False
    knows_kill_after_antidote_used: bool = False


class GuardRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    can_guard_self: bool = True
    can_guard_same_target_consecutively: bool = False
    guard_plus_antidote_cancels: bool = True


class SheriffRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = True
    vote_weight: float = 1.5
    election_before_first_death_announce: bool = True
    badge_flow_enabled: bool = True
    wolf_selfdestruct_eats_badge: bool = True


class RoleSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: RoleType
    count: int


def _default_roles() -> list[RoleSlot]:
    return [
        RoleSlot(role=RoleType.WEREWOLF, count=4),
        RoleSlot(role=RoleType.VILLAGER, count=4),
        RoleSlot(role=RoleType.SEER, count=1),
        RoleSlot(role=RoleType.WITCH, count=1),
        RoleSlot(role=RoleType.HUNTER, count=1),
        RoleSlot(role=RoleType.IDIOT, count=1),
    ]


def _default_night_order() -> list[RoleType]:
    return [
        RoleType.GUARD,
        RoleType.WEREWOLF,
        RoleType.WITCH,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.IDIOT,
    ]


class GameConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str
    name: str = "标准12人预女猎白"
    num_players: int = 12
    roles: list[RoleSlot] = Field(default_factory=_default_roles)
    win_condition: WinCondition = WinCondition.KILL_SIDE
    night_order: list[RoleType] = Field(default_factory=_default_night_order)
    speech_order_rule: SpeechOrderRule = SpeechOrderRule.SHERIFF_DECIDES
    tie_rule: TieRule = TieRule.PK_THEN_NO_EXILE
    witch: WitchRule = Field(default_factory=WitchRule)
    guard: GuardRule = Field(default_factory=GuardRule)
    sheriff: SheriffRule = Field(default_factory=SheriffRule)
    last_words: LastWordsRule = LastWordsRule.FIRST_NIGHT_ONLY
    allow_wolf_self_knife: bool = True
    allow_wolf_empty_knife: bool = True
    wolf_first_kill_priority: bool = True
    speech_timeout_sec: int = 90
    action_timeout_sec: int = 45
    max_rounds: int = 20
    seed: int | None = None


class ConfigError(ValueError):
    """GameConfig 校验失败。"""


def _preset_12_yn_hunter_idiot() -> GameConfig:
    return GameConfig(config_id="std_12_yn_hunter_idiot", name="标准12人预女猎白")


def _preset_12_yn_hunter_guard() -> GameConfig:
    return GameConfig(
        config_id="std_12_yn_hunter_guard",
        name="标准12人预女猎守",
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=4),
            RoleSlot(role=RoleType.VILLAGER, count=4),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.HUNTER, count=1),
            RoleSlot(role=RoleType.GUARD, count=1),
        ],
    )


def _preset_9_kill_side() -> GameConfig:
    return GameConfig(
        config_id="std_9_kill_side",
        name="9人屠边预女猎",
        num_players=9,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=3),
            RoleSlot(role=RoleType.VILLAGER, count=3),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.HUNTER, count=1),
        ],
        win_condition=WinCondition.KILL_SIDE,
        night_order=[
            RoleType.WEREWOLF,
            RoleType.WITCH,
            RoleType.SEER,
            RoleType.HUNTER,
        ],
        witch=WitchRule(self_rescue_first_night=True),
    )


def _preset_9_kill_all() -> GameConfig:
    return _preset_9_kill_side().model_copy(
        update={
            "config_id": "std_9_kill_all",
            "name": "9人屠城预女猎",
            "win_condition": WinCondition.KILL_ALL,
        }
    )


_PRESETS = {
    "std_12_yn_hunter_idiot": _preset_12_yn_hunter_idiot,
    "std_12_yn_hunter_guard": _preset_12_yn_hunter_guard,
    "std_9_kill_side": _preset_9_kill_side,
    "std_9_kill_all": _preset_9_kill_all,
}


def build_preset(name: str) -> GameConfig:
    if name not in _PRESETS:
        raise ConfigError(f"未知 preset：{name}；可用：{sorted(_PRESETS)}")
    return _PRESETS[name]()


def validate_config(config: GameConfig) -> None:
    """校验人数、night_order 角色归属、胜利条件相容性。失败抛 ConfigError。"""
    total = sum(slot.count for slot in config.roles)
    if total != config.num_players:
        raise ConfigError(
            f"角色总数 {total} 与 num_players {config.num_players} 不一致"
        )
    if any(slot.count < 0 for slot in config.roles):
        raise ConfigError("角色 count 不能为负")

    setup_roles = {slot.role for slot in config.roles if slot.count > 0}
    for role in config.night_order:
        if role not in setup_roles:
            raise ConfigError(f"night_order 含板子中不存在的角色：{role}")

    if RoleType.WEREWOLF not in setup_roles:
        raise ConfigError("板子必须至少有 1 名狼人")
    if not any(faction_of(slot.role) == Faction.GOOD for slot in config.roles):
        raise ConfigError("板子必须至少有 1 名好人")
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS（全部 parametrize + 9 个用例通过）。

- [ ] **Step 5: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过。
```bash
git add backend/app/engine/config.py backend/tests/test_config.py
git commit -m "feat(engine): GameConfig、presets 与 validate_config"
```

### Task 3: 状态模型 `state.py`

**Files:**
- Create: `backend/app/engine/state.py`
- Test: `backend/tests/test_state.py`

**Interfaces:**
- Consumes: `config.RoleType`、`config.Faction`、`config.GameConfig`、`config.faction_of`。
- Produces：
  - `Player`（frozen）：`seat, display_name, player_type, role, faction, alive, is_sheriff, idiot_revealed, can_vote, witch_antidote, witch_poison, hunter_can_shoot, last_guard_target`。
  - `NightActions`（frozen）：`guard_target, wolf_target, witch_save, witch_poison_target, seer_check`。
  - `GameState`（frozen）：见下字段清单。
  - helper 纯函数：`player_at(state, seat) -> Player`、`living(state) -> list[Player]`、`living_seats(state) -> list[int]`、`living_wolves(state) -> list[Player]`、`living_of_role(state, role) -> list[Player]`。

> **注意**：`GameState.players` 用 `tuple[Player, ...]`（frozen 语义），`votes`/`wolf_proposals` 用 `dict`。frozen 只禁止属性重绑定；`reduce` 永远构造新 tuple/dict，绝不原地改。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_state.py`：
```python
import pytest

from app.engine.config import Faction, RoleType, build_preset
from app.engine.phases import Phase
from app.engine.state import (
    GameState,
    NightActions,
    Player,
    living,
    living_seats,
    living_wolves,
    player_at,
)


def _mk_player(seat: int, role: RoleType, alive: bool = True) -> Player:
    return Player(
        seat=seat,
        display_name=f"P{seat}",
        player_type="AGENT",
        role=role,
        faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
        alive=alive,
    )


def _mk_state() -> GameState:
    players = (
        _mk_player(0, RoleType.WEREWOLF),
        _mk_player(1, RoleType.WEREWOLF, alive=False),
        _mk_player(2, RoleType.SEER),
        _mk_player(3, RoleType.VILLAGER),
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.NIGHT_WEREWOLF,
        round=1,
        players=players,
    )


def test_player_defaults() -> None:
    p = _mk_player(0, RoleType.WITCH)
    assert p.alive is True
    assert p.witch_antidote is True
    assert p.witch_poison is True
    assert p.hunter_can_shoot is True
    assert p.can_vote is True
    assert p.last_guard_target is None


def test_player_at_and_living() -> None:
    state = _mk_state()
    assert player_at(state, 2).role == RoleType.SEER
    assert living_seats(state) == [0, 2, 3]
    assert [p.seat for p in living(state)] == [0, 2, 3]
    assert [p.seat for p in living_wolves(state)] == [0]


def test_player_at_missing_raises() -> None:
    state = _mk_state()
    with pytest.raises(KeyError):
        player_at(state, 99)


def test_nightactions_defaults_empty() -> None:
    na = NightActions()
    assert na.guard_target is None
    assert na.wolf_target is None
    assert na.witch_save is False
    assert na.witch_poison_target is None
    assert na.seer_check is None


def test_gamestate_is_frozen() -> None:
    state = _mk_state()
    with pytest.raises(Exception):
        state.round = 2  # type: ignore[misc]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL（`app.engine.state` / `app.engine.phases` 不存在）。

> 说明：`phases.Phase` 由 Task 6 实现；本任务先建 `phases.py` 的最小 `Phase` 枚举占位以让 import 成立，Task 6 再补 `expected_actors`。为避免顺序耦合，下一步同时建 `phases.py`。

- [ ] **Step 3: 建最小 `phases.py`（仅 Phase 枚举）**

Create `backend/app/engine/phases.py`：
```python
"""阶段枚举与转移逻辑。expected_actors 由 Task 6 补全。"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    LOBBY = "LOBBY"
    ROLE_ASSIGN = "ROLE_ASSIGN"
    NIGHT_GUARD = "NIGHT_GUARD"
    NIGHT_WEREWOLF = "NIGHT_WEREWOLF"
    NIGHT_WITCH = "NIGHT_WITCH"
    NIGHT_SEER = "NIGHT_SEER"
    NIGHT_HUNTER_CONFIRM = "NIGHT_HUNTER_CONFIRM"
    WIN_CHECK = "WIN_CHECK"
    SHERIFF_ELECTION = "SHERIFF_ELECTION"
    SHERIFF_PK = "SHERIFF_PK"
    DEATH_ANNOUNCE = "DEATH_ANNOUNCE"
    LAST_WORDS = "LAST_WORDS"
    DAY_SPEECH = "DAY_SPEECH"
    VOTE = "VOTE"
    VOTE_PK = "VOTE_PK"
    EXILE = "EXILE"
    HUNTER_SHOOT = "HUNTER_SHOOT"
    IDIOT_FLIP = "IDIOT_FLIP"
    GAME_OVER = "GAME_OVER"
```

- [ ] **Step 4: 实现 `state.py`**

Create `backend/app/engine/state.py`：
```python
"""游戏状态模型（frozen Pydantic）与只读查询 helper。

reduce 用 model_copy(update=...) 返回副本；本模块不含任何转移逻辑。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.config import Faction, GameConfig, RoleType
from app.engine.phases import Phase


class Player(BaseModel):
    model_config = ConfigDict(frozen=True)

    seat: int
    display_name: str
    player_type: Literal["HUMAN", "AGENT"] = "AGENT"
    role: RoleType
    faction: Faction
    alive: bool = True
    is_sheriff: bool = False
    idiot_revealed: bool = False
    can_vote: bool = True
    # 角色专属状态
    witch_antidote: bool = True
    witch_poison: bool = True
    hunter_can_shoot: bool = True
    last_guard_target: int | None = None


class NightActions(BaseModel):
    model_config = ConfigDict(frozen=True)

    guard_target: int | None = None
    wolf_target: int | None = None
    witch_save: bool = False
    witch_poison_target: int | None = None
    seer_check: int | None = None


class GameState(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    config: GameConfig
    phase: Phase
    round: int = 0
    players: tuple[Player, ...]
    sheriff_seat: int | None = None

    # 发言与投票收集
    speech_order: tuple[int, ...] = ()
    speech_idx: int = 0
    votes: dict[int, int | None] = Field(default_factory=dict)
    vote_candidates: tuple[int, ...] = ()  # 空=全体存活；PK 时限定
    tie_round: int = 0  # 0=首轮投票，1=PK 轮

    # 夜晚收集
    pending_night: NightActions = Field(default_factory=NightActions)
    wolf_proposals: dict[int, int | None] = Field(default_factory=dict)  # seat->target(None=空刀)
    acted_seats: frozenset[int] = frozenset()  # 本夜已提交夜间行动的座位（含狼）
    night_deaths: tuple[int, ...] = ()  # 本夜结算出的死者（供公布/遗言）
    resolved_first_night: bool = False

    # 待处理技能 / 出局
    pending_hunter: int | None = None
    day_exiled: int | None = None

    winner: str | None = None
    rng_state: int = 0
    state_version: int = 0


def player_at(state: GameState, seat: int) -> Player:
    for p in state.players:
        if p.seat == seat:
            return p
    raise KeyError(f"座位 {seat} 不存在")


def living(state: GameState) -> list[Player]:
    return [p for p in state.players if p.alive]


def living_seats(state: GameState) -> list[int]:
    return [p.seat for p in state.players if p.alive]


def living_wolves(state: GameState) -> list[Player]:
    return [p for p in state.players if p.alive and p.faction == Faction.WOLF]


def living_of_role(state: GameState, role: RoleType) -> list[Player]:
    return [p for p in state.players if p.alive and p.role == role]
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 6: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过。
```bash
git add backend/app/engine/state.py backend/app/engine/phases.py backend/tests/test_state.py
git commit -m "feat(engine): 状态模型 state 与 Phase 枚举骨架"
```

### Task 4: 事件、类型化 payload 与 `reduce`

**Files:**
- Create: `backend/app/engine/events.py`
- Test: `backend/tests/test_events.py`

**Interfaces:**
- Consumes: `state.GameState`、`state.Player`、`state.NightActions`、`phases.Phase`、`config.RoleType`。
- Produces：
  - `Visibility`（PUBLIC/WOLVES/ROLE_SELF/GM_ONLY）。
  - `EventType`（见实现枚举；Stage 1 只用其中一部分，后续 stage 复用同一枚举）。
  - 类型化 payload 模型（frozen）：`RolesAssignedPayload`、`PhaseChangedPayload`、`GuardProtectedPayload`、`WolfKillProposedPayload`、`WolfKillDecidedPayload`、`WitchActedPayload`、`SeerCheckedPayload`、`NightResolvedPayload`、`DeathAnnouncedPayload`、`PlayerSpokePayload`、`VoteCastPayload`、`VoteResultPayload`、`PlayerExiledPayload`、`GameOverPayload`、`SkipPayload`、`RoundStartedPayload`。（Stage 2/3 会在本文件追加更多 payload。）
  - `Event`（frozen）：`seq, game_id, ts, type, actor_seat, payload, visibility, meta`。
  - `reduce(state: GameState, event: Event) -> GameState`。
  - `reduce_all(initial: GameState, events: Iterable[Event]) -> GameState`。

> **payload 设计**：payload 是 `EventPayload` 的具体子类（frozen `BaseModel`），`Event.payload: EventPayload`。`reduce` 按 `event.type` 分派并对 payload 做 `isinstance` 收窄（mypy strict 下有效）。`reduce` 每次都从 `event.type` 决定新状态，绝不原地改。**每个 event 应用后都把 `state_version` +1**（在 `reduce` 末尾统一处理）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_events.py`：
```python
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    PhaseChangedPayload,
    Visibility,
    reduce,
    reduce_all,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _base_state() -> GameState:
    players = tuple(
        Player(
            seat=s,
            display_name=f"P{s}",
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for s in range(4)
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.NIGHT_WEREWOLF,
        players=players,
    )


def _evt(seq: int, type_: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g1",
        ts=float(seq),
        type=type_,
        actor_seat=actor,
        payload=payload,  # type: ignore[arg-type]
        visibility=Visibility.GM_ONLY,
    )


def test_phase_changed_updates_phase_and_bumps_version() -> None:
    state = _base_state()
    ev = _evt(1, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WITCH))
    new = reduce(state, ev)
    assert new.phase == Phase.NIGHT_WITCH
    assert new.state_version == state.state_version + 1
    assert state.phase == Phase.NIGHT_WEREWOLF  # 原状态不变（纯函数）


def test_death_announced_marks_dead() -> None:
    state = _base_state()
    ev = _evt(1, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(2,)))
    new = reduce(state, ev)
    assert next(p for p in new.players if p.seat == 2).alive is False
    assert next(p for p in new.players if p.seat == 0).alive is True


def test_reduce_all_applies_in_order() -> None:
    state = _base_state()
    events = [
        _evt(1, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(2,))),
        _evt(2, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH)),
    ]
    new = reduce_all(state, events)
    assert new.phase == Phase.DAY_SPEECH
    assert next(p for p in new.players if p.seat == 2).alive is False
    assert new.state_version == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL（`app.engine.events` 不存在）。

- [ ] **Step 3: 实现 `events.py`**

Create `backend/app/engine/events.py`：
```python
"""事件溯源：类型化 payload、Event、reduce。

reduce 是唯一写路径。state = reduce_all(initial, events)。
每个事件应用后 state_version += 1，rng_state 由使用随机的事件在 payload 里带出新值。
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.engine.config import Faction, RoleType
from app.engine.phases import Phase
from app.engine.state import GameState, NightActions, Player


class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    WOLVES = "WOLVES"
    ROLE_SELF = "ROLE_SELF"
    GM_ONLY = "GM_ONLY"


class EventType(str, Enum):
    GAME_CREATED = "GAME_CREATED"
    ROLES_ASSIGNED = "ROLES_ASSIGNED"
    GAME_STARTED = "GAME_STARTED"
    ROUND_STARTED = "ROUND_STARTED"
    PHASE_CHANGED = "PHASE_CHANGED"
    GUARD_PROTECTED = "GUARD_PROTECTED"
    WOLF_KILL_PROPOSED = "WOLF_KILL_PROPOSED"
    WOLF_KILL_DECIDED = "WOLF_KILL_DECIDED"
    WITCH_SAVED = "WITCH_SAVED"
    WITCH_POISONED = "WITCH_POISONED"
    SEER_CHECKED = "SEER_CHECKED"
    NIGHT_RESOLVED = "NIGHT_RESOLVED"
    DEATH_ANNOUNCED = "DEATH_ANNOUNCED"
    PLAYER_SPOKE = "PLAYER_SPOKE"
    VOTE_STARTED = "VOTE_STARTED"
    VOTE_CAST = "VOTE_CAST"
    VOTE_RESULT = "VOTE_RESULT"
    PLAYER_EXILED = "PLAYER_EXILED"
    ROLE_SKIPPED = "ROLE_SKIPPED"
    GAME_OVER = "GAME_OVER"
    # Stage 2/3 追加：LAST_WORDS, HUNTER_SHOT, IDIOT_REVEALED,
    # SHERIFF_CANDIDACY, SHERIFF_WITHDREW, SHERIFF_ELECTED, BADGE_PASSED,
    # WOLF_SELF_DESTRUCT ...
    LAST_WORDS = "LAST_WORDS"
    HUNTER_SHOT = "HUNTER_SHOT"
    IDIOT_REVEALED = "IDIOT_REVEALED"
    SHERIFF_CANDIDACY = "SHERIFF_CANDIDACY"
    SHERIFF_WITHDREW = "SHERIFF_WITHDREW"
    SHERIFF_VOTE_CAST = "SHERIFF_VOTE_CAST"
    SHERIFF_ELECTED = "SHERIFF_ELECTED"
    SHERIFF_BADGE_LOST = "SHERIFF_BADGE_LOST"
    BADGE_PASSED = "BADGE_PASSED"
    WOLF_SELF_DESTRUCT = "WOLF_SELF_DESTRUCT"


class EventPayload(BaseModel):
    model_config = ConfigDict(frozen=True)


class RolesAssignedPayload(EventPayload):
    # 座位->角色（GM_ONLY）；用 list[tuple] 以便确定性序列化
    assignments: tuple[tuple[int, RoleType], ...]
    new_rng_state: int


class RoundStartedPayload(EventPayload):
    round: int


class PhaseChangedPayload(EventPayload):
    to: Phase
    speech_order: tuple[int, ...] | None = None  # 进入 DAY_SPEECH/PK 发言时一并设定顺序


class VoteStartedPayload(EventPayload):
    candidates: tuple[int, ...]  # 空=全体存活可投；PK 时限定被投对象
    tie_round: int  # 0=首轮，1=PK


class GuardProtectedPayload(EventPayload):
    target: int | None  # None=空守


class WolfKillProposedPayload(EventPayload):
    wolf_seat: int
    target: int | None  # None=空刀


class WolfKillDecidedPayload(EventPayload):
    target: int | None  # None=空刀（含意见不统一）


class WitchActedPayload(EventPayload):
    save: bool = False
    poison_target: int | None = None


class SeerCheckedPayload(EventPayload):
    target: int
    result: Faction


class NightResolvedPayload(EventPayload):
    deaths: tuple[int, ...]


class DeathAnnouncedPayload(EventPayload):
    seats: tuple[int, ...]


class PlayerSpokePayload(EventPayload):
    content: str
    claim_role: RoleType | None = None
    badge_flow: tuple[int, ...] = ()


class VoteCastPayload(EventPayload):
    voter: int
    target: int | None  # None=弃票


class VoteResultPayload(EventPayload):
    tally: tuple[tuple[int, float], ...]  # (target_seat, weighted_votes)
    exiled: int | None
    tie_seats: tuple[int, ...]


class PlayerExiledPayload(EventPayload):
    seat: int | None  # None=无人出局


class RoleSkippedPayload(EventPayload):
    role: RoleType
    reason: str  # "absent" | "dead" | "no_potion" ...


class GameOverPayload(EventPayload):
    winner: str | None  # "GOOD" | "WOLF" | None(平局)


def _replace_player(
    players: tuple[Player, ...], seat: int, **updates: object
) -> tuple[Player, ...]:
    return tuple(p.model_copy(update=updates) if p.seat == seat else p for p in players)


def _actor(event: Event) -> int:
    if event.actor_seat is None:
        raise ValueError(f"事件 {event.type} 缺少 actor_seat")
    return event.actor_seat


def reduce(state: GameState, event: Event) -> GameState:
    """把单个事件应用到状态，返回新状态。唯一写路径。"""
    updates = _reduce_dispatch(state, event)
    updates["state_version"] = state.state_version + 1
    return state.model_copy(update=updates)


def _reduce_dispatch(state: GameState, event: Event) -> dict[str, object]:
    p = event.payload
    t = event.type

    if t == EventType.ROLES_ASSIGNED and isinstance(p, RolesAssignedPayload):
        role_by_seat = dict(p.assignments)
        from app.engine.config import faction_of

        players = tuple(
            pl.model_copy(
                update={
                    "role": role_by_seat[pl.seat],
                    "faction": faction_of(role_by_seat[pl.seat]),
                }
            )
            for pl in state.players
        )
        return {"players": players, "rng_state": p.new_rng_state}

    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        # 新的一夜：清空夜晚收集与投票暂存
        return {
            "round": p.round,
            "pending_night": NightActions(),
            "wolf_proposals": {},
            "acted_seats": frozenset(),
            "night_deaths": (),
            "votes": {},
            "vote_candidates": (),
            "tie_round": 0,
            "speech_order": (),
            "speech_idx": 0,
        }

    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        upd: dict[str, object] = {"phase": p.to}
        if p.speech_order is not None:
            upd["speech_order"] = p.speech_order
            upd["speech_idx"] = 0
        return upd

    if t == EventType.VOTE_STARTED and isinstance(p, VoteStartedPayload):
        return {"votes": {}, "vote_candidates": p.candidates, "tie_round": p.tie_round}

    if t == EventType.GUARD_PROTECTED and isinstance(p, GuardProtectedPayload):
        return {
            "pending_night": state.pending_night.model_copy(update={"guard_target": p.target}),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.WOLF_KILL_PROPOSED and isinstance(p, WolfKillProposedPayload):
        proposals = dict(state.wolf_proposals)
        proposals[p.wolf_seat] = p.target
        return {
            "wolf_proposals": proposals,
            "acted_seats": state.acted_seats | {p.wolf_seat},
        }

    if t == EventType.WOLF_KILL_DECIDED and isinstance(p, WolfKillDecidedPayload):
        return {"pending_night": state.pending_night.model_copy(update={"wolf_target": p.target})}

    if t == EventType.WITCH_SAVED and isinstance(p, WitchActedPayload):
        return {
            "pending_night": state.pending_night.model_copy(update={"witch_save": True}),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.WITCH_POISONED and isinstance(p, WitchActedPayload):
        return {
            "pending_night": state.pending_night.model_copy(
                update={"witch_poison_target": p.poison_target}
            ),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        return {
            "pending_night": state.pending_night.model_copy(update={"seer_check": p.target}),
            "acted_seats": state.acted_seats | {_actor(event)},
        }

    if t == EventType.NIGHT_RESOLVED and isinstance(p, NightResolvedPayload):
        # 结算只记录死者名单；实际置死在 DEATH_ANNOUNCED（保证「结算/公布」两步可分别过滤可见性）
        return {"night_deaths": p.deaths, "resolved_first_night": True}

    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        players = state.players
        for seat in p.seats:
            players = _replace_player(players, seat, alive=False)
        return {"players": players}

    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        return {"speech_idx": state.speech_idx + 1}

    if t == EventType.VOTE_CAST and isinstance(p, VoteCastPayload):
        votes = dict(state.votes)
        votes[p.voter] = p.target
        return {"votes": votes}

    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        return {}  # 纯公示，不改状态；出局在 PLAYER_EXILED

    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        if p.seat is None:
            return {"day_exiled": None}
        players = _replace_player(state.players, p.seat, alive=False)
        return {"players": players, "day_exiled": p.seat}

    if t == EventType.ROLE_SKIPPED and isinstance(p, RoleSkippedPayload):
        # 玩家主动 skip（actor 非空）也算「已行动」；系统跳过缺席/死亡角色 actor 为 None
        if event.actor_seat is not None:
            return {"acted_seats": state.acted_seats | {event.actor_seat}}
        return {}

    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        return {"winner": p.winner, "phase": Phase.GAME_OVER}

    # GAME_CREATED / GAME_STARTED 仅审计
    return {}


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    game_id: str
    ts: float  # 纯引擎内是逻辑 tick；墙钟时间由 runtime(M2) 写入 meta
    type: EventType
    actor_seat: int | None = None
    payload: EventPayload
    visibility: Visibility
    meta: dict[str, str] = {}


def reduce_all(initial: GameState, events: Iterable[Event]) -> GameState:
    state = initial
    for ev in events:
        state = reduce(state, ev)
    return state
```

> **实现顺序提示**：`Event` 引用 `EventPayload`，`reduce` 引用 `Event`。上面把 `Event` 定义放在 `reduce` 之后仅为叙述聚合；实现时把 `Event` 类移到 `EventPayload` 子类之后、`reduce` 之前即可（Python 需要 `Event` 在 `reduce_all` 使用前定义）。`_reduce_dispatch` 用 `event.payload` 是 `EventPayload` 基类，isinstance 收窄到具体子类。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_events.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过。
```bash
git add backend/app/engine/events.py backend/tests/test_events.py
git commit -m "feat(engine): 事件、类型化 payload 与 reduce"
```

### Task 5: 行动意图 `actions.py` 与测试工厂

**Files:**
- Create: `backend/app/engine/actions.py`
- Create: `backend/tests/factories.py`
- Test: `backend/tests/test_actions.py`

**Interfaces:**
- Consumes: `config.RoleType`。
- Produces：
  - `RejectedReason`（枚举，见实现）。
  - 行动模型（frozen）：`NightAction(actor_seat, action_type, target_seat)`；`DayVote(actor_seat, target_seat, abstain)`；`Speak(actor_seat, content, claim_role, badge_flow)`；`SheriffAction(actor_seat, action_type, target_seat, direction)`；`SelfDestruct(actor_seat)`。
  - `Action = NightAction | DayVote | Speak | SheriffAction | SelfDestruct`（type alias）。
  - `NightActionType`（kill/check/save/poison/guard/shoot/skip）、`SheriffActionType`、`Direction`（LEFT/RIGHT）枚举。
- `tests/factories.py` Produces：`stage1_config(seed: int) -> GameConfig`（9 人：3 狼+3 民+预言家+女巫+守卫，无猎人/白痴/警长），`stage1_game(seed: int) -> StepResult`（Task 9 后可用；本任务先只放 config）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_actions.py`：
```python
import pytest

from app.engine.actions import (
    DayVote,
    NightAction,
    NightActionType,
    SelfDestruct,
    Speak,
)


def test_night_action_construct() -> None:
    a = NightAction(actor_seat=3, action_type=NightActionType.CHECK, target_seat=5)
    assert a.actor_seat == 3
    assert a.action_type == NightActionType.CHECK
    assert a.target_seat == 5


def test_night_action_skip_allows_no_target() -> None:
    a = NightAction(actor_seat=2, action_type=NightActionType.SKIP)
    assert a.target_seat is None


def test_day_vote_abstain() -> None:
    v = DayVote(actor_seat=1, abstain=True)
    assert v.abstain is True
    assert v.target_seat is None


def test_speak_defaults() -> None:
    s = Speak(actor_seat=0, content="hello")
    assert s.claim_role is None
    assert s.badge_flow == ()


def test_self_destruct_only_actor() -> None:
    sd = SelfDestruct(actor_seat=7)
    assert sd.actor_seat == 7


def test_action_is_frozen() -> None:
    a = NightAction(actor_seat=1, action_type=NightActionType.SKIP)
    with pytest.raises(Exception):
        a.actor_seat = 2  # type: ignore[misc]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_actions.py -v`
Expected: FAIL（`app.engine.actions` 不存在）。

- [ ] **Step 3: 实现 `actions.py`**

Create `backend/app/engine/actions.py`：
```python
"""玩家行动意图模型（与 §4.1 工具 schema 一一对应）与拒绝原因。

行动只表达意图；是否合法由 engine.validate 裁决。
"""

from __future__ import annotations

from enum import Enum
from typing import Union

from pydantic import BaseModel, ConfigDict

from app.engine.config import RoleType


class NightActionType(str, Enum):
    KILL = "kill"
    CHECK = "check"
    SAVE = "save"
    POISON = "poison"
    GUARD = "guard"
    SHOOT = "shoot"
    SKIP = "skip"


class SheriffActionType(str, Enum):
    RUN_FOR_SHERIFF = "run_for_sheriff"
    WITHDRAW = "withdraw"
    VOTE_SHERIFF = "vote_sheriff"
    PASS_BADGE = "pass_badge"
    TEAR_BADGE = "tear_badge"
    SET_SPEECH_DIRECTION = "set_speech_direction"


class Direction(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class RejectedReason(str, Enum):
    NOT_YOUR_TURN = "NOT_YOUR_TURN"
    WRONG_PHASE = "WRONG_PHASE"
    DEAD_ACTOR = "DEAD_ACTOR"
    DEAD_TARGET = "DEAD_TARGET"
    INVALID_TARGET = "INVALID_TARGET"
    ALREADY_ACTED = "ALREADY_ACTED"
    NOT_WEREWOLF = "NOT_WEREWOLF"
    GUARD_SAME_TARGET = "GUARD_SAME_TARGET"
    GUARD_SELF_FORBIDDEN = "GUARD_SELF_FORBIDDEN"
    WITCH_NO_ANTIDOTE = "WITCH_NO_ANTIDOTE"
    WITCH_NO_POISON = "WITCH_NO_POISON"
    WITCH_SELF_RESCUE_FORBIDDEN = "WITCH_SELF_RESCUE_FORBIDDEN"
    WITCH_TWO_POTIONS_FORBIDDEN = "WITCH_TWO_POTIONS_FORBIDDEN"
    HUNTER_CANNOT_SHOOT = "HUNTER_CANNOT_SHOOT"
    NOT_A_CANDIDATE = "NOT_A_CANDIDATE"
    CANNOT_VOTE = "CANNOT_VOTE"
    NOT_SELF_DESTRUCTABLE = "NOT_SELF_DESTRUCTABLE"
    BIDDING_NOT_IMPLEMENTED = "BIDDING_NOT_IMPLEMENTED"


class NightAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    action_type: NightActionType
    target_seat: int | None = None


class DayVote(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    target_seat: int | None = None
    abstain: bool = False


class Speak(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    content: str
    claim_role: RoleType | None = None
    badge_flow: tuple[int, ...] = ()


class SheriffAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int
    action_type: SheriffActionType
    target_seat: int | None = None
    direction: Direction | None = None


class SelfDestruct(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_seat: int


Action = Union[NightAction, DayVote, Speak, SheriffAction, SelfDestruct]
```

- [ ] **Step 4: 建测试工厂（Stage 1 板子）**

Create `backend/tests/factories.py`：
```python
"""测试专用工厂。Stage 1 用无猎人/白痴/警长的 9 人板跑通核心循环。"""

from __future__ import annotations

from app.engine.config import (
    GameConfig,
    GuardRule,
    RoleSlot,
    RoleType,
    SheriffRule,
    WinCondition,
)


def stage1_config(seed: int) -> GameConfig:
    """3 狼 + 3 民 + 预言家 + 女巫 + 守卫 = 9 人，屠边，无警长。"""
    return GameConfig(
        config_id="stage1_test",
        name="Stage1 测试板",
        num_players=9,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=3),
            RoleSlot(role=RoleType.VILLAGER, count=3),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.GUARD, count=1),
        ],
        win_condition=WinCondition.KILL_SIDE,
        night_order=[
            RoleType.GUARD,
            RoleType.WEREWOLF,
            RoleType.WITCH,
            RoleType.SEER,
        ],
        guard=GuardRule(),
        sheriff=SheriffRule(enabled=False),
        seed=seed,
    )
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_actions.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 6: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过（`Union` 用于 type alias；如 ruff 建议 `X | Y` 语法，可改为 `NightAction | DayVote | ...` 并删除 `Union` import）。
```bash
git add backend/app/engine/actions.py backend/tests/factories.py backend/tests/test_actions.py
git commit -m "feat(engine): 行动意图模型、拒绝原因与测试工厂"
```

### Task 6: 结算纯函数 `resolver.py`

**Files:**
- Create: `backend/app/engine/resolver.py`
- Test: `backend/tests/test_night_resolution.py`
- Test: `backend/tests/test_win_conditions.py`

**Interfaces:**
- Consumes: `config.GameConfig`、`config.WinCondition`、`config.Faction`、`state.GameState`、`state.NightActions`、`state.living`、`state.living_wolves`。
- Produces：
  - `resolve_night(config: GameConfig, na: NightActions) -> frozenset[int]` —— 返回死者座位集合，实现 §3.3 伪代码。
  - `count_votes(votes: dict[int, int | None], weights: dict[int, float]) -> tuple[int | None, tuple[int, ...]]` —— 返回 `(exiled_or_None, tie_seats)`；无并列则 `tie_seats=()`，`exiled` 为唯一最高票；并列则 `exiled=None`，`tie_seats` 为并列最高者（升序）。
  - `check_win(state: GameState) -> str | None` —— 返回 `"GOOD"`/`"WOLF"`/`None`（未结束）。实现屠边/屠城。

- [ ] **Step 1: 写夜晚结算矩阵测试**

Create `backend/tests/test_night_resolution.py`：
```python
from app.engine.config import GuardRule
from app.engine.resolver import resolve_night
from app.engine.state import NightActions
from tests.factories import stage1_config


def _cfg(**guard_kw: object):
    cfg = stage1_config(seed=1)
    if guard_kw:
        return cfg.model_copy(update={"guard": GuardRule(**guard_kw)})  # type: ignore[arg-type]
    return cfg


def test_plain_kill_dies() -> None:
    na = NightActions(wolf_target=4)
    assert resolve_night(_cfg(), na) == frozenset({4})


def test_guard_blocks_kill() -> None:
    na = NightActions(wolf_target=4, guard_target=4)
    assert resolve_night(_cfg(), na) == frozenset()


def test_witch_save_blocks_kill() -> None:
    na = NightActions(wolf_target=4, witch_save=True)
    assert resolve_night(_cfg(), na) == frozenset()


def test_guard_plus_antidote_cancels_target_dies() -> None:
    # 同守同救：默认 guard_plus_antidote_cancels=True -> 奶死
    na = NightActions(wolf_target=4, guard_target=4, witch_save=True)
    assert resolve_night(_cfg(guard_plus_antidote_cancels=True), na) == frozenset({4})


def test_guard_plus_antidote_no_cancel_target_lives() -> None:
    na = NightActions(wolf_target=4, guard_target=4, witch_save=True)
    assert resolve_night(_cfg(guard_plus_antidote_cancels=False), na) == frozenset()


def test_poison_kills_through_guard() -> None:
    # 守卫挡不住毒
    na = NightActions(poison_target := 5 and None)  # placeholder, replaced below
    na = NightActions(guard_target=5, witch_poison_target=5)
    assert resolve_night(_cfg(), na) == frozenset({5})


def test_empty_knife_no_death() -> None:
    na = NightActions(wolf_target=None)
    assert resolve_night(_cfg(), na) == frozenset()


def test_kill_and_poison_two_deaths() -> None:
    na = NightActions(wolf_target=4, witch_poison_target=6)
    assert resolve_night(_cfg(), na) == frozenset({4, 6})
```

> 修掉上面的占位行：删除 `na = NightActions(poison_target := 5 and None)  # placeholder...` 这一行，只保留其下的 `na = NightActions(guard_target=5, witch_poison_target=5)`。（写测试时直接按修正版写；此处保留说明以免误抄。）

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_night_resolution.py -v`
Expected: FAIL（`app.engine.resolver` 不存在）。

- [ ] **Step 3: 写胜负判定测试**

Create `backend/tests/test_win_conditions.py`：
```python
from app.engine.config import (
    Faction,
    RoleType,
    WinCondition,
)
from app.engine.resolver import check_win
from app.engine.phases import Phase
from app.engine.state import GameState, Player
from tests.factories import stage1_config


def _state(alive_roles: list[tuple[RoleType, bool]], win: WinCondition) -> GameState:
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=role,
            faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
            alive=alive,
        )
        for i, (role, alive) in enumerate(alive_roles)
    )
    cfg = stage1_config(seed=1).model_copy(update={"win_condition": win})
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.WIN_CHECK,
        round=1,
        players=players,
    )


def test_good_wins_when_all_wolves_dead() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, False),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "GOOD"


def test_kill_side_wolf_wins_when_villagers_gone() -> None:
    # 屠边：村民杀光即狼胜（神职还在也算）
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, False),
            (RoleType.SEER, True),
            (RoleType.WITCH, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "WOLF"


def test_kill_side_wolf_wins_when_gods_gone() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, False),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "WOLF"


def test_kill_all_wolf_needs_all_good_dead() -> None:
    # 屠城：还有任一好人存活 -> 未结束
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, False),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_ALL,
    )
    assert check_win(st) is None


def test_ongoing_returns_none() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) is None
```

- [ ] **Step 4: 写票数统计测试**

Append 到 `backend/tests/test_win_conditions.py` 末尾（或新建 `test_votes.py`；此处并入以省文件）：
```python
from app.engine.resolver import count_votes


def test_count_votes_simple_majority() -> None:
    votes = {0: 3, 1: 3, 2: 4}
    weights = {0: 1.0, 1: 1.0, 2: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 3
    assert tie == ()


def test_count_votes_tie() -> None:
    votes = {0: 3, 1: 4}
    weights = {0: 1.0, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled is None
    assert tie == (3, 4)


def test_count_votes_abstain_ignored() -> None:
    votes = {0: None, 1: 5, 2: None}
    weights = {0: 1.0, 1: 1.0, 2: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 5


def test_count_votes_sheriff_weight_breaks_tie() -> None:
    # 警长 1.5 票：seat0(警长)投3，seat1投4 -> 3 得 1.5 票胜
    votes = {0: 3, 1: 4}
    weights = {0: 1.5, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 3
    assert tie == ()


def test_count_votes_all_abstain_no_exile() -> None:
    votes = {0: None, 1: None}
    weights = {0: 1.0, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled is None
    assert tie == ()
```

- [ ] **Step 5: 实现 `resolver.py`**

Create `backend/app/engine/resolver.py`：
```python
"""夜晚结算、票数统计、胜负判定 —— 全部纯函数，无 IO、无状态副作用。"""

from __future__ import annotations

from app.engine.config import Faction, GameConfig, RoleType, WinCondition, faction_of
from app.engine.state import GameState, NightActions


def resolve_night(config: GameConfig, na: NightActions) -> frozenset[int]:
    """实现规格 §3.3 结算：守卫挡刀不挡毒；同守同救按开关判死。"""
    deaths: set[int] = set()

    killed = na.wolf_target
    if killed is not None:
        protected = killed == na.guard_target
        rescued = na.witch_save
        if protected and rescued and config.guard.guard_plus_antidote_cancels:
            deaths.add(killed)  # 同守同救 -> 奶死
        elif protected or rescued:
            pass  # 活
        else:
            deaths.add(killed)

    if na.witch_poison_target is not None:
        deaths.add(na.witch_poison_target)  # 毒穿守

    return frozenset(deaths)


def count_votes(
    votes: dict[int, int | None], weights: dict[int, float]
) -> tuple[int | None, tuple[int, ...]]:
    """加权计票。返回 (唯一最高票座位 或 None, 并列最高票座位升序元组)。"""
    tally: dict[int, float] = {}
    for voter, target in votes.items():
        if target is None:
            continue
        tally[target] = tally.get(target, 0.0) + weights.get(voter, 1.0)

    if not tally:
        return None, ()

    top = max(tally.values())
    leaders = sorted(seat for seat, w in tally.items() if w == top)
    if len(leaders) == 1:
        return leaders[0], ()
    return None, tuple(leaders)


def _alive_by_faction(state: GameState) -> tuple[int, int]:
    wolves = sum(1 for p in state.players if p.alive and p.faction == Faction.WOLF)
    goods = sum(1 for p in state.players if p.alive and p.faction == Faction.GOOD)
    return wolves, goods


def check_win(state: GameState) -> str | None:
    """屠边/屠城胜负判定。GOOD/WOLF/None。"""
    wolves, goods = _alive_by_faction(state)

    if wolves == 0:
        return "GOOD"
    if goods == 0:
        return "WOLF"

    if state.config.win_condition == WinCondition.KILL_ALL:
        return None  # 屠城：好人未清光则继续

    # 屠边：村民全灭 或 神职全灭 -> 狼胜
    villagers = sum(
        1 for p in state.players if p.alive and p.role == RoleType.VILLAGER
    )
    gods = sum(
        1
        for p in state.players
        if p.alive and faction_of(p.role) == Faction.GOOD and p.role != RoleType.VILLAGER
    )
    has_villagers_in_setup = any(
        slot.role == RoleType.VILLAGER and slot.count > 0 for slot in state.config.roles
    )
    has_gods_in_setup = any(
        slot.role != RoleType.VILLAGER
        and faction_of(slot.role) == Faction.GOOD
        and slot.count > 0
        for slot in state.config.roles
    )
    if has_villagers_in_setup and villagers == 0:
        return "WOLF"
    if has_gods_in_setup and gods == 0:
        return "WOLF"
    return None
```

- [ ] **Step 6: 运行确认全绿**

Run: `uv run pytest tests/test_night_resolution.py tests/test_win_conditions.py -v`
Expected: PASS（夜晚 8 项 + 胜负 5 项 + 计票 5 项）。

- [ ] **Step 7: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过。
```bash
git add backend/app/engine/resolver.py backend/tests/test_night_resolution.py backend/tests/test_win_conditions.py
git commit -m "feat(engine): 夜晚结算/计票/胜负判定 resolver"
```

### Task 7: 阶段行动者 `phases.expected_actors`

**Files:**
- Modify: `backend/app/engine/phases.py`（补全 `Phase` 之外的逻辑）
- Test: `backend/tests/test_phases.py`

**Interfaces:**
- Consumes: `state.GameState`、`state.living`、`state.living_wolves`、`state.living_of_role`、`config.RoleType`。
- Produces：
  - `phase_for_role(role: RoleType) -> Phase | None`。
  - `night_phase_sequence(config: GameConfig) -> list[Phase]` —— 按 `night_order` 过滤出有对应夜间阶段的角色序列。
  - `next_night_phase(config: GameConfig, current: Phase) -> Phase | None` —— 序列中的下一夜间阶段；末尾返回 None。
  - `expected_actors(state: GameState) -> set[int]` —— 当前必须行动的座位集合；系统阶段返回空集。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_phases.py`：
```python
from app.engine.config import RoleType
from app.engine.phases import (
    Phase,
    expected_actors,
    next_night_phase,
    night_phase_sequence,
    phase_for_role,
)
from app.engine.state import GameState, NightActions
from tests.factories import stage1_config
from tests.test_state import _mk_player  # 复用构造 helper


def _state(phase: Phase, **kw: object) -> GameState:
    players = (
        _mk_player(0, RoleType.WEREWOLF),
        _mk_player(1, RoleType.WEREWOLF),
        _mk_player(2, RoleType.WEREWOLF),
        _mk_player(3, RoleType.SEER),
        _mk_player(4, RoleType.WITCH),
        _mk_player(5, RoleType.GUARD),
        _mk_player(6, RoleType.VILLAGER),
        _mk_player(7, RoleType.VILLAGER),
        _mk_player(8, RoleType.VILLAGER),
    )
    base: dict[str, object] = {
        "game_id": "g",
        "config": stage1_config(seed=1),
        "phase": phase,
        "round": 1,
        "players": players,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_phase_for_role() -> None:
    assert phase_for_role(RoleType.GUARD) == Phase.NIGHT_GUARD
    assert phase_for_role(RoleType.WEREWOLF) == Phase.NIGHT_WEREWOLF
    assert phase_for_role(RoleType.WITCH) == Phase.NIGHT_WITCH
    assert phase_for_role(RoleType.SEER) == Phase.NIGHT_SEER
    assert phase_for_role(RoleType.VILLAGER) is None


def test_night_sequence_stage1() -> None:
    seq = night_phase_sequence(stage1_config(seed=1))
    assert seq == [
        Phase.NIGHT_GUARD,
        Phase.NIGHT_WEREWOLF,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
    ]
    assert next_night_phase(stage1_config(seed=1), Phase.NIGHT_WEREWOLF) == Phase.NIGHT_WITCH
    assert next_night_phase(stage1_config(seed=1), Phase.NIGHT_SEER) is None


def test_expected_guard_phase() -> None:
    assert expected_actors(_state(Phase.NIGHT_GUARD)) == {5}


def test_expected_wolves_excludes_already_proposed() -> None:
    st = _state(Phase.NIGHT_WEREWOLF, wolf_proposals={0: 6})
    assert expected_actors(st) == {1, 2}


def test_expected_witch_needs_potion() -> None:
    # 无药女巫 -> 不再期待其行动
    players = tuple(
        p.model_copy(update={"witch_antidote": False, "witch_poison": False})
        if p.seat == 4
        else p
        for p in _state(Phase.NIGHT_WITCH).players
    )
    st = _state(Phase.NIGHT_WITCH).model_copy(update={"players": players})
    assert expected_actors(st) == set()
    assert expected_actors(_state(Phase.NIGHT_WITCH)) == {4}


def test_expected_day_speech_current_speaker() -> None:
    st = _state(Phase.DAY_SPEECH, speech_order=(6, 7, 8), speech_idx=1)
    assert expected_actors(st) == {7}
    st_done = _state(Phase.DAY_SPEECH, speech_order=(6, 7, 8), speech_idx=3)
    assert expected_actors(st_done) == set()


def test_expected_vote_excludes_voted() -> None:
    st = _state(Phase.VOTE, votes={0: 6})
    assert 0 not in expected_actors(st)
    assert expected_actors(st) == {1, 2, 3, 4, 5, 6, 7, 8}


def test_expected_vote_pk_excludes_candidates() -> None:
    st = _state(Phase.VOTE_PK, vote_candidates=(6, 7))
    got = expected_actors(st)
    assert 6 not in got and 7 not in got
    assert got == {0, 1, 2, 3, 4, 5, 8}


def test_expected_system_phases_empty() -> None:
    for ph in (Phase.WIN_CHECK, Phase.DEATH_ANNOUNCE, Phase.EXILE, Phase.GAME_OVER):
        assert expected_actors(_state(ph)) == set()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_phases.py -v`
Expected: FAIL（`expected_actors` 等未定义）。

- [ ] **Step 3: 补全 `phases.py`**

在 `backend/app/engine/phases.py` 的 `Phase` 枚举之后追加（保留已有 import 与枚举，新增下方内容）：
```python
from typing import TYPE_CHECKING

from app.engine.config import GameConfig, RoleType
from app.engine.state import (
    GameState,
    living,
    living_of_role,
    living_wolves,
)

if TYPE_CHECKING:  # 仅类型，避免循环 import 影响运行
    pass


_ROLE_TO_NIGHT_PHASE: dict[RoleType, Phase] = {
    RoleType.GUARD: Phase.NIGHT_GUARD,
    RoleType.WEREWOLF: Phase.NIGHT_WEREWOLF,
    RoleType.WITCH: Phase.NIGHT_WITCH,
    RoleType.SEER: Phase.NIGHT_SEER,
    RoleType.HUNTER: Phase.NIGHT_HUNTER_CONFIRM,
}


def phase_for_role(role: RoleType) -> Phase | None:
    return _ROLE_TO_NIGHT_PHASE.get(role)


def night_phase_sequence(config: GameConfig) -> list[Phase]:
    seq: list[Phase] = []
    for role in config.night_order:
        ph = phase_for_role(role)
        if ph is not None and ph not in seq:
            seq.append(ph)
    return seq


def next_night_phase(config: GameConfig, current: Phase) -> Phase | None:
    seq = night_phase_sequence(config)
    if current not in seq:
        return seq[0] if seq else None
    idx = seq.index(current)
    return seq[idx + 1] if idx + 1 < len(seq) else None


def expected_actors(state: GameState) -> set[int]:
    ph = state.phase

    if ph == Phase.NIGHT_GUARD:
        return {p.seat for p in living_of_role(state, RoleType.GUARD) if p.seat not in state.acted_seats}
    if ph == Phase.NIGHT_WEREWOLF:
        return {w.seat for w in living_wolves(state) if w.seat not in state.wolf_proposals}
    if ph == Phase.NIGHT_WITCH:
        return {
            w.seat
            for w in living_of_role(state, RoleType.WITCH)
            if w.seat not in state.acted_seats and (w.witch_antidote or w.witch_poison)
        }
    if ph == Phase.NIGHT_SEER:
        return {p.seat for p in living_of_role(state, RoleType.SEER) if p.seat not in state.acted_seats}
    if ph == Phase.NIGHT_HUNTER_CONFIRM:
        if state.round != 1:
            return set()
        return {p.seat for p in living_of_role(state, RoleType.HUNTER) if p.seat not in state.acted_seats}

    if ph == Phase.DAY_SPEECH:
        if state.speech_idx < len(state.speech_order):
            return {state.speech_order[state.speech_idx]}
        return set()

    if ph == Phase.VOTE:
        return {p.seat for p in living(state) if p.can_vote and p.seat not in state.votes}
    if ph == Phase.VOTE_PK:
        return {
            p.seat
            for p in living(state)
            if p.can_vote and p.seat not in state.vote_candidates and p.seat not in state.votes
        }

    if ph == Phase.HUNTER_SHOOT:
        return {state.pending_hunter} if state.pending_hunter is not None else set()

    # Stage 3 会补 SHERIFF_ELECTION / SHERIFF_PK；其余为系统阶段
    return set()
```

> **循环 import 提示**：`phases.py` 现在 import `state`，而 `state.py` import `phases.Phase`。为避免循环，`state.py` 只 import `Phase`（一个纯枚举，无反向依赖），`phases.py` 的 `expected_actors` 等在模块底部 import `state` 的函数。若运行时报循环，将 `phases.py` 里 `from app.engine.state import ...` 延迟到函数内 import。实测：因 `state` 只需要 `Phase` 类（在 `phases.py` 顶部已定义），顶层顺序为 `config → phases(Phase) → state → phases(rest)` 不成立于单文件；稳妥做法是在 `expected_actors`/`night_phase_sequence` 内部 import `state` 的 helper。实现时如遇 `ImportError`，改为函数内延迟 import。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_phases.py -v`
Expected: PASS（全部用例）。若报循环 import，按上面提示把 `state` helper 改为函数内延迟 import，再跑一次。

- [ ] **Step 5: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过。
```bash
git add backend/app/engine/phases.py backend/tests/test_phases.py
git commit -m "feat(engine): expected_actors 与夜间阶段序"
```

### Task 8: 引擎主循环 `engine.py`（create_game / step / advance）

**Files:**
- Create: `backend/app/engine/engine.py`
- Test: `backend/tests/test_engine_core.py`

**Interfaces:**
- Consumes: 之前所有模块。
- Produces：
  - `StepResult`（frozen）：`state: GameState`、`events: list[Event]`、`rejection: RejectedReason | None`。
  - `EngineInvariantError(RuntimeError)`。
  - `create_game(config: GameConfig, game_id: str) -> StepResult` —— 校验、发牌、推进到首夜第一个行动点。
  - `step(state: GameState, action: Action) -> StepResult` —— 校验 → 决定事件 → advance。非法则 `rejection` 非空、`events=[]`、`state` 不变。
  - `advance(state: GameState) -> tuple[GameState, list[Event]]` —— 纯系统推进循环。

> **本任务只覆盖 Stage 1 行动**（NightAction 的 guard/kill/save/poison/check/skip、Speak、DayVote）。`SheriffAction`/`SelfDestruct` 在 Stage 1 一律 `WRONG_PHASE`。猎人/白痴/警长/遗言分支在 Stage 2/3 追加。

- [ ] **Step 1: 写集成测试（脚本化确定性首夜 + 白天）**

Create `backend/tests/test_engine_core.py`：
```python
from app.engine.actions import DayVote, NightAction, NightActionType, Speak
from app.engine.config import Faction, RoleType
from app.engine.engine import advance, create_game, step
from app.engine.events import reduce_all
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_of_role, living_wolves, player_at
from tests.factories import stage1_config


def _start() -> GameState:
    res = create_game(stage1_config(seed=42), game_id="g1")
    assert res.rejection is None
    return res.state


def test_create_game_reaches_first_night_actor() -> None:
    state = _start()
    # 首夜第一个夜间阶段是守卫（night_order 首位）
    assert state.phase == Phase.NIGHT_GUARD
    assert state.round == 1
    guard = living_of_role(state, RoleType.GUARD)[0]
    assert expected_actors(state) == {guard.seat}
    # 发牌确定：同 seed 再来一次身份完全一致
    again = create_game(stage1_config(seed=42), game_id="g1")
    assert [p.role for p in again.state.players] == [p.role for p in state.players]


def _submit(state: GameState, action: object) -> GameState:
    res = step(state, action)  # type: ignore[arg-type]
    assert res.rejection is None, res.rejection
    return res.state


def test_full_night_resolves_and_enters_day() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    villager = next(
        p.seat for p in state.players if p.role == RoleType.VILLAGER
    )

    # 守卫守 seer
    state = _submit(state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer))
    assert state.phase == Phase.NIGHT_WEREWOLF
    # 三狼一致刀 villager
    for w in wolves:
        state = _submit(state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=villager))
    # 狼刀共识决定后进入女巫
    assert state.phase == Phase.NIGHT_WITCH
    # 女巫不救不毒
    state = _submit(state, NightAction(actor_seat=witch, action_type=NightActionType.SKIP))
    # 预言家验一只狼
    state = _submit(state, NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=wolves[0]))
    # 夜晚结算 -> 公布死讯 -> 进入白天发言
    assert state.phase == Phase.DAY_SPEECH
    assert player_at(state, villager).alive is False
    # 发言顺序为存活玩家（含被投前）
    assert villager not in state.speech_order


def test_reject_out_of_turn() -> None:
    state = _start()
    seer = living_of_role(state, RoleType.SEER)[0].seat
    # 现在是守卫阶段，预言家行动应被拒
    res = step(state, NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=0))
    assert res.rejection is not None
    assert res.state is state  # 状态不变
    assert res.events == []


def test_guard_cannot_repeat_target() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    # 设置守卫上次守护目标 = seer
    players = tuple(
        p.model_copy(update={"last_guard_target": seer}) if p.seat == guard else p
        for p in state.players
    )
    state = state.model_copy(update={"players": players})
    res = step(state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer))
    assert res.rejection is not None


def test_replay_matches_live_state() -> None:
    res = create_game(stage1_config(seed=7), game_id="g1")
    all_events = list(res.events)
    state = res.state
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    step_res = step(state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=guard))
    all_events += step_res.events
    live = step_res.state
    # 从初始空局重放全部事件 == 实时状态
    initial = create_game(stage1_config(seed=7), game_id="g1")
    # 重放需要一个「未推进」的基态；这里用 reduce_all 校验事件流内部一致性：
    replayed = reduce_all(initial.state.model_copy(update={"state_version": live.state_version - len(step_res.events)}), step_res.events)
    assert replayed.phase == live.phase
    assert [p.alive for p in replayed.players] == [p.alive for p in live.players]
```

> `test_replay_matches_live_state` 是烟雾级校验；完整的「从 seq=0 逐字节重放」在 Stage 4 的 `test_determinism.py` 用引擎产出的完整事件流做（见 Task 19）。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_engine_core.py -v`
Expected: FAIL（`app.engine.engine` 不存在）。

- [ ] **Step 3: 实现 `engine.py`**

Create `backend/app/engine/engine.py`：
```python
"""引擎主循环：create_game / step / advance。

step 固定为「校验 → 决定事件 → reduce 应用」；advance 纯系统推进到下一个行动点。
事件是唯一写路径；seq == state_version（每事件 +1），ts=float(seq) 为逻辑 tick。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.engine import rng
from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    NightActionType,
    RejectedReason,
    SelfDestruct,
    SheriffAction,
    Speak,
)
from app.engine.config import Faction, GameConfig, RoleType, faction_of, validate_config
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventPayload,
    EventType,
    GameOverPayload,
    GuardProtectedPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoleSkippedPayload,
    RolesAssignedPayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    Visibility,
    VoteCastPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WitchActedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    reduce,
)
from app.engine.phases import (
    Phase,
    expected_actors,
    next_night_phase,
    night_phase_sequence,
    phase_for_role,
)
from app.engine.resolver import check_win, count_votes, resolve_night
from app.engine.state import (
    GameState,
    Player,
    living,
    living_of_role,
    living_seats,
    living_wolves,
    player_at,
)

_MAX_SYSTEM_STEPS = 10_000


class EngineInvariantError(RuntimeError):
    """引擎进入了不可能状态；绝不静默继续。"""


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: GameState
    events: list[Event]
    rejection: RejectedReason | None = None


def _emit(
    state: GameState,
    type_: EventType,
    payload: EventPayload,
    visibility: Visibility,
    actor: int | None = None,
) -> tuple[GameState, Event]:
    seq = state.state_version + 1
    ev = Event(
        seq=seq,
        game_id=state.game_id,
        ts=float(seq),
        type=type_,
        actor_seat=actor,
        payload=payload,
        visibility=visibility,
    )
    return reduce(state, ev), ev


# ---------- 建局 ----------

def create_game(config: GameConfig, game_id: str) -> StepResult:
    validate_config(config)
    players = tuple(
        Player(
            seat=seat,
            display_name=f"P{seat}",
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

    expanded: list[RoleType] = []
    for slot in config.roles:
        expanded.extend([slot.role] * slot.count)
    seed = config.seed if config.seed is not None else 0
    dealt = rng.shuffle(seed=seed, purpose="deal", items=expanded)
    assignments = tuple((seat, dealt[seat]) for seat in range(config.num_players))

    events: list[Event] = []
    state, e = _emit(
        state,
        EventType.ROLES_ASSIGNED,
        RolesAssignedPayload(assignments=assignments, new_rng_state=state.rng_state + 1),
        Visibility.GM_ONLY,
    )
    events.append(e)
    # 进入首夜
    state, more = _begin_night(state, first=True)
    events.extend(more)
    state, adv = advance(state)
    events.extend(adv)
    return StepResult(state=state, events=events)


def _begin_night(state: GameState, first: bool) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    state, e = _emit(
        state, EventType.ROUND_STARTED, RoundStartedPayload(round=state.round + 1), Visibility.GM_ONLY
    )
    events.append(e)
    seq = night_phase_sequence(state.config)
    first_phase = seq[0] if seq else Phase.WIN_CHECK
    state, e = _emit(
        state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=first_phase), Visibility.GM_ONLY
    )
    events.append(e)
    return state, events


# ---------- 校验 ----------

def _validate(state: GameState, action: Action) -> RejectedReason | None:
    if isinstance(action, (SheriffAction, SelfDestruct)):
        return RejectedReason.WRONG_PHASE  # Stage 3 实现

    actor = action.actor_seat
    try:
        pl = player_at(state, actor)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    if not pl.alive:
        return RejectedReason.DEAD_ACTOR
    if actor not in expected_actors(state):
        return RejectedReason.NOT_YOUR_TURN

    if isinstance(action, NightAction):
        return _validate_night(state, pl, action)
    if isinstance(action, Speak):
        return None  # 发言内容对引擎不透明
    if isinstance(action, DayVote):
        return _validate_vote(state, pl, action)
    return RejectedReason.WRONG_PHASE


def _alive_target(state: GameState, seat: int | None) -> bool:
    if seat is None:
        return False
    try:
        return player_at(state, seat).alive
    except KeyError:
        return False


def _validate_night(state: GameState, pl: Player, a: NightAction) -> RejectedReason | None:
    ph = state.phase
    at = a.action_type

    if ph == Phase.NIGHT_GUARD:
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.GUARD:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        if a.target_seat == pl.seat and not state.config.guard.can_guard_self:
            return RejectedReason.GUARD_SELF_FORBIDDEN
        if (
            pl.last_guard_target is not None
            and a.target_seat == pl.last_guard_target
            and not state.config.guard.can_guard_same_target_consecutively
        ):
            return RejectedReason.GUARD_SAME_TARGET
        return None

    if ph == Phase.NIGHT_WEREWOLF:
        if at == NightActionType.SKIP:
            if not state.config.allow_wolf_empty_knife:
                return RejectedReason.WRONG_PHASE
            return None
        if at != NightActionType.KILL:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        assert a.target_seat is not None
        tgt = player_at(state, a.target_seat)
        if tgt.faction == Faction.WOLF and not state.config.allow_wolf_self_knife:
            return RejectedReason.INVALID_TARGET
        return None

    if ph == Phase.NIGHT_WITCH:
        if at == NightActionType.SKIP:
            return None
        if at == NightActionType.SAVE:
            if not pl.witch_antidote:
                return RejectedReason.WITCH_NO_ANTIDOTE
            killed = state.pending_night.wolf_target
            if killed is None:
                return RejectedReason.INVALID_TARGET  # 无刀口可救
            if killed == pl.seat:
                w = state.config.witch
                first_night = state.round == 1
                allowed = w.self_rescue_always or (first_night and w.self_rescue_first_night)
                if not allowed:
                    return RejectedReason.WITCH_SELF_RESCUE_FORBIDDEN
            return None
        if at == NightActionType.POISON:
            if not pl.witch_poison:
                return RejectedReason.WITCH_NO_POISON
            if not _alive_target(state, a.target_seat):
                return RejectedReason.DEAD_TARGET
            return None
        return RejectedReason.WRONG_PHASE

    if ph == Phase.NIGHT_SEER:
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.CHECK:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None

    return RejectedReason.WRONG_PHASE


def _validate_vote(state: GameState, pl: Player, v: DayVote) -> RejectedReason | None:
    if not pl.can_vote:
        return RejectedReason.CANNOT_VOTE
    if v.abstain or v.target_seat is None:
        return None
    if not _alive_target(state, v.target_seat):
        return RejectedReason.DEAD_TARGET
    if state.vote_candidates and v.target_seat not in state.vote_candidates:
        return RejectedReason.INVALID_TARGET
    return None


# ---------- 应用行动 ----------

def _apply_action(state: GameState, action: Action) -> tuple[GameState, list[Event]]:
    if isinstance(action, NightAction):
        return _apply_night(state, action)
    if isinstance(action, Speak):
        s, e = _emit(
            state,
            EventType.PLAYER_SPOKE,
            PlayerSpokePayload(content=action.content, claim_role=action.claim_role, badge_flow=action.badge_flow),
            Visibility.PUBLIC,
            actor=action.actor_seat,
        )
        return s, [e]
    if isinstance(action, DayVote):
        target = None if action.abstain else action.target_seat
        s, e = _emit(
            state,
            EventType.VOTE_CAST,
            VoteCastPayload(voter=action.actor_seat, target=target),
            Visibility.PUBLIC,
            actor=action.actor_seat,
        )
        return s, [e]
    raise EngineInvariantError(f"不应到达：{type(action)}")


def _apply_night(state: GameState, a: NightAction) -> tuple[GameState, list[Event]]:
    ph = state.phase
    at = a.action_type
    actor = a.actor_seat

    if ph == Phase.NIGHT_GUARD:
        target = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(state, EventType.GUARD_PROTECTED, GuardProtectedPayload(target=target), Visibility.ROLE_SELF, actor=actor)
        return s, [e]

    if ph == Phase.NIGHT_WEREWOLF:
        target = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(state, EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=actor, target=target), Visibility.WOLVES, actor=actor)
        return s, [e]

    if ph == Phase.NIGHT_WITCH:
        if at == NightActionType.SAVE:
            s, e = _emit(state, EventType.WITCH_SAVED, WitchActedPayload(save=True), Visibility.ROLE_SELF, actor=actor)
            return s, [e]
        if at == NightActionType.POISON:
            s, e = _emit(state, EventType.WITCH_POISONED, WitchActedPayload(poison_target=a.target_seat), Visibility.ROLE_SELF, actor=actor)
            # 用毒后本人 witch_poison 置 False：通过修改 player 完成（事件驱动）
            s = _consume_witch_potion(s, actor, poison=True)
            return s, [e]
        s, e = _emit(state, EventType.ROLE_SKIPPED, RoleSkippedPayload(role=RoleType.WITCH, reason="skip"), Visibility.ROLE_SELF, actor=actor)
        return s, [e]

    if ph == Phase.NIGHT_SEER:
        if at == NightActionType.SKIP:
            s, e = _emit(state, EventType.ROLE_SKIPPED, RoleSkippedPayload(role=RoleType.SEER, reason="skip"), Visibility.ROLE_SELF, actor=actor)
            return s, [e]
        assert a.target_seat is not None
        result = faction_of(player_at(state, a.target_seat).role)
        s, e = _emit(state, EventType.SEER_CHECKED, SeerCheckedPayload(target=a.target_seat, result=result), Visibility.ROLE_SELF, actor=actor)
        return s, [e]

    raise EngineInvariantError(f"夜间行动落在非夜间阶段 {ph}")
```

> **药水消耗**：`_consume_witch_potion` 与「解药救人扣药」需通过修改 `Player.witch_antidote/witch_poison` 落地。为保持「事件是唯一写路径」，用一个内部事件 `WITCH_POTION_CONSUMED` 承载。下一步补该事件与 helper。

- [ ] **Step 4: 补 `WITCH_POTION_CONSUMED` 事件（events.py）与 helper（engine.py）**

在 `backend/app/engine/events.py` 追加（枚举里加一项、payload、reduce 分支）：
```python
# EventType 里追加：
    WITCH_POTION_CONSUMED = "WITCH_POTION_CONSUMED"

# 新 payload：
class WitchPotionConsumedPayload(EventPayload):
    seat: int
    antidote: bool = False
    poison: bool = False

# reduce 分支（放在 WITCH_POISONED 分支附近）：
    if t == EventType.WITCH_POTION_CONSUMED and isinstance(p, WitchPotionConsumedPayload):
        updates: dict[str, object] = {}
        if p.antidote:
            updates["witch_antidote"] = False
        if p.poison:
            updates["witch_poison"] = False
        return {"players": _replace_player(state.players, p.seat, **updates)}
```

在 `backend/app/engine/engine.py` 追加 helper（并在 import 里加 `WitchPotionConsumedPayload`）：
```python
def _consume_witch_potion(state: GameState, seat: int, *, antidote: bool = False, poison: bool = False) -> GameState:
    s, _ = _emit(
        state,
        EventType.WITCH_POTION_CONSUMED,
        WitchPotionConsumedPayload(seat=seat, antidote=antidote, poison=poison),
        Visibility.GM_ONLY,
        actor=seat,
    )
    return s
```

> 注意：`WITCH_POTION_CONSUMED` 的 `actor_seat` 会经 `ROLE_SKIPPED`/`acted_seats` 逻辑之外，不影响 acted（它不是 ROLE_SKIPPED/夜间行动事件）。解药救人时（下一步 `_system_transition` 结算里）也调用它扣解药。

- [ ] **Step 5: 实现 `advance` 与 `_system_transition`（engine.py 追加）**

在 `backend/app/engine/engine.py` 追加：
```python
def step(state: GameState, action: Action) -> StepResult:
    rej = _validate(state, action)
    if rej is not None:
        return StepResult(state=state, events=[], rejection=rej)
    state, events = _apply_action(state, action)
    state, more = advance(state)
    return StepResult(state=state, events=[*events, *more])


def advance(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    guard = 0
    while state.phase != Phase.GAME_OVER and not expected_actors(state):
        state, evs = _system_transition(state)
        if not evs:
            break
        events.extend(evs)
        guard += 1
        if guard > _MAX_SYSTEM_STEPS:
            raise EngineInvariantError("系统推进未收敛（可能存在阶段死循环）")
    return state, events


def _wolf_consensus(state: GameState) -> int | None:
    vals = set(state.wolf_proposals.values())
    if len(vals) == 1 and None not in vals:
        return next(iter(vals))
    return None


def _night_role_present(state: GameState, phase: Phase) -> bool:
    role_by_phase = {
        Phase.NIGHT_GUARD: RoleType.GUARD,
        Phase.NIGHT_WITCH: RoleType.WITCH,
        Phase.NIGHT_SEER: RoleType.SEER,
        Phase.NIGHT_HUNTER_CONFIRM: RoleType.HUNTER,
    }
    role = role_by_phase.get(phase)
    if role is None:
        return True
    members = living_of_role(state, role)
    if not members:
        return False
    if phase == Phase.NIGHT_WITCH:
        return any(m.witch_antidote or m.witch_poison for m in members)
    return True


def _system_transition(state: GameState) -> tuple[GameState, list[Event]]:
    ph = state.phase
    events: list[Event] = []

    # --- 夜间子阶段收尾 ---
    if ph in night_phase_sequence(state.config):
        if ph == Phase.NIGHT_WEREWOLF:
            state, e = _emit(state, EventType.WOLF_KILL_DECIDED, WolfKillDecidedPayload(target=_wolf_consensus(state)), Visibility.GM_ONLY)
            events.append(e)
        elif not _night_role_present(state, ph) and not any(
            s in state.acted_seats for s in living_seats(state)
        ):
            # 该角色缺席/死亡/无药：记跳过（审计）
            events.append(_skip_event(state, ph))
            state = events[-1] and state  # noqa: 占位，见下修正
        nxt = next_night_phase(state.config, ph)
        if nxt is not None:
            state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=nxt), Visibility.GM_ONLY)
            events.append(e)
            return state, events
        # 夜序结束 -> 结算
        state, ev = _resolve_night_and_continue(state)
        return state, [*events, *ev]

    if ph == Phase.DAY_SPEECH:
        # 发言轮结束 -> 投票
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.VOTE_STARTED, VoteStartedPayload(candidates=(), tie_round=0), Visibility.PUBLIC)
        events.append(e)
        return state, events

    if ph == Phase.VOTE:
        return _tally_and_continue(state)

    if ph == Phase.VOTE_PK:
        return _tally_and_continue(state)

    if ph == Phase.EXILE:
        return _after_exile(state)

    return state, events
```

> **修正上面的占位**：`_system_transition` 里 `state = events[-1] and state  # 占位` 一行是错误占位，实现时删除它，改为下面干净版本的跳过分支。用这段替换整个「夜间子阶段收尾」块中 `elif` 分支：
> ```python
>         elif not _night_role_present(state, ph):
>             state, e = _emit(
>                 state,
>                 EventType.ROLE_SKIPPED,
>                 RoleSkippedPayload(role=_role_of_night_phase(ph), reason="absent_or_dead"),
>                 Visibility.GM_ONLY,
>             )
>             events.append(e)
> ```
> 并新增 helper：
> ```python
> def _role_of_night_phase(phase: Phase) -> RoleType:
>     for role, ph in {
>         RoleType.GUARD: Phase.NIGHT_GUARD,
>         RoleType.WITCH: Phase.NIGHT_WITCH,
>         RoleType.SEER: Phase.NIGHT_SEER,
>         RoleType.HUNTER: Phase.NIGHT_HUNTER_CONFIRM,
>     }.items():
>         if ph == phase:
>             return role
>     return RoleType.WEREWOLF
> ```

- [ ] **Step 6: 实现结算与白天收尾（engine.py 追加）**

在 `backend/app/engine/engine.py` 追加：
```python
def _resolve_night_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    na = state.pending_night

    # 解药救人：扣女巫解药（若本夜确实救了刀口）
    if na.witch_save and na.wolf_target is not None:
        witches = living_of_role(state, RoleType.WITCH)
        if witches:
            state = _consume_witch_potion(state, witches[0].seat, antidote=True)

    deaths = resolve_night(state.config, na)
    ordered = tuple(sorted(deaths))
    state, e = _emit(state, EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=ordered), Visibility.GM_ONLY)
    events.append(e)

    # 狼刀在先：以「死者已出局」的假想态判胜
    winner = _check_win_with_deaths(state, deaths)
    if winner is not None and state.config.wolf_first_kill_priority:
        state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
        events.append(e)
        return state, events

    # 公布死讯（应用出局）。Stage 2 在此后插入遗言；Stage 3 首日在此前插入警长竞选。
    state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
    events.append(e)

    winner2 = check_win(state)
    if winner2 is not None:
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner2), Visibility.PUBLIC)
        events.append(e)
        return state, events

    state, ev = _enter_day_speech(state)
    return state, [*events, *ev]


def _check_win_with_deaths(state: GameState, deaths: frozenset[int]) -> str | None:
    if not deaths:
        return check_win(state)
    players = state.players
    for seat in deaths:
        players = tuple(pl.model_copy(update={"alive": False}) if pl.seat == seat else pl for pl in players)
    hypo = state.model_copy(update={"players": players})
    return check_win(hypo)


def _speech_order(state: GameState) -> tuple[int, ...]:
    # Stage 1：按座号升序的存活玩家。Stage 3 依 speech_order_rule 改写。
    return tuple(living_seats(state))


def _enter_day_speech(state: GameState) -> tuple[GameState, list[Event]]:
    order = _speech_order(state)
    s, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH, speech_order=order), Visibility.PUBLIC)
    return s, [e]


def _tally_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    weights = {p.seat: (1.5 if p.is_sheriff else 1.0) for p in living(state)}
    exiled, tie = count_votes(state.votes, weights)
    tally = tuple(sorted(((seat, weights_sum(state.votes, weights, seat)) for seat in _voted_targets(state.votes)), key=lambda x: x[0]))
    state, e = _emit(state, EventType.VOTE_RESULT, VoteResultPayload(tally=tally, exiled=exiled, tie_seats=tie), Visibility.PUBLIC)
    events.append(e)

    if exiled is not None:
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=exiled), Visibility.PUBLIC)
        events.append(e)
        # EXILE 阶段的后续（猎人/白痴/遗言/胜负）交给 advance 再次进入 EXILE 分支处理
        return state, events

    # 平票
    if state.tie_round == 0 and state.config.tie_rule.name.startswith("PK"):
        # 进入 PK：平票者发言 + 其余人重投（Stage 1 简化为直接重投，PK 发言在 Stage 3 补）
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.VOTE_STARTED, VoteStartedPayload(candidates=tie, tie_round=1), Visibility.PUBLIC)
        events.append(e)
        return state, events

    # 再平票或 NO_EXILE：无人出局
    if state.config.tie_rule.name == "PK_THEN_RANDOM" and tie:
        seed = state.config.seed if state.config.seed is not None else 0
        idx = rng.derive_int(seed=seed, purpose="tie", seq=state.rng_state, modulo=len(tie))
        chosen = sorted(tie)[idx]
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=chosen), Visibility.PUBLIC)
        events.append(e)
        return state, events

    state, e = _emit(state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=None), Visibility.PUBLIC)
    events.append(e)
    state, ev = _after_day_death(state)
    return state, [*events, *ev]


def _voted_targets(votes: dict[int, int | None]) -> set[int]:
    return {t for t in votes.values() if t is not None}


def weights_sum(votes: dict[int, int | None], weights: dict[int, float], target: int) -> float:
    return sum(weights.get(voter, 1.0) for voter, t in votes.items() if t == target)


def _after_exile(state: GameState) -> tuple[GameState, list[Event]]:
    # Stage 1：出局即结束当天（无猎人/白痴/遗言）。Stage 2/3 在此插入分支。
    return _after_day_death(state)


def _after_day_death(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    winner = check_win(state)
    if winner is not None:
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
        return state, [e]
    if state.round >= state.config.max_rounds:
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=None), Visibility.PUBLIC)
        return state, [e]
    state, ev = _begin_night(state, first=False)
    return state, ev
```

> **`_tally_and_continue` 里的 `tally` 计算**：`weights_sum`/`_voted_targets` 是把票型汇总成 `(target, weighted)` 列表用于 `VOTE_RESULT` 公示。实现时确保 `tally` 只含被投过的座位、按座号排序，保证确定性。
>
> **EXILE 二次进入**：`_tally_and_continue` 出局时把 phase 设为 `EXILE` 并出局，然后返回；`advance` 循环再看到 `phase==EXILE` 且无 expected → 调 `_after_exile`。这样猎人/白痴分支（Stage 2）只需改 `_after_exile`。

- [ ] **Step 7: 运行确认通过**

Run: `uv run pytest tests/test_engine_core.py -v`
Expected: PASS（5 项）。若 `_system_transition` 的占位行未删干净会立即报错——按 Step 5 的「修正」替换。

- [ ] **Step 8: 全量回归 + 类型检查**

Run:
```bash
uv run pytest -q
uv run mypy app
uv run ruff check .
```
Expected: 全绿。

- [ ] **Step 9: 提交**

```bash
git add backend/app/engine/engine.py backend/app/engine/events.py backend/tests/test_engine_core.py
git commit -m "feat(engine): 主循环 create_game/step/advance 与夜昼结算"
```

### Task 9: 信息隔离 `observation.py`

**Files:**
- Create: `backend/app/engine/observation.py`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: `state.GameState`、`state.Player`、`events.Event`、`events.Visibility`、`config.RoleType`/`Faction`。
- Produces：
  - `PlayerObservation`（frozen）：见规格 §4.2 字段（M1 子集）。
  - `build_observation(state: GameState, seat: int) -> PlayerObservation`。
  - `visible_events(events: list[Event], viewer: int | Literal["SPECTATOR", "GM"]) -> list[Event]`。

> Stage 1 已可测隔离核心：狼队友/私聊、预言家验人、女巫药态与刀口、守卫上次守护、死者不再收私有信息、可见性过滤。猎人 `can_shoot`、白痴字段在 Stage 2 补，但本任务先把 `private` 结构建好。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_isolation.py`：
```python
from app.engine.actions import NightAction, NightActionType
from app.engine.config import Faction, RoleType
from app.engine.engine import create_game, step
from app.engine.events import Event, Visibility
from app.engine.observation import build_observation, visible_events
from app.engine.state import GameState, living_of_role, living_wolves
from tests.factories import stage1_config


def _start() -> GameState:
    return create_game(stage1_config(seed=3), game_id="g").state


def test_non_wolf_has_no_teammates_or_chat() -> None:
    state = _start()
    for p in state.players:
        obs = build_observation(state, p.seat)
        if p.faction != Faction.WOLF:
            assert obs.private.get("teammates") in (None, [])
            assert obs.private.get("wolf_chat") in (None, [])


def test_wolf_sees_teammates() -> None:
    state = _start()
    wolf = living_wolves(state)[0]
    obs = build_observation(state, wolf.seat)
    teammates = obs.private["teammates"]
    assert set(teammates) == {w.seat for w in living_wolves(state)} - {wolf.seat}


def test_seer_private_has_check_results_after_check() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    state = step(state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer)).state
    for w in wolves:
        state = step(state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=seer)).state
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    state = step(state, NightAction(actor_seat=witch, action_type=NightActionType.SKIP)).state
    state = step(state, NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=wolves[0])).state
    obs = build_observation(state, seer)
    results = obs.private["check_results"]
    assert any(r["seat"] == wolves[0] and r["result"] == Faction.WOLF.value for r in results)


def test_witch_sees_kill_only_with_antidote() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    victim = next(p.seat for p in state.players if p.role == RoleType.VILLAGER)
    state = step(state, NightAction(actor_seat=guard, action_type=NightActionType.SKIP)).state
    for w in wolves:
        state = step(state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=victim)).state
    # 现在轮到女巫，且解药未用 -> 应看到刀口
    obs = build_observation(state, witch)
    assert obs.private["tonight_killed_seat"] == victim
    assert obs.private["antidote_available"] is True


def test_dead_player_gets_no_private_night_info() -> None:
    state = _start()
    # 手动把预言家标记死亡
    seer = living_of_role(state, RoleType.SEER)[0].seat
    players = tuple(p.model_copy(update={"alive": False}) if p.seat == seer else p for p in state.players)
    state = state.model_copy(update={"players": players})
    obs = build_observation(state, seer)
    assert obs.my_status == "DEAD"
    assert obs.private.get("check_results") in (None, [])


def _mk_event(vis: Visibility, actor: int | None = None) -> Event:
    from app.engine.events import EventType, PlayerSpokePayload

    return Event(
        seq=1, game_id="g", ts=1.0, type=EventType.PLAYER_SPOKE,
        actor_seat=actor, payload=PlayerSpokePayload(content="x"), visibility=vis,
    )


def test_visible_events_filtering() -> None:
    state = _start()
    wolf = living_wolves(state)[0].seat
    non_wolf = next(p.seat for p in state.players if p.faction == Faction.GOOD)
    evs = [
        _mk_event(Visibility.PUBLIC),
        _mk_event(Visibility.WOLVES),
        _mk_event(Visibility.ROLE_SELF, actor=wolf),
        _mk_event(Visibility.GM_ONLY),
    ]
    # 引擎 visible_events 需要 state 判定「谁是狼」；用带 state 的闭包封装（见实现说明）
    from app.engine.observation import make_visibility_filter

    vis_for = make_visibility_filter(state)
    gm = vis_for(evs, "GM")
    assert len(gm) == 4
    spec = vis_for(evs, "SPECTATOR")
    assert [e.visibility for e in spec] == [Visibility.PUBLIC]
    wolf_view = vis_for(evs, wolf)
    assert Visibility.WOLVES in {e.visibility for e in wolf_view}
    assert Visibility.GM_ONLY not in {e.visibility for e in wolf_view}
    non_wolf_view = vis_for(evs, non_wolf)
    assert Visibility.WOLVES not in {e.visibility for e in non_wolf_view}
```

> **可见性需要 state**：判断「viewer 是不是狼」「ROLE_SELF 是否本人」需要局面。因此 `visible_events` 签名带 state：`visible_events(state, events, viewer)`。上面测试用 `make_visibility_filter(state)` 返回一个 `(events, viewer) -> list[Event]` 闭包，等价封装。两者都实现即可（`visible_events` 为主，闭包只是便捷包装）。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_isolation.py -v`
Expected: FAIL（`app.engine.observation` 不存在）。

- [ ] **Step 3: 实现 `observation.py`**

Create `backend/app/engine/observation.py`：
```python
"""信息隔离：per-seat observation 与事件可见性过滤。此为唯一过滤点（安全边界）。"""

from __future__ import annotations

from typing import Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict

from app.engine.config import Faction, RoleType
from app.engine.events import Event, Visibility
from app.engine.phases import expected_actors
from app.engine.state import GameState, living_wolves, player_at

Viewer = Union[int, Literal["SPECTATOR", "GM"]]


class PlayerObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    state_version: int
    my_seat: int
    my_role: RoleType
    my_status: Literal["ALIVE", "DEAD"]
    phase: str
    round: int
    seats: list[dict[str, Any]]
    sheriff_seat: int | None
    private: dict[str, Any]
    available_actions: list[int]  # M1：当前是否轮到本人（空=否）；M2 换成工具名


def _public_seats(state: GameState) -> list[dict[str, Any]]:
    return [
        {
            "seat": p.seat,
            "alive": p.alive,
            "is_sheriff": p.is_sheriff,
            "idiot_revealed": p.idiot_revealed,
        }
        for p in state.players
    ]


def build_observation(state: GameState, seat: int) -> PlayerObservation:
    me = player_at(state, seat)
    private: dict[str, Any] = {}

    if me.alive:
        if me.faction == Faction.WOLF:
            private["teammates"] = sorted(w.seat for w in living_wolves(state) if w.seat != seat)
            private["wolf_chat"] = []  # M1 无私聊内容；结构预留
            if state.pending_night.wolf_target is not None:
                private["tonight_kill_proposal"] = state.pending_night.wolf_target

        if me.role == RoleType.SEER:
            # 从 pending/历史推导；M1 直接由本夜 pending 与既往 last_guard 类比无处存 —— 见说明
            private["check_results"] = _seer_results(state, seat)

        if me.role == RoleType.WITCH:
            private["antidote_available"] = me.witch_antidote
            private["poison_available"] = me.witch_poison
            killed = state.pending_night.wolf_target
            knows = me.witch_antidote or state.config.witch.knows_kill_after_antidote_used
            if killed is not None and knows:
                private["tonight_killed_seat"] = killed

        if me.role == RoleType.GUARD:
            private["last_guard_target"] = me.last_guard_target

        if me.role == RoleType.HUNTER:
            private["can_shoot"] = me.hunter_can_shoot

    return PlayerObservation(
        game_id=state.game_id,
        state_version=state.state_version,
        my_seat=seat,
        my_role=me.role,
        my_status="ALIVE" if me.alive else "DEAD",
        phase=state.phase.value,
        round=state.round,
        seats=_public_seats(state),
        sheriff_seat=state.sheriff_seat,
        private=private,
        available_actions=[seat] if seat in expected_actors(state) else [],
    )


def _seer_results(state: GameState, seat: int) -> list[dict[str, Any]]:
    """预言家验人历史。M1 从 pending_night.seer_check（当夜）派生。

    说明：跨夜验人历史需要一处存储。M1 用 GameState.seer_log 累积（下一步补该字段与 reduce）。
    """
    return list(state.seer_log.get(seat, []))


def visible_events(state: GameState, events: list[Event], viewer: Viewer) -> list[Event]:
    if viewer == "GM":
        return list(events)
    if viewer == "SPECTATOR":
        return [e for e in events if e.visibility == Visibility.PUBLIC]

    wolf_seats = {p.seat for p in state.players if p.faction == Faction.WOLF}
    out: list[Event] = []
    for e in events:
        if e.visibility == Visibility.PUBLIC:
            out.append(e)
        elif e.visibility == Visibility.WOLVES and viewer in wolf_seats:
            out.append(e)
        elif e.visibility == Visibility.ROLE_SELF and e.actor_seat == viewer:
            out.append(e)
        # GM_ONLY 永不对 seat 可见
    return out


def make_visibility_filter(state: GameState) -> Callable[[list[Event], Viewer], list[Event]]:
    def _f(events: list[Event], viewer: Viewer) -> list[Event]:
        return visible_events(state, events, viewer)

    return _f
```

- [ ] **Step 4: 补 `seer_log` 字段（state.py + events.py）**

在 `backend/app/engine/state.py` 的 `GameState` 追加字段（放在 sheriff 相关字段附近）：
```python
    seer_log: dict[int, list[dict[str, int | str]]] = Field(default_factory=dict)
    # seat -> [{"round": r, "seat": s, "result": "GOOD"/"WOLF"}]
```

在 `backend/app/engine/events.py` 的 `SEER_CHECKED` reduce 分支改为同时写 `seer_log`：
```python
    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        log = {k: list(v) for k, v in state.seer_log.items()}
        entry = {"round": state.round, "seat": p.target, "result": p.result.value}
        log.setdefault(_actor(event), []).append(entry)
        return {
            "pending_night": state.pending_night.model_copy(update={"seer_check": p.target}),
            "acted_seats": state.acted_seats | {_actor(event)},
            "seer_log": log,
        }
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_isolation.py -v`
Expected: PASS（7 项）。

- [ ] **Step 6: 类型检查与提交**

Run: `uv run mypy app && uv run ruff check .`
Expected: 通过（`Union`/`Callable` 如被 ruff 提示，可换 `X | Y` 与 `collections.abc.Callable`）。
```bash
git add backend/app/engine/observation.py backend/app/engine/state.py backend/app/engine/events.py backend/tests/test_isolation.py
git commit -m "feat(engine): 信息隔离 observation 与可见性过滤"
```

### Task 10: RandomBot 与 CLI 模拟

**Files:**
- Create: `backend/app/cli/bot.py`
- Create: `backend/app/cli/simulate.py`
- Test: `backend/tests/test_sim_game.py`

**Interfaces:**
- Consumes: 引擎全部 + `observation`。
- Produces：
  - `RandomBot.choose_action(state: GameState, seat: int) -> Action` —— 在合法行动集合内按 `(seed, seat, state_version)` 派生均匀随机选择，全程确定。
  - `run_game(config: GameConfig, game_id: str) -> tuple[GameState, list[Event]]` —— 用 RandomBot 跑完一局，返回终态与完整事件流。
  - `python -m app.cli.simulate --preset <name> --seed <n> [--games N] [--verbose]` 入口。

- [ ] **Step 1: 写失败测试（完整对局必终局 + 回放一致）**

Create `backend/tests/test_sim_game.py`：
```python
import pytest

from app.cli.bot import run_game
from app.engine.events import EventType, reduce_all
from app.engine.engine import create_game
from app.engine.phases import Phase
from tests.factories import stage1_config


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42, 99, 123, 2024])
def test_random_game_terminates_with_result(seed: int) -> None:
    final, events = run_game(stage1_config(seed=seed), game_id=f"g{seed}")
    assert final.phase == Phase.GAME_OVER
    # 有胜负或达 max_rounds 判平局
    game_over = [e for e in events if e.type == EventType.GAME_OVER]
    assert len(game_over) == 1


def test_replay_equals_live() -> None:
    final, events = run_game(stage1_config(seed=5), game_id="g5")
    # 从「发牌前」的空局基态重放全部事件，应得到与实时终态一致的关键投影
    base = create_game(stage1_config(seed=5), game_id="g5")
    # base.events 已含首夜推进；用完整 run_game 的 events 与 live 对比其派生态：
    replayed = reduce_all(_blank_state(final), events)
    assert replayed.phase == final.phase
    assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
    assert replayed.winner == final.winner


def _blank_state(final):  # type: ignore[no-untyped-def]
    from app.engine.config import Faction, RoleType
    from app.engine.state import GameState, Player

    players = tuple(
        Player(seat=p.seat, display_name=p.display_name, role=RoleType.VILLAGER, faction=Faction.GOOD)
        for p in final.players
    )
    return GameState(
        game_id=final.game_id, config=final.config, phase=Phase.LOBBY, round=0, players=players
    )


def test_determinism_same_seed_identical_events() -> None:
    _, ev1 = run_game(stage1_config(seed=77), game_id="g")
    _, ev2 = run_game(stage1_config(seed=77), game_id="g")
    assert [e.model_dump() for e in ev1] == [e.model_dump() for e in ev2]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_sim_game.py -v`
Expected: FAIL（`app.cli.bot` 不存在）。

- [ ] **Step 3: 实现 `bot.py`**

Create `backend/app/cli/bot.py`：
```python
"""脚本 bot 与单局驱动。零 LLM、零 IO（除 simulate.py 打印）。"""

from __future__ import annotations

from app.engine import rng
from app.engine.actions import Action, DayVote, NightAction, NightActionType, Speak
from app.engine.config import GameConfig
from app.engine.engine import create_game, step
from app.engine.events import Event
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_seats, player_at


def _legal_night_targets(state: GameState, seat: int) -> list[int]:
    return [s for s in living_seats(state) if s != seat] or living_seats(state)


class RandomBot:
    """在合法行动集合内均匀随机选择，随机源由 (seed, seat, state_version) 派生。"""

    @staticmethod
    def choose_action(state: GameState, seat: int) -> Action:
        seed = state.config.seed if state.config.seed is not None else 0
        pick = lambda items, salt: items[  # noqa: E731
            rng.derive_int(seed=seed, purpose=f"bot:{seat}:{salt}", seq=state.state_version, modulo=len(items))
        ]
        ph = state.phase
        pl = player_at(state, seat)

        if ph == Phase.NIGHT_GUARD:
            targets = [s for s in living_seats(state) if s != pl.last_guard_target]
            return NightAction(actor_seat=seat, action_type=NightActionType.GUARD, target_seat=pick(targets, "g"))
        if ph == Phase.NIGHT_WEREWOLF:
            targets = _legal_night_targets(state, seat)
            return NightAction(actor_seat=seat, action_type=NightActionType.KILL, target_seat=pick(targets, "k"))
        if ph == Phase.NIGHT_WITCH:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        if ph == Phase.NIGHT_SEER:
            targets = _legal_night_targets(state, seat)
            return NightAction(actor_seat=seat, action_type=NightActionType.CHECK, target_seat=pick(targets, "c"))
        if ph == Phase.DAY_SPEECH:
            return Speak(actor_seat=seat, content="(bot)")
        if ph in (Phase.VOTE, Phase.VOTE_PK):
            cands = list(state.vote_candidates) or [s for s in living_seats(state) if s != seat]
            cands = cands or living_seats(state)
            return DayVote(actor_seat=seat, target_seat=pick(cands, "v"))
        # 其它阶段（猎人/警长，Stage 2/3）默认 skip 发言
        return Speak(actor_seat=seat, content="(bot-skip)")


def run_game(config: GameConfig, game_id: str) -> tuple[GameState, list[Event]]:
    res = create_game(config, game_id)
    state, events = res.state, list(res.events)
    guard = 0
    while state.phase != Phase.GAME_OVER:
        actors = sorted(expected_actors(state))
        if not actors:
            raise RuntimeError(f"无人可行动但未终局：phase={state.phase}")
        for seat in actors:
            if state.phase == Phase.GAME_OVER:
                break
            if seat not in expected_actors(state):
                continue
            action = RandomBot.choose_action(state, seat)
            res = step(state, action)
            if res.rejection is not None:
                raise RuntimeError(f"bot 行动被拒：{res.rejection} @ {state.phase}")
            state, new_events = res.state, res.events
            events.extend(new_events)
        guard += 1
        if guard > 100_000:
            raise RuntimeError("对局未收敛")
    return state, events
```

- [ ] **Step 4: 实现 `simulate.py`**

Create `backend/app/cli/simulate.py`：
```python
"""CLI：uv run python -m app.cli.simulate --preset <name> --seed <n> [--games N] [--verbose]"""

from __future__ import annotations

import argparse

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import EventType, reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState, Player
from app.engine.config import Faction, RoleType


def _blank(final: GameState) -> GameState:
    players = tuple(
        Player(seat=p.seat, display_name=p.display_name, role=RoleType.VILLAGER, faction=Faction.GOOD)
        for p in final.players
    )
    return GameState(
        game_id=final.game_id, config=final.config, phase=Phase.LOBBY, round=0, players=players
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentHowl 随机 bot 对局模拟")
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    wins: dict[str, int] = {}
    for i in range(args.games):
        seed = args.seed + i
        config = build_preset(args.preset).model_copy(update={"seed": seed})
        final, events = run_game(config, game_id=f"g{seed}")
        assert final.phase == Phase.GAME_OVER, f"seed {seed} 未终局"
        replayed = reduce_all(_blank(final), events)
        assert replayed.winner == final.winner, f"seed {seed} 回放与实时不一致"
        result = final.winner or "DRAW"
        wins[result] = wins.get(result, 0) + 1
        if args.verbose:
            deaths = [e for e in events if e.type == EventType.GAME_OVER]
            print(f"seed={seed} winner={result} events={len(events)} rounds={final.round}")

    print(f"跑完 {args.games} 局：{wins}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/test_sim_game.py -v`
Expected: PASS（8 个 seed + 回放 + 确定性）。

- [ ] **Step 6: 手动跑 CLI 冒烟**

Run: `uv run python -m app.cli.simulate --preset std_9_kill_side --seed 42 --games 20 --verbose`
Expected: 打印每局 winner，末行汇总；无断言失败。

- [ ] **Step 7: 全量回归 + 类型 + lint，然后提交**

Run:
```bash
uv run pytest -q
uv run mypy app
uv run ruff check .
```
Expected: 全绿。
```bash
git add backend/app/cli backend/tests/test_sim_game.py
git commit -m "feat(cli): RandomBot 与 simulate 完整对局"
```

> **Stage 1 完成判据**：`uv run pytest -q` 全绿；`simulate` 能用随机 bot 跑完 9 人测试板多局，每局终局且回放一致。此时核心循环（config/state/events/reduce + 守狼女预夜晚 + 白天发言/投票/放逐/平票 + 胜负）已闭环。

---

## Stage 2 — 角色补全

交付：猎人（首夜确认 / 出局开枪 / 被毒不可开枪）、白痴（翻牌免死一次 / 失投票权 / 当天投票作废）、遗言规则（首夜有、之后无、白天始终有）。四个官方 preset 全绿。

**新增中断机制**：出局/夜死会打断主流程去处理猎人开枪与遗言。用一个 `resume_token` 字段记录「中断处理完回到哪」。

### Task 11: 遗言、猎人、白痴的事件与状态字段

**Files:**
- Modify: `backend/app/engine/events.py`（加事件类型、payload、reduce 分支）
- Modify: `backend/app/engine/state.py`（加字段）
- Test: `backend/tests/test_last_words.py`（先只测 reduce 层，行为在 Task 12/13）

**Interfaces:**
- Produces（events.py）：`EventType.LAST_WORDS/HUNTER_SHOT/IDIOT_REVEALED` 及 payload：
  - `LastWordsPayload(seat: int, content: str)`
  - `HunterShotPayload(shooter: int, victim: int | None)`
  - `IdiotRevealedPayload(seat: int)`
- Produces（state.py）新增字段：`resume_token: str | None = None`。

- [ ] **Step 1: 加 state 字段**

在 `backend/app/engine/state.py` 的 `GameState` 追加：
```python
    resume_token: str | None = None  # 中断（猎人开枪/遗言）处理完后的续接标记
```

- [ ] **Step 2: 加事件类型与 payload（events.py）**

`EventType` 里这几项已在 Task 4 预留（`LAST_WORDS`、`HUNTER_SHOT`、`IDIOT_REVEALED`），无需再加。追加 payload 模型：
```python
class LastWordsPayload(EventPayload):
    seat: int
    content: str


class HunterShotPayload(EventPayload):
    shooter: int
    victim: int | None  # None=不开枪


class IdiotRevealedPayload(EventPayload):
    seat: int
```

- [ ] **Step 3: 加 reduce 分支（events.py）**

在 `_reduce_dispatch` 追加（放在 PLAYER_EXILED 之后）：
```python
    if t == EventType.LAST_WORDS and isinstance(p, LastWordsPayload):
        return {"speech_idx": state.speech_idx + 1}

    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        updates: dict[str, object] = {"pending_hunter": None}
        if p.victim is not None:
            updates["players"] = _replace_player(state.players, p.victim, alive=False)
        return updates

    if t == EventType.IDIOT_REVEALED and isinstance(p, IdiotRevealedPayload):
        # 翻牌免死：不出局、失投票权、标记已翻
        players = _replace_player(state.players, p.seat, idiot_revealed=True, can_vote=False)
        return {"players": players}
```

- [ ] **Step 4: 写 reduce 单元测试**

Create `backend/tests/test_last_words.py`（本任务先测 reduce；行为测试在 Task 12/13 追加到本文件）：
```python
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    HunterShotPayload,
    IdiotRevealedPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player, player_at


def _state() -> GameState:
    players = tuple(
        Player(seat=s, display_name=f"P{s}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for s in range(4)
    )
    return GameState(
        game_id="g", config=build_preset("std_9_kill_side"), phase=Phase.HUNTER_SHOOT,
        round=1, players=players, pending_hunter=0,
    )


def _evt(type_: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(seq=1, game_id="g", ts=1.0, type=type_, actor_seat=actor, payload=payload, visibility=Visibility.PUBLIC)  # type: ignore[arg-type]


def test_hunter_shot_kills_victim_and_clears_pending() -> None:
    new = reduce(_state(), _evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=0, victim=2), actor=0))
    assert player_at(new, 2).alive is False
    assert new.pending_hunter is None


def test_hunter_shot_no_victim() -> None:
    new = reduce(_state(), _evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=0, victim=None), actor=0))
    assert new.pending_hunter is None
    assert all(p.alive for p in new.players)


def test_idiot_revealed_survives_loses_vote() -> None:
    new = reduce(_state(), _evt(EventType.IDIOT_REVEALED, IdiotRevealedPayload(seat=1), actor=1))
    p = player_at(new, 1)
    assert p.alive is True
    assert p.idiot_revealed is True
    assert p.can_vote is False
```

- [ ] **Step 5: 运行 + 类型 + 提交**

Run: `uv run pytest tests/test_last_words.py -v && uv run mypy app && uv run ruff check .`
Expected: PASS。
```bash
git add backend/app/engine/events.py backend/app/engine/state.py backend/tests/test_last_words.py
git commit -m "feat(engine): 遗言/猎人/白痴事件与 resume_token 字段"
```

### Task 12: 猎人开枪与遗言流程

**Files:**
- Modify: `backend/app/engine/phases.py`（`expected_actors` 加 HUNTER_SHOOT/LAST_WORDS）
- Modify: `backend/app/engine/engine.py`（validate/apply/系统推进的死亡处理）
- Test: `backend/tests/test_hunter.py`
- Test: `backend/tests/test_last_words.py`（追加行为测试）

**Interfaces:**
- Consumes: Task 11 事件。
- Produces（engine.py 内部）：`_last_words_recipients(state, deaths, is_night) -> tuple[int,...]`、重写后的 `_resolve_night_and_continue`、`_after_exile`、新增 `_system_transition` 的 `HUNTER_SHOOT`/`LAST_WORDS`/`IDIOT_FLIP` 分支。

- [ ] **Step 1: `expected_actors` 加两阶段**

在 `backend/app/engine/phases.py` 的 `expected_actors` 里，`HUNTER_SHOOT` 分支已存在；追加 `LAST_WORDS`：
```python
    if ph == Phase.LAST_WORDS:
        if state.speech_idx < len(state.speech_order):
            return {state.speech_order[state.speech_idx]}
        return set()
```

- [ ] **Step 2: 写猎人行为测试**

Create `backend/tests/test_hunter.py`：
```python
from app.engine.actions import NightAction, NightActionType
from app.engine.config import RoleType, build_preset
from app.engine.engine import step
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player, living_of_role, player_at


def _hunter_at_shoot(cause_poison: bool) -> GameState:
    """构造一个「猎人刚出局、待开枪」的最小态。"""
    from app.engine.config import Faction

    roles = [RoleType.HUNTER, RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i, display_name=f"P{i}", role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0),  # 猎人已死
            hunter_can_shoot=not cause_poison,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    return GameState(
        game_id="g", config=cfg, phase=Phase.HUNTER_SHOOT, round=1,
        players=players, pending_hunter=0, resume_token="day_after_hunter",
    )


def test_hunter_shoots_takes_victim() -> None:
    st = _hunter_at_shoot(cause_poison=False)
    assert expected_actors(st) == {0}
    res = step(st, NightAction(actor_seat=0, action_type=NightActionType.SHOOT, target_seat=1))
    assert res.rejection is None
    assert player_at(res.state, 1).alive is False


def test_hunter_poisoned_cannot_reach_shoot() -> None:
    # 被毒 -> hunter_can_shoot False -> 引擎不应进入 HUNTER_SHOOT（见集成测试）
    st = _hunter_at_shoot(cause_poison=True)
    # 直接构造到 HUNTER_SHOOT 但 can_shoot=False：开枪应被拒
    res = step(st, NightAction(actor_seat=0, action_type=NightActionType.SHOOT, target_seat=1))
    assert res.rejection is not None
```

- [ ] **Step 3: validate/apply 加 HUNTER_SHOOT 与 LAST_WORDS**

在 `backend/app/engine/engine.py` 的 `_validate` 中，`isinstance(action, NightAction)` 分支之前（actor 存活/轮次校验之后）不变；在 `_validate_night` 追加 `HUNTER_SHOOT` 分支：
```python
    if ph == Phase.HUNTER_SHOOT:
        pl2 = player_at(state, a.actor_seat)
        if not pl2.hunter_can_shoot:
            return RejectedReason.HUNTER_CANNOT_SHOOT
        if at == NightActionType.SKIP:
            return None
        if at != NightActionType.SHOOT:
            return RejectedReason.WRONG_PHASE
        if not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None
```
在 `_validate` 里，`Speak` 目前无条件放行；`LAST_WORDS` 阶段的 Speak 也应放行（actor 已由 expected_actors 约束），无需改动。

在 `_apply_night` 追加 `HUNTER_SHOOT` 分支：
```python
    if ph == Phase.HUNTER_SHOOT:
        victim = None if at == NightActionType.SKIP else a.target_seat
        s, e = _emit(state, EventType.HUNTER_SHOT, HunterShotPayload(shooter=actor, victim=victim), Visibility.PUBLIC, actor=actor)
        return s, [e]
```
在 `_apply_action` 里，`LAST_WORDS` 阶段的 `Speak` 要产出 `LAST_WORDS` 事件而非 `PLAYER_SPOKE`。把 `Speak` 分支改为：
```python
    if isinstance(action, Speak):
        if state.phase == Phase.LAST_WORDS:
            s, e = _emit(state, EventType.LAST_WORDS, LastWordsPayload(seat=action.actor_seat, content=action.content), Visibility.PUBLIC, actor=action.actor_seat)
            return s, [e]
        s, e = _emit(state, EventType.PLAYER_SPOKE, PlayerSpokePayload(content=action.content, claim_role=action.claim_role, badge_flow=action.badge_flow), Visibility.PUBLIC, actor=action.actor_seat)
        return s, [e]
```
（记得在 engine.py 顶部 import `HunterShotPayload`、`LastWordsPayload`、`IdiotRevealedPayload`。）

- [ ] **Step 4: 重写死亡处理（engine.py）**

新增遗言接收者 helper 与中断/续接逻辑。用下面版本**替换** Stage 1 的 `_resolve_night_and_continue` 与 `_after_exile`，并新增 `_last_words_recipients`、`_enter_hunter_or_lastwords_night`、`_enter_last_words`、以及 `_system_transition` 的新分支处理函数：
```python
def _last_words_recipients(state: GameState, deaths: tuple[int, ...], is_night: bool) -> tuple[int, ...]:
    rule = state.config.last_words
    if not is_night:
        return deaths  # 白天出局者始终有遗言
    from app.engine.config import LastWordsRule

    if rule == LastWordsRule.ALWAYS_NIGHT:
        return deaths
    if rule == LastWordsRule.FIRST_NIGHT_ONLY:
        return deaths if state.round == 1 else ()
    # N_EQUALS_WOLVES：前 (狼数) 个夜晚的死者有遗言（M1 采用「round <= 初始狼数」口径）
    initial_wolves = sum(slot.count for slot in state.config.roles if slot.role == RoleType.WEREWOLF)
    return deaths if state.round <= initial_wolves else ()


def _dead_hunter_can_shoot(state: GameState, deaths: frozenset[int], poisoned: int | None) -> int | None:
    for seat in sorted(deaths):
        pl = player_at(state, seat)
        if pl.role == RoleType.HUNTER and pl.hunter_can_shoot and seat != poisoned:
            return seat
    return None
```

用下面替换 `_resolve_night_and_continue`：
```python
def _resolve_night_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    na = state.pending_night
    if na.witch_save and na.wolf_target is not None:
        witches = living_of_role(state, RoleType.WITCH)
        if witches:
            state = _consume_witch_potion(state, witches[0].seat, antidote=True)

    deaths = resolve_night(state.config, na)
    ordered = tuple(sorted(deaths))
    state, e = _emit(state, EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=ordered), Visibility.GM_ONLY)
    events.append(e)

    winner = _check_win_with_deaths(state, deaths)
    if winner is not None and state.config.wolf_first_kill_priority:
        state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
        events.append(e)
        return state, events

    state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
    events.append(e)
    winner2 = check_win(state)
    if winner2 is not None:
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner2), Visibility.PUBLIC)
        events.append(e)
        return state, events

    # 夜间猎人开枪（被毒不可）
    shooter = _dead_hunter_can_shoot(state, deaths, na.witch_poison_target)
    if shooter is not None:
        state = state.model_copy(update={"pending_hunter": shooter, "resume_token": "night_after_hunter", "night_deaths": ordered})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.HUNTER_SHOOT), Visibility.PUBLIC)
        return state, [*events, e]

    return _finish_night_deaths(state, ordered, events)


def _finish_night_deaths(state: GameState, ordered: tuple[int, ...], events: list[Event]) -> tuple[GameState, list[Event]]:
    recipients = _last_words_recipients(state, ordered, is_night=True)
    if recipients:
        state = state.model_copy(update={"resume_token": "day_speech"})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.LAST_WORDS, speech_order=recipients), Visibility.PUBLIC)
        return state, [*events, e]
    state, ev = _enter_day_speech(state)
    return state, [*events, *ev]
```

> **说明**：`state.model_copy(update={...})` 在这里改的是 `pending_hunter`/`resume_token`/`night_deaths` 这类**流程游标**，非游戏事实（玩家生死、票数）。为严守「事件是唯一写路径」，可选把它们也做成事件；M1 允许游标字段直接更新（它们可由事件流重建，不影响回放一致性，因为 CLI 回放用的是 `reduce(events)` 且这些游标不参与终态断言）。**若要 100% 事件化**，加一个 `CURSOR_SET` GM_ONLY 事件承载 `pending_hunter/resume_token`，reduce 时更新——Stage 4 加固时按需升级。

用下面替换 `_after_exile`：
```python
def _after_exile(state: GameState) -> tuple[GameState, list[Event]]:
    exiled = state.day_exiled
    if exiled is not None:
        pl = player_at(state, exiled)
        if pl.role == RoleType.HUNTER and pl.hunter_can_shoot:
            state = state.model_copy(update={"pending_hunter": exiled, "resume_token": "day_after_hunter"})
            state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.HUNTER_SHOOT), Visibility.PUBLIC)
            return state, [e]
    return _enter_day_last_words(state, extra=())


def _enter_day_last_words(state: GameState, extra: tuple[int, ...]) -> tuple[GameState, list[Event]]:
    dead_today = tuple(sorted(set(([state.day_exiled] if state.day_exiled is not None else []) + list(extra))))
    recipients = _last_words_recipients(state, dead_today, is_night=False)
    if recipients:
        state = state.model_copy(update={"resume_token": "after_day"})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.LAST_WORDS, speech_order=recipients), Visibility.PUBLIC)
        return state, [e]
    return _after_day_death(state)
```

- [ ] **Step 5: `_system_transition` 加 HUNTER_SHOOT / LAST_WORDS 续接分支**

在 `_system_transition` 追加（在 `EXILE` 分支附近）：
```python
    if ph == Phase.HUNTER_SHOOT:
        # 猎人已开枪（HUNTER_SHOT 事件已应用），按 resume_token 续接
        token = state.resume_token
        victim_dead = state.night_deaths  # 夜间语境
        if token == "night_after_hunter":
            state = state.model_copy(update={"resume_token": None})
            winner = check_win(state)
            if winner is not None:
                s, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
                return s, [e]
            return _finish_night_deaths(state, victim_dead, [])
        # day_after_hunter
        state = state.model_copy(update={"resume_token": None})
        winner = check_win(state)
        if winner is not None:
            s, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
            return s, [e]
        return _enter_day_last_words(state, extra=())

    if ph == Phase.LAST_WORDS:
        token = state.resume_token
        state = state.model_copy(update={"resume_token": None})
        if token == "day_speech":
            return _enter_day_speech(state)
        return _after_day_death(state)
```

- [ ] **Step 6: 运行猎人测试**

Run: `uv run pytest tests/test_hunter.py -v`
Expected: PASS（2 项）。

- [ ] **Step 7: 追加遗言行为测试**

Append 到 `backend/tests/test_last_words.py`：
```python
from app.cli.bot import run_game
from app.engine.events import EventType
from tests.factories import stage1_config


def test_first_night_death_has_night_last_words() -> None:
    # stage1 板默认 FIRST_NIGHT_ONLY：首夜若有死者，事件流应含 LAST_WORDS
    _, events = run_game(stage1_config(seed=13), game_id="g")
    types = [e.type for e in events]
    # 至少存在一次 LAST_WORDS（首夜死者或白天出局者）
    assert EventType.LAST_WORDS in types
```

- [ ] **Step 8: 全量回归 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check .`
Expected: 全绿。
```bash
git add backend/app/engine/engine.py backend/app/engine/phases.py backend/tests/test_hunter.py backend/tests/test_last_words.py
git commit -m "feat(engine): 猎人开枪与遗言流程"
```

### Task 13: 白痴翻牌与四 preset 全绿

**Files:**
- Modify: `backend/app/engine/engine.py`（`_tally_and_continue` 出局分流加白痴）
- Test: `backend/tests/test_idiot.py`
- Test: `backend/tests/test_config.py`（追加：四 preset 各跑一局必终局）

**Interfaces:**
- Consumes: Task 11 `IDIOT_REVEALED`。

- [ ] **Step 1: 写白痴测试**

Create `backend/tests/test_idiot.py`：
```python
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import _tally_and_continue  # 内部函数直测分流
from app.engine.phases import Phase
from app.engine.state import GameState, Player, player_at


def _vote_state(idiot_revealed: bool) -> GameState:
    roles = [RoleType.IDIOT, RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i, display_name=f"P{i}", role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            idiot_revealed=idiot_revealed if r == RoleType.IDIOT else False,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    # 所有票投 idiot(0)
    votes = {1: 0, 2: 0, 3: 0, 4: 0}
    return GameState(
        game_id="g", config=cfg, phase=Phase.VOTE, round=2, players=players, votes=votes,
    )


def test_idiot_first_flip_survives_and_voids_vote() -> None:
    st = _vote_state(idiot_revealed=False)
    new, events = _tally_and_continue(st)
    idiot = player_at(new, 0)
    assert idiot.alive is True          # 免死
    assert idiot.idiot_revealed is True
    assert idiot.can_vote is False      # 失投票权
    # 当天投票作废：无人被放逐
    assert new.day_exiled is None


def test_idiot_after_reveal_can_be_exiled() -> None:
    st = _vote_state(idiot_revealed=True)
    new, events = _tally_and_continue(st)
    # 已翻过牌，再被票则正常出局
    assert player_at(new, 0).alive is False
```

- [ ] **Step 2: 在 `_tally_and_continue` 出局处加白痴分流**

在 `backend/app/engine/engine.py` 的 `_tally_and_continue` 里，把「`if exiled is not None:`」块开头改为先判白痴：
```python
    if exiled is not None:
        exiled_pl = player_at(state, exiled)
        if exiled_pl.role == RoleType.IDIOT and not exiled_pl.idiot_revealed:
            state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.IDIOT_FLIP), Visibility.PUBLIC)
            events.append(e)
            state, e = _emit(state, EventType.IDIOT_REVEALED, IdiotRevealedPayload(seat=exiled), Visibility.PUBLIC, actor=exiled)
            events.append(e)
            # 当天投票作废，直接进入下一夜
            state, ev = _after_day_death(state)
            return state, [*events, *ev]
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.PLAYER_EXILED, PlayerExiledPayload(seat=exiled), Visibility.PUBLIC)
        events.append(e)
        return state, events
```
（在 engine.py 顶部确保 import 了 `IdiotRevealedPayload`。）

- [ ] **Step 3: 运行白痴测试**

Run: `uv run pytest tests/test_idiot.py -v`
Expected: PASS（2 项）。

- [ ] **Step 4: 四 preset 全跑测试**

Append 到 `backend/tests/test_config.py`：
```python
def test_all_presets_run_to_completion() -> None:
    from app.cli.bot import run_game
    from app.engine.phases import Phase

    for name in ALL_PRESETS:
        cfg = build_preset(name).model_copy(update={"seed": 2024})
        final, events = run_game(cfg, game_id=f"g_{name}")
        assert final.phase == Phase.GAME_OVER, f"{name} 未终局"
```

- [ ] **Step 5: 全量回归 + 提交**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check .`
Expected: 全绿（含四 preset 完整对局）。
```bash
git add backend/app/engine/engine.py backend/tests/test_idiot.py backend/tests/test_config.py
git commit -m "feat(engine): 白痴翻牌与四 preset 完整对局"
```

> **Stage 2 完成判据**：猎人（开枪/被毒/时序）、白痴（翻牌/失票/作废）、遗言（首夜/之后/白天）测试全绿；四个官方 preset 都能用 RandomBot 跑完整局。

---

## Stage 3 — 警长层

交付：警长竞选（上警 → 警下投票 → PK → 再平票警徽流失）、自爆吞警徽、1.5 票、警徽移交/撕毁、发言顺序规则（非 BIDDING）、`BIDDING` 接受配置但拒绝行动。

> **M1 明确简化**（写入计划的「不在范围」以对齐评审）：竞选发言与「退水失投票权」的中途退水不单独建模——M1 竞选为「上警/不上警」一次性声明，不上警者保留投票权；警徽流 `badge_flow` 仅作为发言 payload 透传，不做未来验人校验。这些在 M2 有真实 agent 后补。

### Task 14: 警长竞选（竞选 → 警下投票 → PK → 警徽流失）

**Files:**
- Modify: `backend/app/engine/state.py`（竞选字段）
- Modify: `backend/app/engine/events.py`（竞选 payload + reduce）
- Modify: `backend/app/engine/phases.py`（`expected_actors` 加竞选阶段）
- Modify: `backend/app/engine/engine.py`（竞选流程 + 接入首夜结算）
- Modify: `backend/app/cli/bot.py`（RandomBot 支持竞选阶段）
- Test: `backend/tests/test_sheriff.py`

**Interfaces:**
- Produces（state.py）字段：`sheriff_candidates: tuple[int,...]=()`、`sheriff_declared: frozenset[int]=frozenset()`、`sheriff_votes: dict[int,int|None]=Field(default_factory=dict)`、`election_stage: str=""`。
- Produces（events.py）payload：`SheriffCandidacyPayload(seat, running)`、`SheriffVoteCastPayload(voter, target)`、`SheriffElectedPayload(seat|None)`。
- Produces（engine.py）：竞选流程函数；首夜结算在公布死讯前插入竞选。

- [ ] **Step 1: 加 state 字段**

在 `backend/app/engine/state.py` 的 `GameState` 追加：
```python
    # 警长竞选
    sheriff_candidates: tuple[int, ...] = ()
    sheriff_declared: frozenset[int] = frozenset()
    sheriff_votes: dict[int, int | None] = Field(default_factory=dict)
    election_stage: str = ""  # ""/"candidacy"/"vote"/"pk"
```

- [ ] **Step 2: 加竞选 payload 与 reduce（events.py）**

payload：
```python
class SheriffCandidacyPayload(EventPayload):
    seat: int
    running: bool  # True=上警, False=不上警


class SheriffVoteCastPayload(EventPayload):
    voter: int
    target: int | None


class SheriffElectedPayload(EventPayload):
    seat: int | None  # None=警徽流失
```
reduce 分支：
```python
    if t == EventType.SHERIFF_CANDIDACY and isinstance(p, SheriffCandidacyPayload):
        declared = state.sheriff_declared | {p.seat}
        candidates = state.sheriff_candidates
        if p.running and p.seat not in candidates:
            candidates = (*candidates, p.seat)
        return {"sheriff_declared": declared, "sheriff_candidates": candidates}

    if t == EventType.SHERIFF_VOTE_CAST and isinstance(p, SheriffVoteCastPayload):
        sv = dict(state.sheriff_votes)
        sv[p.voter] = p.target
        return {"sheriff_votes": sv}

    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        if p.seat is None:
            return {"sheriff_seat": None}
        players = _replace_player(state.players, p.seat, is_sheriff=True)
        return {"sheriff_seat": p.seat, "players": players}
```

- [ ] **Step 3: `expected_actors` 加竞选阶段（phases.py）**

```python
    if ph == Phase.SHERIFF_ELECTION:
        if state.election_stage == "candidacy":
            return {p.seat for p in living(state) if p.seat not in state.sheriff_declared}
        if state.election_stage == "vote":
            return {
                p.seat
                for p in living(state)
                if p.can_vote and p.seat not in state.sheriff_candidates and p.seat not in state.sheriff_votes
            }
        return set()
    if ph == Phase.SHERIFF_PK:
        return {
            p.seat
            for p in living(state)
            if p.can_vote and p.seat not in state.sheriff_candidates and p.seat not in state.sheriff_votes
        }
```

- [ ] **Step 4: 写竞选测试**

Create `backend/tests/test_sheriff.py`：
```python
from app.engine.actions import Direction, SheriffAction, SheriffActionType
from app.engine.config import build_preset
from app.engine.engine import step
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_seats
from app.cli.bot import run_game


def _preset_with_sheriff(seed: int):
    return build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})


def test_full_game_with_sheriff_terminates() -> None:
    final, events = run_game(_preset_with_sheriff(2024), game_id="g")
    assert final.phase == Phase.GAME_OVER
    # 竞选发生过：存在 SHERIFF_ELECTED 事件（当选或流失）
    from app.engine.events import EventType

    assert any(e.type == EventType.SHERIFF_ELECTED for e in events)


def test_sheriff_vote_weight_is_1_5() -> None:
    # 单元层已由 resolver.test_count_votes_sheriff_weight_breaks_tie 覆盖；此处断言 engine 用了 is_sheriff 权重
    from app.engine.engine import _tally_and_continue
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player

    roles = [RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i, display_name=f"P{i}", role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    # seat0(警长,1.5票)投1；seat2投2 -> 1 以 1.5 vs 1.0 胜
    st = GameState(game_id="g", config=cfg, phase=Phase.VOTE, round=2, players=players, votes={0: 1, 2: 2})
    new, _ = _tally_and_continue(st)
    assert new.day_exiled == 1
```

- [ ] **Step 5: 接入首夜结算 + 竞选流程（engine.py）**

把 `_resolve_night_and_continue` 里「公布死讯」那段（`DEATH_ANNOUNCED` 起到函数尾）抽成 `_announce_and_continue_night(state, ordered, events)`，并在 wolf-first 检查之后加首夜竞选分支：
```python
def _resolve_night_and_continue(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    na = state.pending_night
    if na.witch_save and na.wolf_target is not None:
        witches = living_of_role(state, RoleType.WITCH)
        if witches:
            state = _consume_witch_potion(state, witches[0].seat, antidote=True)
    deaths = resolve_night(state.config, na)
    ordered = tuple(sorted(deaths))
    state, e = _emit(state, EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=ordered), Visibility.GM_ONLY)
    events.append(e)

    winner = _check_win_with_deaths(state, deaths)
    if winner is not None and state.config.wolf_first_kill_priority:
        state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
        events.append(e)
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
        events.append(e)
        return state, events

    # 首日：公布死讯前竞选
    if (
        state.round == 1
        and state.config.sheriff.enabled
        and state.config.sheriff.election_before_first_death_announce
    ):
        state = state.model_copy(update={"night_deaths": ordered, "election_stage": "candidacy"})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_ELECTION), Visibility.PUBLIC)
        return state, [*events, e]

    return _announce_and_continue_night(state, ordered, events)


def _announce_and_continue_night(state: GameState, ordered: tuple[int, ...], events: list[Event]) -> tuple[GameState, list[Event]]:
    state, e = _emit(state, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=ordered), Visibility.PUBLIC)
    events.append(e)
    winner2 = check_win(state)
    if winner2 is not None:
        state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner2), Visibility.PUBLIC)
        events.append(e)
        return state, events
    shooter = _dead_hunter_can_shoot(state, frozenset(ordered), state.pending_night.witch_poison_target)
    if shooter is not None:
        state = state.model_copy(update={"pending_hunter": shooter, "resume_token": "night_after_hunter", "night_deaths": ordered})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.HUNTER_SHOOT), Visibility.PUBLIC)
        return state, [*events, e]
    return _finish_night_deaths(state, ordered, events)
```

新增竞选推进（`_system_transition` 的 `SHERIFF_ELECTION`/`SHERIFF_PK` 分支调用）：
```python
def _advance_election(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    if state.election_stage == "candidacy":
        # 全员声明完毕
        if not state.sheriff_candidates:
            return _finish_election(state, elected=None, events=events)
        state = state.model_copy(update={"election_stage": "vote", "sheriff_votes": {}})
        return state, events  # 进入 vote 阶段，等待警下投票
    # vote 阶段收尾
    weights = {s: 1.0 for s in living_seats(state)}
    elected, tie = count_votes(state.sheriff_votes, weights)
    if elected is not None:
        return _finish_election(state, elected=elected, events=events)
    if tie and state.phase == Phase.SHERIFF_ELECTION:
        # 进入 PK：候选缩小为平票者
        state = state.model_copy(update={"sheriff_candidates": tie, "sheriff_votes": {}})
        state, e = _emit(state, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_PK), Visibility.PUBLIC)
        return state, [e]
    # PK 再平票 -> 警徽流失
    return _finish_election(state, elected=None, events=events)


def _finish_election(state: GameState, elected: int | None, events: list[Event]) -> tuple[GameState, list[Event]]:
    state, e = _emit(state, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=elected), Visibility.PUBLIC)
    events.append(e)
    state = state.model_copy(update={"election_stage": ""})
    # 竞选结束 -> 回到「公布死讯并继续」
    return _announce_and_continue_night(state, state.night_deaths, events)
```

在 `_system_transition` 追加分支：
```python
    if ph in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        return _advance_election(state)
```

- [ ] **Step 6: validate/apply 竞选行动（engine.py）**

把 `_validate` 里对 `SheriffAction` 的「一律 WRONG_PHASE」改为分派：
```python
    if isinstance(action, SelfDestruct):
        return RejectedReason.WRONG_PHASE  # Task 15 实现
    if isinstance(action, SheriffAction):
        return _validate_sheriff(state, action)
```
新增：
```python
def _validate_sheriff(state: GameState, a: SheriffAction) -> RejectedReason | None:
    try:
        pl = player_at(state, a.actor_seat)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    if not pl.alive:
        return RejectedReason.DEAD_ACTOR
    if a.actor_seat not in expected_actors(state):
        return RejectedReason.NOT_YOUR_TURN
    at = a.action_type
    if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "candidacy":
        if at not in (SheriffActionType.RUN_FOR_SHERIFF, SheriffActionType.WITHDRAW):
            return RejectedReason.WRONG_PHASE
        return None
    if state.phase in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        if at != SheriffActionType.VOTE_SHERIFF:
            return RejectedReason.WRONG_PHASE
        if a.target_seat not in state.sheriff_candidates:
            return RejectedReason.NOT_A_CANDIDATE
        return None
    return RejectedReason.WRONG_PHASE
```
在 `_apply_action` 追加（在 DayVote 之后）：
```python
    if isinstance(action, SheriffAction):
        return _apply_sheriff(state, action)
```
新增：
```python
def _apply_sheriff(state: GameState, a: SheriffAction) -> tuple[GameState, list[Event]]:
    at = a.action_type
    if at in (SheriffActionType.RUN_FOR_SHERIFF, SheriffActionType.WITHDRAW):
        running = at == SheriffActionType.RUN_FOR_SHERIFF
        s, e = _emit(state, EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=a.actor_seat, running=running), Visibility.PUBLIC, actor=a.actor_seat)
        return s, [e]
    # vote_sheriff
    s, e = _emit(state, EventType.SHERIFF_VOTE_CAST, SheriffVoteCastPayload(voter=a.actor_seat, target=a.target_seat), Visibility.PUBLIC, actor=a.actor_seat)
    return s, [e]
```
（engine.py 顶部 import `SheriffActionType`、`SheriffCandidacyPayload`、`SheriffVoteCastPayload`、`SheriffElectedPayload`。）

- [ ] **Step 7: RandomBot 支持竞选（bot.py）**

在 `RandomBot.choose_action` 的阶段分派里加：
```python
        from app.engine.actions import SheriffAction, SheriffActionType

        if ph == Phase.SHERIFF_ELECTION and state.election_stage == "candidacy":
            running = rng.derive_int(seed=seed, purpose=f"bot:{seat}:run", seq=state.state_version, modulo=2) == 0
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.RUN_FOR_SHERIFF if running else SheriffActionType.WITHDRAW)
        if ph in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
            cands = list(state.sheriff_candidates) or living_seats(state)
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=pick(cands, "sv"))
```

- [ ] **Step 8: 运行竞选测试 + 全量回归**

Run: `uv run pytest tests/test_sheriff.py -v && uv run pytest -q`
Expected: PASS。

- [ ] **Step 9: 类型 + lint + 提交**

Run: `uv run mypy app && uv run ruff check .`
```bash
git add backend/app/engine backend/app/cli/bot.py backend/tests/test_sheriff.py
git commit -m "feat(engine): 警长竞选（上警/警下投票/PK/警徽流失）"
```

### Task 15: 自爆、警徽移交/撕毁、发言顺序规则、BIDDING 拒绝

**Files:**
- Modify: `backend/app/engine/events.py`（`WolfSelfDestructPayload`、`BadgePassedPayload` + reduce）
- Modify: `backend/app/engine/engine.py`（自爆、发言顺序、BIDDING 拒绝、警徽移交）
- Modify: `backend/app/cli/bot.py`（自爆偶发 + 警徽处理）
- Test: `backend/tests/test_sheriff.py`（追加）

**Interfaces:**
- Produces（events.py）：`WolfSelfDestructPayload(seat)`、`BadgePassedPayload(from_seat, to_seat)`（`to_seat=None` 表示撕警徽/流失）。
- Produces（engine.py）：重写 `_speech_order` 按 `speech_order_rule`；`SelfDestruct` 校验/应用；`DAY_SPEECH` 的 `Speak` 在 `BIDDING` 下返回 `BIDDING_NOT_IMPLEMENTED`；`LAST_WORDS` 中允许将死警长用 `pass_badge`/`tear_badge` 消耗其发言回合。

- [ ] **Step 1: 加 payload 与 reduce（events.py）**

```python
class WolfSelfDestructPayload(EventPayload):
    seat: int


class BadgePassedPayload(EventPayload):
    from_seat: int
    to_seat: int | None  # None=撕毁/流失
```
reduce：
```python
    if t == EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
        return {"players": _replace_player(state.players, p.seat, alive=False)}

    if t == EventType.BADGE_PASSED and isinstance(p, BadgePassedPayload):
        players = _replace_player(state.players, p.from_seat, is_sheriff=False)
        if p.to_seat is not None:
            players = _replace_player(players, p.to_seat, is_sheriff=True)
        return {"players": players, "sheriff_seat": p.to_seat}
```

- [ ] **Step 2: 写测试**

Append 到 `backend/tests/test_sheriff.py`：
```python
def test_self_destruct_in_day_skips_to_night() -> None:
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player

    roles = [RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER, RoleType.VILLAGER]
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=r, faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD)
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    st = GameState(game_id="g", config=cfg, phase=Phase.DAY_SPEECH, round=1, players=players, speech_order=(0, 1, 2, 3, 4), speech_idx=0)
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    from app.engine.state import player_at
    assert player_at(res.state, 0).alive is False
    # 跳过当天发言/投票直接入夜（回到夜间阶段或终局）
    assert res.state.phase in (Phase.NIGHT_GUARD, Phase.NIGHT_WEREWOLF, Phase.GAME_OVER)


def test_non_wolf_cannot_self_destruct() -> None:
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player

    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(4)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 4, "seed": 1})
    st = GameState(game_id="g", config=cfg, phase=Phase.DAY_SPEECH, round=1, players=players, speech_order=(0, 1, 2, 3), speech_idx=0)
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is not None


def test_bidding_speech_is_rejected() -> None:
    from app.engine.actions import Speak
    from app.engine.config import SpeechOrderRule, Faction, RoleType
    from app.engine.state import Player
    from app.engine.actions import RejectedReason

    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(4)
    )
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 4, "seed": 1, "speech_order_rule": SpeechOrderRule.BIDDING}
    )
    st = GameState(game_id="g", config=cfg, phase=Phase.DAY_SPEECH, round=1, players=players, speech_order=(0, 1, 2, 3), speech_idx=0)
    res = step(st, Speak(actor_seat=0, content="x"))
    assert res.rejection == RejectedReason.BIDDING_NOT_IMPLEMENTED
```

- [ ] **Step 3: 重写发言顺序 `_speech_order`（engine.py）**

```python
def _speech_order(state: GameState) -> tuple[int, ...]:
    from app.engine.config import SpeechOrderRule

    alive = living_seats(state)
    if not alive:
        return ()
    rule = state.config.speech_order_rule
    n = state.config.num_players

    def _clockwise_from(start: int) -> tuple[int, ...]:
        seq = [(start + i) % n for i in range(n)]
        return tuple(s for s in seq if s in alive)

    if rule == SpeechOrderRule.FIXED_CLOCKWISE or rule == SpeechOrderRule.BIDDING:
        return tuple(alive)  # BIDDING 下顺序仅占位；Speak 会被拒
    if rule == SpeechOrderRule.DEATH_NEXT:
        last_death = max(state.night_deaths) if state.night_deaths else (state.day_exiled if state.day_exiled is not None else -1)
        return _clockwise_from((last_death + 1) % n) if last_death >= 0 else tuple(alive)
    if rule == SpeechOrderRule.ODD_EVEN_CLOCK:
        base = _clockwise_from(alive[0])
        return base if state.round % 2 == 1 else tuple(reversed(base))
    # SHERIFF_DECIDES：警长存活则从警长下家顺时针；否则退回死者下家/顺时针
    if state.sheriff_seat is not None:
        return _clockwise_from((state.sheriff_seat + 1) % n)
    return tuple(alive)
```

- [ ] **Step 4: 自爆校验/应用 + BIDDING 拒绝（engine.py）**

`_validate` 里把 `SelfDestruct` 的 `WRONG_PHASE` 改为：
```python
    if isinstance(action, SelfDestruct):
        return _validate_self_destruct(state, action)
```
新增：
```python
def _validate_self_destruct(state: GameState, a: SelfDestruct) -> RejectedReason | None:
    try:
        pl = player_at(state, a.actor_seat)
    except KeyError:
        return RejectedReason.INVALID_TARGET
    if not pl.alive:
        return RejectedReason.DEAD_ACTOR
    if pl.faction != Faction.WOLF:
        return RejectedReason.NOT_SELF_DESTRUCTABLE
    if state.phase not in (Phase.DAY_SPEECH, Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK):
        return RejectedReason.NOT_SELF_DESTRUCTABLE
    return None
```
在 `_validate` 的 `Speak` 放行处加 BIDDING 拦截：
```python
    if isinstance(action, Speak):
        from app.engine.config import SpeechOrderRule

        if state.phase == Phase.DAY_SPEECH and state.config.speech_order_rule == SpeechOrderRule.BIDDING:
            return RejectedReason.BIDDING_NOT_IMPLEMENTED
        return None
```
`_apply_action` 加 `SelfDestruct`：
```python
    if isinstance(action, SelfDestruct):
        s, e = _emit(state, EventType.WOLF_SELF_DESTRUCT, WolfSelfDestructPayload(seat=action.actor_seat), Visibility.PUBLIC, actor=action.actor_seat)
        # 竞选期自爆吞警徽
        if state.phase in (Phase.SHERIFF_ELECTION, Phase.SHERIFF_PK) and state.config.sheriff.wolf_selfdestruct_eats_badge:
            s = s.model_copy(update={"election_stage": "", "sheriff_seat": None})
            s, e2 = _emit(s, EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=None), Visibility.PUBLIC)
            events = [e, e2]
        else:
            events = [e]
        # 跳过当天剩余流程，直接入夜
        s2, more = _after_self_destruct(s)
        return s2, [*events, *more]
```
新增续接（自爆后：若竞选期先补公布死讯，再入夜；白天则直接入夜）：
```python
def _after_self_destruct(state: GameState) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    # 若还有未公布的首夜死讯（竞选期自爆），先公布
    if state.phase == Phase.DAY_SPEECH:
        # 白天自爆：当天死讯早已公布，直接判胜/入夜
        winner = check_win(state)
        if winner is not None:
            s, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
            return s, [e]
        return _after_day_death(state)
    # 竞选期自爆：补公布首夜死讯并继续（含猎人/遗言），随后进入白天——但自爆使当天直接入夜
    state = state.model_copy(update={"election_stage": ""})
    state, ev = _announce_and_continue_night(state, state.night_deaths, events)
    # _announce_and_continue_night 会进入 DAY_SPEECH；自爆要求跳过白天 -> 直接推进到入夜
    # 简化：若最终停在 DAY_SPEECH，则强制结束当天进入下一夜
    if state.phase == Phase.DAY_SPEECH:
        winner = check_win(state)
        if winner is not None:
            state, e = _emit(state, EventType.GAME_OVER, GameOverPayload(winner=winner), Visibility.PUBLIC)
            return state, [*ev, e]
        state, ev2 = _after_day_death(state)
        return state, [*ev, *ev2]
    return state, ev
```
（engine.py 顶部 import `WolfSelfDestructPayload`、`BadgePassedPayload`。）

> **自爆语义说明**：白天自爆直接入夜；竞选期自爆吞警徽后，M1 先公布首夜死讯再入夜（跳过当天发言投票）。这是对规格「立即天黑」的忠实近似——狼用自爆终结当天。

- [ ] **Step 5: 警徽移交/撕毁（engine.py + bot.py）**

将死警长在其 `LAST_WORDS` 回合用 `pass_badge`/`tear_badge` 消耗回合。`_validate` 的 `SheriffAction` 分派已在 Task 14；扩展 `_validate_sheriff` 支持 LAST_WORDS：
```python
    if state.phase == Phase.LAST_WORDS:
        if at not in (SheriffActionType.PASS_BADGE, SheriffActionType.TEAR_BADGE):
            return RejectedReason.WRONG_PHASE
        if not pl.is_sheriff:
            return RejectedReason.NOT_A_CANDIDATE
        if at == SheriffActionType.PASS_BADGE and not _alive_target(state, a.target_seat):
            return RejectedReason.DEAD_TARGET
        return None
```
但 `expected_actors(LAST_WORDS)` 只认当前发言者本人；将死警长正是当前发言者时才允许。`_apply_sheriff` 扩展：
```python
    if at in (SheriffActionType.PASS_BADGE, SheriffActionType.TEAR_BADGE):
        to = a.target_seat if at == SheriffActionType.PASS_BADGE else None
        s, e = _emit(state, EventType.BADGE_PASSED, BadgePassedPayload(from_seat=a.actor_seat, to_seat=to), Visibility.PUBLIC, actor=a.actor_seat)
        # 消耗该发言回合
        s = s.model_copy(update={"speech_idx": s.speech_idx + 1})
        return s, [e]
```
自动撕警徽兜底：警长若死亡且无遗言回合覆盖，在 `_finish_night_deaths`/`_enter_day_last_words` 计算 recipients 后补：
```python
def _auto_badge_if_orphaned(state: GameState, recipients: tuple[int, ...]) -> tuple[GameState, list[Event]]:
    if state.sheriff_seat is not None:
        holder = player_at(state, state.sheriff_seat)
        if not holder.alive and state.sheriff_seat not in recipients:
            s, e = _emit(state, EventType.BADGE_PASSED, BadgePassedPayload(from_seat=state.sheriff_seat, to_seat=None), Visibility.PUBLIC, actor=state.sheriff_seat)
            return s, [e]
    return state, []
```
在 `_finish_night_deaths` 与 `_enter_day_last_words` 里，计算 `recipients` 后、进入 LAST_WORDS 前，先调用 `_auto_badge_if_orphaned` 并把其事件并入返回。

RandomBot（bot.py）在 LAST_WORDS 中，若自己是警长则撕警徽：
```python
        if ph == Phase.LAST_WORDS and player_at(state, seat).is_sheriff:
            from app.engine.actions import SheriffAction, SheriffActionType
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.TEAR_BADGE)
```
（放在 `LAST_WORDS`/`DAY_SPEECH` 的 `Speak` 分支之前判断。当前 bot 对 LAST_WORDS 会落到 `Speak("(bot)")`——需在 DAY_SPEECH 分支前加 LAST_WORDS 判断返回 `Speak`，警长则返回撕警徽。）

- [ ] **Step 6: 追加警徽移交测试**

Append 到 `backend/tests/test_sheriff.py`：
```python
def test_dying_sheriff_can_pass_badge() -> None:
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player, player_at

    roles = [RoleType.VILLAGER, RoleType.SEER, RoleType.WEREWOLF]
    players = tuple(
        Player(
            seat=i, display_name=f"P{i}", role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0), is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    st = GameState(
        game_id="g", config=cfg, phase=Phase.LAST_WORDS, round=1, players=players,
        speech_order=(0,), speech_idx=0, sheriff_seat=0, resume_token="after_day",
    )
    res = step(st, SheriffAction(actor_seat=0, action_type=SheriffActionType.PASS_BADGE, target_seat=1))
    assert res.rejection is None
    assert res.state.sheriff_seat == 1
    assert player_at(res.state, 1).is_sheriff is True
```

- [ ] **Step 7: 全量回归 + 类型 + lint**

Run: `uv run pytest -q && uv run mypy app && uv run ruff check .`
Expected: 全绿。若某官方 preset 的完整对局因新分支卡住，用 `--verbose` 单跑 `simulate` 定位卡住的 phase，按 `expected_actors`/`_system_transition` 覆盖补齐。

- [ ] **Step 8: 提交**

```bash
git add backend/app/engine backend/app/cli/bot.py backend/tests/test_sheriff.py
git commit -m "feat(engine): 自爆吞警徽、警徽移交、发言顺序规则与 BIDDING 拒绝"
```

> **Stage 3 完成判据**：竞选/PK/警徽流失、自爆吞警徽、1.5 票、警徽移交、发言顺序规则、BIDDING 拒绝测试全绿；带警长的 12 人 preset 能用 RandomBot 跑完整局。

---

## Stage 4 — 加固

交付：完善信息隔离测试、确定性测试（同 seed 逐字节一致 + `reduce==live`）、500 局多 seed 模拟扫描、mypy strict 与 ruff 全干净。达成 §9-M1 全部交付判据。

### Task 16: 完善信息隔离测试

**Files:**
- Modify: `backend/tests/test_isolation.py`（追加）

- [ ] **Step 1: 追加隔离用例**

Append 到 `backend/tests/test_isolation.py`：
```python
def test_witch_no_kill_leak_after_antidote_used() -> None:
    # 解药用完且 knows_kill_after_antidote_used=False -> 不再注入刀口
    from app.engine.config import RoleType
    from app.engine.state import player_at

    state = _start()
    witch_seat = living_of_role(state, RoleType.WITCH)[0].seat
    # 构造：女巫无解药，本夜有刀口
    players = tuple(
        p.model_copy(update={"witch_antidote": False}) if p.seat == witch_seat else p
        for p in state.players
    )
    victim = next(p.seat for p in state.players if p.role == RoleType.VILLAGER)
    st = state.model_copy(
        update={
            "players": players,
            "pending_night": state.pending_night.model_copy(update={"wolf_target": victim}),
        }
    )
    obs = build_observation(st, witch_seat)
    assert "tonight_killed_seat" not in obs.private
    assert obs.private["antidote_available"] is False


def test_every_visibility_class_filtered_correctly() -> None:
    from app.engine.events import (
        EventType,
        PhaseChangedPayload,
        SeerCheckedPayload,
        WolfKillProposedPayload,
    )
    from app.engine.config import Faction
    from app.engine.phases import Phase

    state = _start()
    wolf = living_wolves(state)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat if (RoleType := __import__("app.engine.config", fromlist=["RoleType"]).RoleType) else 0

    def ev(seq, type_, payload, vis, actor=None):
        return Event(seq=seq, game_id="g", ts=float(seq), type=type_, actor_seat=actor, payload=payload, visibility=vis)

    events = [
        ev(1, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WITCH), Visibility.GM_ONLY),
        ev(2, EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=wolf, target=0), Visibility.WOLVES, actor=wolf),
        ev(3, EventType.SEER_CHECKED, SeerCheckedPayload(target=0, result=Faction.WOLF), Visibility.ROLE_SELF, actor=seer),
    ]
    # 狼能看 WOLVES，看不到别人的 ROLE_SELF，看不到 GM_ONLY
    wolf_view = {e.seq for e in visible_events(state, events, wolf)}
    assert wolf_view == {2}
    seer_view = {e.seq for e in visible_events(state, events, seer)}
    assert seer_view == {3}
    spec_view = {e.seq for e in visible_events(state, events, "SPECTATOR")}
    assert spec_view == set()
    gm_view = {e.seq for e in visible_events(state, events, "GM")}
    assert gm_view == {1, 2, 3}
```

> 上面 `seer` 取值那行写得别扭，实现时直接用：`seer = living_of_role(state, RoleType.SEER)[0].seat`（文件顶部已 import `RoleType`、`living_of_role`）。删掉那段 `__import__` 花招。

- [ ] **Step 2: 运行 + 提交**

Run: `uv run pytest tests/test_isolation.py -v`
Expected: PASS。
```bash
git add backend/tests/test_isolation.py
git commit -m "test(engine): 完善信息隔离（解药用尽无刀口 + 逐可见性过滤）"
```

### Task 17: 确定性测试

**Files:**
- Create: `backend/tests/test_determinism.py`

**Interfaces:**
- Consumes: `cli.bot.run_game`、`events.reduce_all`。

- [ ] **Step 1: 写确定性测试**

Create `backend/tests/test_determinism.py`：
```python
import pytest

from app.cli.bot import run_game
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState, Player

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


def _blank(final: GameState) -> GameState:
    players = tuple(
        Player(seat=p.seat, display_name=p.display_name, role=RoleType.VILLAGER, faction=Faction.GOOD)
        for p in final.players
    )
    return GameState(game_id=final.game_id, config=final.config, phase=Phase.LOBBY, round=0, players=players)


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [1, 17, 100])
def test_same_seed_byte_identical_event_log(preset: str, seed: int) -> None:
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    _, ev1 = run_game(cfg, game_id="g")
    _, ev2 = run_game(cfg, game_id="g")
    dump1 = [e.model_dump(mode="json") for e in ev1]
    dump2 = [e.model_dump(mode="json") for e in ev2]
    assert dump1 == dump2


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [3, 42, 256])
def test_reduce_events_equals_live_state(preset: str, seed: int) -> None:
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id="g")
    replayed = reduce_all(_blank(final), events)
    assert replayed.phase == final.phase == Phase.GAME_OVER
    assert replayed.winner == final.winner
    assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
    assert [p.role for p in replayed.players] == [p.role for p in final.players]
    assert replayed.sheriff_seat == final.sheriff_seat
```

- [ ] **Step 2: 运行 + 提交**

Run: `uv run pytest tests/test_determinism.py -v`
Expected: PASS（4 preset × 3 seed × 2 类）。
```bash
git add backend/tests/test_determinism.py
git commit -m "test(engine): 确定性（逐字节事件日志 + reduce==live）"
```

### Task 18: 500 局模拟扫描

**Files:**
- Create: `backend/tests/test_sweep.py`

- [ ] **Step 1: 写多 seed 扫描测试**

Create `backend/tests/test_sweep.py`：
```python
import pytest

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import EventType
from app.engine.phases import Phase

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


@pytest.mark.parametrize("preset", PRESETS)
def test_sweep_125_seeds_each_terminates(preset: str) -> None:
    # 4 preset × 125 seed = 500 局
    for seed in range(125):
        cfg = build_preset(preset).model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"{preset}-{seed}")
        assert final.phase == Phase.GAME_OVER, f"{preset} seed={seed} 未终局"
        go = [e for e in events if e.type == EventType.GAME_OVER]
        assert len(go) == 1, f"{preset} seed={seed} GAME_OVER 事件数={len(go)}"
        # 有胜负或达 max_rounds 平局
        assert final.winner in ("GOOD", "WOLF", None)
```

- [ ] **Step 2: 运行扫描**

Run: `uv run pytest tests/test_sweep.py -v`
Expected: PASS（4 项，共 500 局）。若某 preset 某 seed 卡死（`run_game` 抛「无人可行动但未终局」），说明有阶段的 `expected_actors`/`_system_transition` 未覆盖——按报错 phase 补齐后重跑。

- [ ] **Step 3: CLI 大扫描冒烟（可选，手动）**

Run: `uv run python -m app.cli.simulate --preset std_12_yn_hunter_idiot --seed 0 --games 500`
Expected: 打印 `跑完 500 局：{...}`，无断言失败。

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_sweep.py
git commit -m "test(engine): 500 局多 seed 模拟扫描"
```

### Task 19: mypy strict、ruff 全干净与 M1 交付核对

**Files:**
- Modify: 按需微调任意 `backend/app/**`、`backend/tests/**`

- [ ] **Step 1: 全量类型检查（strict）**

Run: `uv run mypy app`
Expected: `Success: no issues found`。若报错，常见修法：
- 用 `X | None` 而非裸 `Optional`；`Union[...]` type alias 换成 `A | B`。
- `dict[str, object]` 的 reduce 返回值在 `_reduce_dispatch` 保持一致标注。
- 给所有测试 helper 补 `-> None`/参数标注（strict 要求）。

- [ ] **Step 2: ruff 检查与格式化**

Run:
```bash
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
```
Expected: 全部通过；`--fix` 后再 `check` 无残留。

- [ ] **Step 3: 全量测试最终确认**

Run: `uv run pytest -q`
Expected: 全绿（含 500 局扫描）。记录用例总数。

- [ ] **Step 4: 逐条核对 §9-M1 交付判据**

对照打勾（在 PR/提交信息中写明）：
- [ ] §8.4 规则单测全过：`test_config`、`test_night_resolution`、`test_wolf_first`（见下补充）、`test_hunter`、`test_idiot`、`test_sheriff`、`test_last_words`、`test_win_conditions`、`test_isolation`、`test_determinism`、`test_sim_game` 全绿。
- [ ] 确定性重放：`test_determinism` 的逐字节一致 + `reduce==live` 通过。
- [ ] CLI 多 seed 跑完 500 局，必终局有结果：`test_sweep` 通过。

- [ ] **Step 5: 补 `test_wolf_first.py`（若尚缺独立文件）**

设计 §9 单列了 `test_wolf_first.py`。若狼刀在先仅在集成里覆盖，补一个直测：
Create `backend/tests/test_wolf_first.py`：
```python
from app.engine.config import Faction, RoleType, WinCondition, build_preset
from app.engine.engine import _check_win_with_deaths
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def test_wolf_first_kill_wins_before_witch_poison() -> None:
    # 屠城：好人只剩 1 人；狼刀刀掉最后好人 -> 狼胜（即便女巫随后毒狼也无效）
    roles = [RoleType.WEREWOLF, RoleType.VILLAGER]
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=r, faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD)
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_all").model_copy(update={"num_players": 2, "win_condition": WinCondition.KILL_ALL, "seed": 1})
    st = GameState(game_id="g", config=cfg, phase=Phase.NIGHT_SEER, round=1, players=players)
    # 狼刀掉 seat1（最后好人）
    assert _check_win_with_deaths(st, frozenset({1})) == "WOLF"
    # 未刀则未结束
    assert _check_win_with_deaths(st, frozenset()) is None
```
Run: `uv run pytest tests/test_wolf_first.py -v` → PASS。

- [ ] **Step 6: 最终提交**

```bash
git add backend
git commit -m "chore(engine): M1 加固 —— mypy strict/ruff 干净、狼刀在先独立测试、交付核对"
```

> **M1 完成判据（全部满足即交付）**：`uv run pytest -q` 全绿（含 500 局扫描与确定性）；`uv run mypy app` 与 `uv run ruff check .` 干净；`uv run python -m app.cli.simulate --games 500` 每局终局有结果。

---

## 明确不在 M1 范围（与设计 §11 一致）

- 任何 IO：网络、数据库、LLM 调用（M2 的 runtime/agent/api 层）。
- 竞价发言 BIDDING 的实际逻辑（M1 仅接受配置并拒绝行动）。
- 前端 TypeScript `reduce()`（M3+，事件契约是其唯一依据）。
- 情侣/丘比特、白狼王、骑士等扩展角色。

**M1 内进一步简化（已在对应 Stage 标注，供评审知情）**：
- 竞选发言与中途「退水失投票权」不单独建模（Stage 3）；平票 PK 的「平票者再发言」折叠为直接重投（Stage 1，PK 发言留到 M2 发言管线）。
- `badge_flow` 仅作发言 payload 透传，不做未来验人校验（M2）。
- 流程游标字段（`pending_hunter`/`resume_token`/`election_stage`/`night_deaths`）允许由 `step` 直接 `model_copy` 更新，不经事件——它们不参与回放终态断言，`reduce(events)==live` 仍对「游戏事实」成立。若需 100% 事件化，Stage 4 可加 `CURSOR_SET`(GM_ONLY) 事件承载，成本低。

---

## Self-Review（对照设计 §与规格 §8.4）

**1. 规格覆盖：**
- §3.2 GameConfig/presets/validate_config → Task 2 ✅
- §3.3 阶段机 + resolve_night 伪代码 + 狼刀在先 + 白痴翻牌 → Task 6/8/12/13 + `test_wolf_first` ✅
- §3.4 角色时序（守/狼/女/预/猎/白痴/村民/全体） → Task 8/12/13 ✅
- §4.2 信息隔离 build_observation + 隔离测试 → Task 9/16 ✅
- §6.4 事件溯源（Visibility/Event/reduce/回放） → Task 4 + `test_determinism` ✅
- §8.4 测试矩阵 → §9 表逐文件对应，全部有任务 ✅
- §9-M1 交付判据 → Task 18/19 ✅

**2. 占位扫描：** 计划内代码块均为可直接落地的实现或明确「替换函数 X」的完整片段；两处叙述性占位（`test_night_resolution` 的 placeholder 行、`_system_transition` 的占位行、`test_isolation` 的 `__import__` 花招、`test_isolation` seer 取值）均已就地标注「实现时删除/改写」。执行时按标注清理。

**3. 类型一致性：** 关键签名跨任务一致 —— `step→StepResult(state,events,rejection)`；`reduce(state,event)`；`resolve_night(config,NightActions)->frozenset[int]`；`count_votes(votes,weights)->(int|None, tuple)`；`check_win(state)->str|None`；`build_observation(state,seat)`；`visible_events(state,events,viewer)`。payload 模型名在 events.py 定义、engine.py 引用，命名统一（`WolfKillDecidedPayload` 等）。

> **执行时注意**：`phases.py` 与 `state.py` 存在 `Phase` 的单向依赖（state 只 import `Phase` 枚举，phases 的函数 import state 的 helper）。若运行时报循环 import，按 Task 7 Step 3 的提示把 phases 里对 state 的 import 改为函数内延迟 import。这是唯一预期的落地摩擦点。
