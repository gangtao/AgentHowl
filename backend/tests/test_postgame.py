"""局后复盘编排（issue #59 终审 F1）：直接调用 run_postgame 验证真人座位 memory_id 隔离。"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from app.agent.agent_player import AgentConfig, AgentPlayerPort
from app.agent.experience import GameReflection
from app.agent.memory import ReflectionResult
from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.engine.config import build_preset
from app.runtime.experience_store import InMemoryExperienceStore
from app.runtime.player_port import HumanPlayerPort
from app.runtime.postgame import run_postgame
from tests.llm_helpers import ScriptedLLMClient


def test_run_postgame_ignores_human_occupied_memory_id() -> None:
    """座位 0 配了 memory_id="alice" 但由真人端口占用：不复盘、不 load/save alice。

    座位 1（bob）的复盘笔记里也不应出现对 0 号的观察——0 号不算「有 memory_id 的对手」。
    """
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    state, _events = run_game(config, "g1")
    store = InMemoryExperienceStore()
    captured: dict[str, str] = {}

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is ReflectionResult:
            return ReflectionResult(summary="(r)", qa=[])
        assert rm is GameReflection
        captured["user"] = user
        # 脚本"越权"给 0 号记笔记：即便如此也不该落到 bob 的 opponent_notes 里
        return GameReflection(lessons=["ok"], opponent_notes={0: ["x"]})

    agent1 = AgentPlayerPort(
        seat=1,
        game_config=config,
        agent_config=AgentConfig(model="scripted", agent_seed=1),
        client=ScriptedLLMClient(script),
        experience=None,
        opponents={},
    )
    ports = {0: HumanPlayerPort(), 1: agent1}
    profiles = {
        "0": AgentProfile(model="m", memory_id="alice"),
        "1": AgentProfile(model="m", memory_id="bob"),
    }
    updated = asyncio.run(
        run_postgame(game_id="g1", final_state=state, profiles=profiles, ports=ports, store=store)
    )
    assert set(updated) == {"bob"} and store.saves == 1
    assert store.load("bob").opponent_notes == {}  # 越权笔记被过滤：0 号不是有记忆的对手
    assert "记笔记：（无）" in captured["user"]  # notable_seats 里不含真人座位
