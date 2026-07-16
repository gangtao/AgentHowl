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
