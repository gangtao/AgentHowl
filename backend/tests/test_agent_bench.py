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
    # _TokenMeter 鸭子实现 CustomLogger.async_log_success_event，挂到 litellm.callbacks
    # （异步成功事件的稳定接口）；此处 import CustomLogger 仅为语义标注钩子契约。
    _ = CustomLogger
    meter = _TokenMeter()
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


@pytest.mark.smoke
async def test_wolf_team_kill_skill_ab_smoke() -> None:
    """A/B 冒烟：wolf-team-kill 开/关各一局，打印狼队空刀率（不断言方向）。"""
    if not SMOKE_MODEL:
        pytest.skip("AGENTHOWL_SMOKE_MODEL 未设置")
    from app.agent.profile import AgentProfile
    from app.engine.events import EventType, WolfKillDecidedPayload

    rates: dict[str, float] = {}
    for label, skills in (("off", []), ("on", ["wolf-team-kill"])):
        registry = GameRegistry(
            InMemoryEventStore(), RunnerTimeouts(speech_sec=120.0, action_sec=120.0)
        )
        config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
        handle = registry.create(
            config,
            allow_spectators=False,
            agents={"*": AgentProfile(model=SMOKE_MODEL, skills=skills)},
        )
        registry.start(handle, fill_with_bots=True)
        assert handle.task is not None
        await asyncio.wait_for(handle.task, timeout=1800)
        events = registry.store.load_events(handle.game_id)
        decided = [e for e in events if e.type == EventType.WOLF_KILL_DECIDED]
        empties = sum(
            1
            for e in decided
            if isinstance(e.payload, WolfKillDecidedPayload) and e.payload.target is None
        )
        rates[label] = empties / max(1, len(decided))
    print(f"wolf-team-kill A/B 空刀率: {rates}")


async def test_personality_contrast_smoke() -> None:
    """一致性冒烟：同一 observation 下「多疑」vs「从众」两种人格各发言一次。

    打印长度与关键词，不断言方向。
    """
    import time

    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.llm_client import LiteLLMInstructorClient
    from app.agent.personality import PersonalitySpec
    from app.engine.config import RoleType
    from app.engine.observation import PlayerObservation

    assert SMOKE_MODEL is not None
    obs = PlayerObservation(
        game_id="bench",
        state_version=3,
        my_seat=2,
        my_role=RoleType.VILLAGER,
        my_status="ALIVE",
        phase="DAY_SPEECH",
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={0: (3, 5)},
        private={},
        available_actions=[2],
    )
    out: dict[str, str] = {}
    for label, traits in (("多疑", {"多疑": 0.9}), ("从众", {"从众": 0.9})):
        port = AgentPlayerPort(
            seat=2,
            game_config=build_preset("std_9_kill_side"),
            agent_config=AgentConfig(model=SMOKE_MODEL),
            client=LiteLLMInstructorClient(),
            personality=PersonalitySpec(traits=traits),
        )
        action = await port.act(obs, time.time() + 120)
        out[label] = getattr(action, "content", "")
    for label, text in out.items():
        has_gold = "金水" in text
        has_suspect = "怀疑" in text
        print(f"[{label}] len={len(text)} 含'金水'={has_gold} 含'怀疑'={has_suspect}: {text[:80]}")


async def test_ab_bench_smoke(tmp_path) -> None:
    """A（多疑 0.9）vs B（从众 0.9）各跑 1 局，打印指标表；不断言方向。"""
    from app.agent.personality import PersonalitySpec
    from app.agent.profile import AgentProfile
    from app.agent.skills import default_library
    from app.cli.bench import label_map, report, run_bench
    from app.store.event_store import JsonFileEventStore

    assert SMOKE_MODEL is not None
    a = {"*": AgentProfile(model=SMOKE_MODEL, personality=PersonalitySpec(traits={"多疑": 0.9}))}
    b = {"*": AgentProfile(model=SMOKE_MODEL, personality=PersonalitySpec(traits={"从众": 0.9}))}
    store = JsonFileEventStore(tmp_path / "bench")
    await run_bench(
        preset="std_9_kill_side", seed=3, games=2, a=a, b=b, library=default_library(), store=store
    )
    table, _doc = report(store, label_map(a, b, "多疑", "从众"))
    print("\n[ab-bench]\n" + table)
    assert "Δ(多疑−从众)" in table
