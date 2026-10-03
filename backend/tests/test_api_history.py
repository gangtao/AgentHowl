"""历史列表与无 token 回放（issue #98）：重启（换 registry、同一 store）后仍可回放；
开关关则回到 401。"""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore, JsonFileEventStore


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


class _CrashedTask:
    """ensure_healthy() 只读 done()/cancelled()/exception()——伪造一个崩溃 task 不需要真跑
    事件循环，也不会被当作真 asyncio.Task 处理（终审 M1 复现用）。"""

    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return False

    def exception(self) -> BaseException:
        return RuntimeError("secret internal detail")


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


def test_crashed_game_anonymous_401_before_health_check(store: InMemoryEventStore) -> None:
    """终审 M1：匿名请求必须先拿 401，不触发 ensure_healthy()——不会把崩溃异常文本泄露给
    未认证访客；带有效 token 的请求仍按原逻辑触发健康检查 → 500（对认证过的调用方不变）。"""
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        c.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=_auth(body["host_token"]),
        )
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        handle.task = _CrashedTask()  # type: ignore[assignment]
        for path in ("replay", "meta", "speeches"):
            resp = c.get(f"/api/v1/games/{gid}/{path}")
            assert resp.status_code == 401, (path, resp.text)
            assert "secret" not in resp.text
        gm = _auth(body["gm_token"])
        for path in ("replay", "meta", "speeches"):
            resp = c.get(f"/api/v1/games/{gid}/{path}", headers=gm)
            assert resp.status_code == 500, (path, resp.text)


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


class _RunningTask(_CrashedTask):
    """未完成的 task：进行中对局不可删（issue #100）。"""

    def done(self) -> bool:
        return False


def test_delete_finished_game_in_process(store: InMemoryEventStore) -> None:
    """issue #100：删除已终局对局 → 204；随后列表/回放都没了，该局旧 token 作废，再删 404。"""
    with _app(store) as c:
        done = _play_to_end(c, seed=31)
        gid, gm = done["game_id"], _auth(done["gm_token"])
        assert c.get(f"/api/v1/games/{gid}/state", headers=gm).status_code == 200
        assert c.delete(f"/api/v1/games/{gid}").status_code == 204
        assert all(r["game_id"] != gid for r in c.get("/api/v1/games").json())
        assert c.get(f"/api/v1/games/{gid}/replay").status_code == 404
        assert c.get(f"/api/v1/games/{gid}/state", headers=gm).status_code == 401
        assert c.delete(f"/api/v1/games/{gid}").status_code == 404
        assert store.list_games() == []


def test_delete_after_restart_store_only(store: InMemoryEventStore) -> None:
    with _app(store) as c:
        done = _play_to_end(c, seed=33)
    gid = done["game_id"]
    with _app(store) as c2:  # 无 handle，只有文件
        assert c2.delete(f"/api/v1/games/{gid}").status_code == 204
        assert c2.get("/api/v1/games").json() == []
        assert c2.get(f"/api/v1/games/{gid}/replay").status_code == 404


def test_delete_live_or_pending_game_409(store: InMemoryEventStore) -> None:
    """进行中（task 未完成）或未开局的对局都不可删：409，且文件/handle 原样。"""
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        assert c.delete(f"/api/v1/games/{gid}").status_code == 409  # 未开局
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(body["host_token"]))
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        real_task = handle.task
        handle.task = _RunningTask()  # type: ignore[assignment]
        resp = c.delete(f"/api/v1/games/{gid}")
        handle.task = real_task
        assert resp.status_code == 409, resp.text
        assert c.app.state.games.get(gid) is handle  # type: ignore[attr-defined]
        assert gid in store.list_games()


def test_delete_crashed_game_allowed(store: InMemoryEventStore) -> None:
    """崩溃（task 已结束且带异常）的对局不在跑，允许删除清理；异常文本不回给调用方。"""
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(body["host_token"]))
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        real_task = handle.task
        handle.task = _CrashedTask()  # type: ignore[assignment]
        resp = c.delete(f"/api/v1/games/{gid}")
        handle.task = real_task
        assert resp.status_code == 204, resp.text
        assert "secret" not in resp.text
        assert gid not in store.list_games()


def test_delete_switch_off_404_even_with_token(store: InMemoryEventStore) -> None:
    """权限跟随 AGENTHOWL_PUBLIC_HISTORY：关 → 功能不存在（404），带 GM token 也一样。"""
    with _app(store, public_history=False) as c:
        done = _play_to_end(c, seed=35)
        gid = done["game_id"]
        assert c.delete(f"/api/v1/games/{gid}").status_code == 404
        assert c.delete(f"/api/v1/games/{gid}", headers=_auth(done["gm_token"])).status_code == 404
        assert gid in store.list_games()


def test_delete_aborted_unknown_and_illegal_id(store: InMemoryEventStore) -> None:
    """中断局（无 GAME_OVER、无 handle）可删 → 204；未知 / 非法 id → 404（不是 500）。"""
    with _app(store) as c:
        done = _play_to_end(c, seed=37)
    gid = done["game_id"]
    meta = store.load_meta(gid)
    events = store.load_events(gid)[:10]
    store.create_game(meta.model_copy(update={"game_id": "g_aborted"}))
    for ev in events:
        store.append("g_aborted", ev.model_copy(update={"game_id": "g_aborted"}))
    with _app(store) as c2:
        rows = {r["game_id"]: r["status"] for r in c2.get("/api/v1/games").json()}
        assert rows["g_aborted"] == "aborted"
        assert c2.delete("/api/v1/games/g_aborted").status_code == 204
        assert c2.delete("/api/v1/games/g_nope").status_code == 404
        assert c2.delete("/api/v1/games/g.nope").status_code == 404
        assert store.list_games() == [gid]


def test_store_fallback_maps_illegal_or_corrupt_game_id_to_404(tmp_path: Path) -> None:
    """终审 m1：store 回退路径（无 handle）下，非法 / 损坏 game_id 对匿名请求应是 404
    （改造前即是 404；曾退化为 500，把文件名/解析错误回给访客）；列表照常 200 并跳过坏文件。"""
    store = JsonFileEventStore(tmp_path)
    with _app(store) as c:
        # 非法 game_id（含 `.`，_check_game_id 拒绝）→ 404，不是 500
        resp = c.get("/api/v1/games/g.nope/replay")
        assert resp.status_code == 404, resp.text
        # 损坏文件：首行不是合法 JSON → StoreCorruptionError（StoreError 子类）→ 404
        (tmp_path / "g_corrupt.jsonl").write_text("not json at all\n", encoding="utf-8")
        resp = c.get("/api/v1/games/g_corrupt/replay")
        assert resp.status_code == 404, resp.text
        # 列表不受坏文件拖累：仍 200，且该局被跳过
        resp = c.get("/api/v1/games")
        assert resp.status_code == 200
        assert all(r["game_id"] != "g_corrupt" for r in resp.json())
