# M2.5 里程碑验收（issue #32）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 锁定 M2 里程碑验收判据——为 4 个真实缺口补测（LLM Agent 经 HTTP+WS 完整对局、instructor 校验重试、活 WS 隔离矩阵、真实模型 token bench），补一处 `create_app` DI 钩子，写 README API 快速开始；既有已覆盖判据以验收矩阵引用。

**Architecture:** `create_app` 增可选 `agent_port_factory` 透传给 `GameRegistry`（默认 None，行为不变），使全 AgentPlayer 局能经真实 ASGI app + 脚本 mock LLM 零网络跑通。补测复用既有 TestClient/WS helper 与 `tests/llm_helpers.py`。真实模型 bench 经 env 门控（`AGENTHOWL_SMOKE_MODEL`）+ `smoke` 标记，默认 skip。

**Tech Stack:** Python 3.11+，FastAPI TestClient（httpx），Pydantic v2，pytest（asyncio_mode=auto），litellm/instructor（bench 用真实调用）。

**规格:** `docs/superpowers/specs/2026-07-17-m25-acceptance-design.md`（本计划唯一裁决依据）

## Global Constraints

- 分支 `feat/m25-acceptance`（已建，规格已提交 82a0f17）；工作目录 `backend/`
- 质量门（每个任务收尾都跑）：`uv run pytest -q`（全量约 140s，Bash timeout 设 360000）、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`
- 注释/docstring 中文；标识符/API 英文；ruff line-length 100
- **不改引擎**；`create_app` 新参数默认 None，既有全部测试语义不变
- 隔离仍是 `build_observation`/`visible_events` 单一过滤点；补测只校验不新增过滤逻辑
- 全 AgentPlayer 经 API 的测试用脚本 mock LLM，**零网络**；真实模型仅 env 门控 bench（默认 skip，不入 CI）
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## 现有 helper（复用，勿重造）

- `tests/test_api_play.py`：`_auth(token)`、`_start_ai_game(client, seed)`、`_wait_done(client, gid, timeout=30)`、`_to_tool_call(action)`
- `tests/llm_helpers.py`：`ScriptedLLMClient(script)`（记录 `.calls`）、`action_to_decision(action, response_model)`
- `tests/test_agent_integration.py`：`_omniscient_script(handle, seat)`、`factory(seat, handle)->PlayerPort` 范式（脚本工厂读 `handle.runner.state` + `RandomBot.choose_action` + `action_to_decision`）
- `tests/test_agent_smoke.py`：env 门控范式（`SMOKE_MODEL`、`_ollama_reachable()`、`pytestmark` skipif）
- `app/main.py::create_app(*, store=None, timeouts=None, data_dir=None)`；`GameRegistry(store, timeouts=None, agent_port_factory=None)`

---

### Task 1: `create_app` 加 `agent_port_factory` + 全 AgentPlayer 经 HTTP+WS 跑到终局（判据 1）

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_acceptance_m25.py`

**Interfaces:**
- Consumes: `GameRegistry(store, timeouts, agent_port_factory=...)`（Task 7/#31 已支持）；`AgentPlayerPort`、`AgentConfig`；`ScriptedLLMClient`、`action_to_decision`；`RandomBot`
- Produces（判据 6 的 Task 3 复用同文件）:
  - `create_app(*, store=None, timeouts=None, data_dir=None, agent_port_factory=None) -> FastAPI`
  - `tests/test_acceptance_m25.py` 内 helper `_scripted_agent_factory() -> Callable[[int, GameHandle], PlayerPort]`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_acceptance_m25.py`：

```python
"""M2.5 验收补测（issue #32）：全 AgentPlayer 经 HTTP+WS 跑局、活 WS 隔离矩阵。

脚本客户端"全知"取 runner state 只为产出合法决策（测试域白盒）；
被测路径（ASGI app → registry → AgentPlayerPort → runner）本身仍只见 observation。
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.memory import ReflectionResult
from app.cli.bot import RandomBot
from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import PlayerPort
from app.runtime.registry import GameHandle
from app.store.event_store import InMemoryEventStore
from tests.llm_helpers import ScriptedLLMClient, action_to_decision
from tests.test_api_play import _auth, _wait_done


def _scripted_agent_factory():
    """registry agent_port_factory：每个 AI 座配 AgentPlayerPort + 全知脚本客户端。"""

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
            if rm is ReflectionResult:
                return ReflectionResult(summary="(scripted reflect)", qa=[])
            assert handle.runner is not None
            action = RandomBot.choose_action(handle.runner.state, seat)
            return action_to_decision(action, rm)

        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=AgentConfig(model="scripted", agent_seed=7),
            client=ScriptedLLMClient(script),
        )

    return factory


@pytest.fixture()
def agent_client() -> Iterator[TestClient]:
    app = create_app(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0),
        agent_port_factory=_scripted_agent_factory(),
    )
    with TestClient(app) as c:
        yield c


def test_all_agentplayer_game_via_http_ws(agent_client: TestClient) -> None:
    """判据 1：全 AgentPlayer（LLM 端口，mock 客户端）经 ASGI app + WS 跑到 GAME_OVER。"""
    created = agent_client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "config_override": {"seed": 3},
            "ai_model": "scripted",
        },
    ).json()
    gid = created["game_id"]
    r = agent_client.post(
        f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"])
    )
    assert r.status_code == 200 and r.json()["num_players"] == 9

    frames: list[dict[str, Any]] = []
    with agent_client.websocket_connect(
        f"/api/v1/ws?token={created['spectator_token']}"
    ) as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "game_over":
                break
    assert frames[0]["type"] == "game_event" and frames[0]["event"]["type"] == "GAME_CREATED"

    # 每个座位确为 AgentPlayerPort（DI 钩子生效，非 RandomBot 填充）
    handle = agent_client.app.state.games.get(gid)  # type: ignore[attr-defined]
    assert handle.ports and all(
        isinstance(p, AgentPlayerPort) for p in handle.ports.values()
    )
    # replay 终局一致
    replay = agent_client.get(
        f"/api/v1/games/{gid}/replay", headers=_auth(created["spectator_token"])
    ).json()
    assert replay[-1]["type"] == "GAME_OVER"
    _wait_done(agent_client, gid)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_acceptance_m25.py -q`
Expected: FAIL —— `create_app()` 不接受 `agent_port_factory`（TypeError）

- [ ] **Step 3: 实现 `create_app` 钩子**

`app/main.py`：`create_app` 签名与 registry 构造增 `agent_port_factory`：

```python
from collections.abc import Callable  # 顶部 import 区

from app.runtime.player_port import NotYourTurnError, PlayerPort  # 扩充既有 import

def create_app(
    *,
    store: EventStore | None = None,
    timeouts: RunnerTimeouts | None = None,
    data_dir: Path | None = None,
    agent_port_factory: Callable[[int, "GameHandle"], PlayerPort] | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentHowl API", version="0.1.0")
    app.state.games = GameRegistry(
        store=store or JsonFileEventStore(data_dir or Path("data/games")),
        timeouts=timeouts,
        agent_port_factory=agent_port_factory,
    )
    ...
```

`GameHandle` 类型仅用于注解，避免运行时循环导入——用 `TYPE_CHECKING`：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.runtime.registry import GameHandle
```

（`Callable[[int, "GameHandle"], PlayerPort]` 用前向字符串引用；`PlayerPort` 已从 player_port 实 import。）

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `uv run pytest tests/test_acceptance_m25.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全部 PASS（既有 create_app 调用不传新参，默认 None，语义不变）
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_acceptance_m25.py
git commit -m "feat(api): create_app 注入 agent_port_factory——全 AgentPlayer 经 HTTP+WS 验收 (issue #32)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: instructor 校验失败→重试恢复（判据 5）

弱模型（Ollama）常产出不合 schema 的 JSON，`LiteLLMInstructorClient(max_retries=2)` 靠 instructor 校验失败后追加纠错消息重试。补测在 `litellm.acompletion` 边界打桩，首次返回校验不通过、二次合法，断言恢复。

**Files:**
- Modify: `backend/tests/test_agent_llm_client.py`

**Interfaces:**
- Consumes: `LiteLLMInstructorClient`；`app.agent.decisions.SpeechDecision`；`litellm`

- [ ] **Step 1: 写失败测试（主路径）**

在 `tests/test_agent_llm_client.py` 末尾追加：

```python
async def test_instructor_retries_on_invalid_then_valid(monkeypatch) -> None:
    """判据 5：底层模型首次返回不合 schema 的 JSON，instructor 校验失败后重试至合法。"""
    import litellm

    from app.agent.decisions import SpeechDecision

    calls = {"n": 0}

    def _resp(content: str):
        # 构造 litellm ModelResponse（OpenAI 形状）；instructor JSON mode 从 message.content 解析
        return litellm.ModelResponse(
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            model="scripted",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    async def fake_acompletion(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # 缺必填字段 content → SpeechDecision 校验失败，触发 instructor 重试
            return _resp('{"reasoning": "先胡说"}')
        return _resp('{"reasoning": "ok", "content": "大家好"}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    client = LiteLLMInstructorClient(max_retries=2)
    result = await client.complete_structured(
        system_prompt="s",
        user_prompt="u",
        response_model=SpeechDecision,
        model="scripted",
    )
    assert isinstance(result, SpeechDecision) and result.content == "大家好"
    assert calls["n"] >= 2  # 首次校验失败确实触发了重试
```

注：`_pick_mode("scripted")` 会因 `litellm.supports_function_calling("scripted")` 抛错/返回 False 落 JSON mode（正是本测试所需）。`monkeypatch.setattr(litellm, "acompletion", ...)` 须在构造 `LiteLLMInstructorClient` 之前生效——`_client_for` 惰性在首个 `complete_structured` 调用时才 `instructor.from_litellm(litellm.acompletion, ...)`，此时读到的已是打桩函数。

- [ ] **Step 2: 跑测试**

Run: `uv run pytest tests/test_agent_llm_client.py::test_instructor_retries_on_invalid_then_valid -q`
Expected: PASS，`calls["n"] >= 2`。

**降级路径（仅当主路径因 instructor 版本内部机制不兼容——即测试 error 而非 assert 失败——才改用）**：删除上面的边界打桩测试，改为断言 `max_retries` 确被透传给 instructor 客户端：

```python
async def test_instructor_client_passes_max_retries(monkeypatch) -> None:
    """判据 5（降级）：确认 max_retries 透传至 instructor.create（边界打桩不兼容时的等价保证）。"""
    from app.agent.decisions import SpeechDecision

    seen: dict[str, object] = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SpeechDecision(reasoning="ok", content="hi")

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeInstructor:
        chat = _FakeChat()

    client = LiteLLMInstructorClient(max_retries=2)
    monkeypatch.setattr(client, "_client_for", lambda mode: _FakeInstructor())
    result = await client.complete_structured(
        system_prompt="s", user_prompt="u", response_model=SpeechDecision, model="scripted"
    )
    assert isinstance(result, SpeechDecision)
    assert seen.get("max_retries") == 2
```

实现者二选一：优先跑通主路径；若主路径在本机 instructor 版本下 error，则删主路径、留降级路径，并在 commit body 注明"instructer 版本边界打桩不兼容，采用 max_retries 透传断言"。规格接受任一。

- [ ] **Step 3: 全量回归 + 质量门**

Run: `uv run pytest -q`（timeout 360000）→ 全部 PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净
（注：新测试用 `monkeypatch` fixture，`async def` 无类型注解参数在 tests/ 不受 `mypy app` 门禁约束。）

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_llm_client.py
git commit -m "test(agent): instructor 校验失败→重试恢复（判据 5，issue #32）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 活 WS 流上的狼/民/观战隔离矩阵（判据 6）

REST `/events` 隔离矩阵已由 `test_api_e2e::test_acceptance_isolation_matrix_via_api` 覆盖；本任务在**活 WS 流**上补齐狼座/民座对照（既有 WS 隔离测试仅覆观战 PUBLIC-only）。用 `from_seq=1` 补发全量可见历史（与实时广播同一 `visible_events` 过滤点），确定性无竞态。

**Files:**
- Modify: `backend/tests/test_acceptance_m25.py`

**Interfaces:**
- Consumes: Task 1 建立的文件与 import；`_start_ai_game`、`_wait_done`、`_auth`；`app.api.deps.TokenInfo`；`app.engine.config.Faction`

- [ ] **Step 1: 写失败测试**

在 `tests/test_acceptance_m25.py` 追加（复用文件顶部已有 import；另需在文件顶部 import 区补 `from tests.test_api_play import _start_ai_game`）：

```python
def _drain_ws_events(client: TestClient, gid: str, token: str) -> list[dict[str, Any]]:
    """从 from_seq=1 连 WS，收集全部 game_event 帧直至 game_over。"""
    out: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={token}&from_seq=1") as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                out.append(frame["event"])
            if frame["type"] == "game_over":
                break
    return out


def test_ws_isolation_matrix_wolf_villager_spectator(client: TestClient) -> None:
    """判据 6：活 WS 流上——狼见 WOLVES、民不见；任何非 GM 流永不见 GM_ONLY。"""
    from app.api.deps import TokenInfo
    from app.engine.config import Faction

    gid, created = _start_ai_game(client, seed=3)
    _wait_done(client, gid)

    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    tokens = client.app.state.tokens  # type: ignore[attr-defined]
    state = handle.runner.state
    wolf_seat = next(p.seat for p in state.players if p.faction == Faction.WOLF)
    villager_seat = next(p.seat for p in state.players if p.faction != Faction.WOLF)

    wolf_tok = tokens.issue(TokenInfo(game_id=gid, seat=wolf_seat, kind="PLAYER"))
    vill_tok = tokens.issue(TokenInfo(game_id=gid, seat=villager_seat, kind="PLAYER"))
    spec_tok = created["spectator_token"]

    wolf_ev = _drain_ws_events(client, gid, wolf_tok)
    vill_ev = _drain_ws_events(client, gid, vill_tok)
    spec_ev = _drain_ws_events(client, gid, spec_tok)

    # 狼座 WS 流含 WOLVES 事件；民座与观战流均无
    assert any(e["visibility"] == "WOLVES" for e in wolf_ev)
    assert not any(e["visibility"] == "WOLVES" for e in vill_ev)
    assert not any(e["visibility"] == "WOLVES" for e in spec_ev)
    # 任何非 GM 流永不含 GM_ONLY
    for stream in (wolf_ev, vill_ev, spec_ev):
        assert not any(e["visibility"] == "GM_ONLY" for e in stream)
    # ROLE_SELF 只能是本座
    assert all(e["actor_seat"] == wolf_seat for e in wolf_ev if e["visibility"] == "ROLE_SELF")
    assert all(
        e["actor_seat"] == villager_seat for e in vill_ev if e["visibility"] == "ROLE_SELF"
    )
    # 观战流纯 PUBLIC
    assert all(e["visibility"] == "PUBLIC" for e in spec_ev)
```

注：本文件的 `client` fixture 需为**普通** RandomBot fixture（非 Task 1 的 `agent_client`）。在文件顶部补一个标准 `client` fixture（照抄 `test_api_play.py` 的 fixture：`create_app(store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0))`，不传 `agent_port_factory`）。若 seed=3 未在任一 WOLVES 事件前的路径上产生 WOLVES 事件（狼刀恒发生，`WOLF_KILL_PROPOSED` 为 WOLVES 可见），断言应恒成立；如异常，改用 `_start_ai_game` 的其它 seed 并核对。

- [ ] **Step 2: 跑测试确认失败→实现→通过**

先跑确认新测试存在且（若 fixture 缺失）报错，补齐标准 `client` fixture 后：
Run: `uv run pytest tests/test_acceptance_m25.py -q` → 全部 PASS
Run: `uv run pytest -q`（timeout 360000）→ PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 3: Commit**

```bash
git add tests/test_acceptance_m25.py
git commit -m "test(api): 活 WS 流狼/民/观战隔离矩阵（判据 6，issue #32）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 单局真实模型 token bench（判据 7，env 门控）

真实 Ollama 跑一局，经 LiteLLM `CustomLogger` 异步成功钩子累计 prompt+completion token，打印总量。默认 skip（`smoke` 标记 + `AGENTHOWL_SMOKE_MODEL` 未设/端点不通即跳），不入 CI。只测量不强制预算。

**Files:**
- Create: `backend/tests/test_agent_bench.py`

**Interfaces:**
- Consumes: `GameRegistry`、`build_agent_port`（真实 `LiteLLMInstructorClient` 路径）、`RunnerTimeouts`、`InMemoryEventStore`；`litellm.integrations.custom_logger.CustomLogger`

- [ ] **Step 1: 写 bench（默认自跳过）**

`backend/tests/test_agent_bench.py`：

```python
"""单局真实模型 token bench（issue #32 判据 7）。默认跳过。

本地跑法：
    ollama pull llama3.1 && ollama serve &
    AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke tests/test_agent_bench.py -q -s

说明：本地 Ollama 无定价，completion_cost≈0——bench 报 token 数（有意义值）。
一局真实对局 LLM 调用较多、耗时以分钟计，属预期（env 门控、手动跑、非 CI）。
"""

import asyncio
import os

import httpx
import pytest

from app.engine.config import build_preset
from app.engine.phases import Phase
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.registry import GameRegistry
from app.store.event_store import InMemoryEventStore

SMOKE_MODEL = os.environ.get("AGENTHOWL_SMOKE_MODEL")


def _ollama_reachable() -> bool:
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(SMOKE_MODEL is None, reason="AGENTHOWL_SMOKE_MODEL 未设置"),
    pytest.mark.skipif(
        SMOKE_MODEL is not None and SMOKE_MODEL.startswith("ollama/") and not _ollama_reachable(),
        reason="Ollama 端点不可达",
    ),
]


class _TokenMeter:
    """LiteLLM 异步成功钩子：累计每次真实调用的 token（issue #32 判据 7）。"""

    def __init__(self) -> None:
        self.prompt = 0
        self.completion = 0
        self.calls = 0

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time) -> None:
        usage = getattr(response_obj, "usage", None)
        if usage is not None:
            self.prompt += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.completion += int(getattr(usage, "completion_tokens", 0) or 0)
            self.calls += 1


async def test_single_game_token_bench() -> None:
    import litellm
    from litellm.integrations.custom_logger import CustomLogger

    assert SMOKE_MODEL is not None
    meter = _TokenMeter()
    # CustomLogger 子类实例挂到 litellm.callbacks（异步成功事件的稳定接口）
    assert isinstance(meter, CustomLogger) or True  # _TokenMeter 鸭子实现 async_log_success_event
    prev_callbacks = list(litellm.callbacks)
    litellm.callbacks = [meter]  # type: ignore[list-item]
    try:
        registry = GameRegistry(
            InMemoryEventStore(),
            RunnerTimeouts(speech_sec=120.0, action_sec=120.0),
        )
        config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
        handle = registry.create(config, allow_spectators=False, ai_model=SMOKE_MODEL)
        registry.start(handle, fill_with_bots=True)
        assert handle.task is not None
        state = await asyncio.wait_for(handle.task, timeout=1800)
        assert state.phase == Phase.GAME_OVER
    finally:
        litellm.callbacks = prev_callbacks  # type: ignore[assignment]

    total = meter.prompt + meter.completion
    print(
        f"\n[token-bench] model={SMOKE_MODEL} calls={meter.calls} "
        f"prompt={meter.prompt} completion={meter.completion} total={total}"
    )
    assert meter.calls > 0, "未捕获任何 LLM 调用——检查 litellm.callbacks 钩子"
    assert total > 0, "token 累计为 0——检查 usage 上报"
```

注：`_TokenMeter` 直接实现 `async_log_success_event` 鸭子接口即可被 litellm 调用；`isinstance ... or True` 仅为形式说明，实现者可直接让 `_TokenMeter(CustomLogger)` 继承以更贴合类型（若继承则 `super().__init__()`）。二者皆可；若继承更省 mypy 顾虑则优先继承。`_pick_mode(SMOKE_MODEL)` 对 `ollama/*` 落 JSON mode，弱模型坏输出由 instructor 重试兜底（本 bench 会把重试的额外调用也计入 token，属真实成本，符合"粗测"意图）。

- [ ] **Step 2: 验证默认跳过 + 质量门**

Run: `uv run pytest tests/test_agent_bench.py -q`
Expected: 1 skipped（env 未设）
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS +（判据 7）1 skipped
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

（可选实跑，非通过条件：`AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke tests/test_agent_bench.py -q -s`——打印 token 总量；一局耗时以分钟计。）

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_bench.py
git commit -m "test(agent): env 门控单局 token bench（判据 7，issue #32）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: README API 快速开始 + 验收矩阵

**Files:**
- Modify: `README.md`（仓库根）

**Interfaces:**
- Consumes: 无（文档任务，收尾）

- [ ] **Step 1: 追加"API 快速开始"与"M2 验收矩阵"两节**

在 `README.md` 末尾追加以下内容（保持既有里程碑小节不动）：

```markdown
## API 快速开始 / API Quick Start

后端提供统一玩家 API（真人与 LLM Agent 走同一套）。启动：

​```bash
cd backend
uv run uvicorn app.main:app --reload   # http://localhost:8000
​```

一局最小流程（`curl`；`$BASE=http://localhost:8000/api/v1`）：

​```bash
# 1) 建局：9 人屠边预设，空位由 LLM Agent 填充（ai_model 省略则用内置随机 bot）
curl -s -X POST $BASE/games -H 'Content-Type: application/json' \
  -d '{"preset":"std_9_kill_side","config_override":{"seed":3},"ai_model":"ollama/llama3.1"}'
# → {game_id, host_token, spectator_token, config}

# 2) （可选）真人加入任意空座，拿 player_token 与 ws_url
curl -s -X POST $BASE/games/$GID/join -H 'Content-Type: application/json' \
  -d '{"display_name":"Alice","player_type":"HUMAN"}'
# → {player_token, seat, ws_url}

# 3) 开局（仅 host_token）：缺员座位按 ai_model 填充后起 runner
curl -s -X POST $BASE/games/$GID/start -H "Authorization: Bearer $HOST_TOKEN" \
  -H 'Content-Type: application/json' -d '{"fill_with_bots":true}'

# 4) 真人轮询自己的行动窗口（长轮询；204=暂未轮到）
curl -s "$BASE/games/$GID/my-turn?wait=5" -H "Authorization: Bearer $PLAYER_TOKEN"

# 5) 提交工具调用（§4.1 契约；actor_seat 一律取自 token，不接受 body 指定）
curl -s -X POST $BASE/games/$GID/actions -H "Authorization: Bearer $PLAYER_TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool":"vote","arguments":{"target_seat":2}}'

# 6) 局终 GM 全量回放
curl -s $BASE/games/$GID/replay -H "Authorization: Bearer $SPECTATOR_TOKEN"
​```

WebSocket（按视角推送过滤后事件流；断线可凭同 token + `from_seq` 重连补发）：

​```
GET /api/v1/ws?token=<token>[&from_seq=<n>]
# server→client 帧：game_event / your_turn / phase_change / game_over
# client→server 帧：与 POST /actions 等价（同 schema 同信封）
​```

真实模型冒烟与 token bench（默认跳过，需本地 Ollama）：

​```bash
ollama pull llama3.1 && ollama serve &
AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke -q -s
​```

## M2 验收矩阵（PRD §9）

| 判据 | 证据（测试） |
|---|---|
| 全 AI 完整对局经 API/WS（RandomBot） | `tests/test_api_e2e.py::test_acceptance_12_ai_full_game_via_api` |
| 全 **LLM Agent** 完整对局经 API/WS | `tests/test_acceptance_m25.py::test_all_agentplayer_game_via_http_ws` |
| 真人经同一玩家 API 顶替任意座位 | `tests/test_api_e2e.py::test_acceptance_human_can_take_any_seat`、`tests/test_api_ws.py::test_human_plays_whole_game_via_ws` |
| 超时代打，事件带 `meta.timeout=true` | `tests/test_game_runner.py::TestTimeoutAndRetry::test_hanging_port_replaced_by_default` |
| 断线重连 `from_seq` 补发一致 | `tests/test_api_e2e.py::test_acceptance_reconnect_restores_view` |
| 工具契约稳定 + instructor 校验重试 | `tests/test_schemas.py`、`tests/test_agent_llm_client.py::test_instructor_retries_on_invalid_then_valid` |
| 信息隔离（REST + 活 WS） | `tests/test_api_e2e.py::test_acceptance_isolation_matrix_via_api`、`tests/test_acceptance_m25.py::test_ws_isolation_matrix_wolf_villager_spectator` |
| 单局 LLM token 粗测 | `tests/test_agent_bench.py::test_single_game_token_bench`（env 门控） |
```

（markdown 内的 `​```` 围栏在实际写入时用三反引号；此计划中以零宽字符占位避免嵌套破坏。实现者按标准三反引号写。）

- [ ] **Step 2: 质量门（文档）**

Run: `uv run pytest -q`（timeout 360000）→ 不受影响，全量 PASS + 1 skipped
（README 改动不触发 lint；无需 mypy/ruff，但跑一遍确认无回归无妨。）

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README API 快速开始 + M2 验收矩阵（issue #32）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **规格覆盖**：判据 1→Task 1（+生产钩子）；判据 5→Task 2（主/降级双路径，规格明许）；判据 6→Task 3；判据 7→Task 4；文档 + 验收矩阵→Task 5。判据 2/3/4 及 RandomBot API 局：规格定为已覆盖，Task 5 矩阵引用既有测试，不重复造。
- **占位符扫描**：无 TBD/TODO。Task 2 的"降级路径"是规格授权的第三方脆弱性应对（二选一由实测决定），非留白；Task 5 的零宽占位仅为避免 heredoc 内嵌三反引号，已注明实现者用标准围栏。
- **类型一致性**：`agent_port_factory: Callable[[int, GameHandle], PlayerPort]` 与 registry Task 7 契约一致；`create_app` 新参数默认 None；`_scripted_agent_factory` 工厂签名 `(seat, handle)->PlayerPort` 与 `test_agent_integration` 范式一致；WS 帧结构 `frame["event"]["visibility"]`/`["actor_seat"]` 与既有 WS 测试一致。
- **不改引擎**：全部改动限 `app/main.py`（DI 钩子）+ tests + README，符合硬约束。
