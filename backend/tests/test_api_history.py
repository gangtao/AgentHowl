"""历史列表与回放（issue #98 / #114）：重启（换 registry、同一 store）后仍可回放；
回放按归属（本人 cookie / admin）或分享 token 放行，他人 404，匿名无分享 401。"""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.runtime.game_runner import RunnerTimeouts
from app.runtime.secret import share_token
from app.runtime.users import InMemoryUserStore
from app.store.event_store import InMemoryEventStore, JsonFileEventStore
from tests.conftest import bearer, login_as, make_app


def _app(store: InMemoryEventStore, users: InMemoryUserStore | None = None) -> TestClient:
    """已登录为 alice 的 client；传同一个 users 可模拟「重启后用户库仍在」。"""
    app = make_app(
        store=store,
        user_store=users or InMemoryUserStore(),
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
    )
    c = TestClient(app)
    login_as(c, "alice")
    return c


def _play_to_end(client: TestClient, seed: int) -> dict:
    body = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": seed}}
    ).json()
    client.post(
        f"/api/v1/games/{body['game_id']}/start",
        json={},
        headers=bearer(body["host_token"]),
    )
    handle = client.app.state.games.get(body["game_id"])  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    return body


_auth = bearer


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
    assert by_id[done["game_id"]]["owner_name"] == "alice"
    assert pending["game_id"] not in by_id  # 未开局没有事件文件，不在列表里
    assert all("token" not in r for r in rows)
    assert all(r["share_token"] for r in rows)


def test_finished_game_replay_access_after_restart(store: InMemoryEventStore) -> None:
    users = InMemoryUserStore()
    with _app(store, users) as c:
        done = _play_to_end(c, seed=5)
    gid = done["game_id"]
    with _app(store, users) as c2, TestClient(c2.app) as anon, TestClient(c2.app) as bob:
        # 新进程：registry/token 全空，只有 store；本人 cookie 仍可回放
        login_as(bob, "bob")
        assert c2.get("/api/v1/games").json()[0]["game_id"] == gid
        replay = c2.get(f"/api/v1/games/{gid}/replay")
        meta = c2.get(f"/api/v1/games/{gid}/meta")
        speeches = c2.get(f"/api/v1/games/{gid}/speeches")
        assert replay.status_code == 200 and replay.json()[-1]["type"] == "GAME_OVER"
        assert meta.status_code == 200 and meta.json()["game_id"] == gid
        assert speeches.status_code == 200
        # 分享 token（HMAC，重启后依旧有效）可回放
        share = {"share": share_token(b"test-secret", gid)}
        assert anon.get(f"/api/v1/games/{gid}/replay", params=share).status_code == 200
        assert anon.get(f"/api/v1/games/{gid}/meta", params=share).status_code == 200
        assert anon.get(f"/api/v1/games/{gid}/speeches", params=share).status_code == 200
        # 他人 404，匿名无分享 401，旧 token / 坏分享 401
        assert bob.get(f"/api/v1/games/{gid}/replay").status_code == 404
        assert anon.get(f"/api/v1/games/{gid}/replay").status_code == 401
        assert anon.get(f"/api/v1/games/{gid}/replay", headers=bearer("stale")).status_code == 401
        assert anon.get(f"/api/v1/games/{gid}/replay", params={"share": "bad"}).status_code == 401
        # 不存在的对局 404
        assert c2.get("/api/v1/games/g_nope/replay").status_code == 404
        assert c2.get(f"/api/v1/games/{gid}/state").status_code == 404  # 无 handle，没有直播状态


def test_live_game_replay_forbidden(store: InMemoryEventStore) -> None:
    with _app(store) as c, TestClient(c.app) as anon:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        assert anon.get(f"/api/v1/games/{gid}/replay").status_code == 401
        assert c.get(f"/api/v1/games/{gid}/replay").status_code == 403  # 本人 cookie 也要等终局
        assert (
            c.get(f"/api/v1/games/{gid}/replay", headers=bearer(body["gm_token"])).status_code
            == 403
        )


def test_speeches_available_before_game_over(store: InMemoryEventStore) -> None:
    """评审 Blocker 1：/speeches 对有 handle 的对局不要求终局。"""
    with _app(store) as c, TestClient(c.app) as anon:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        # 未开局 + GM token → 200 []
        resp = c.get(f"/api/v1/games/{gid}/speeches", headers=_auth(body["gm_token"]))
        assert resp.status_code == 200 and resp.json() == []
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(body["host_token"]))
        # 进行中 + 分享 token → 200（不要求 GAME_OVER）
        share = {"share": body["share_token"]}
        assert anon.get(f"/api/v1/games/{gid}/speeches", params=share).status_code == 200
        # 进行中 + 匿名无分享 → 401
        assert anon.get(f"/api/v1/games/{gid}/speeches").status_code == 401


def test_finished_game_token_scope(store: InMemoryEventStore) -> None:
    """对局 token 永远限定本局：别局 token → 403（终局也一样）；HOST token 读流 403。"""
    with _app(store) as c:
        done = _play_to_end(c, seed=21)
        other = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = done["game_id"]
        assert (
            c.get(f"/api/v1/games/{gid}/replay", headers=_auth(other["gm_token"])).status_code
            == 403
        )
        assert (
            c.get(f"/api/v1/games/{gid}/events", headers=_auth(done["host_token"])).status_code
            == 403
        )
        assert (
            c.get(f"/api/v1/games/{gid}/state", headers=_auth(done["host_token"])).status_code
            == 403
        )
        assert (
            c.get(f"/api/v1/games/{gid}/replay", headers=_auth(done["gm_token"])).status_code == 200
        )


def test_crashed_game_anonymous_401_without_leak(store: InMemoryEventStore) -> None:
    """终审 M1：匿名请求先拿 401，不泄露崩溃异常文本；本人读流端点触发健康检查 → 500。"""
    with _app(store) as c, TestClient(c.app) as anon:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(body["host_token"]))
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        handle.task = _CrashedTask()  # type: ignore[assignment]
        for path in ("replay", "meta", "speeches", "state", "events"):
            resp = anon.get(f"/api/v1/games/{gid}/{path}")
            assert resp.status_code == 401, (path, resp.text)
            assert "secret" not in resp.text
        for path in ("speeches", "state", "events"):
            resp = c.get(f"/api/v1/games/{gid}/{path}")
            assert resp.status_code == 500, (path, resp.text)


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
    users = InMemoryUserStore()
    with _app(store, users) as c:
        done = _play_to_end(c, seed=33)
    gid = done["game_id"]
    with _app(store, users) as c2:  # 无 handle，只有文件
        assert c2.delete(f"/api/v1/games/{gid}").status_code == 204
        assert c2.get("/api/v1/games").json() == []
        assert c2.get(f"/api/v1/games/{gid}/replay").status_code == 404


def test_delete_live_or_pending_game_409(store: InMemoryEventStore) -> None:
    """进行中（task 未完成）的对局不可删：409，且文件/handle 原样；未开局可删（issue #115）。"""
    with _app(store) as c:
        body = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        gid = body["game_id"]
        pending = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()["game_id"]
        assert c.delete(f"/api/v1/games/{pending}").status_code == 204  # 未开局可删（issue #115）
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
        assert gid not in store.list_games()


def test_delete_store_failure_is_500_without_leaking_and_keeps_handle(
    store: InMemoryEventStore, monkeypatch
) -> None:
    """评审 Major：文件真删不掉（权限/磁盘）不能装作 204 把 handle/token 清掉，
    也不把文件名 / OS 错误文本回给调用方。"""
    from app.store.event_store import StoreError

    with _app(store) as c:
        done = _play_to_end(c, seed=39)
        gid, gm = done["game_id"], _auth(done["gm_token"])

        def boom(game_id: str) -> None:
            raise StoreError(f"{game_id}.jsonl：删除失败：[Errno 13] secret-path")

        monkeypatch.setattr(store, "delete_game", boom)
        resp = c.delete(f"/api/v1/games/{gid}")
        assert resp.status_code == 500, resp.text
        assert "secret-path" not in resp.text and ".jsonl" not in resp.text
        # handle 与 token 都还在，列表照常
        assert c.get(f"/api/v1/games/{gid}/state", headers=gm).status_code == 200
        assert any(r["game_id"] == gid for r in c.get("/api/v1/games").json())


def test_delete_requires_login_and_ownership(store: InMemoryEventStore) -> None:
    with _app(store) as c, TestClient(c.app) as anon, TestClient(c.app) as bob:
        login_as(bob, "bob")
        done = _play_to_end(c, seed=35)
        gid = done["game_id"]
        assert anon.delete(f"/api/v1/games/{gid}").status_code == 401
        assert bob.delete(f"/api/v1/games/{gid}").status_code == 404
        assert (
            anon.delete(f"/api/v1/games/{gid}", headers=_auth(done["gm_token"])).status_code == 401
        )
        assert gid in store.list_games()


def test_delete_aborted_unknown_and_illegal_id(store: InMemoryEventStore) -> None:
    """中断局（无 GAME_OVER、无 handle）可删 → 204；未知 / 非法 id → 404（不是 500）。"""
    users = InMemoryUserStore()
    with _app(store, users) as c:
        done = _play_to_end(c, seed=37)
    gid = done["game_id"]
    meta = store.load_meta(gid)
    events = store.load_events(gid)[:10]
    store.create_game(meta.model_copy(update={"game_id": "g_aborted"}))
    for ev in events:
        store.append("g_aborted", ev.model_copy(update={"game_id": "g_aborted"}))
    with _app(store, users) as c2:
        rows = {r["game_id"]: r["status"] for r in c2.get("/api/v1/games").json()}
        assert rows["g_aborted"] == "aborted"
        assert c2.delete("/api/v1/games/g_aborted").status_code == 204
        assert c2.delete("/api/v1/games/g_nope").status_code == 404
        assert c2.delete("/api/v1/games/g.nope").status_code == 404
        assert store.list_games() == [gid]


def test_store_fallback_maps_illegal_or_corrupt_game_id_to_404(tmp_path: Path) -> None:
    """终审 m1：store 回退路径（无 handle）下，非法 / 损坏 game_id 是 404（不是 500，
    不把文件名/解析错误回给调用方）；列表照常 200 并跳过坏文件。"""
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
