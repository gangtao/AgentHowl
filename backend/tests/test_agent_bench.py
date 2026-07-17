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
