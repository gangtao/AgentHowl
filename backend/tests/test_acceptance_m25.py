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
    with agent_client.websocket_connect(f"/api/v1/ws?token={created['spectator_token']}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "game_over":
                break
    assert frames[0]["type"] == "game_event" and frames[0]["event"]["type"] == "GAME_CREATED"

    # 每个座位确为 AgentPlayerPort（DI 钩子生效，非 RandomBot 填充）
    handle = agent_client.app.state.games.get(gid)  # type: ignore[attr-defined]
    assert handle.ports and all(isinstance(p, AgentPlayerPort) for p in handle.ports.values())
    # replay 终局一致
    replay = agent_client.get(
        f"/api/v1/games/{gid}/replay", headers=_auth(created["spectator_token"])
    ).json()
    assert replay[-1]["type"] == "GAME_OVER"
    _wait_done(agent_client, gid)
