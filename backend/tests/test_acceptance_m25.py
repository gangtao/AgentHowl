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
from tests.test_api_play import _auth, _start_ai_game, _wait_done


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
def client() -> Iterator[TestClient]:
    """标准 RandomBot 填充 fixture（非 Task 1 的 agent_client）：供活 WS 隔离矩阵测试使用。"""
    app = create_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0)
    )
    with TestClient(app) as c:
        yield c


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
    assert all(e["actor_seat"] == villager_seat for e in vill_ev if e["visibility"] == "ROLE_SELF")
    # 观战流纯 PUBLIC
    assert all(e["visibility"] == "PUBLIC" for e in spec_ev)
