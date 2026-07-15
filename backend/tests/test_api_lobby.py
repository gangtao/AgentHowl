"""REST 大厅端点：create/join/start 与鉴权（issue #30）。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
    )
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_join_start_all_ai(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 42}}
    )
    assert r.status_code == 200
    body = r.json()
    gid, host = body["game_id"], body["host_token"]
    assert body["spectator_token"] and body["config"]["seed"] == 42

    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host))
    assert r.status_code == 200 and r.json()["num_players"] == 9

    # 全 AI 局在后台事件循环中跑完（TestClient 事件循环在后台线程，轮询 task 即可）
    registry = client.app.state.games  # type: ignore[attr-defined]
    handle = registry.get(gid)
    import time as _t

    deadline = _t.time() + 30
    while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
        _t.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    assert handle.task.result().winner is not None


def test_join_assigns_seats_and_tokens(client: TestClient) -> None:
    gid = client.post("/api/v1/games", json={"config_override": {"seed": 7}}).json()["game_id"]
    r1 = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Alice"})
    r2 = client.post(
        f"/api/v1/games/{gid}/join", json={"display_name": "Bot 客户端", "player_type": "AGENT"}
    )
    assert r1.json()["seat"] == 0 and r2.json()["seat"] == 1
    assert r1.json()["player_token"] != r2.json()["player_token"]
    assert r1.json()["ws_url"].startswith("/api/v1/ws?token=")


def test_start_requires_host_token(client: TestClient) -> None:
    created = client.post("/api/v1/games", json={"config_override": {"seed": 3}}).json()
    gid = created["game_id"]
    player = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "A"}).json()

    assert client.post(f"/api/v1/games/{gid}/start", json={}).status_code == 401  # 无 token
    assert (
        client.post(
            f"/api/v1/games/{gid}/start", json={}, headers=_auth(player["player_token"])
        ).status_code
        == 403
    )  # 玩家 token 非 HOST
    assert (
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth("garbage")).status_code
        == 401
    )
    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    assert r.status_code == 200
    # 重复开局 → 409；开局后加入 → 409
    assert (
        client.post(
            f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"])
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Late"}).status_code == 409
    )


def test_bad_preset_400_unknown_game_404(client: TestClient) -> None:
    assert client.post("/api/v1/games", json={"preset": "no_such"}).status_code == 400
    created = client.post("/api/v1/games", json={}).json()
    assert (
        client.post(
            "/api/v1/games/g_nope/start", json={}, headers=_auth(created["host_token"])
        ).status_code
        == 404
    )


def test_no_spectator_token_when_disabled(client: TestClient) -> None:
    body = client.post("/api/v1/games", json={"allow_spectators": False}).json()
    assert body["spectator_token"] is None
