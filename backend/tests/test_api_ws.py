"""WS 端点：观战流隔离、真人经 WS 对局、重连补发（issue #30）。"""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.cli.bot import RandomBot
from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore
from tests.test_api_play import _auth, _start_ai_game, _to_tool_call


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0)
    )
    with TestClient(app) as c:
        yield c


def test_spectator_stream_public_only_until_game_over(client: TestClient) -> None:
    gid, created = _start_ai_game(client, seed=42)
    frames: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={created['spectator_token']}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "game_over":
                break
    events = [f for f in frames if f["type"] == "game_event"]
    assert events and all(f["event"]["visibility"] == "PUBLIC" for f in events)
    assert any(
        f["type"] == "phase_change" for f in frames
    )  # PUBLIC 的 PHASE_CHANGED 存在（如 VOTE）
    assert frames[-1]["winner"] in ("GOOD", "WOLF", None)


def test_unknown_token_closes_4401(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/ws?token=garbage") as ws,
    ):
        ws.receive_json()


def test_human_plays_whole_game_via_ws(client: TestClient) -> None:
    created = client.post("/api/v1/games", json={"config_override": {"seed": 42}}).json()
    gid = created["game_id"]
    joined = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Alice"}).json()
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    seat = joined["seat"]
    with client.websocket_connect(f"/api/v1/ws?token={joined['player_token']}") as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "game_over":
                break
            if frame["type"] == "your_turn":
                assert frame["observation"]["my_seat"] == seat
                action = RandomBot.choose_action(handle.runner.state, seat)
                ws.send_json(_to_tool_call(action))
            if frame["type"] == "action_result":
                assert frame["ok"], frame["rejected_reason"]
    assert handle.task.done() and handle.task.result().winner is not None


def test_reconnect_backfills_from_seq(client: TestClient) -> None:
    gid, created = _start_ai_game(client, seed=7)
    spec = created["spectator_token"]
    # 等对局结束后模拟"错过整场"的重连：from_seq 补发应与 REST /events 完全一致
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not handle.task.done() and time.time() < deadline:
        time.sleep(0.05)
    rest_events = client.get(f"/api/v1/games/{gid}/events?from_seq=5", headers=_auth(spec)).json()
    got: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={spec}&from_seq=5") as ws:
        # 补发帧中夹带 phase_change/game_over 派生帧（不计入 rest_events），故按
        # game_event 数量而非固定收帧次数收敛——原按 len(rest_events) 收帧次数的写法
        # 在派生帧存在时会提前耗尽收帧配额，属测试自身计数缺陷，非 ws.py 实现问题。
        while len(got) < len(rest_events):
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                got.append(frame["event"])
    assert [e["seq"] for e in got] == [e["seq"] for e in rest_events]
