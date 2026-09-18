# AgentProfile 每座位独立配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个座位可独立配置内置 LLM Agent（模型三层路由、thinking、温度、展示名），经 API `agents` 字段与 CLI `--agents profiles.yaml` 建局；旧 `ai_model` 入口等价于 `"*"` 默认档案（issue #56）。

**Architecture:** 新模块 `app/agent/profile.py` 集中放 `AgentProfile` schema、`profile_for` 查找、`validate_profiles` 校验、`legacy_to_profiles` 旧字段折叠、`to_agent_config` 映射；registry / API / CLI 三个入口都只调它。`GameHandle` 持 `agents` 映射并按座位建端口；大厅填空位时按档案取名。任务顺序：profile 模块 → registry/agent_player → API → CLI/渲染/Makefile/README。

**Tech Stack:** Python 3.11、Pydantic v2、FastAPI、pytest、pyyaml（新增）；`uv` 管理。Python 命令在 `backend/` 下执行。

**Spec:** `docs/superpowers/specs/2026-09-18-agent-profile-design.md`（执行者须同时阅读）

## Global Constraints

- 引擎（`backend/app/engine/`）本期**不改**。档案属 runtime/agent/api/cli 层。
- 确定性不变：`AgentConfig.agent_seed` 仍取 `GameConfig.seed`（None → 0）。
- 信息隔离：档案是 HOST 建局输入，不进 observation / 观众视图；终端档案表只在本地打印。
- 旧入口行为不变：API `ai_model` / `ai_model_speech`、CLI `--ai-model` / `--ai-model-speech` / `--reflection-model` / `--thinking` 等价于 `"*"` 档案；`registry.create(..., ai_model=…)` 旧 kwargs 保留。
- 键名笔误 fail-loud：`AgentProfile` `extra="forbid"`；座位键越界/新旧冲突 → `ValueError`（API 400、CLI 参数错误）。
- 文档与代码注释用中文；标识符、API 名、schema 用英文。注释密度与周边代码一致。ruff 行宽 100 且中文按宽 2 计。
- 测试零 IO、零 mock（YAML 文件用 `tmp_path`）。
- 每个任务结束时：`uv run pytest -q -x --ignore=tests/test_api_e2e.py` 全绿、`uv run ruff check .`（须 All checks passed!）、`uv run ruff format --check .`、`uv run mypy app` 全过（最后一个任务跑含 E2E 的 `uv run pytest -q`）。
- commit message 风格 `feat(agent): … (issue #56)`，结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `backend/app/agent/profile.py`（新建） | schema、查找、校验、旧字段折叠、到 `AgentConfig` 的映射 | 1 |
| `backend/app/agent/agent_player.py` | `build_agent_port(seat, config, profile)` | 2 |
| `backend/app/runtime/game_runner.py` | `GameLobby.fill_with_bots(name_for=)` | 2 |
| `backend/app/runtime/registry.py` | `GameHandle.agents` / `profile_for`；`create(agents=…)`；按座位建端口 | 2 |
| `backend/app/schemas/games.py`、`backend/app/api/rest.py` | `agents` 请求/回显；冲突 400 | 3 |
| `backend/app/cli/play.py`、`play_human.py`、`render.py`、`Makefile`、`README.md`、`docs/specs/requirements.md` | `--agents` 加载、`_wire_game(agents=)`、档案表、文档 | 4 |
| `backend/pyproject.toml` | `pyyaml` / `types-PyYAML` | 4 |
| `backend/tests/test_agent_profile.py`（新建） | profile 模块测试 | 1 |

---

### Task 1: `app/agent/profile.py`——schema、查找、校验、折叠、映射

**Files:**
- Create: `backend/app/agent/profile.py`
- Create: `backend/tests/test_agent_profile.py`

**Interfaces:**
- Consumes: `app.agent.agent_player.AgentConfig`（既有）、`app.engine.config.GameConfig`。
- Produces（后续任务逐字依赖）:
  - `class AgentProfile(BaseModel)`：`name: str | None`、`model: str`、`model_speech: str | None`、`reflection_model: str | None`、`thinking: bool`、`temperature: float`；`frozen=True, extra="forbid"`
  - `AgentProfiles = dict[str, AgentProfile]`
  - `profile_for(agents: AgentProfiles, seat: int) -> AgentProfile | None`
  - `validate_profiles(agents: AgentProfiles, num_players: int) -> None`（越界/非法键抛 `ValueError`）
  - `legacy_to_profiles(ai_model: str | None, ai_model_speech: str | None = None, *, reflection_model: str | None = None, thinking: bool = False) -> AgentProfiles`
  - `merge_profiles(agents: AgentProfiles | None, legacy: AgentProfiles) -> AgentProfiles`（`"*"` 冲突抛 `ValueError`）
  - `to_agent_config(profile: AgentProfile, game_config: GameConfig) -> AgentConfig`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_profile.py`：

```python
"""AgentProfile（issue #56）：schema、查找、校验、旧字段折叠、到 AgentConfig 的映射。"""

import pytest
from pydantic import ValidationError

from app.agent.profile import (
    AgentProfile,
    legacy_to_profiles,
    merge_profiles,
    profile_for,
    to_agent_config,
    validate_profiles,
)
from app.engine.config import build_preset


def test_schema_defaults_and_forbid_unknown_keys() -> None:
    p = AgentProfile(model="ollama/a")
    assert p.name is None and p.model_speech is None and p.reflection_model is None
    assert p.thinking is False and p.temperature == 0.3
    with pytest.raises(ValidationError):
        AgentProfile(model="ollama/a", modle_speech="x")  # type: ignore[call-arg]  # 键名笔误
    with pytest.raises(ValidationError):
        AgentProfile(model="ollama/a", temperature=2.5)
    with pytest.raises(ValidationError):
        AgentProfile()  # type: ignore[call-arg]  # 缺 model


def test_profile_for_prefers_seat_then_star() -> None:
    star = AgentProfile(model="ollama/star")
    seat3 = AgentProfile(model="ollama/three")
    agents = {"*": star, "3": seat3}
    assert profile_for(agents, 3) is seat3
    assert profile_for(agents, 0) is star
    assert profile_for({"3": seat3}, 0) is None
    assert profile_for({}, 0) is None


def test_validate_profiles_keys() -> None:
    p = AgentProfile(model="m")
    validate_profiles({"*": p, "0": p, "8": p}, num_players=9)
    for bad in ("9", "-1", "a", "01"):
        with pytest.raises(ValueError, match="座位"):
            validate_profiles({bad: p}, num_players=9)


def test_legacy_to_profiles_and_merge() -> None:
    assert legacy_to_profiles(None) == {}
    legacy = legacy_to_profiles("ollama/a", "ollama/b", reflection_model="ollama/c", thinking=True)
    assert legacy == {
        "*": AgentProfile(
            model="ollama/a", model_speech="ollama/b", reflection_model="ollama/c", thinking=True
        )
    }
    seat0 = {"0": AgentProfile(model="ollama/z")}
    merged = merge_profiles(seat0, legacy)
    assert merged["0"].model == "ollama/z" and merged["*"].model == "ollama/a"
    assert merge_profiles(None, legacy) == legacy
    assert merge_profiles(seat0, {}) == seat0
    with pytest.raises(ValueError, match=r"agents\['\*'\]"):
        merge_profiles({"*": AgentProfile(model="ollama/x")}, legacy)


def test_to_agent_config_maps_fields_and_seed() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    p = AgentProfile(
        model="ollama/a",
        model_speech="ollama/b",
        reflection_model="ollama/c",
        thinking=True,
        temperature=0.7,
    )
    ac = to_agent_config(p, cfg)
    assert (ac.model, ac.model_speech, ac.reflection_model) == ("ollama/a", "ollama/b", "ollama/c")
    assert ac.thinking is True and ac.temperature == 0.7
    assert ac.agent_seed == 11
    assert to_agent_config(p, cfg.model_copy(update={"seed": None})).agent_seed == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_profile.py -q`
Expected: 收集期 `ModuleNotFoundError: No module named 'app.agent.profile'`

- [ ] **Step 3: 实现**

新建 `backend/app/agent/profile.py`：

```python
"""AgentProfile（issue #56）：每座位独立的内置 Agent 配置。

registry / api / cli 三个入口都只经本模块解析档案：查找（座位优先于 "*"）、
键校验、旧字段（ai_model 等）折叠、到 AgentConfig 的映射。本期只有模型路由一组字段；
人格 / 技能 / 记忆标识由各自 issue 增量添加，extra="forbid" 保证在此之前被拒绝而非静默忽略。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agent.agent_player import AgentConfig
from app.engine.config import GameConfig

STAR = "*"  # 默认档案键：未单独配置的空位


class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None  # 展示名（roster display_name）；缺省 Bot{seat}
    model: str
    model_speech: str | None = None  # 发言层模型（None=同 model；PRD §8.3 分层路由）
    reflection_model: str | None = None
    thinking: bool = False
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


AgentProfiles = dict[str, AgentProfile]


def profile_for(agents: AgentProfiles, seat: int) -> AgentProfile | None:
    """座位专属档案优先，其次 "*"；都没有 → None（该座位用 RandomBot）。"""
    return agents.get(str(seat)) or agents.get(STAR)


def validate_profiles(agents: AgentProfiles, num_players: int) -> None:
    """键只能是 "*" 或 0..num_players-1 的十进制座位号。"""
    for key in agents:
        if key == STAR:
            continue
        if not key.isdecimal() or str(int(key)) != key or not 0 <= int(key) < num_players:
            raise ValueError(f"agents 键 {key!r} 非法：须为 '*' 或 0..{num_players - 1} 的座位号")


def legacy_to_profiles(
    ai_model: str | None,
    ai_model_speech: str | None = None,
    *,
    reflection_model: str | None = None,
    thinking: bool = False,
) -> AgentProfiles:
    """旧入口（ai_model 等）等价于 "*" 默认档案；ai_model 为空 → 空映射（全 RandomBot）。"""
    if ai_model is None:
        return {}
    return {
        STAR: AgentProfile(
            model=ai_model,
            model_speech=ai_model_speech,
            reflection_model=reflection_model,
            thinking=thinking,
        )
    }


def merge_profiles(agents: AgentProfiles | None, legacy: AgentProfiles) -> AgentProfiles:
    """合并显式档案与旧字段折叠结果；两边都给了 "*" 视为冲突。"""
    agents = dict(agents or {})
    if STAR in agents and STAR in legacy:
        raise ValueError("ai_model 与 agents['*'] 不能同时指定")
    agents.update(legacy)
    return agents


def to_agent_config(profile: AgentProfile, game_config: GameConfig) -> AgentConfig:
    """agent_seed 仍取 GameConfig.seed（候选洗牌本已按座位区分），其余字段逐项映射。"""
    return AgentConfig(
        model=profile.model,
        model_speech=profile.model_speech,
        reflection_model=profile.reflection_model,
        thinking=profile.thinking,
        temperature=profile.temperature,
        agent_seed=game_config.seed if game_config.seed is not None else 0,
    )
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `uv run pytest tests/test_agent_profile.py -q`
Expected: 5 passed

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿（新模块尚无调用方）

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/profile.py backend/tests/test_agent_profile.py
git commit -m "feat(agent): AgentProfile 档案 schema、查找、校验、旧字段折叠与 AgentConfig 映射 (issue #56)"
```

---

### Task 2: registry / agent_player / lobby——按座位档案建端口与命名

**Files:**
- Modify: `backend/app/agent/agent_player.py`（`build_agent_port` 约 line 123-145）
- Modify: `backend/app/runtime/game_runner.py`（`GameLobby.fill_with_bots` 约 line 66-69）
- Modify: `backend/app/runtime/registry.py`（`GameHandle.__init__`、`GameRegistry.create`、`start`、`_build_agent_port`）
- Test: `backend/tests/test_registry.py`、`backend/tests/test_agent_integration.py`

**Interfaces:**
- Consumes: Task 1 全部。
- Produces:
  - `build_agent_port(seat: int, game_config: GameConfig, profile: AgentProfile) -> AgentPlayerPort`（旧多参数签名删除）
  - `GameLobby.fill_with_bots(name_for: Callable[[int], str] | None = None) -> None`
  - `GameHandle.agents: AgentProfiles`、`GameHandle.profile_for(seat) -> AgentProfile | None`（`ai_model` / `ai_model_speech` 属性删除）
  - `GameRegistry.create(config, *, allow_spectators, num_ai_players=None, agents=None, ai_model=None, ai_model_speech=None)`
  - `agent_port_factory` 签名 `(seat, handle)` 不变

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registry.py` 末尾：

```python
async def test_create_with_agents_resolves_per_seat_and_names_bots() -> None:
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    agents = {"0": AgentProfile(name="老张", model="ollama/a"), "2": AgentProfile(model="ollama/b")}
    handle = reg.create(cfg, allow_spectators=False, agents=agents)
    assert handle.profile_for(0) is agents["0"] and handle.profile_for(2) is agents["2"]
    assert handle.profile_for(1) is None
    # 有档案的座位由 agent 工厂建端口（此处注入桩，避免 litellm）
    reg._agent_port_factory = lambda seat, h: BotPlayerPort(state_provider=h.live_state)
    reg.start(handle, fill_with_bots=True)
    names = [e.display_name for e in handle.lobby.roster()]
    assert names[0] == "老张" and names[1] == "Bot1" and names[2] == "Bot2"  # 无 name 缺省 Bot{seat}
    assert handle.task is not None
    handle.task.cancel()


def test_create_legacy_ai_model_folds_to_star_and_conflict_raises() -> None:
    from app.agent.profile import AgentProfile

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(cfg, allow_spectators=False, ai_model="ollama/a", ai_model_speech="ollama/b")
    star = handle.profile_for(7)
    assert star is not None and star.model == "ollama/a" and star.model_speech == "ollama/b"
    with pytest.raises(ValueError, match="agents"):
        reg.create(
            cfg,
            allow_spectators=False,
            agents={"*": AgentProfile(model="x")},
            ai_model="ollama/a",
        )
    with pytest.raises(ValueError, match="座位"):
        reg.create(cfg, allow_spectators=False, agents={"9": AgentProfile(model="x")})


async def test_human_joined_seat_ignores_profile() -> None:
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort, HumanPlayerPort

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(cfg, allow_spectators=False, agents={"0": AgentProfile(model="x")})
    reg.join(handle, "Alice", "HUMAN")  # 占 0 号
    reg._agent_port_factory = lambda seat, h: BotPlayerPort(state_provider=h.live_state)
    reg.start(handle, fill_with_bots=True)
    assert isinstance(handle.ports[0], HumanPlayerPort)
    assert handle.lobby.roster()[0].display_name == "Alice"
    assert handle.task is not None
    handle.task.cancel()
```

追加到 `backend/tests/test_agent_integration.py` 末尾（该文件已 import `AgentConfig`、`AgentPlayerPort`、`GameHandle`、`GameRegistry`、`InMemoryEventStore`、`PlayerPort`、`ScriptedLLMClient`、`TIMEOUTS`、`build_preset`、`Phase`、`asyncio`；缺的按文件头风格补）：

```python
async def test_per_seat_profiles_reach_agent_config() -> None:
    """两座位不同档案 → 各自 AgentConfig.model 不同（经 profile_for + to_agent_config）。"""
    from app.agent.profile import AgentProfile, to_agent_config

    seen: dict[int, str] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        profile = handle.profile_for(seat)
        assert profile is not None
        cfg = to_agent_config(profile, handle.config)
        seen[seat] = cfg.model
        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=cfg,
            client=ScriptedLLMClient(_omniscient_script(handle, seat)),
        )

    registry = GameRegistry(InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(
        config,
        allow_spectators=False,
        agents={"0": AgentProfile(model="scripted-zero"), "*": AgentProfile(model="scripted")},
    )
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER
    assert seen[0] == "scripted-zero" and seen[1] == "scripted" and len(seen) == 9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_registry.py tests/test_agent_integration.py -q`
Expected: 新用例 FAIL（`create()` 无 `agents` 参数 / `GameHandle` 无 `profile_for`）

- [ ] **Step 3: 实现**

`app/agent/agent_player.py`——`build_agent_port` 整体替换为：

```python
def build_agent_port(seat: int, game_config: GameConfig, profile: AgentProfile) -> AgentPlayerPort:
    """registry / CLI 默认工厂：真实 LiteLLM 客户端 + 档案映射的 AgentConfig（issue #56）。"""
    from app.agent.llm_client import LiteLLMInstructorClient
    from app.agent.profile import to_agent_config

    return AgentPlayerPort(
        seat=seat,
        game_config=game_config,
        agent_config=to_agent_config(profile, game_config),
        client=LiteLLMInstructorClient(),
    )
```

文件头加 `if TYPE_CHECKING: from app.agent.profile import AgentProfile`（`profile.py` import 了本模块的 `AgentConfig`，运行期须避免循环 import；`from typing import TYPE_CHECKING`）。

`app/runtime/game_runner.py`——`GameLobby.fill_with_bots`：

```python
    def fill_with_bots(self, name_for: Callable[[int], str] | None = None) -> None:
        """填满空位；name_for(seat) 给出展示名（issue #56 档案名），缺省 Bot{seat}。"""
        while not self.is_full:
            seat = len(self._entries)
            name = name_for(seat) if name_for is not None else f"Bot{seat}"
            self._entries.append(RosterEntry(display_name=name, player_type="AGENT"))
```

（若文件尚未 import `Callable`，从 `collections.abc` 补。）

`app/runtime/registry.py`：
- import：`from app.agent.profile import AgentProfile, AgentProfiles, legacy_to_profiles, merge_profiles, profile_for, validate_profiles`（`profile.py` 不 import runtime，无循环）。
- `GameHandle.__init__(..., agents: AgentProfiles)`：删除 `ai_model` / `ai_model_speech` 参数与属性，改为 `self.agents = agents`；加方法：

```python
    def profile_for(self, seat: int) -> AgentProfile | None:
        return profile_for(self.agents, seat)
```

- `GameRegistry.create`：

```python
    def create(
        self,
        config: GameConfig,
        *,
        allow_spectators: bool,
        num_ai_players: int | None = None,
        agents: AgentProfiles | None = None,
        ai_model: str | None = None,
        ai_model_speech: str | None = None,
    ) -> GameHandle:
        # 旧入口 ai_model 折叠为 "*" 默认档案；与显式 agents["*"] 冲突 / 座位键非法 → ValueError（api 映射 400）
        resolved = merge_profiles(agents, legacy_to_profiles(ai_model, ai_model_speech))
        validate_profiles(resolved, config.num_players)
        game_id = f"g_{secrets.token_hex(4)}"
        handle = GameHandle(
            game_id,
            config,
            allow_spectators=allow_spectators,
            num_ai_players=num_ai_players,
            agents=resolved,
        )
        self._games[game_id] = handle
        return handle
```

- `start`：`handle.lobby.fill_with_bots()` 改为

```python
        if fill_with_bots:

            def _bot_name(seat: int) -> str:
                p = handle.profile_for(seat)
                return p.name if p is not None and p.name else f"Bot{seat}"

            handle.lobby.fill_with_bots(name_for=_bot_name)
```

空位建端口的分支改为：

```python
            if seat not in handle.ports:
                if handle.profile_for(seat) is None:
                    handle.ports[seat] = BotPlayerPort(state_provider=_state_of)
                else:
                    handle.ports[seat] = self._build_agent_port(seat, handle)
```

- `_build_agent_port`：

```python
        profile = handle.profile_for(seat)
        assert profile is not None
        return build_agent_port(seat, handle.config, profile)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_registry.py tests/test_agent_integration.py tests/test_acceptance_m25.py tests/test_api_lobby.py tests/test_api_play.py tests/test_api_ws.py -q`
Expected: 全部 PASS（`rest.py` 仍传旧 kwargs，暂不改）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿。注意 `tests/test_cli_play_watch.py::test_wire_game_threads_speech_and_reflection_models` 与 `app/cli/play.py` 仍调用旧签名 `build_agent_port(seat, config, ai_model, ...)`——**本任务先把 `play.py` 的调用改为** `build_agent_port(seat, config, legacy_to_profiles(ai_model, ai_model_speech, reflection_model=reflection_model, thinking=thinking)["*"])`（最小改动，Task 4 再整体替换为 `agents`），使 CLI 与该测试保持通过。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/agent_player.py backend/app/runtime/game_runner.py backend/app/runtime/registry.py backend/app/cli/play.py backend/tests/test_registry.py backend/tests/test_agent_integration.py
git commit -m "feat(runtime): GameHandle 持每座位档案；按档案建端口与命名；旧 ai_model 折叠为 '*' (issue #56)"
```

---

### Task 3: API——`agents` 建局字段、回显与错误码

**Files:**
- Modify: `backend/app/schemas/games.py`（`CreateGameRequest` / `CreateGameResponse`）
- Modify: `backend/app/api/rest.py`（`create_game_endpoint` 约 line 49-75）
- Test: `backend/tests/test_api_lobby.py`

**Interfaces:**
- Consumes: Task 1 `AgentProfile`；Task 2 `GameRegistry.create(agents=…)`、`GameHandle.agents`。
- Produces: `CreateGameRequest.agents: dict[str, AgentProfile] = {}`；`CreateGameResponse.agents: dict[str, AgentProfile]`（回显解析后映射）；`ValueError` → 400。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_api_lobby.py` 末尾：

```python
def test_create_with_agents_echoes_resolved_profiles(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "agents": {"0": {"name": "老张", "model": "ollama/a"}, "*": {"model": "ollama/b"}},
        },
    )
    assert r.status_code == 200, r.text
    agents = r.json()["agents"]
    assert agents["0"]["name"] == "老张" and agents["0"]["model"] == "ollama/a"
    assert agents["*"]["model"] == "ollama/b" and agents["*"]["temperature"] == 0.3


def test_create_legacy_ai_model_echoes_star(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "ai_model": "ollama/a", "ai_model_speech": "ollama/b"},
    )
    assert r.status_code == 200
    assert r.json()["agents"] == {
        "*": {
            "name": None,
            "model": "ollama/a",
            "model_speech": "ollama/b",
            "reflection_model": None,
            "thinking": False,
            "temperature": 0.3,
        }
    }
    r2 = client.post("/api/v1/games", json={"preset": "std_9_kill_side"})
    assert r2.status_code == 200 and r2.json()["agents"] == {}


def test_create_agents_errors(client: TestClient) -> None:
    # 新旧冲突 → 400
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "ai_model": "x", "agents": {"*": {"model": "y"}}},
    )
    assert r.status_code == 400 and "agents" in r.json()["detail"]
    # 座位键越界 → 400
    r = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "agents": {"9": {"model": "y"}}}
    )
    assert r.status_code == 400 and "座位" in r.json()["detail"]
    # 档案未知键 → 422（请求体校验）
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"0": {"model": "y", "modle_speech": "z"}}},
    )
    assert r.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api_lobby.py -q`
Expected: 三个新用例 FAIL（响应无 `agents` 键 / 冲突未报 400）

- [ ] **Step 3: 实现**

`app/schemas/games.py`——import `from app.agent.profile import AgentProfile`；`CreateGameRequest` 加字段：

```python
    agents: dict[str, AgentProfile] = Field(default_factory=dict)  # 每座位档案，键=座位号或 "*"（issue #56）
```

`CreateGameResponse` 加：

```python
    agents: dict[str, AgentProfile]  # 解析后的档案映射（含旧 ai_model 折叠为 "*"）
```

`app/api/rest.py` `create_game_endpoint`：`games.create(...)` 调用改为

```python
    try:
        handle = games.create(
            config,
            allow_spectators=req.allow_spectators,
            num_ai_players=req.num_ai_players,
            agents=req.agents,
            ai_model=req.ai_model,
            ai_model_speech=req.ai_model_speech,
        )
    except ValueError as exc:
        raise ToolCallError(f"agents 非法：{exc}") from exc
```

并在响应加 `agents=handle.agents`。（先确认本文件里 `ToolCallError` 映射为 400 的既有约定——`preset/config_override 非法` 即走这条。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_api_lobby.py tests/test_api_play.py tests/test_api_ws.py tests/test_acceptance_m25.py tests/test_agent_integration.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/games.py backend/app/api/rest.py backend/tests/test_api_lobby.py
git commit -m "feat(api): 建局 agents 每座位档案字段与回显；冲突/越界 400 (issue #56)"
```

---

### Task 4: CLI——`--agents` YAML、`_wire_game(agents=)`、档案表、Makefile、README、PRD

**Files:**
- Modify: `backend/pyproject.toml`（`pyyaml` 核心依赖、`types-PyYAML` dev）
- Modify: `backend/app/cli/play.py`（`_wire_game`、`run_watch`、`main`；新增 `load_agent_profiles`）
- Modify: `backend/app/cli/play_human.py`（`run_play` 签名）
- Modify: `backend/app/cli/render.py`（`render_agent_roster`）
- Modify: `Makefile`、`README.md`、`docs/specs/requirements.md`（§5.2）
- Test: `backend/tests/test_cli_play_watch.py`、`backend/tests/test_cli_render.py`、`backend/tests/test_cli_play_human.py`（若其调用 `run_play(ai_model=…)` 需同步）

**Interfaces:**
- Consumes: Task 1 全部；Task 2 `build_agent_port(seat, config, profile)`。
- Produces:
  - `app.cli.play.load_agent_profiles(path: str) -> AgentProfiles`（错误 → `argparse.ArgumentTypeError`）
  - `_wire_game(config, *, human_seat=None, agents: AgentProfiles | None = None)`（旧 `ai_model` 等参数删除）
  - `run_watch(config, *, view, delay, step, agents=None, read_line=…)`、`run_play(config, *, seat, agents=None, read_line=…, on_wired=None)`
  - `app.cli.render.render_agent_roster(agents: AgentProfiles, num_players: int, human_seat: int | None) -> str`

- [ ] **Step 1: 加依赖**

Run（`backend/`）: `uv add pyyaml && uv add --group dev types-PyYAML`
Expected: `pyproject.toml` 的 `dependencies` 含 `pyyaml>=…`，dev 组含 `types-PyYAML>=…`；`uv.lock` 更新。

- [ ] **Step 2: 写失败测试**

`backend/tests/test_cli_play_watch.py`：把 `test_wire_game_threads_speech_and_reflection_models` 整体替换为下面两例，并追加其余：

```python
def test_wire_game_threads_profiles_per_seat() -> None:
    """每座位档案落到各自 AgentConfig；无档案座位为 BotPlayerPort；档案名进 roster。"""
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.runtime.player_port import BotPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    agents = {
        "0": AgentProfile(name="老张", model="ollama/a", model_speech="ollama/b", thinking=True),
        "2": AgentProfile(model="ollama/c", reflection_model="ollama/d", temperature=0.9),
    }
    runner, _conns, ports = _wire_game(config, agents=agents)
    p0, p2 = ports[0], ports[2]
    assert isinstance(p0, AgentPlayerPort) and isinstance(p2, AgentPlayerPort)
    assert (p0._cfg.model, p0._cfg.model_speech, p0._cfg.thinking) == ("ollama/a", "ollama/b", True)
    assert (p2._cfg.model, p2._cfg.reflection_model, p2._cfg.temperature) == ("ollama/c", "ollama/d", 0.9)
    assert isinstance(ports[1], BotPlayerPort)
    assert runner._roster[0].display_name == "老张" and runner._roster[1].display_name == "P1"
    # 任一档案 thinking → 放宽超时
    from app.cli.play import _THINK_TIMEOUTS

    assert runner._timeouts == _THINK_TIMEOUTS


def test_wire_game_star_profile_and_human_seat() -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.cli.play import _CLI_TIMEOUTS
    from app.runtime.player_port import HumanPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    runner, _c, ports = _wire_game(config, human_seat=4, agents={"*": AgentProfile(model="ollama/z")})
    assert isinstance(ports[4], HumanPlayerPort)
    assert all(isinstance(ports[s], AgentPlayerPort) for s in range(9) if s != 4)
    assert runner._timeouts == _CLI_TIMEOUTS


def test_load_agent_profiles_yaml_and_errors(tmp_path) -> None:
    from app.cli.play import load_agent_profiles

    good = tmp_path / "agents.yaml"
    good.write_text(
        'seats:\n  "0": {name: 老张, model: ollama/a, thinking: true}\n  "*": {model: ollama/b}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(good))
    assert agents["0"].name == "老张" and agents["0"].thinking is True
    assert agents["*"].model == "ollama/b"

    bad_key = tmp_path / "bad.yaml"
    bad_key.write_text('seats:\n  "0": {model: ollama/a, modle_speech: x}\n', encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError, match="bad.yaml"):
        load_agent_profiles(str(bad_key))

    no_seats = tmp_path / "noseats.yaml"
    no_seats.write_text("agents: {}\n", encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError, match="seats"):
        load_agent_profiles(str(no_seats))

    with pytest.raises(argparse.ArgumentTypeError):
        load_agent_profiles(str(tmp_path / "missing.yaml"))
```

追加到 `backend/tests/test_cli_render.py` 末尾：

```python
def test_render_agent_roster() -> None:
    from app.agent.profile import AgentProfile
    from app.cli.render import render_agent_roster

    agents = {
        "0": AgentProfile(name="老张", model="ollama/a", model_speech="ollama/b", thinking=True),
        "*": AgentProfile(model="ollama/z", temperature=0.7),
    }
    out = render_agent_roster(agents, num_players=3, human_seat=2)
    lines = out.splitlines()
    assert len(lines) == 3
    assert "0号" in lines[0] and "老张" in lines[0] and "ollama/a" in lines[0]
    assert "ollama/b" in lines[0] and "thinking" in lines[0]
    assert "1号" in lines[1] and "ollama/z" in lines[1] and "T=0.7" in lines[1]
    assert "2号" in lines[2] and "真人" in lines[2]
    bots = render_agent_roster({}, num_players=2, human_seat=None)
    assert "随机" in bots and bots.count("\n") == 1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_play_watch.py tests/test_cli_render.py -q`
Expected: 新用例 FAIL（`_wire_game` 无 `agents` 参数；`load_agent_profiles` / `render_agent_roster` 不存在）

- [ ] **Step 4: 实现**

`app/cli/render.py` 末尾加：

```python
def render_agent_roster(
    agents: AgentProfiles, num_players: int, human_seat: int | None
) -> str:
    """开局座位档案表（GM 视角，仅本地终端）：一行一座位。"""
    lines: list[str] = []
    for seat in range(num_players):
        if seat == human_seat:
            lines.append(f"{seat}号 你（真人）")
            continue
        p = profile_for(agents, seat)
        if p is None:
            lines.append(f"{seat}号 Bot（随机）")
            continue
        parts = [p.name or f"Bot{seat}", p.model]
        if p.model_speech:
            parts.append(f"发言 {p.model_speech}")
        if p.reflection_model:
            parts.append(f"反思 {p.reflection_model}")
        if p.thinking:
            parts.append("thinking")
        parts.append(f"T={p.temperature}")
        lines.append(f"{seat}号 " + " · ".join(parts))
    return "\n".join(lines)
```

（import：`from app.agent.profile import AgentProfiles, profile_for`——`render.py` 已 import engine 层，`profile.py` 只依赖 agent_player/engine，无循环。）

`app/cli/play.py`：
- import：`import yaml`、`from pydantic import ValidationError`、`from app.agent.profile import AgentProfile, AgentProfiles, legacy_to_profiles, merge_profiles, profile_for, validate_profiles`、`from app.cli.render import render_agent_roster, render_event`。
- 新增：

```python
def load_agent_profiles(path: str) -> AgentProfiles:
    """--agents 档案文件：YAML（JSON 亦可），顶层 seats 映射；任何错误 → 参数错误（含文件名）。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise argparse.ArgumentTypeError(f"{path}: 无法读取档案文件：{exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("seats"), dict):
        raise argparse.ArgumentTypeError(f"{path}: 顶层须为 seats 映射（键为座位号或 '*'）")
    agents: AgentProfiles = {}
    for key, body in raw["seats"].items():
        try:
            agents[str(key)] = AgentProfile.model_validate(body)
        except ValidationError as exc:
            raise argparse.ArgumentTypeError(f"{path}: seats[{key!r}] 非法：{exc}") from exc
    return agents
```

- `_wire_game`：

```python
def _wire_game(
    config: GameConfig,
    *,
    human_seat: int | None = None,
    agents: AgentProfiles | None = None,
) -> tuple[GameRunner, ConnectionManager, dict[int, PlayerPort]]:
    """装配 store/roster/ports/conns/runner（不订阅、不 run）。agents 缺省=全随机 bot。"""
    from app.store.event_store import InMemoryEventStore

    agents = agents or {}
    n = config.num_players
    holder: dict[str, GameRunner] = {}

    def state_of() -> GameState:
        return holder["r"].state

    ports: dict[int, PlayerPort] = {}
    names: list[str] = []
    for seat in range(n):
        profile = None if seat == human_seat else profile_for(agents, seat)
        if seat == human_seat:
            ports[seat] = HumanPlayerPort()
        elif profile is not None:
            from app.agent.agent_player import build_agent_port

            ports[seat] = build_agent_port(seat, config, profile)
        else:
            ports[seat] = BotPlayerPort(state_provider=state_of)
        names.append(profile.name if profile is not None and profile.name else f"P{seat}")

    roster = [
        RosterEntry(display_name=names[i], player_type=("HUMAN" if i == human_seat else "AGENT"))
        for i in range(n)
    ]
    any_thinking = any(p.thinking for p in agents.values())
    conns = ConnectionManager(state_provider=state_of)
    runner = GameRunner(
        store=InMemoryEventStore(),
        config=config,
        game_id="cli",
        roster=roster,
        ports=ports,
        connections=conns,
        # 思考模式单次决策可达数分钟，放宽窗口避免被超时代打
        timeouts=_THINK_TIMEOUTS if any_thinking else _CLI_TIMEOUTS,
    )
    holder["r"] = runner
    return runner, conns, ports
```

- `run_watch(config, *, view, delay, step, agents: AgentProfiles | None = None, read_line=default_read_line)`：删除 `ai_model` 等四个参数，`_wire_game(config, agents=agents)`；`conns.subscribe` 之前 `print(render_agent_roster(agents or {}, config.num_players, None))`。
- `main`：加 `parser.add_argument("--agents", type=load_agent_profiles, default=None, help="每座位 Agent 档案 YAML（seats: {座位号|'*': {model, ...}}）")`；解析后：

```python
    legacy = legacy_to_profiles(
        args.ai_model,
        args.ai_model_speech,
        reflection_model=args.reflection_model,
        thinking=args.thinking,
    )
    try:
        agents = merge_profiles(args.agents, legacy)
        validate_profiles(agents, config.num_players)
    except ValueError as exc:
        parser.error(str(exc))
```

`run_watch(...)` / `run_play(...)` 的调用改为传 `agents=agents`（删除四个旧 kwargs）。

`app/cli/play_human.py` `run_play`：签名改为 `(config, *, seat, agents: AgentProfiles | None = None, read_line=..., on_wired=None)`，`_wire_game(config, human_seat=seat, agents=agents)`；在 `conns.subscribe(seat, narrate)` 之前 `print(render_agent_roster(agents or {}, config.num_players, seat))`（import `render_agent_roster`、`AgentProfiles`）。`tests/test_cli_play_human.py` 若调用 `run_play(..., ai_model=…)` 同步改为 `agents=`（先 grep 确认）。

`Makefile`：变量块加 `AGENTS ?=     # 每座位 Agent 档案 YAML（seats: {座位号|'*': {model,...}}）`；`_AIFLAGS` 加一行 `$(if $(AGENTS),--agents $(AGENTS),)`；`watch`/`play` help 文案补 `AGENTS=`。

`README.md`「终端对局」示例块加：

```bash
make watch AGENTS=agents.yaml            # 每座位独立模型/温度/thinking（见下方样例）
```

其后加一小节「每座位 Agent 档案」含 YAML 样例（同规格 §3.3）与查找规则一句话（座位优先于 `*`，无匹配用随机 bot；`--ai-model` 等价于 `*`）。

`docs/specs/requirements.md` §5.2 建局请求体说明处补：`agents: {"<seat>"|"*": AgentProfile}`——每座位内置 Agent 档案（model / model_speech / reflection_model / thinking / temperature / name）；座位优先于 `*`；`ai_model` 等价于 `agents["*"]`，二者同时给出 → 400。

- [ ] **Step 5: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_cli_play_watch.py tests/test_cli_render.py tests/test_cli_play_human.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全量（含 E2E）全绿；lint/type 全过

- [ ] **Step 6: 真机看一眼**

Run（`backend/`）：

```bash
printf 'seats:\n  "0": {name: 老张, model: ollama/a}\n  "*": {model: ollama/b, temperature: 0.7}\n' > /tmp/agents-demo.yaml
uv run python -m app.cli.play --preset std_9_kill_side --seed 3 --view gm --delay 0 --no-color --agents /tmp/agents-demo.yaml 2>&1 | head -12
```

Expected: 前 9 行为档案表（`0号 老张 · ollama/a · T=0.3`、`1号 Bot1 · ollama/b · T=0.7` …）；随后进程会因 `ollama/a` 不可达而由 runner 超时代打或报错——**只看档案表**，用 `head` 截断即可。再跑一次不带 `--agents`，确认前两行仍是 `0号 Bot（随机）`、`1号 Bot（随机）`。

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/cli/ backend/tests/test_cli_play_watch.py backend/tests/test_cli_render.py backend/tests/test_cli_play_human.py Makefile README.md docs/specs/requirements.md
git commit -m "feat(cli): --agents 每座位档案 YAML、开局档案表；Makefile/README/PRD 同步 (issue #56)"
```

---

## Self-Review

- **Spec 覆盖**：§2 schema/查找/校验/折叠/映射→T1；§3.1 registry/lobby→T2；§3.2 `build_agent_port`→T2；§3.3 CLI/渲染/Makefile→T4；§3.4 API→T3；§3.5 依赖→T4 Step 1；§4 文档→T4；§5 测试逐条落在 T1–T4；§6 不在范围无任务。
- **占位符扫描**：无 TBD/TODO；T4 Step 6 的 `head` 截断说明是明确执行指令。
- **类型一致性**：`AgentProfile` 字段、`AgentProfiles`、`profile_for(agents, seat)`、`validate_profiles(agents, num_players)`、`legacy_to_profiles(ai_model, ai_model_speech, *, reflection_model, thinking)`、`merge_profiles(agents, legacy)`、`to_agent_config(profile, game_config)`、`build_agent_port(seat, game_config, profile)`、`fill_with_bots(name_for=)`、`GameHandle.profile_for`、`_wire_game(config, *, human_seat, agents)`、`render_agent_roster(agents, num_players, human_seat)` 在各任务间一致。
- **循环 import**：`profile.py` → `agent_player.AgentConfig`；`agent_player.build_agent_port` 运行期内 import `profile.to_agent_config`、类型注解经 `TYPE_CHECKING`——已在 T2 说明。
- **过渡态**：T2 先把 `play.py` 的旧调用改为经 `legacy_to_profiles(...)["*"]`，保证 T2/T3 结束时全量测试仍绿；T4 再整体替换。
