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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def test_speeches_unaffected_before_game_over(store: InMemoryEventStore) -> None:
    """评审 Blocker 1：/speeches 对有 handle 的对局必须保持现状——不要求终局。"""
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        # 未开局 + GM token → 200 []（原行为：未开局直接返回空列表）
        resp = c.get(f"/api/v1/games/{gid}/speeches", headers=_auth(body["gm_token"]))
        assert resp.status_code == 200 and resp.json() == []
        c.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=_auth(body["host_token"]),
        )
        # 进行中 + SPECTATOR token → 200（不要求 GAME_OVER）
        assert (
            c.get(
                f"/api/v1/games/{gid}/speeches", headers=_auth(body["spectator_token"])
            ).status_code
            == 200
        )
        # 进行中 + 无 token → 401（匿名访问仍只对已终局开放，原样不变）
        assert c.get(f"/api/v1/games/{gid}/speeches").status_code == 401


def test_finished_game_any_valid_token_equals_anonymous(store: InMemoryEventStore) -> None:
    """Ruling 4：开关开 + 已终局时，任意有效 token（含 HOST、别局）都降级为匿名放行。"""
    with _app(store) as c:
        done = _play_to_end(c, seed=21)
        other = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        live = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid, host_token, other_gm = done["game_id"], done["host_token"], other["gm_token"]
        # /speeches 的 kinds 本不含 HOST——已终局时也一视同仁放行
        assert c.get(f"/api/v1/games/{gid}/speeches", headers=_auth(host_token)).status_code == 200
        # 别局的有效 GM token 同理放行
        assert c.get(f"/api/v1/games/{gid}/replay", headers=_auth(other_gm)).status_code == 200
        # 未知 game_id + 别局有效 token：先判存在性，不再先查 kind → 仍是 404
        assert c.get("/api/v1/games/g_nope/replay", headers=_auth(other_gm)).status_code == 404
        # 进行中对局 + 别局 token：未终局不降级，仍按 kind 校验 → 403（不变）
        assert (
            c.get(f"/api/v1/games/{live['game_id']}/replay", headers=_auth(other_gm)).status_code
            == 403
        )


def test_public_history_switch_off_handle_path_intact(store: InMemoryEventStore) -> None:
    """Ruling 2：开关关时，有 handle 的已终局对局走原逻辑，不受开关影响。"""
    with _app(store, public_history=False) as c:
        done = _play_to_end(c, seed=23)
        gid, gm_token = done["game_id"], done["gm_token"]
        assert c.get(f"/api/v1/games/{gid}/replay", headers=_auth(gm_token)).status_code == 200


def test_public_history_switch_off_no_handle_still_404(store: InMemoryEventStore) -> None:
    """Ruling 2：开关关 + 无 handle 时不走 store 回退，即使带有效 token 也是 404。"""
    with _app(store) as c:
        done = _play_to_end(c, seed=25)
    gid = done["game_id"]
    with _app(store, public_history=False) as c2:
        # 新进程铸造的有效 token（任意对局皆可，只需在本进程的 TokenRegistry 里能 resolve 成功）
        fresh = c2.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        assert (
            c2.get(f"/api/v1/games/{gid}/replay", headers=_auth(fresh["gm_token"])).status_code
            == 404
        )
