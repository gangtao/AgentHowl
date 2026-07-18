"""CLI LLM 自对局冒烟（issue #44 Task 4）。默认跳过。

本地跑法：
    ollama pull llama3.1 && ollama serve &
    AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke tests/test_cli_smoke.py -q -s
"""

import asyncio
import os

import httpx
import pytest

from app.cli.play import run_watch
from app.engine.config import build_preset
from app.engine.phases import Phase

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


async def _no_read(prompt: str) -> str:
    raise AssertionError("看局不应读输入")


def test_cli_llm_self_play_watch(capsys: pytest.CaptureFixture[str]) -> None:
    assert SMOKE_MODEL is not None
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    state = asyncio.run(
        run_watch(
            config,
            view="GM",
            delay=0.0,
            step=False,
            ai_model=SMOKE_MODEL,
            read_line=_no_read,
        )
    )
    assert state.phase == Phase.GAME_OVER
    assert "游戏结束" in capsys.readouterr().out
