"""视角解析（issue #114）：对局 token / 分享 token / 会话归属；allow_spectators；终局放行。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.runtime.secret import share_token
from tests.conftest import bearer, login_as, make_app

PRESET = {"preset": "std_9_kill_side", "config_override": {"seed": 1}}


def _wait_over(client: TestClient, gid: str, timeout: float = 30.0) -> None:
    registry = client.app.state.games  # type: ignore[attr-defined]
    h = registry.get(gid)
    deadline = time.time() + timeout
    while not (h.task is not None and h.task.done()):
        assert time.time() < deadline, "对局未在超时内结束"
        time.sleep(0.05)


def _create(client: TestClient, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/v1/games", json={**PRESET, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_share_token_is_hmac_and_viewer_spectator() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        assert created["share_token"] == share_token(b"test-secret", gid)
        owner.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=bearer(created["host_token"]),
        )
        r = anon.get(f"/api/v1/games/{gid}/state", params={"share": created["share_token"]})
        assert r.status_code == 200 and "seats" in r.json() and "players" not in r.json()
        assert anon.get(f"/api/v1/games/{gid}/state", params={"share": "bad"}).status_code == 401
        assert anon.get(f"/api/v1/games/{gid}/state").status_code == 401
        assert (
            anon.get(
                f"/api/v1/games/{gid}/speeches", params={"share": created["share_token"]}
            ).status_code
            == 200
        )
        assert (
            anon.get(
                f"/api/v1/games/{gid}/audio", params={"share": created["share_token"]}
            ).status_code
            == 200
        )


def test_share_blocked_live_when_spectators_disabled() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner, allow_spectators=False)
        gid = created["game_id"]
        assert created["share_token"] is None
        tok = share_token(b"test-secret", gid)
        # 未开局（handle 在、未终局）：分享链接被挡在视角解析层，不会走到 409
        assert anon.get(f"/api/v1/games/{gid}/state", params={"share": tok}).status_code == 403
        owner.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=bearer(created["host_token"]),
        )
        _wait_over(owner, gid)
        assert anon.get(f"/api/v1/games/{gid}/replay", params={"share": tok}).status_code == 200
        assert anon.get(f"/api/v1/games/{gid}/meta", params={"share": tok}).status_code == 200


def test_session_owner_is_gm_and_other_user_404() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as bob, TestClient(app) as root:
        login_as(owner, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        created = _create(owner)
        gid = created["game_id"]
        owner.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=bearer(created["host_token"]),
        )
        r = owner.get(f"/api/v1/games/{gid}/state")  # 仅 cookie
        assert r.status_code == 200 and "players" in r.json()  # GM 全量
        assert owner.get(f"/api/v1/games/{gid}/events").status_code == 200
        assert bob.get(f"/api/v1/games/{gid}/state").status_code == 404
        assert bob.get(f"/api/v1/games/{gid}/events").status_code == 404
        assert root.get(f"/api/v1/games/{gid}/state").status_code == 200
        _wait_over(owner, gid)
        assert owner.get(f"/api/v1/games/{gid}/replay").status_code == 200
        assert bob.get(f"/api/v1/games/{gid}/replay").status_code == 404


def test_replay_before_game_over_403_for_gm_token() -> None:
    app = make_app()
    with TestClient(app) as owner:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        # 不开局：handle 在但未终局 → 403（开局后 9 个 bot 几秒就打完，断言会漂）
        r = owner.get(
            f"/api/v1/games/{gid}/replay",
            headers=bearer(created["gm_token"]),
        )
        assert r.status_code == 403


def test_game_token_for_wrong_game_403() -> None:
    app = make_app()
    with TestClient(app) as owner:
        login_as(owner, "alice")
        a = _create(owner)
        b = _create(owner)
        owner.post(
            f"/api/v1/games/{b['game_id']}/start",
            json={},
            headers=bearer(b["host_token"]),
        )
        r = owner.get(
            f"/api/v1/games/{b['game_id']}/state",
            headers=bearer(a["gm_token"]),
        )
        assert r.status_code == 403


def test_audio_part_accepts_share_query() -> None:
    app = make_app()
    with TestClient(app) as owner, TestClient(app) as anon:
        login_as(owner, "alice")
        created = _create(owner)
        gid = created["game_id"]
        owner.post(
            f"/api/v1/games/{gid}/start",
            json={},
            headers=bearer(created["host_token"]),
        )
        r = anon.get(f"/api/v1/games/{gid}/audio/1/0", params={"share": created["share_token"]})
        assert r.status_code == 404  # 没开语音：文件不存在，但鉴权已通过（不是 401）
        assert anon.get(f"/api/v1/games/{gid}/audio/1/0").status_code == 401
