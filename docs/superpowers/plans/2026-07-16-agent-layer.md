# Agent 层（M2.4，issue #31）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `backend/app/agent/`：LLM Agent 作为"诚实观察者"经 `PlayerPort.act(observation, deadline_ts)` 接入 runner，只依据 observation 与订阅到的可见事件决策；LiteLLM + instructor 模型无关，默认 Ollama 本地。

**Architecture:** decisions（各阶段 Pydantic 决策模型 + 纯映射到引擎 Action）→ llm_client（async Protocol + instructor 结构化输出，TOOLS/JSON mode 自选）→ memory（可见事件摄入 + Freshness K=15 + Informativeness 打分 + 惰性反思）→ prompts（三段式，昼间装配函数签名上拿不到夜间私有分区）→ agent_player（端口实现，狼夜私有推理独立调用）→ registry 接线（`ai_model` 建局字段，AgentPlayerPort 注入 + memory 订阅）。

**Tech Stack:** Python 3.11+，Pydantic v2，litellm + instructor（新增生产依赖），pytest（mock LLMClient 零网络；`smoke` marker env 门控真模型）。

**规格:** `docs/superpowers/specs/2026-07-16-agent-layer-design.md`（本计划的唯一裁决依据）

## Global Constraints

- 分支 `feat/agent-layer`（已建，规格已提交）；工作目录 `backend/`
- 质量门（每个任务收尾都跑）：`uv run pytest -q`（全量约 140s，Bash timeout 设 360000）、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`
- 注释/docstring 中文；标识符/API 英文；ruff line-length 100
- 分层：engine 不 import agent；agent 可 import engine/schemas，**不 import api、不 import runtime**（防循环：runtime 会 import agent）；litellm/instructor 只在 `app/agent/llm_client.py` 顶层 import，registry 对默认 agent 工厂做**惰性 import**（避免拖慢无 agent 路径）
- 狼私聊与公开发言是**分开的 LLM 调用**；`night_private` 分区内容**永不**进入任何昼间 prompt（类型层面隔离 + 单测断言）
- Agent 内**零兜底逻辑**：LLM 异常/超时一律上抛，活性由 runner 既有 异常→默认行动 机制负责
- 每个 port 同时至多一个未决 `act`（#30 终审口径，无流水线）
- 所有随机（候选洗牌）确定性：`random.Random(hash((agent_seed, seat, state_version)))`
- 提交信息结尾：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: PlayerObservation 补公开字段（引擎小增量）

Agent 只凭 observation 决策，但现有 observation 缺四个**公开**信息（谁在竞选、谁上 PK 台、竞选子阶段、PK 台上是否还在发言期）——bot 靠全知 state 读它们。全是场上公开事实，加入 observation 零隔离泄露。

**Files:**
- Modify: `backend/app/engine/observation.py`
- Test: `backend/tests/test_observation_fields.py`（新建）

**Interfaces:**
- Produces: `PlayerObservation` 新增字段（后续任务的 dispatch 依据）：
  - `election_stage: str = ""`（`state.election_stage` 原样；`ElectionStage` 的值域：`""`/`candidacy`/`withdraw`/`vote`/`direction`/`announce`）
  - `sheriff_candidates: list[int] = []`
  - `vote_candidates: list[int] = []`
  - `pk_speech_pending: bool = False`（`state.speech_idx < len(state.speech_order)`，仅 PK 阶段有语义）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_observation_fields.py`：

```python
"""observation 公开字段增量（issue #31 Task 1）：竞选/PK 公开信息对所有座位可见。"""

from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState


def _advance_until(state: GameState, pred) -> GameState:
    """用 RandomBot 推进种子局直至谓词成立（终局前必须命中，否则测试失败）。"""
    guard = 0
    while not pred(state):
        assert state.phase != Phase.GAME_OVER, "种子局终局仍未命中目标阶段"
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            res = step(state, RandomBot.choose_action(state, seat))
            assert res.rejection is None
            state = res.state
            if pred(state):
                return state
        guard += 1
        assert guard < 100_000
    return state


def test_election_fields_visible_to_all_seats() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs").state
    state = _advance_until(
        state, lambda s: s.phase == Phase.SHERIFF_ELECTION and s.election_stage == "vote"
    )
    for seat in range(config.num_players):
        obs = build_observation(state, seat)
        assert obs.election_stage == "vote"
        assert obs.sheriff_candidates == sorted(state.sheriff_candidates)


def test_vote_candidates_and_pk_pending() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs2").state
    state = _advance_until(state, lambda s: s.phase == Phase.VOTE)
    obs = build_observation(state, 0)
    assert obs.vote_candidates == sorted(state.vote_candidates)


def test_defaults_keep_old_constructions_valid() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs3").state
    obs = build_observation(state, 0)
    # 夜晚前新字段为空默认值
    assert obs.election_stage == ""
    assert obs.sheriff_candidates == []
    assert obs.vote_candidates == []
    assert obs.pk_speech_pending is False
```

注：`state.sheriff_candidates` / `state.vote_candidates` 的容器类型以 state.py 实际定义为准（可能是 tuple/frozenset）——测试里统一 `sorted(...)` 比较。若 seed 11 的种子局未命中目标阶段（`_advance_until` 断言失败），遍历 seed 1..30 选首个同时命中三个测试目标阶段的 seed 并写死。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_observation_fields.py -q`
Expected: FAIL —— `PlayerObservation` 无 `election_stage` 属性

- [ ] **Step 3: 实现**

`app/engine/observation.py` 的 `PlayerObservation` 增加（放在 `available_actions` 之前，带默认值保持向后兼容）：

```python
    # issue #31：竞选/PK 公开信息（全场可见事实，供 agent 无 state 决策）
    election_stage: str = ""
    sheriff_candidates: list[int] = []
    vote_candidates: list[int] = []
    pk_speech_pending: bool = False
```

（frozen 模型上可变默认值由 Pydantic 深拷贝处理，无共享陷阱。）

`build_observation(...)` 的构造调用中补：

```python
        election_stage=state.election_stage,
        sheriff_candidates=sorted(state.sheriff_candidates),
        vote_candidates=sorted(state.vote_candidates),
        pk_speech_pending=state.speech_idx < len(state.speech_order),
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `uv run pytest tests/test_observation_fields.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全部 PASS（307+3）
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/engine/observation.py tests/test_observation_fields.py
git commit -m "feat(engine): observation 补竞选/PK 公开字段，供 agent 无 state 决策 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: decisions.py —— 决策模型与纯映射

**Files:**
- Create: `backend/app/agent/__init__.py`（空 docstring 模块）
- Create: `backend/app/agent/decisions.py`
- Test: `backend/tests/test_agent_decisions.py`

**Interfaces:**
- Consumes: Task 1 的 `PlayerObservation` 新字段；`app.engine.actions` 全部构造器；`app.engine.phases.Phase`
- Produces（后续任务依赖的精确签名）:
  - `class DecisionKind(StrEnum)`: `NIGHT`/`WOLF_NIGHT`/`SPEECH`/`VOTE`/`SHERIFF`
  - 决策模型（全部 `BaseModel`，`reasoning: str` 先行引导 CoT）：
    - `NightDecision{reasoning: str, action_type: NightActionType, target_seat: int | None = None}`
    - `WolfDeliberation{analysis: str, proposed_target: int}`
    - `SpeechDecision{reasoning: str, content: str, claim_role: RoleType | None = None, badge_flow: list[int] = [], self_destruct: bool = False}`
    - `VoteDecision{reasoning: str, target_seat: int | None = None, abstain: bool = False}`
    - `SheriffDecision{reasoning: str, action_type: SheriffActionType, target_seat: int | None = None, direction: Direction | None = None, self_destruct: bool = False}`
  - `decision_kind_for(obs: PlayerObservation) -> DecisionKind`
  - `response_model_for(kind: DecisionKind) -> type[BaseModel]`
  - `to_action(kind: DecisionKind, decision: BaseModel, seat: int) -> Action`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_decisions.py`：

```python
"""agent 决策模型与 Action 映射（issue #31 Task 2）：纯函数，零 LLM 零 IO。"""

import pytest

from app.agent.decisions import (
    DecisionKind,
    NightDecision,
    SheriffDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
    decision_kind_for,
    response_model_for,
    to_action,
)
from app.engine.actions import (
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SelfDestruct,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import RoleType
from app.engine.observation import PlayerObservation


def _obs(phase: str, **kw) -> PlayerObservation:
    """最小 observation 桩：仅 dispatch 所需字段有意义。"""
    seats = kw.pop("seats", [{"seat": 0, "alive": True, "is_sheriff": False}])
    return PlayerObservation(
        game_id="g_t",
        state_version=7,
        my_seat=0,
        my_role=kw.pop("my_role", RoleType.VILLAGER),
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=seats,
        sheriff_seat=None,
        badge_flow_claims={},
        private={},
        available_actions=[0],
        **kw,
    )


@pytest.mark.parametrize(
    ("phase", "kw", "expected"),
    [
        ("NIGHT_WEREWOLF", {}, DecisionKind.WOLF_NIGHT),
        ("NIGHT_SEER", {}, DecisionKind.NIGHT),
        ("NIGHT_WITCH", {}, DecisionKind.NIGHT),
        ("NIGHT_GUARD", {}, DecisionKind.NIGHT),
        ("HUNTER_SHOOT", {}, DecisionKind.NIGHT),
        ("DAY_SPEECH", {}, DecisionKind.SPEECH),
        ("VOTE", {}, DecisionKind.VOTE),
        ("VOTE_PK", {"pk_speech_pending": True}, DecisionKind.SPEECH),
        ("VOTE_PK", {"pk_speech_pending": False}, DecisionKind.VOTE),
        ("SHERIFF_ELECTION", {"election_stage": "candidacy"}, DecisionKind.SHERIFF),
        ("SHERIFF_ELECTION", {"election_stage": "vote"}, DecisionKind.SHERIFF),
        ("SHERIFF_PK", {"pk_speech_pending": True}, DecisionKind.SPEECH),
        ("SHERIFF_PK", {"pk_speech_pending": False}, DecisionKind.SHERIFF),
        # 未映射阶段回退发言（镜像 RandomBot 兜底分支）
        ("NIGHT_HUNTER_CONFIRM", {}, DecisionKind.SPEECH),
    ],
)
def test_dispatch(phase: str, kw: dict, expected: DecisionKind) -> None:
    assert decision_kind_for(_obs(phase, **kw)) is expected


def test_dispatch_last_words_sheriff_vs_plain() -> None:
    sheriff_seats = [{"seat": 0, "alive": True, "is_sheriff": True}]
    assert decision_kind_for(_obs("LAST_WORDS", seats=sheriff_seats)) is DecisionKind.SHERIFF
    assert decision_kind_for(_obs("LAST_WORDS")) is DecisionKind.SPEECH


def test_response_model_roundtrip() -> None:
    assert response_model_for(DecisionKind.WOLF_NIGHT) is WolfDeliberation
    assert response_model_for(DecisionKind.NIGHT) is NightDecision
    assert response_model_for(DecisionKind.SPEECH) is SpeechDecision
    assert response_model_for(DecisionKind.VOTE) is VoteDecision
    assert response_model_for(DecisionKind.SHERIFF) is SheriffDecision


def test_to_action_mappings() -> None:
    a1 = to_action(
        DecisionKind.WOLF_NIGHT, WolfDeliberation(analysis="x", proposed_target=3), seat=1
    )
    assert a1 == NightAction(actor_seat=1, action_type=NightActionType.KILL, target_seat=3)

    a2 = to_action(
        DecisionKind.NIGHT,
        NightDecision(reasoning="r", action_type=NightActionType.CHECK, target_seat=5),
        seat=2,
    )
    assert a2 == NightAction(actor_seat=2, action_type=NightActionType.CHECK, target_seat=5)

    a3 = to_action(
        DecisionKind.SPEECH,
        SpeechDecision(reasoning="r", content="大家好", claim_role=RoleType.SEER, badge_flow=[4, 5]),
        seat=3,
    )
    assert a3 == Speak(actor_seat=3, content="大家好", claim_role=RoleType.SEER, badge_flow=(4, 5))

    a4 = to_action(DecisionKind.VOTE, VoteDecision(reasoning="r", target_seat=6), seat=4)
    assert a4 == DayVote(actor_seat=4, target_seat=6, abstain=False)

    a5 = to_action(DecisionKind.VOTE, VoteDecision(reasoning="r", abstain=True), seat=4)
    assert a5 == DayVote(actor_seat=4, target_seat=None, abstain=True)

    a6 = to_action(
        DecisionKind.SHERIFF,
        SheriffDecision(
            reasoning="r",
            action_type=SheriffActionType.SET_SPEECH_DIRECTION,
            direction=Direction.LEFT,
        ),
        seat=5,
    )
    assert a6 == SheriffAction(
        actor_seat=5,
        action_type=SheriffActionType.SET_SPEECH_DIRECTION,
        target_seat=None,
        direction=Direction.LEFT,
    )


def test_self_destruct_overrides() -> None:
    a = to_action(
        DecisionKind.SPEECH, SpeechDecision(reasoning="r", content="", self_destruct=True), seat=7
    )
    assert a == SelfDestruct(actor_seat=7)
    b = to_action(
        DecisionKind.SHERIFF,
        SheriffDecision(
            reasoning="r", action_type=SheriffActionType.WITHDRAW, self_destruct=True
        ),
        seat=8,
    )
    assert b == SelfDestruct(actor_seat=8)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_decisions.py -q`
Expected: FAIL —— `ModuleNotFoundError: app.agent`

- [ ] **Step 3: 实现**

`backend/app/agent/__init__.py`：

```python
"""agent 层：LLM Agent 玩家（issue #31，PRD §4.4）。诚实观察者——只凭 observation 与可见事件决策。"""
```

`backend/app/agent/decisions.py`：

```python
"""各阶段 LLM 决策模型与到引擎 Action 的纯映射（issue #31）。

只表达意图，不做合法性裁决——非法值由引擎拒绝、runner 重试兜底。
dispatch 分支镜像 app.cli.bot.RandomBot（同一阶段语义的唯一另一处实现）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.engine.actions import (
    Action,
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SelfDestruct,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import RoleType
from app.engine.observation import PlayerObservation
from app.engine.phases import ElectionStage, Phase


class DecisionKind(StrEnum):
    NIGHT = "night"
    WOLF_NIGHT = "wolf_night"
    SPEECH = "speech"
    VOTE = "vote"
    SHERIFF = "sheriff"


class NightDecision(BaseModel):
    """夜间/猎人行动：先写推理，再给行动。"""

    reasoning: str
    action_type: NightActionType
    target_seat: int | None = None


class WolfDeliberation(BaseModel):
    """狼人夜间私有推理（独立 LLM 调用；analysis 只进 night_private 记忆分区）。"""

    analysis: str
    proposed_target: int


class SpeechDecision(BaseModel):
    reasoning: str
    content: str
    claim_role: RoleType | None = None
    badge_flow: list[int] = Field(default_factory=list)
    self_destruct: bool = False


class VoteDecision(BaseModel):
    reasoning: str
    target_seat: int | None = None
    abstain: bool = False


class SheriffDecision(BaseModel):
    reasoning: str
    action_type: SheriffActionType
    target_seat: int | None = None
    direction: Direction | None = None
    self_destruct: bool = False


_RESPONSE_MODELS: dict[DecisionKind, type[BaseModel]] = {
    DecisionKind.NIGHT: NightDecision,
    DecisionKind.WOLF_NIGHT: WolfDeliberation,
    DecisionKind.SPEECH: SpeechDecision,
    DecisionKind.VOTE: VoteDecision,
    DecisionKind.SHERIFF: SheriffDecision,
}


def response_model_for(kind: DecisionKind) -> type[BaseModel]:
    return _RESPONSE_MODELS[kind]


def _is_sheriff(obs: PlayerObservation) -> bool:
    return any(s.get("seat") == obs.my_seat and s.get("is_sheriff") for s in obs.seats)


def decision_kind_for(obs: PlayerObservation) -> DecisionKind:
    ph = Phase(obs.phase)
    if ph == Phase.NIGHT_WEREWOLF:
        return DecisionKind.WOLF_NIGHT
    if ph in (Phase.NIGHT_SEER, Phase.NIGHT_WITCH, Phase.NIGHT_GUARD, Phase.HUNTER_SHOOT):
        return DecisionKind.NIGHT
    if ph == Phase.DAY_SPEECH:
        return DecisionKind.SPEECH
    if ph == Phase.LAST_WORDS:
        return DecisionKind.SHERIFF if _is_sheriff(obs) else DecisionKind.SPEECH
    if ph == Phase.VOTE:
        return DecisionKind.VOTE
    if ph == Phase.VOTE_PK:
        return DecisionKind.SPEECH if obs.pk_speech_pending else DecisionKind.VOTE
    if ph == Phase.SHERIFF_PK:
        return DecisionKind.SPEECH if obs.pk_speech_pending else DecisionKind.SHERIFF
    if ph == Phase.SHERIFF_ELECTION:
        return DecisionKind.SHERIFF
    # 未映射阶段回退发言（镜像 RandomBot 兜底；如 NIGHT_HUNTER_CONFIRM）
    return DecisionKind.SPEECH


def to_action(kind: DecisionKind, decision: BaseModel, seat: int) -> Action:
    if kind is DecisionKind.WOLF_NIGHT:
        assert isinstance(decision, WolfDeliberation)
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.KILL,
            target_seat=decision.proposed_target,
        )
    if kind is DecisionKind.NIGHT:
        assert isinstance(decision, NightDecision)
        return NightAction(
            actor_seat=seat, action_type=decision.action_type, target_seat=decision.target_seat
        )
    if kind is DecisionKind.SPEECH:
        assert isinstance(decision, SpeechDecision)
        if decision.self_destruct:
            return SelfDestruct(actor_seat=seat)
        return Speak(
            actor_seat=seat,
            content=decision.content,
            claim_role=decision.claim_role,
            badge_flow=tuple(decision.badge_flow),
        )
    if kind is DecisionKind.VOTE:
        assert isinstance(decision, VoteDecision)
        return DayVote(actor_seat=seat, target_seat=decision.target_seat, abstain=decision.abstain)
    assert isinstance(decision, SheriffDecision)
    if decision.self_destruct:
        return SelfDestruct(actor_seat=seat)
    return SheriffAction(
        actor_seat=seat,
        action_type=decision.action_type,
        target_seat=decision.target_seat,
        direction=decision.direction,
    )


__all__ = [
    "DecisionKind",
    "ElectionStage",
    "NightDecision",
    "SheriffDecision",
    "SpeechDecision",
    "VoteDecision",
    "WolfDeliberation",
    "decision_kind_for",
    "response_model_for",
    "to_action",
]
```

注：`assert isinstance` 在此是内部契约（kind 与模型由 `response_model_for` 配对产生），mypy strict 需要窄化；若 ruff 报 S101 类规则未启用则无碍（本仓 select 无 S）。

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_agent_decisions.py -q` → PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/agent/ tests/test_agent_decisions.py
git commit -m "feat(agent): 各阶段决策模型与 Action 纯映射 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: llm_client.py —— async LLMClient Protocol + LiteLLM/instructor 实现 + 测试脚本客户端

**Files:**
- Modify: `backend/pyproject.toml`（新增生产依赖 litellm、instructor；mypy overrides）
- Create: `backend/app/agent/llm_client.py`
- Create: `backend/tests/llm_helpers.py`（ScriptedLLMClient + action_to_decision，供 Task 4-7 复用）
- Test: `backend/tests/test_agent_llm_client.py`

**Interfaces:**
- Consumes: Task 2 的决策模型（helpers 的逆映射用）
- Produces:
  - `class LLMClient(Protocol)`: `async def complete_structured(self, *, system_prompt: str, user_prompt: str, response_model: type[TModel], model: str, temperature: float = 0.3) -> TModel`（`TModel = TypeVar("TModel", bound=BaseModel)`）
  - `class LiteLLMInstructorClient`: 同签名实现；`_pick_mode(model: str) -> instructor.Mode`（TOOLS/JSON）；`max_retries` 构造参数默认 2
  - `tests/llm_helpers.py`:
    - `class ScriptedLLMClient`: `__init__(self, script: Callable[[type[BaseModel], str, str], BaseModel])`；`calls: list[RecordedCall]`（`RecordedCall = tuple[str, str, str]` 即 (model, system_prompt, user_prompt)）；实现 `LLMClient`
    - `action_to_decision(action: Action, response_model: type[BaseModel]) -> BaseModel`（引擎 Action → 决策模型的逆映射，集成测试用）

- [ ] **Step 1: 加依赖**

```bash
uv add litellm instructor
```

`pyproject.toml` 追加 mypy overrides（litellm/instructor 类型不完备）：

```toml
[[tool.mypy.overrides]]
module = ["litellm", "litellm.*", "instructor", "instructor.*"]
ignore_missing_imports = true
follow_imports = "skip"
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_agent_llm_client.py`：

```python
"""LLM 客户端（issue #31 Task 3）：mode 选择与脚本客户端契约。零网络。"""

import pytest
from pydantic import BaseModel

from app.agent.llm_client import LiteLLMInstructorClient, LLMClient, _pick_mode
from tests.llm_helpers import ScriptedLLMClient


class _Echo(BaseModel):
    text: str


def test_pick_mode_tools_when_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    import instructor
    import litellm

    monkeypatch.setattr(litellm, "supports_function_calling", lambda model: True)
    assert _pick_mode("gpt-x") is instructor.Mode.TOOLS


def test_pick_mode_json_when_unsupported_or_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    import instructor
    import litellm

    monkeypatch.setattr(litellm, "supports_function_calling", lambda model: False)
    assert _pick_mode("ollama/llama3.1") is instructor.Mode.JSON

    def _boom(model: str) -> bool:
        raise ValueError("unknown model")

    monkeypatch.setattr(litellm, "supports_function_calling", _boom)
    assert _pick_mode("ollama/whatever") is instructor.Mode.JSON  # 查询异常按不支持处理


def test_client_constructs_without_network() -> None:
    client = LiteLLMInstructorClient()
    assert client is not None


async def test_scripted_client_satisfies_protocol_and_records() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        assert rm is _Echo
        return _Echo(text="hi")

    scripted: LLMClient = ScriptedLLMClient(script)
    out = await scripted.complete_structured(
        system_prompt="sys", user_prompt="usr", response_model=_Echo, model="scripted"
    )
    assert out == _Echo(text="hi")
    assert scripted.calls == [("scripted", "sys", "usr")]  # type: ignore[attr-defined]
```

（`scripted.calls` 处对 Protocol 变量取实现属性需要 `# type: ignore[attr-defined]`，或直接用具体类型变量再单独一行赋给 `LLMClient` 变量做静态契约检查——实现者可二选一，保持 mypy strict 干净。）

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_llm_client.py -q`
Expected: FAIL —— `app.agent.llm_client` / `tests.llm_helpers` 不存在

- [ ] **Step 4: 实现**

`backend/app/agent/llm_client.py`：

```python
"""模型无关 LLM 客户端（issue #31，PRD §4.4.3）。

相对 PRD 签名去掉冗余 tools_schema 参数：结构化输出 schema 由 response_model
携带（instructor 负责校验与重试），工具语义在 prompts 指令段以文字呈现。
弱工具调用模型（如 Ollama）自动落 JSON mode。
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

import instructor
import litellm
from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_MODEL = "ollama/llama3.1"


class LLMClient(Protocol):
    """结构化补全的唯一入口；实现必须无游戏状态（可跨座位复用）。"""

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        model: str,
        temperature: float = 0.3,
    ) -> TModel: ...


def _pick_mode(model: str) -> instructor.Mode:
    """支持函数调用 → TOOLS；不支持或未知模型 → JSON（instructor 校验+重试兜底）。"""
    try:
        supported = bool(litellm.supports_function_calling(model))
    except Exception:
        supported = False
    return instructor.Mode.TOOLS if supported else instructor.Mode.JSON


class LiteLLMInstructorClient:
    def __init__(self, max_retries: int = 2) -> None:
        self._max_retries = max_retries
        self._clients: dict[instructor.Mode, Any] = {}  # instructor 异步客户端按 mode 缓存

    def _client_for(self, mode: instructor.Mode) -> Any:
        if mode not in self._clients:
            self._clients[mode] = instructor.from_litellm(litellm.acompletion, mode=mode)
        return self._clients[mode]

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        model: str,
        temperature: float = 0.3,
    ) -> TModel:
        client = self._client_for(_pick_mode(model))
        result = await client.chat.completions.create(
            model=model,
            response_model=response_model,
            max_retries=self._max_retries,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        assert isinstance(result, response_model)  # instructor 已校验；为 mypy 窄化
        return result
```

`backend/tests/llm_helpers.py`：

```python
"""测试用 LLM 客户端与 Action→决策 逆映射（issue #31）。仅测试进程使用，零网络。"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from app.agent.decisions import (
    NightDecision,
    SheriffDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
)
from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    SelfDestruct,
    SheriffAction,
    Speak,
)

RecordedCall = tuple[str, str, str]  # (model, system_prompt, user_prompt)


class ScriptedLLMClient:
    """按脚本函数返回决策；记录每次调用的 (model, system, user) 供 prompt 断言。"""

    def __init__(self, script: Callable[[type[BaseModel], str, str], BaseModel]) -> None:
        self._script = script
        self.calls: list[RecordedCall] = []

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        model: str,
        temperature: float = 0.3,
    ) -> BaseModel:
        self.calls.append((model, system_prompt, user_prompt))
        return self._script(response_model, system_prompt, user_prompt)


def action_to_decision(action: Action, response_model: type[BaseModel]) -> BaseModel:
    """引擎 Action → 决策模型的逆映射：集成测试里让脚本客户端复用 RandomBot 的合法行动。"""
    if response_model is WolfDeliberation:
        assert isinstance(action, NightAction) and action.target_seat is not None
        return WolfDeliberation(analysis="(scripted)", proposed_target=action.target_seat)
    if response_model is NightDecision:
        assert isinstance(action, NightAction)
        return NightDecision(
            reasoning="(scripted)", action_type=action.action_type, target_seat=action.target_seat
        )
    if response_model is SpeechDecision:
        if isinstance(action, SelfDestruct):
            return SpeechDecision(reasoning="(scripted)", content="", self_destruct=True)
        assert isinstance(action, Speak)
        return SpeechDecision(
            reasoning="(scripted)",
            content=action.content,
            claim_role=action.claim_role,
            badge_flow=list(action.badge_flow),
        )
    if response_model is VoteDecision:
        assert isinstance(action, DayVote)
        return VoteDecision(
            reasoning="(scripted)", target_seat=action.target_seat, abstain=action.abstain
        )
    assert response_model is SheriffDecision
    if isinstance(action, SelfDestruct):
        from app.engine.actions import SheriffActionType

        return SheriffDecision(
            reasoning="(scripted)",
            action_type=SheriffActionType.WITHDRAW,
            self_destruct=True,
        )
    assert isinstance(action, SheriffAction)
    return SheriffDecision(
        reasoning="(scripted)",
        action_type=action.action_type,
        target_seat=action.target_seat,
        direction=action.direction,
    )
```

- [ ] **Step 5: 跑测试 + 质量门**

Run: `uv run pytest tests/test_agent_llm_client.py -q` → PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净
（注意首次 import litellm 较慢属预期；若 `uv run mypy app` 因 litellm 类型爆炸变慢，确认 overrides 的 `follow_imports = "skip"` 生效。）

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/agent/llm_client.py tests/llm_helpers.py tests/test_agent_llm_client.py
git commit -m "feat(agent): async LLMClient 协议 + LiteLLM/instructor 实现，TOOLS/JSON mode 自选 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: memory.py —— 事件摄入、打分裁剪与惰性反思

**Files:**
- Create: `backend/app/agent/memory.py`
- Test: `backend/tests/test_agent_memory.py`

**Interfaces:**
- Consumes: `app.engine.events.Event/EventType`；Task 3 的 `LLMClient`（反思调用）与 `ScriptedLLMClient`（测试）
- Produces:
  - `class MemoryEntry(BaseModel)`: `seq: int, round: int, kind: str, text: str, score: int`
  - `class ReflectionQA(BaseModel)`: `question: str, answer: str`
  - `class ReflectionResult(BaseModel)`: `summary: str, qa: list[ReflectionQA]`
  - `PREDEFINED_QUESTIONS: list[str]`（L=5）
  - `class AgentMemory`:
    - `__init__(self, seat: int, *, freshness_k: int = 15, informative_top_n: int = 10)`
    - `ingest(self, events: list[Event]) -> None`（同步，纯内存）
    - `async def on_events(self, events: list[Event]) -> None`（ConnectionManager 订阅适配；**只摄入，零 LLM**——broadcast 路径不得被阻塞）
    - `note_night_private(self, text: str, round: int) -> None`
    - `build_context(self) -> str`（昼间上下文：反思摘要 + 高分补充 + 最近 K 条；**永不含** night_private）
    - `night_private_context(self) -> str`
    - `rounds_needing_reflection(self) -> list[int]`
    - `async def reflect(self, client: LLMClient, model: str, temperature: float = 0.3) -> None`（失败告警降级并标记已尝试，不重试不上抛）
    - `entries: list[MemoryEntry]`（只读语义，测试用）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_memory.py`：

```python
"""agent 记忆（issue #31 Task 4）：K=15 新鲜窗口、打分 top-N、私有分区隔离、惰性反思。"""

from pydantic import BaseModel

from app.agent.memory import (
    PREDEFINED_QUESTIONS,
    AgentMemory,
    ReflectionQA,
    ReflectionResult,
)
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    Visibility,
)
from app.engine.config import Faction
from tests.llm_helpers import ScriptedLLMClient


def _ev(seq: int, etype: EventType, payload, *, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g_m",
        ts=float(seq),
        type=etype,
        actor_seat=actor,
        payload=payload,
        visibility=Visibility.PUBLIC,
    )


def _spoke(seq: int, seat: int, content: str) -> Event:
    return _ev(seq, EventType.PLAYER_SPOKE, PlayerSpokePayload(content=content), actor=seat)


def test_round_tracking_and_scoring() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest(
        [
            _ev(2, EventType.SEER_CHECKED, SeerCheckedPayload(target=3, result=Faction.WOLF), actor=0),
            _ev(3, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))),
            _spoke(4, 2, "平安夜"),
        ]
    )
    by_kind = {e.kind: e for e in mem.entries}
    assert by_kind[EventType.SEER_CHECKED.value].score == 5  # 自身查验最高分
    assert by_kind[EventType.DEATH_ANNOUNCED.value].score == 4
    assert by_kind[EventType.PLAYER_SPOKE.value].score == 1  # 无声称的普通发言
    assert all(e.round == 1 for e in mem.entries)


def test_claim_speech_scores_3() -> None:
    mem = AgentMemory(seat=0)
    from app.engine.config import RoleType

    mem.ingest(
        [
            _ev(
                1,
                EventType.PLAYER_SPOKE,
                PlayerSpokePayload(content="我是预言家", claim_role=RoleType.SEER),
                actor=4,
            )
        ]
    )
    assert mem.entries[0].score == 3


def test_freshness_window_plus_topn() -> None:
    mem = AgentMemory(seat=0, freshness_k=3, informative_top_n=2)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    # 一条高分旧事件 + 一串低分发言把它挤出新鲜窗口
    mem.ingest([_ev(2, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(7,)))])
    mem.ingest([_spoke(10 + i, 1, f"话{i}") for i in range(6)])
    ctx = mem.build_context()
    assert "话5" in ctx and "话4" in ctx and "话3" in ctx  # 最近 K=3
    assert "7" in ctx  # 高分死亡事件经 top-N 补充保留
    assert "话0" not in ctx  # 低分旧发言被裁剪


def test_night_private_partition_never_in_context() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.note_night_private("私谋：今晚刀 3 号，明天悍跳预言家", round=1)
    assert "私谋" not in mem.build_context()
    assert "私谋" in mem.night_private_context()


async def test_reflection_folds_summary_and_questions() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest([_spoke(2, 1, "第一轮发言")])
    mem.ingest([_ev(3, EventType.ROUND_STARTED, RoundStartedPayload(round=2))])
    assert mem.rounds_needing_reflection() == [1]

    seen_prompts: list[str] = []

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        seen_prompts.append(user)
        assert rm is ReflectionResult
        return ReflectionResult(
            summary="首轮平稳",
            qa=[ReflectionQA(question=q, answer="a") for q in PREDEFINED_QUESTIONS],
        )

    await mem.reflect(ScriptedLLMClient(script), model="scripted")
    assert mem.rounds_needing_reflection() == []
    assert "首轮平稳" in mem.build_context()
    # L=5 预置问句进了反思 prompt
    assert all(q in seen_prompts[0] for q in PREDEFINED_QUESTIONS)


async def test_reflection_failure_degrades() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest([_spoke(2, 1, "x")])
    mem.ingest([_ev(3, EventType.ROUND_STARTED, RoundStartedPayload(round=2))])

    def boom(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise RuntimeError("llm down")

    await mem.reflect(ScriptedLLMClient(boom), model="scripted")
    # 失败：标记已尝试（不重试烧预算），原始条目保留
    assert mem.rounds_needing_reflection() == []
    assert "x" in mem.build_context()


async def test_on_events_is_pure_ingest() -> None:
    mem = AgentMemory(seat=0)
    await mem.on_events([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    assert len(mem.entries) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_memory.py -q`
Expected: FAIL —— `app.agent.memory` 不存在

- [ ] **Step 3: 实现**

`backend/app/agent/memory.py`：

```python
"""agent 记忆（issue #31，PRD §4.4.2 初版"三件套"）。

Freshness（最近 K 条原文）+ Informativeness（规则打分 top-N 补充）+ 每轮反思
（惰性触发，Completeness L=5 预置 + M=2 自问并入同一次调用）。不引入向量检索。
night_private 分区单列：狼人夜间私有推理只能经 night_private_context() 读取，
build_context()（昼间上下文）在实现上不触碰该分区。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMClient
from app.engine.events import (
    Event,
    EventType,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
)

logger = logging.getLogger(__name__)

PREDEFINED_QUESTIONS: list[str] = [
    "你的角色和阵营是什么？",
    "当前是第几轮、什么阶段？",
    "本轮谁死亡或出局了？",
    "谁声称了什么身份？可信度如何？",
    "你当前的目标是什么？下一步计划？",
]


class MemoryEntry(BaseModel):
    seq: int
    round: int
    kind: str
    text: str
    score: int


class ReflectionQA(BaseModel):
    question: str
    answer: str


class ReflectionResult(BaseModel):
    summary: str
    qa: list[ReflectionQA] = Field(default_factory=list)


_SCORE_4 = {
    EventType.DEATH_ANNOUNCED,
    EventType.NIGHT_RESOLVED,
    EventType.PLAYER_EXILED,
    EventType.HUNTER_SHOT,
    EventType.WOLF_SELF_DESTRUCT,
}
_SCORE_3 = {
    EventType.SHERIFF_ELECTED,
    EventType.BADGE_PASSED,
    EventType.SHERIFF_BADGE_LOST,
    EventType.LAST_WORDS,
}
_SCORE_2 = {
    EventType.WITCH_SAVED,
    EventType.WITCH_POISONED,
    EventType.WITCH_POTION_CONSUMED,
    EventType.GUARD_PROTECTED,
    EventType.WOLF_KILL_PROPOSED,
    EventType.WOLF_KILL_DECIDED,
    EventType.VOTE_RESULT,
}


def _score(event: Event, seat: int) -> int:
    if event.type == EventType.SEER_CHECKED and event.actor_seat == seat:
        return 5  # 自身查验结果：最高信息量
    if event.type == EventType.ROLES_ASSIGNED:
        return 5
    if event.type in _SCORE_4:
        return 4
    if event.type in _SCORE_3:
        return 3
    if event.type == EventType.PLAYER_SPOKE:
        p = event.payload
        if isinstance(p, PlayerSpokePayload) and (p.claim_role is not None or p.badge_flow):
            return 3  # 跳身份/报警徽流的发言
        return 1
    if event.type in _SCORE_2:
        return 2
    return 1


def _render(event: Event) -> str:
    """事件 → 中文一行文本。特判高频类型，其余回退通用格式。"""
    p = event.payload
    t = event.type
    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        claim = f"（声称{p.claim_role.value}）" if p.claim_role is not None else ""
        bf = f"（警徽流{list(p.badge_flow)}）" if p.badge_flow else ""
        return f"{event.actor_seat}号发言{claim}{bf}：{p.content}"
    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        return f"你查验了{p.target}号：{p.result.value}"
    dumped = p.model_dump(mode="json")
    actor = f" actor={event.actor_seat}" if event.actor_seat is not None else ""
    return f"{t.value}{actor} {dumped}"


class AgentMemory:
    def __init__(self, seat: int, *, freshness_k: int = 15, informative_top_n: int = 10) -> None:
        self._seat = seat
        self._k = freshness_k
        self._top_n = informative_top_n
        self.entries: list[MemoryEntry] = []
        self._reflections: list[tuple[int, str]] = []  # (round, rendered_text)
        self._night_private: list[tuple[int, str]] = []  # (round, text)
        self._current_round = 0
        self._reflected_rounds: set[int] = set()  # 含"已尝试但失败"，避免重试烧预算

    def ingest(self, events: list[Event]) -> None:
        for e in events:
            if e.type == EventType.ROUND_STARTED and isinstance(e.payload, RoundStartedPayload):
                self._current_round = e.payload.round
            self.entries.append(
                MemoryEntry(
                    seq=e.seq,
                    round=self._current_round,
                    kind=e.type.value,
                    text=_render(e),
                    score=_score(e, self._seat),
                )
            )

    async def on_events(self, events: list[Event]) -> None:
        """ConnectionManager 订阅适配：只摄入。broadcast 在 runner 提交路径上，禁止阻塞。"""
        self.ingest(events)

    def note_night_private(self, text: str, round: int) -> None:
        self._night_private.append((round, text))

    def _context_lines(self) -> list[str]:
        recent = self.entries[-self._k :]
        older = self.entries[: -self._k] if len(self.entries) > self._k else []
        picked = sorted(
            sorted(older, key=lambda e: e.score, reverse=True)[: self._top_n],
            key=lambda e: e.seq,
        )
        lines = [f"[反思·第{r}轮] {t}" for r, t in self._reflections]
        lines += [f"[要点] {e.text}" for e in picked]
        lines += [e.text for e in recent]
        return lines

    def build_context(self) -> str:
        """昼间上下文。实现上不读 _night_private —— 公私分离的结构落点。"""
        return "\n".join(self._context_lines())

    def night_private_context(self) -> str:
        return "\n".join(f"[第{r}夜私谋] {t}" for r, t in self._night_private)

    def rounds_needing_reflection(self) -> list[int]:
        done = {e.round for e in self.entries if e.round > 0}
        return sorted(r for r in done if r < self._current_round and r not in self._reflected_rounds)

    async def reflect(self, client: LLMClient, model: str, temperature: float = 0.3) -> None:
        for r in self.rounds_needing_reflection():
            round_lines = "\n".join(e.text for e in self.entries if e.round == r)
            questions = "\n".join(f"- {q}" for q in PREDEFINED_QUESTIONS)
            user_prompt = (
                f"以下是狼人杀第{r}轮你观察到的全部事件：\n{round_lines}\n\n"
                f"请总结本轮局势（summary），并回答以下问题（qa），"
                f"另外自行提出并回答 2 个你认为对后续决策最重要的问题：\n{questions}"
            )
            self._reflected_rounds.add(r)  # 先标记：失败也不重试（降级保留原始条目）
            try:
                result = await client.complete_structured(
                    system_prompt="你是狼人杀玩家，正在复盘上一轮。",
                    user_prompt=user_prompt,
                    response_model=ReflectionResult,
                    model=model,
                    temperature=temperature,
                )
            except Exception:
                logger.warning("座位 %d 第 %d 轮反思失败，降级保留原始记忆", self._seat, r, exc_info=True)
                continue
            qa_text = "；".join(f"{x.question}→{x.answer}" for x in result.qa)
            self._reflections.append((r, f"{result.summary}｜{qa_text}"))
```

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_agent_memory.py -q` → PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/agent/memory.py tests/test_agent_memory.py
git commit -m "feat(agent): 记忆三件套——K=15 新鲜窗口 + 规则打分 top-N + 惰性每轮反思 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: prompts.py —— 三段式装配与候选洗牌（昼间签名拿不到私有分区）

**Files:**
- Create: `backend/app/agent/prompts.py`
- Test: `backend/tests/test_agent_prompts.py`

**Interfaces:**
- Consumes: Task 2 `DecisionKind`/决策模型；Task 1 observation 字段
- Produces:
  - `shuffle_candidates(candidates: list[int], *, agent_seed: int, seat: int, state_version: int) -> list[int]`
  - `static_system_prompt(config: GameConfig, seat: int, role: RoleType) -> str`（静态段：规则+config 要点+角色说明，可整段缓存）
  - `candidates_for(kind: DecisionKind, obs: PlayerObservation) -> list[int]`
  - `build_prompt(kind: DecisionKind, obs: PlayerObservation, memory_context: str, *, agent_seed: int) -> str`（**全部昼间与非狼夜间**决策的 user prompt；签名上不存在私有分区参数——公私分离的类型落点）
  - `build_wolf_night_prompt(obs: PlayerObservation, memory_context: str, night_private_context: str, *, agent_seed: int) -> str`（唯一能接收私有分区的装配函数）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_prompts.py`：

```python
"""prompt 三段式装配（issue #31 Task 5）：洗牌确定性、角色注入、私有分区只进狼夜 prompt。"""

import inspect

from app.agent.decisions import DecisionKind
from app.agent.prompts import (
    build_prompt,
    build_wolf_night_prompt,
    candidates_for,
    shuffle_candidates,
    static_system_prompt,
)
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation


def _obs(phase: str = "DAY_SPEECH", **kw) -> PlayerObservation:
    return PlayerObservation(
        game_id="g_p",
        state_version=kw.pop("state_version", 42),
        my_seat=kw.pop("my_seat", 0),
        my_role=kw.pop("my_role", RoleType.WEREWOLF),
        my_status="ALIVE",
        phase=phase,
        round=2,
        seats=[
            {"seat": i, "alive": i != 5, "is_sheriff": i == 3} for i in range(9)
        ],
        sheriff_seat=3,
        badge_flow_claims={},
        private=kw.pop("private", {"teammates": [4, 7]}),
        available_actions=[0],
        **kw,
    )


def test_shuffle_deterministic_permutation() -> None:
    cands = [1, 2, 3, 4, 5, 6]
    a = shuffle_candidates(cands, agent_seed=9, seat=0, state_version=42)
    b = shuffle_candidates(cands, agent_seed=9, seat=0, state_version=42)
    c = shuffle_candidates(cands, agent_seed=9, seat=1, state_version=42)
    assert a == b  # 同键确定性
    assert sorted(a) == cands  # 是置换
    assert cands == [1, 2, 3, 4, 5, 6]  # 不改原列表
    # 不同座位大概率不同序（弱断言：至少键参与了派生）
    assert (a != c) or (shuffle_candidates(cands, agent_seed=9, seat=1, state_version=43) != c)


def test_static_prompt_contains_role_and_config() -> None:
    config = build_preset("std_9_kill_side")
    sp = static_system_prompt(config, seat=2, role=RoleType.SEER)
    assert "预言家" in sp and "2" in sp
    assert "屠边" in sp or "KILL_SIDE" in sp  # 胜利条件入静态段


def test_candidates_for_vote_and_sheriff() -> None:
    obs = _obs("VOTE", vote_candidates=[3, 1])
    assert set(candidates_for(DecisionKind.VOTE, obs)) == {3, 1}
    obs2 = _obs("SHERIFF_ELECTION", election_stage="vote", sheriff_candidates=[2, 6])
    assert set(candidates_for(DecisionKind.SHERIFF, obs2)) == {2, 6}
    # 无显式候选 → 存活他人
    obs3 = _obs("VOTE")
    assert set(candidates_for(DecisionKind.VOTE, obs3)) == {1, 2, 3, 4, 6, 7, 8}


def test_day_prompt_builder_has_no_private_param() -> None:
    # 公私分离的类型落点：昼间装配函数签名上不存在私有分区参数
    params = inspect.signature(build_prompt).parameters
    assert "night_private_context" not in params
    assert "night_private" not in params


def test_prompts_carry_memory_and_self_check() -> None:
    up = build_prompt(DecisionKind.SPEECH, _obs(), "记忆内容ABC", agent_seed=1)
    assert "记忆内容ABC" in up
    assert "当前" in up and "角色" in up  # 反幻觉自检问句
    wolf = build_wolf_night_prompt(
        _obs("NIGHT_WEREWOLF"), "记忆内容ABC", "[第1夜私谋] 刀3号", agent_seed=1
    )
    assert "刀3号" in wolf and "记忆内容ABC" in wolf
    assert "队友" in wolf and "4" in wolf  # teammates 进狼夜动态段
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_prompts.py -q`
Expected: FAIL —— `app.agent.prompts` 不存在

- [ ] **Step 3: 实现**

`backend/app/agent/prompts.py`：

```python
"""三段式 prompt 装配（issue #31，PRD §4.4.1）：静态段 + 动态段 + 指令段。

公私分离的类型落点：build_prompt（全部昼间与非狼夜间决策）签名上没有私有分区
参数；唯一能接收 night_private 的是 build_wolf_night_prompt。
候选列表经确定性洗牌（抗位置偏置，PRD §4.4.4）。
"""

from __future__ import annotations

import random
from typing import Any

from app.agent.decisions import DecisionKind
from app.engine.config import GameConfig, RoleType, WinCondition
from app.engine.observation import PlayerObservation

ROLE_BRIEFS: dict[RoleType, str] = {
    RoleType.WEREWOLF: "狼人：夜间与队友共同袭击一名玩家；白天隐藏身份、误导好人；可自爆结束白天。",
    RoleType.VILLAGER: "村民：无夜间能力；靠发言与投票找出狼人。",
    RoleType.SEER: "预言家：每夜查验一名玩家的阵营（好人/狼人）。",
    RoleType.WITCH: "女巫：一瓶解药一瓶毒药，全局各一次；通常同夜不能双用。",
    RoleType.HUNTER: "猎人：被狼杀或被放逐时可开枪带走一名玩家（被毒死不能开枪）。",
    RoleType.GUARD: "守卫：每夜守护一名玩家免受狼刀；通常不能连守同一人。",
    RoleType.IDIOT: "白痴：被投票放逐时翻牌免死，但失去投票权。",
}

_WIN_TEXT = {
    WinCondition.KILL_SIDE: "屠边：狼人杀光全部村民或全部神职即胜",
    WinCondition.KILL_ALL: "屠城：狼人杀光所有好人即胜",
}

_SELF_CHECK = "回答前自检：当前是什么阶段？你的座位号和角色是什么？不要臆造未发生的事件。"


def shuffle_candidates(
    candidates: list[int], *, agent_seed: int, seat: int, state_version: int
) -> list[int]:
    out = list(candidates)
    random.Random(hash((agent_seed, seat, state_version))).shuffle(out)
    return out


def static_system_prompt(config: GameConfig, seat: int, role: RoleType) -> str:
    roles_desc = "、".join(f"{slot.role.value}x{slot.count}" for slot in config.roles)
    win = _WIN_TEXT.get(config.win_condition, str(config.win_condition))
    sheriff = "启用警长（1.5 票与发言顺序权）" if config.sheriff.enabled else "无警长"
    return (
        "你在玩狼人杀。服务器是唯一裁决者，你只提交意图。\n"
        f"本局配置：{config.num_players} 人（{roles_desc}）；胜利条件：{win}；{sheriff}。\n"
        f"你是 {seat} 号，角色：{role.value}。{ROLE_BRIEFS[role]}\n"
        "发言用中文，符合角色立场；狼人白天绝不能泄露夜间的私下谋划。"
    )


def _alive_others(obs: PlayerObservation) -> list[int]:
    return [
        s["seat"] for s in obs.seats if s.get("alive") and s.get("seat") != obs.my_seat
    ]


def candidates_for(kind: DecisionKind, obs: PlayerObservation) -> list[int]:
    if kind is DecisionKind.VOTE and obs.vote_candidates:
        return list(obs.vote_candidates)
    if kind is DecisionKind.SHERIFF and obs.sheriff_candidates:
        return list(obs.sheriff_candidates)
    if kind is DecisionKind.SPEECH:
        return []
    return _alive_others(obs)


def _render_observation(obs: PlayerObservation) -> str:
    alive = [s["seat"] for s in obs.seats if s.get("alive")]
    lines = [
        f"第 {obs.round} 轮，阶段 {obs.phase}。存活座位：{alive}。",
        f"警长：{obs.sheriff_seat if obs.sheriff_seat is not None else '无'}。",
    ]
    if obs.election_stage:
        lines.append(f"竞选子阶段：{obs.election_stage}；候选人：{obs.sheriff_candidates}。")
    if obs.badge_flow_claims:
        lines.append(f"公开警徽流声明：{obs.badge_flow_claims}。")
    priv = {k: v for k, v in obs.private.items() if k != "wolf_chat"}
    if priv:
        lines.append(f"你的私有信息：{priv}。")
    return "\n".join(lines)


def _instruction_for(kind: DecisionKind, obs: PlayerObservation, cands: list[int]) -> str:
    cand_text = f"候选座位（顺序无含义）：{cands}。" if cands else ""
    body: dict[DecisionKind, str] = {
        DecisionKind.NIGHT: "给出夜间/开枪行动：action_type 与 target_seat（可 skip）。",
        DecisionKind.SPEECH: (
            "给出你的发言 content；可选声称身份 claim_role、报警徽流 badge_flow；"
            "狼人可选 self_destruct 自爆。"
        ),
        DecisionKind.VOTE: "投票放逐一人（target_seat）或弃票（abstain=true）。",
        DecisionKind.SHERIFF: (
            "警长相关决策：按当前子阶段给出 action_type"
            "（run_for_sheriff/withdraw/vote_sheriff/pass_badge/tear_badge/set_speech_direction）"
            "及必要的 target_seat 或 direction。"
        ),
    }
    return f"{body[kind]}\n{cand_text}\n先在 reasoning 中简短推理。{_SELF_CHECK}"


def build_prompt(
    kind: DecisionKind,
    obs: PlayerObservation,
    memory_context: str,
    *,
    agent_seed: int,
) -> str:
    """昼间与非狼夜间决策的 user prompt。注意：本函数拿不到 night_private 分区。"""
    cands = shuffle_candidates(
        candidates_for(kind, obs),
        agent_seed=agent_seed,
        seat=obs.my_seat,
        state_version=obs.state_version,
    )
    return (
        f"== 局势 ==\n{_render_observation(obs)}\n\n"
        f"== 你的记忆 ==\n{memory_context or '（暂无）'}\n\n"
        f"== 本次决策 ==\n{_instruction_for(kind, obs, cands)}"
    )


def build_wolf_night_prompt(
    obs: PlayerObservation,
    memory_context: str,
    night_private_context: str,
    *,
    agent_seed: int,
) -> str:
    """狼人夜间私有推理调用的 user prompt —— 唯一能接收私有分区的装配函数。"""
    teammates: Any = obs.private.get("teammates", [])
    cands = shuffle_candidates(
        candidates_for(DecisionKind.WOLF_NIGHT, obs),
        agent_seed=agent_seed,
        seat=obs.my_seat,
        state_version=obs.state_version,
    )
    proposal = obs.private.get("tonight_kill_proposal")
    proposal_line = f"队友已提议刀 {proposal} 号。\n" if proposal is not None else ""
    return (
        f"== 局势 ==\n{_render_observation(obs)}\n\n"
        f"== 你的记忆 ==\n{memory_context or '（暂无）'}\n\n"
        f"== 狼队私有 ==\n你的队友座位：{teammates}。\n{proposal_line}"
        f"{night_private_context or '（无历史私谋）'}\n\n"
        f"== 本次决策 ==\n分析局势（analysis）并提议今晚击杀目标 proposed_target。"
        f"候选座位（顺序无含义）：{cands}。{_SELF_CHECK}"
    )
```

注：`config.roles` 元素字段名（`role`/`count`）与 `config.sheriff.enabled`、`config.win_condition` 以 `app/engine/config.py` 实际定义为准——实现前先读该文件，字段不同则同义替换，测试断言随之核对。

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_agent_prompts.py -q` → PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/agent/prompts.py tests/test_agent_prompts.py
git commit -m "feat(agent): 三段式 prompt 装配 + 候选确定性洗牌；昼间装配签名隔离私有分区 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: agent_player.py —— AgentPlayerPort（端口实现，狼夜独立调用）

**Files:**
- Create: `backend/app/agent/agent_player.py`
- Test: `backend/tests/test_agent_player.py`

**Interfaces:**
- Consumes: Task 2-5 全部；`app.runtime.player_port.PlayerPort` 的鸭子契约（**不 import runtime**，只实现同签名 `act`）
- Produces:
  - `class AgentConfig(BaseModel)`: `model: str = DEFAULT_MODEL, model_speech: str | None = None, reflection_model: str | None = None, temperature: float = 0.3, agent_seed: int = 0, deadline_margin_s: float = 2.0, reflection_min_remaining_s: float = 10.0`
  - `class AgentPlayerPort`:
    - `__init__(self, seat: int, game_config: GameConfig, agent_config: AgentConfig, client: LLMClient, memory: AgentMemory | None = None)`
    - `async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action`
    - `async def on_events(self, events: list[Event]) -> None`（转发 memory；Task 7 的订阅点）
    - `memory: AgentMemory`（公开属性，测试/接线用）
  - `build_agent_port(seat: int, game_config: GameConfig, ai_model: str, ai_model_speech: str | None) -> AgentPlayerPort`（Task 7 registry 默认工厂；内部构造 `LiteLLMInstructorClient`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_player.py`：

```python
"""AgentPlayerPort（issue #31 Task 6）：决策流、狼夜两段隔离、超时边际、模型路由。零网络。"""

import time

import pytest
from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.decisions import (
    NightDecision,
    SpeechDecision,
    VoteDecision,
    WolfDeliberation,
)
from app.engine.actions import NightAction, NightActionType, Speak
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation
from tests.llm_helpers import ScriptedLLMClient

SECRET = "夜间私谋：今晚刀3号，明天悍跳"


def _obs(phase: str, *, seat: int = 0, role: RoleType = RoleType.WEREWOLF, **kw) -> PlayerObservation:
    return PlayerObservation(
        game_id="g_a",
        state_version=kw.pop("state_version", 10),
        my_seat=seat,
        my_role=role,
        my_status="ALIVE",
        phase=phase,
        round=kw.pop("round", 1),
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private=kw.pop("private", {"teammates": [4, 7]}),
        available_actions=[seat],
        **kw,
    )


def _port(script, *, agent_config: AgentConfig | None = None) -> tuple[AgentPlayerPort, ScriptedLLMClient]:
    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side"),
        agent_config=agent_config or AgentConfig(model="scripted"),
        client=client,
    )
    return port, client


async def test_speech_act_maps_to_speak() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        assert rm is SpeechDecision
        assert "0 号" in system or "0 号" in user or "0" in system  # 静态段含座位
        return SpeechDecision(reasoning="r", content="我是好人")

    port, client = _port(script)
    action = await port.act(_obs("DAY_SPEECH"), time.time() + 30)
    assert action == Speak(actor_seat=0, content="我是好人", claim_role=None, badge_flow=())
    assert len(client.calls) == 1


async def test_wolf_night_then_day_isolation() -> None:
    """核心隔离测试：狼夜私谋文本绝不出现在任何昼间 prompt 中。"""

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is WolfDeliberation:
            assert "队友" in user  # 狼夜 prompt 含私有段
            return WolfDeliberation(analysis=SECRET, proposed_target=3)
        assert rm is VoteDecision or rm is SpeechDecision
        if rm is VoteDecision:
            return VoteDecision(reasoning="r", target_seat=3)
        return SpeechDecision(reasoning="r", content="昨晚平安夜")

    port, client = _port(script)
    kill = await port.act(_obs("NIGHT_WEREWOLF"), time.time() + 30)
    assert kill == NightAction(actor_seat=0, action_type=NightActionType.KILL, target_seat=3)
    assert SECRET in port.memory.night_private_context()

    await port.act(_obs("DAY_SPEECH", state_version=11), time.time() + 30)
    await port.act(_obs("VOTE", state_version=12), time.time() + 30)

    wolf_calls = [c for c in client.calls if SECRET in c[2]]
    assert len(wolf_calls) == 1  # 只有狼夜那一次调用见得到私谋
    for model, system, user in client.calls[1:]:
        assert SECRET not in user and SECRET not in system


async def test_night_role_uses_night_model_speech_uses_speech_model() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is NightDecision:
            return NightDecision(reasoning="r", action_type=NightActionType.CHECK, target_seat=2)
        return SpeechDecision(reasoning="r", content="hi")

    cfg = AgentConfig(model="night-model", model_speech="speech-model")
    port, client = _port(script, agent_config=cfg)
    await port.act(_obs("NIGHT_SEER", role=RoleType.SEER, private={}), time.time() + 30)
    await port.act(
        _obs("DAY_SPEECH", role=RoleType.SEER, private={}, state_version=11), time.time() + 30
    )
    assert client.calls[0][0] == "night-model"
    assert client.calls[1][0] == "speech-model"


async def test_deadline_margin_raises_without_llm_call() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise AssertionError("不应发起 LLM 调用")

    port, client = _port(script)
    with pytest.raises(TimeoutError):
        await port.act(_obs("DAY_SPEECH"), time.time() + 1.0)  # 剩余 < margin 2s
    assert client.calls == []


async def test_llm_exception_propagates() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise RuntimeError("provider down")

    port, _ = _port(script)
    with pytest.raises(RuntimeError, match="provider down"):
        await port.act(_obs("DAY_SPEECH"), time.time() + 30)


async def test_lazy_reflection_runs_before_decision_when_time_allows() -> None:
    from app.agent.memory import ReflectionQA, ReflectionResult
    from app.engine.events import EventType, RoundStartedPayload, Visibility
    from app.engine.events import Event as Ev

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is ReflectionResult:
            return ReflectionResult(summary="首轮总结", qa=[ReflectionQA(question="q", answer="a")])
        return SpeechDecision(reasoning="r", content="ok")

    port, client = _port(script)
    for rnd, seq in ((1, 1), (2, 2)):
        await port.on_events(
            [
                Ev(
                    seq=seq,
                    game_id="g_a",
                    ts=float(seq),
                    type=EventType.ROUND_STARTED,
                    actor_seat=None,
                    payload=RoundStartedPayload(round=rnd),
                    visibility=Visibility.PUBLIC,
                )
            ]
        )
    await port.act(_obs("DAY_SPEECH", round=2), time.time() + 60)
    assert len(client.calls) == 2  # 反思 + 决策
    assert "首轮总结" in client.calls[1][2]  # 反思摘要进了决策 prompt 的记忆段
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_player.py -q`
Expected: FAIL —— `app.agent.agent_player` 不存在

- [ ] **Step 3: 实现**

`backend/app/agent/agent_player.py`：

```python
"""AgentPlayerPort：LLM Agent 的 PlayerPort 实现（issue #31）。

诚实观察者：只凭 observation 与订阅到的可见事件决策，不触碰引擎 state。
活性兜底完全由 runner 持有（异常/超时 → 默认行动）；本端口零兜底逻辑，
LLM 任何失败一律上抛。狼夜私有推理是独立调用，产出只进 night_private 分区。
"""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from app.agent.decisions import (
    DecisionKind,
    WolfDeliberation,
    decision_kind_for,
    response_model_for,
    to_action,
)
from app.agent.llm_client import DEFAULT_MODEL, LLMClient
from app.agent.memory import AgentMemory
from app.agent.prompts import build_prompt, build_wolf_night_prompt, static_system_prompt
from app.engine.actions import Action
from app.engine.config import GameConfig
from app.engine.events import Event
from app.engine.observation import PlayerObservation


class AgentConfig(BaseModel):
    model: str = DEFAULT_MODEL
    model_speech: str | None = None  # §8.3 分层路由落点：发言用（可更强的）模型
    reflection_model: str | None = None
    temperature: float = 0.3
    agent_seed: int = 0
    deadline_margin_s: float = 2.0  # 剩余时间低于此不再发起 LLM 调用
    reflection_min_remaining_s: float = 10.0  # 剩余时间高于此才做惰性反思


class AgentPlayerPort:
    def __init__(
        self,
        seat: int,
        game_config: GameConfig,
        agent_config: AgentConfig,
        client: LLMClient,
        memory: AgentMemory | None = None,
    ) -> None:
        self._seat = seat
        self._game_config = game_config
        self._cfg = agent_config
        self._client = client
        self.memory = memory if memory is not None else AgentMemory(seat)
        self._system_prompt: str | None = None  # 静态段按首个 observation 的角色惰性生成

    async def on_events(self, events: list[Event]) -> None:
        await self.memory.on_events(events)

    def _system_for(self, obs: PlayerObservation) -> str:
        if self._system_prompt is None:
            self._system_prompt = static_system_prompt(self._game_config, self._seat, obs.my_role)
        return self._system_prompt

    def _model_for(self, kind: DecisionKind) -> str:
        if kind is DecisionKind.SPEECH and self._cfg.model_speech is not None:
            return self._cfg.model_speech
        return self._cfg.model

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        remaining = deadline_ts - time.time()
        if remaining <= self._cfg.deadline_margin_s:
            raise TimeoutError(f"座位 {self._seat} 行动窗口剩余不足（{remaining:.1f}s）")

        # 惰性反思：只在时间宽裕时补做，失败由 memory 内部降级
        if (
            remaining > self._cfg.reflection_min_remaining_s
            and self.memory.rounds_needing_reflection()
        ):
            await self.memory.reflect(
                self._client,
                self._cfg.reflection_model or self._cfg.model,
                self._cfg.temperature,
            )

        kind = decision_kind_for(observation)
        if kind is DecisionKind.WOLF_NIGHT:
            user_prompt = build_wolf_night_prompt(
                observation,
                self.memory.build_context(),
                self.memory.night_private_context(),
                agent_seed=self._cfg.agent_seed,
            )
        else:
            # 注意：这条路径拿不到 night_private —— 公私分离
            user_prompt = build_prompt(
                kind,
                observation,
                self.memory.build_context(),
                agent_seed=self._cfg.agent_seed,
            )

        budget = deadline_ts - time.time() - self._cfg.deadline_margin_s
        if budget <= 0:
            raise TimeoutError(f"座位 {self._seat} 装配后已无调用预算")
        decision = await asyncio.wait_for(
            self._client.complete_structured(
                system_prompt=self._system_for(observation),
                user_prompt=user_prompt,
                response_model=response_model_for(kind),
                model=self._model_for(kind),
                temperature=self._cfg.temperature,
            ),
            timeout=budget,
        )
        if isinstance(decision, WolfDeliberation):
            self.memory.note_night_private(decision.analysis, observation.round)
        return to_action(kind, decision, observation.my_seat)


def build_agent_port(
    seat: int, game_config: GameConfig, ai_model: str, ai_model_speech: str | None
) -> AgentPlayerPort:
    """registry 默认工厂：真实 LiteLLM 客户端 + 按 GameConfig.seed 派生 agent_seed。"""
    from app.agent.llm_client import LiteLLMInstructorClient

    return AgentPlayerPort(
        seat=seat,
        game_config=game_config,
        agent_config=AgentConfig(
            model=ai_model,
            model_speech=ai_model_speech,
            agent_seed=game_config.seed if game_config.seed is not None else 0,
        ),
        client=LiteLLMInstructorClient(),
    )
```

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_agent_player.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/agent/agent_player.py tests/test_agent_player.py
git commit -m "feat(agent): AgentPlayerPort——狼夜独立私有调用、超时边际、模型分层路由 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 接线 —— ai_model 建局字段、registry 注入、memory 订阅 + 全 Agent 集成测试

**Files:**
- Modify: `backend/app/runtime/player_port.py`（追加 `SupportsEventIngest` Protocol）
- Modify: `backend/app/runtime/registry.py`（GameHandle/create/start）
- Modify: `backend/app/schemas/games.py`（CreateGameRequest 两个新字段）
- Modify: `backend/app/api/rest.py`（create 端点透传）
- Test: `backend/tests/test_agent_integration.py`

**Interfaces:**
- Consumes: Task 6 `AgentPlayerPort`/`build_agent_port`；Task 3 `ScriptedLLMClient`、`action_to_decision`
- Produces:
  - `player_port.SupportsEventIngest`（runtime_checkable Protocol）: `async def on_events(self, events: list[Event]) -> None`
  - `GameHandle.__init__` 增 `ai_model: str | None = None, ai_model_speech: str | None = None`（存为同名属性）
  - `GameRegistry.__init__(store, timeouts=None, agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None)`
  - `GameRegistry.create(config, *, allow_spectators, num_ai_players=None, ai_model=None, ai_model_speech=None)`
  - `CreateGameRequest` 增 `ai_model: str | None = None`、`ai_model_speech: str | None = None`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_agent_integration.py`：

```python
"""全 Agent 集成（issue #31 Task 7）：9 座全 AgentPlayerPort 经真 runner 跑到终局。

脚本客户端"全知"取 runner state 只为产出合法决策（测试域白盒），
被测路径（AgentPlayerPort → prompts → runner）本身仍只见 observation。
"""

import asyncio

from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.memory import ReflectionResult
from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.phases import Phase
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.registry import GameHandle, GameRegistry
from app.runtime.player_port import PlayerPort
from app.store.event_store import InMemoryEventStore
from tests.llm_helpers import ScriptedLLMClient, action_to_decision

TIMEOUTS = RunnerTimeouts(speech_sec=30.0, action_sec=30.0)


def _omniscient_script(handle: GameHandle, seat: int):
    """RandomBot 的合法行动 → 决策模型逆映射；反思调用返回固定摘要。"""

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is ReflectionResult:
            return ReflectionResult(summary="(scripted reflect)", qa=[])
        assert handle.runner is not None
        action = RandomBot.choose_action(handle.runner.state, seat)
        return action_to_decision(action, rm)

    return script


def _make_registry(broken_seat: int | None = None) -> GameRegistry:
    holder: dict[str, GameHandle] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        holder.setdefault("h", handle)
        if seat == broken_seat:

            def boom(rm: type[BaseModel], system: str, user: str) -> BaseModel:
                raise RuntimeError("agent LLM 永久故障")

            client = ScriptedLLMClient(boom)
        else:
            client = ScriptedLLMClient(_omniscient_script(handle, seat))
        return AgentPlayerPort(
            seat=seat,
            game_config=handle.config,
            agent_config=AgentConfig(model="scripted", agent_seed=7),
            client=client,
        )

    return GameRegistry(InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory)


async def _run_full_game(registry: GameRegistry) -> GameHandle:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(
        config, allow_spectators=False, num_ai_players=None, ai_model="scripted"
    )
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER
    return handle


async def test_all_agent_game_reaches_game_over_and_memory_ingests() -> None:
    handle = await _run_full_game(_make_registry())
    # 每个座位都是 AgentPlayerPort 且 memory 确有摄入（订阅接线生效）
    for seat, port in handle.ports.items():
        assert isinstance(port, AgentPlayerPort), f"座位 {seat} 不是 AgentPlayerPort"
        assert port.memory.entries, f"座位 {seat} memory 未摄入任何事件"
    # 隔离抽查：非狼座位的 memory 不含 WOLVES 事件
    from app.engine.config import Faction

    assert handle.runner is not None
    state = handle.runner.state
    for p in state.players:
        if p.faction != Faction.WOLF:
            port = handle.ports[p.seat]
            assert isinstance(port, AgentPlayerPort)
            kinds = {e.kind for e in port.memory.entries}
            assert "WOLF_KILL_PROPOSED" not in kinds
            assert "WOLF_KILL_DECIDED" not in kinds


async def test_broken_agent_falls_back_to_default_and_game_completes() -> None:
    await _run_full_game(_make_registry(broken_seat=0))  # 0 号 LLM 永久故障仍收敛


async def test_ai_model_none_keeps_bot_fill() -> None:
    registry = GameRegistry(InMemoryEventStore(), TIMEOUTS)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = registry.create(config, allow_spectators=False)
    registry.start(handle, fill_with_bots=True)
    assert handle.task is not None
    from app.runtime.player_port import BotPlayerPort

    assert all(isinstance(p, BotPlayerPort) for p in handle.ports.values())
    state = await asyncio.wait_for(handle.task, timeout=120)
    assert state.phase == Phase.GAME_OVER


def test_create_game_request_accepts_ai_model() -> None:
    from app.schemas.games import CreateGameRequest

    req = CreateGameRequest(ai_model="ollama/llama3.1", ai_model_speech="ollama/qwen2.5")
    assert req.ai_model == "ollama/llama3.1"
    assert CreateGameRequest().ai_model is None  # 默认关（现有行为零变化）
```

注：`InMemoryEventStore` 的 import 路径以 `app/store/` 实际模块名为准（Task 执行者先 `grep -rn "class InMemoryEventStore" app/store/`）。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_integration.py -q`
Expected: FAIL —— `GameRegistry.__init__` 无 `agent_port_factory` / `create` 无 `ai_model`

- [ ] **Step 3: 实现**

3a. `app/runtime/player_port.py` 追加（import 区补 `from app.engine.events import Event`）：

```python
@runtime_checkable
class SupportsEventIngest(Protocol):
    """可摄入可见事件流的端口能力（AgentPlayerPort 实现；registry 据此订阅 memory）。"""

    async def on_events(self, events: list[Event]) -> None: ...
```

3b. `app/runtime/registry.py`：

- `GameHandle.__init__` 增参数并存属性：

```python
        ai_model: str | None = None,
        ai_model_speech: str | None = None,
```

- `GameRegistry.__init__` 增 `agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None`（import 区补 `from collections.abc import Callable`），存 `self._agent_port_factory`。
- `create(...)` 增 `ai_model: str | None = None, ai_model_speech: str | None = None` 透传给 `GameHandle`。
- `start(...)` 的空位填充改为：

```python
        for seat in range(handle.config.num_players):
            if seat not in handle.ports:
                if handle.ai_model is None:
                    handle.ports[seat] = BotPlayerPort(state_provider=_state_of)
                else:
                    handle.ports[seat] = self._build_agent_port(seat, handle)
```

- runner 创建之后、`asyncio.create_task` 之前，订阅事件摄入端口（此时 `handle.connections` 已建）：

```python
        for seat, port in handle.ports.items():
            if isinstance(port, SupportsEventIngest):
                handle.connections.subscribe(seat, port.on_events)
```

（import 区补 `SupportsEventIngest`。订阅必须在 `create_task(runner.run())` 之前完成，否则漏 GAME_CREATED/ROLES_ASSIGNED 首批事件。）

- 新增私有方法（默认工厂惰性 import，避免无 agent 路径背 litellm 的导入开销）：

```python
    def _build_agent_port(self, seat: int, handle: GameHandle) -> PlayerPort:
        if self._agent_port_factory is not None:
            return self._agent_port_factory(seat, handle)
        from app.agent.agent_player import build_agent_port  # 惰性：litellm 仅在需要时加载

        assert handle.ai_model is not None
        return build_agent_port(seat, handle.config, handle.ai_model, handle.ai_model_speech)
```

3c. `app/schemas/games.py` 的 `CreateGameRequest` 追加：

```python
    ai_model: str | None = None  # 设置后空位由 LLM Agent 填充（None=沿用 RandomBot）
    ai_model_speech: str | None = None  # 发言层模型（None=同 ai_model；PRD §8.3 分层路由）
```

3d. `app/api/rest.py` 的 `create_game_endpoint` 中 `games.create(...)` 调用补：

```python
        ai_model=req.ai_model,
        ai_model_speech=req.ai_model_speech,
```

- [ ] **Step 4: 跑测试 + 全量回归 + 质量门**

Run: `uv run pytest tests/test_agent_integration.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS（现有 registry/API 测试不受默认值影响）
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/runtime/player_port.py app/runtime/registry.py app/schemas/games.py app/api/rest.py tests/test_agent_integration.py
git commit -m "feat(runtime,api): ai_model 建局字段——registry 注入 AgentPlayerPort 并订阅 memory (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: smoke 测试（env 门控真 Ollama）+ marker 注册

**Files:**
- Modify: `backend/pyproject.toml`（注册 `smoke` marker）
- Test: `backend/tests/test_agent_smoke.py`

**Interfaces:**
- Consumes: Task 6 `AgentPlayerPort`/`AgentConfig`/`LiteLLMInstructorClient`
- Produces: 无（叶子任务）

- [ ] **Step 1: 注册 marker**

`pyproject.toml` 的 `[tool.pytest.ini_options]` 追加：

```toml
markers = [
    "smoke: 真模型冒烟测试（需 AGENTHOWL_SMOKE_MODEL 环境变量且 Ollama 端点可达）",
]
```

- [ ] **Step 2: 写 smoke 测试（默认自跳过，CI 零影响）**

`backend/tests/test_agent_smoke.py`：

```python
"""真模型冒烟（issue #31 Task 8）：一次真实夜间行动 + 一次真实发言。

默认跳过；本地跑法：
    ollama pull llama3.1 && ollama serve &
    AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke -q
"""

import os
import time

import httpx
import pytest

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.llm_client import LiteLLMInstructorClient
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation

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


def _obs(phase: str, role: RoleType, private: dict) -> PlayerObservation:
    return PlayerObservation(
        game_id="g_smoke",
        state_version=1,
        my_seat=0,
        my_role=role,
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private=private,
        available_actions=[0],
    )


def _port(role_seed: int) -> AgentPlayerPort:
    assert SMOKE_MODEL is not None
    return AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side").model_copy(update={"seed": role_seed}),
        agent_config=AgentConfig(model=SMOKE_MODEL, agent_seed=role_seed),
        client=LiteLLMInstructorClient(),
    )


async def test_real_wolf_night_action() -> None:
    from app.engine.actions import NightAction, NightActionType

    port = _port(1)
    action = await port.act(
        _obs("NIGHT_WEREWOLF", RoleType.WEREWOLF, {"teammates": [4, 7]}),
        time.time() + 120,
    )
    assert isinstance(action, NightAction)
    assert action.action_type == NightActionType.KILL
    assert action.target_seat in range(9)
    assert port.memory.night_private_context()  # 私有推理已入分区


async def test_real_speech() -> None:
    from app.engine.actions import SelfDestruct, Speak

    port = _port(2)
    action = await port.act(_obs("DAY_SPEECH", RoleType.VILLAGER, {}), time.time() + 120)
    # 真模型偶发 self_destruct=true 也算合法映射；主断言是结构化输出成功
    assert isinstance(action, Speak | SelfDestruct)
    if isinstance(action, Speak):
        assert action.content.strip()
```

- [ ] **Step 3: 验证默认跳过 + 质量门**

Run: `uv run pytest tests/test_agent_smoke.py -q`
Expected: 2 skipped（env 未设）
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS + 2 skipped
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

（若本机已起 Ollama，可选实跑：`AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke -q`——不作为任务通过条件，弱模型结构化输出可能需 instructor 重试，耗时数十秒属正常。）

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/test_agent_smoke.py
git commit -m "test(agent): env 门控真模型冒烟——一次夜间行动 + 一次发言 (issue #31)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 计划外但相关（不做，另立/已立 issue）

- **#39 WS 崩溃可观测性**（"before M2.4"标记项）：与本计划正交（agent 走进程内 port，不经 WS）；仍留在 #39 单独处理
- 多轮狼人群聊事件、Sentence-BERT 记忆、token 预算硬闸、AFK 接管：见规格 YAGNI 清单

## Self-Review 记录

- **规格覆盖**：决策摘要 5 项 → Task 3（Ollama/JSON mode）、Task 6-7（进程内 port）、Task 8（env 门控）、Task 5-6（狼夜单次私有调用）、Task 4（反思并入 Completeness）。模块划分 5 文件 → Task 2-6 一一对应；接线增量 → Task 7；observation 缺口 → Task 1（规格"引擎小 PR"条款的落点，随本分支一并评审）。硬约束 4 条 → Global Constraints + Task 5/6 隔离测试 + Task 7 惰性 import。
- **占位符扫描**：无 TBD/TODO；两处"以实际定义为准"是对既有代码字段名的核对指令（附核对命令），非实现留白。
- **类型一致性**：`complete_structured` 关键字签名在 Task 3/4/6/8 一致；`ScriptedLLMClient.calls` 三元组 (model, system, user) 在 Task 6 测试的解构顺序一致；`AgentMemory` 公开方法名在 Task 4/6/7 一致；`agent_port_factory(seat, handle)` 与 Task 7 测试闭包签名一致。
