"""真人入座与建局者玩家视角（issue #115）：指定座位、viewer 回传、GM 封锁、终局恢复。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.cli.bot import RandomBot
from app.runtime.game_runner import RunnerTimeouts
from tests.conftest import bearer, login_as, make_app

PRESET = {"preset": "std_9_kill_side", "config_override": {"seed": 11}}


def _app() -> Any:
    return make_app(timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0))


def _create(client: TestClient) -> dict[str, Any]:
    r = client.post("/api/v1/games", json=PRESET)
    assert r.status_code == 200, r.text
    return r.json()


def _start(client: TestClient, created: dict[str, Any]) -> None:
    r = client.post(
        f"/api/v1/games/{created['game_id']}/start", json={}, headers=bearer(created["host_token"])
    )
    assert r.status_code == 200, r.text


def _play_to_end_via_cookie(client: TestClient, gid: str, seat: int, timeout: float = 30.0) -> None:
    """建局者用 cookie 连 WS 当玩家把整局打完（白盒选合法行动）。"""
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + timeout
    with client.websocket_connect(f"/api/v1/ws?game_id={gid}") as ws:
        while time.time() < deadline:
            frame = ws.receive_json()
            if frame["type"] == "game_over":
                break
            if frame["type"] == "your_turn":
                assert frame["observation"]["my_seat"] == seat
                from tests.test_api_play import _to_tool_call

                ws.send_json(_to_tool_call(RandomBot.choose_action(handle.runner.state, seat)))
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()


class TestJoinBySeat:
    def test_join_specific_seat_conflicts_and_default(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as ext:
            login_as(owner, "alice")
            created = _create(owner)
            gid, host = created["game_id"], created["host_token"]
            # 外部客户端（无 cookie，host_token）指定 5 号
            r = ext.post(
                f"/api/v1/games/{gid}/join",
                json={"display_name": "A", "seat": 5},
                headers=bearer(host),
            )
            assert r.status_code == 200 and r.json()["seat"] == 5
            r = ext.post(
                f"/api/v1/games/{gid}/join",
                json={"display_name": "B", "seat": 5},
                headers=bearer(host),
            )
            assert r.status_code == 409 and r.json()["detail"] == "座位 5 已被占用"
            r = ext.post(
                f"/api/v1/games/{gid}/join",
                json={"display_name": "C", "seat": 9},
                headers=bearer(host),
            )
            assert r.status_code == 409 and r.json()["detail"] == "座位号越界：9（0–8）"
            r = ext.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "D"}, headers=bearer(host)
            )
            assert r.json()["seat"] == 0

    def test_same_account_cannot_join_twice(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 2})
            assert r.status_code == 200 and r.json()["seat"] == 2
            r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我2"})
            assert r.status_code == 409 and r.json()["detail"] == "你已入座 2 号"


class TestViewerField:
    def test_state_and_meta_carry_viewer(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as admin:
            login_as(owner, "alice")
            login_as(admin, "root", role="admin")
            created = _create(owner)
            gid = created["game_id"]
            joined = owner.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 2}
            ).json()
            _start(owner, created)
            # PLAYER token：观察 + viewer=座位号 + seats 带 display_name
            st = owner.get(
                f"/api/v1/games/{gid}/state", headers=bearer(joined["player_token"])
            ).json()
            assert st["viewer"] == 2 and st["my_seat"] == 2
            assert st["seats"][2]["display_name"] == "我"
            assert all("display_name" in s for s in st["seats"])
            # 分享 → SPECTATOR；admin cookie → GM（完整 state 带 players）
            sp = anon.get(
                f"/api/v1/games/{gid}/state", params={"share": created["share_token"]}
            ).json()
            assert sp["viewer"] == "SPECTATOR" and "players" not in sp
            gm = admin.get(f"/api/v1/games/{gid}/state").json()
            assert gm["viewer"] == "GM" and "players" in gm
            _play_to_end_via_cookie(owner, gid, 2)
            meta = admin.get(f"/api/v1/games/{gid}/meta").json()
            assert meta["viewer"] == "GM" and meta["game_id"] == gid and "roster" in meta
            meta_sp = anon.get(
                f"/api/v1/games/{gid}/meta", params={"share": created["share_token"]}
            ).json()
            assert meta_sp["viewer"] == "SPECTATOR"


class TestDeleteUnstarted:
    def test_delete_unstarted_game(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 0})
            assert owner.delete(f"/api/v1/games/{gid}").status_code == 204
            assert owner.get(f"/api/v1/games/{gid}/state").status_code == 404
            # token 已作废
            r = owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"]))
            assert r.status_code == 401


class TestGmLock:
    def _seated_game(self, owner: TestClient) -> tuple[str, dict[str, Any]]:
        created = _create(owner)
        gid = created["game_id"]
        r = owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 1})
        assert r.status_code == 200
        _start(owner, created)
        return gid, created

    def test_owner_cookie_is_player_and_gm_token_403_until_over(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as anon, TestClient(app) as admin:
            login_as(owner, "alice")
            login_as(admin, "root", role="admin")
            gid, created = self._seated_game(owner)
            # cookie → PLAYER（1 号的观察）
            st = owner.get(f"/api/v1/games/{gid}/state").json()
            assert st["viewer"] == 1 and st["my_seat"] == 1 and "players" not in st
            # GM token 封锁
            r = owner.get(f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"]))
            assert r.status_code == 403
            assert r.json()["detail"] == "建局者已入座，对局结束前不能查看上帝视角"
            r = owner.get(f"/api/v1/games/{gid}/events", params={"token": created["gm_token"]})
            assert r.status_code == 403
            # 分享照旧观战；admin 照旧 GM
            assert (
                anon.get(
                    f"/api/v1/games/{gid}/state", params={"share": created["share_token"]}
                ).json()["viewer"]
                == "SPECTATOR"
            )
            assert admin.get(f"/api/v1/games/{gid}/state").json()["viewer"] == "GM"
            # 终局后恢复
            _play_to_end_via_cookie(owner, gid, 1)
            assert owner.get(f"/api/v1/games/{gid}/meta").json()["viewer"] == "GM"
            assert (
                owner.get(
                    f"/api/v1/games/{gid}/replay", headers=bearer(created["gm_token"])
                ).status_code
                == 200
            )
            assert (
                owner.get(f"/api/v1/games/{gid}/meta", headers=bearer(created["gm_token"])).json()[
                    "viewer"
                ]
                == "GM"
            )

    def test_lock_applies_before_start_too(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            owner.post(f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 0})
            # 未开局：cookie 解析为 PLAYER 后 /state 仍是 409（尚未开始），GM token 403
            assert owner.get(f"/api/v1/games/{gid}/state").status_code == 409
            assert (
                owner.get(
                    f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"])
                ).status_code
                == 403
            )

    def test_admin_owner_seated_is_player(self) -> None:
        app = _app()
        with TestClient(app) as root:
            login_as(root, "root", role="admin")
            gid, _created = self._seated_game(root)
            st = root.get(f"/api/v1/games/{gid}/state").json()
            assert st["viewer"] == 1 and st["my_seat"] == 1

    def test_unseated_owner_and_external_seat_keep_gm(self) -> None:
        app = _app()
        with TestClient(app) as owner, TestClient(app) as ext:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            # 外部客户端用 host_token 入座：user_id=None，不触发封锁
            ext.post(
                f"/api/v1/games/{gid}/join",
                json={"display_name": "Ext", "seat": 0},
                headers=bearer(created["host_token"]),
            )
            _start(owner, created)
            assert owner.get(f"/api/v1/games/{gid}/state").json()["viewer"] == "GM"
            assert (
                owner.get(
                    f"/api/v1/games/{gid}/state", headers=bearer(created["gm_token"])
                ).status_code
                == 200
            )

    def test_ws_cookie_player_can_act_and_gm_token_4403(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            gid, created = self._seated_game(owner)
            from starlette.websockets import WebSocketDisconnect

            try:
                with owner.websocket_connect(f"/api/v1/ws?token={created['gm_token']}") as ws:
                    ws.receive_json()
                    raise AssertionError("GM token 应被 4403 关闭")
            except WebSocketDisconnect as exc:
                assert exc.code == 4403
            _play_to_end_via_cookie(owner, gid, 1)  # cookie 入口能收 your_turn 并提交

    def test_cookie_player_view_equals_player_token_view(self) -> None:
        app = _app()
        with TestClient(app) as owner:
            login_as(owner, "alice")
            created = _create(owner)
            gid = created["game_id"]
            joined = owner.post(
                f"/api/v1/games/{gid}/join", json={"display_name": "我", "seat": 4}
            ).json()
            _start(owner, created)
            tok = bearer(joined["player_token"])
            a = owner.get(f"/api/v1/games/{gid}/state").json()
            b = owner.get(f"/api/v1/games/{gid}/state", headers=tok).json()
            # 快照可能相差一个 state_version（对局在跑）：只比字段集合与身份字段
            assert (
                set(a) == set(b)
                and a["my_seat"] == b["my_seat"] == 4
                and a["my_role"] == b["my_role"]
            )
            ea = owner.get(f"/api/v1/games/{gid}/events").json()
            eb = owner.get(f"/api/v1/games/{gid}/events", headers=tok).json()
            n = min(len(ea), len(eb))
            assert ea[:n] == eb[:n] and all(e["visibility"] != "GM_ONLY" for e in ea)
