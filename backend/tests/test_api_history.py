"""历史列表与无 token 回放（issue #98）：重启（换 registry、同一 store）后仍可回放；
开关关则回到 401。"""

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore


def _app(store: InMemoryEventStore, public_history: bool | None = None) -> TestClient:
    app = create_app(
        store=store,
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
        public_history=public_history,
    )
    return TestClient(app)


def _play_to_end(client: TestClient, seed: int) -> dict:
    body = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": seed}}
    ).json()
    client.post(
        f"/api/v1/games/{body['game_id']}/start",
        json={},
        headers={"Authorization": f"Bearer {body['host_token']}"},
    )
    handle = client.app.state.games.get(body["game_id"])  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    return body


@pytest.fixture
def store() -> Iterator[InMemoryEventStore]:
    yield InMemoryEventStore()


def test_list_games_mixes_finished_and_live(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=3)
        pending = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()  # 未开局
        rows = c.get("/api/v1/games").json()
    by_id = {r["game_id"]: r for r in rows}
    assert by_id[done["game_id"]]["status"] == "finished"
    assert by_id[done["game_id"]]["winner"] in ("GOOD", "WOLF")
    assert pending["game_id"] not in by_id  # 未开局没有事件文件，不在列表里
    assert all("token" not in r for r in rows)


def test_finished_game_replays_without_token_after_restart(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=5)
    gid = done["game_id"]
    with _app(store) as c2:  # 新进程：registry/token 全空，只有 store
        assert c2.get("/api/v1/games").json()[0]["game_id"] == gid
        replay = c2.get(f"/api/v1/games/{gid}/replay")
        meta = c2.get(f"/api/v1/games/{gid}/meta")
        speeches = c2.get(f"/api/v1/games/{gid}/speeches")
        assert replay.status_code == 200 and replay.json()[-1]["type"] == "GAME_OVER"
        assert meta.status_code == 200 and meta.json()["game_id"] == gid
        assert speeches.status_code == 200
        # 旧 token 失效也无妨
        assert (
            c2.get(
                f"/api/v1/games/{gid}/replay", headers={"Authorization": "Bearer stale"}
            ).status_code
            == 401
        )
        # 进行中 / 不存在的对局不受影响
        assert c2.get("/api/v1/games/g_nope/replay").status_code == 404
        assert c2.get(f"/api/v1/games/{gid}/state").status_code == 401


def test_live_game_still_requires_token(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        assert c.get(f"/api/v1/games/{gid}/replay").status_code == 401
        assert (
            c.get(
                f"/api/v1/games/{gid}/replay",
                headers={"Authorization": f"Bearer {body['gm_token']}"},
            ).status_code
            == 403
        )  # 未结束：与现状一致


def test_public_history_switch_off(store: InMemoryEventStore, monkeypatch) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=7)
    gid = done["game_id"]
    with _app(store, public_history=False) as c2:
        assert c2.get("/api/v1/games").status_code == 401
        assert c2.get(f"/api/v1/games/{gid}/replay").status_code == 401
    monkeypatch.setenv("AGENTHOWL_PUBLIC_HISTORY", "0")
    with _app(store) as c3:
        assert c3.get("/api/v1/games").status_code == 401
    monkeypatch.setenv("AGENTHOWL_PUBLIC_HISTORY", "1")
    with _app(store) as c4:
        assert c4.get("/api/v1/games").status_code == 200
