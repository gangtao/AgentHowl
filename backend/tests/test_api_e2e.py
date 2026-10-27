"""issue #30 验收 E2E：12 AI 全自动、真人顶替、隔离、越权、重连（issue #30）。"""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.cli.bot import RandomBot
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore
from tests.conftest import login_as, make_app
from tests.test_api_play import _auth, _start_ai_game, _to_tool_call, _wait_done


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = make_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0)
    )
    with TestClient(app) as c:
        login_as(c, "host")
        yield c


def test_acceptance_12_ai_full_game_via_api(client: TestClient) -> None:
    """判据 1：12 AI 全自动完整对局经 API/WS 跑通（非 CLI 直连引擎）。"""
    created = client.post(
        "/api/v1/games",
        json={"preset": "std_12_yn_hunter_idiot", "config_override": {"seed": 42}},
    ).json()
    gid = created["game_id"]
    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    assert r.status_code == 200 and r.json()["num_players"] == 12
    frames: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?game_id={gid}&share={created['share_token']}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "game_over":
                break
    assert frames[0]["type"] == "game_event" and frames[0]["event"]["type"] == "GAME_CREATED"
    replay = client.get(
        f"/api/v1/games/{gid}/replay", params={"share": created["share_token"]}
    ).json()
    assert replay[-1]["type"] == "GAME_OVER"


@pytest.mark.parametrize("seat_to_take", [0, 5])
def test_acceptance_human_can_take_any_seat(client: TestClient, seat_to_take: int) -> None:
    """判据 2：真人可经同一玩家 API 顶替任意座位（此处以先后加入取不同座）。"""
    created = client.post("/api/v1/games", json={"config_override": {"seed": 7}}).json()
    gid = created["game_id"]
    # issue #115：建局者本人入座会封锁 GM 视角，这里用外部客户端入座
    ext = TestClient(client.app)  # 无 cookie：join 不绑定账号（user_id=None）
    # 先以外部 Agent 身份占满目标座位之前的座（同栈同 API），收集各座 token
    all_ports: dict[int, str] = {}
    for i in range(seat_to_take):
        resp = ext.post(
            f"/api/v1/games/{gid}/join",
            json={"display_name": f"Ext{i}", "player_type": "AGENT"},
            headers=_auth(created["host_token"]),
        ).json()
        all_ports[resp["seat"]] = resp["player_token"]
    joined = ext.post(
        f"/api/v1/games/{gid}/join",
        json={"display_name": "Human"},
        headers=_auth(created["host_token"]),
    ).json()
    assert joined["seat"] == seat_to_take
    all_ports[joined["seat"]] = joined["player_token"]
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]

    # 所有外接座位统一用 my-turn 轮询 + POST actions 驱动至终局。
    # issue #74：原来按 wait=1 顺序探测 6 个外接座位，非命中座位每次都等满 1s 才 204，
    # seat_to_take=5 实测 ~130s、满负载下偶发超过 200s 截止。改为 wait=0.05 短轮询
    # （my-turn 现保证至少探测一次，已开窗立即返回），整局只需几秒。
    deadline = time.time() + 120
    while not handle.task.done() and time.time() < deadline:
        for seat, tok in all_ports.items():
            r = client.get(f"/api/v1/games/{gid}/my-turn?wait=0.05", headers=_auth(tok))
            if r.status_code == 200:
                action = RandomBot.choose_action(handle.runner.state, seat)
                client.post(
                    f"/api/v1/games/{gid}/actions", json=_to_tool_call(action), headers=_auth(tok)
                )
    st = handle.runner.state
    assert handle.task.done(), f"未在截止前终局：phase={st.phase} round={st.round}"
    assert handle.task.result().winner is not None


def test_acceptance_isolation_matrix_via_api(client: TestClient) -> None:
    """判据 3：各视角事件流与 test_isolation 口径一致（狼/民/观众）。"""
    gid, created = _start_ai_game(client, seed=3)
    _wait_done(client, gid)
    spec = created["share_token"]
    replay = client.get(f"/api/v1/games/{gid}/replay", params={"share": spec}).json()
    roles = next(e for e in replay if e["type"] == "ROLES_ASSIGNED")["payload"]["assignments"]
    from app.api.deps import TokenInfo

    tokens = client.app.state.tokens  # type: ignore[attr-defined]
    by_faction = {"WOLF": [], "GOOD": []}  # type: dict[str, list[list[dict[str, Any]]]]
    for seat, role in roles:
        tok = tokens.issue(TokenInfo(game_id=gid, seat=seat, kind="PLAYER"))
        evs = client.get(f"/api/v1/games/{gid}/events", headers=_auth(tok)).json()
        by_faction["WOLF" if role == "WEREWOLF" else "GOOD"].append(evs)
    for evs in by_faction["WOLF"]:
        assert any(e["visibility"] == "WOLVES" for e in evs)
        assert not any(e["visibility"] == "GM_ONLY" for e in evs)
    for evs in by_faction["GOOD"]:
        assert not any(e["visibility"] == "WOLVES" for e in evs)
        assert not any(e["visibility"] == "GM_ONLY" for e in evs)
    # ROLE_SELF 只能是自己的
    for seat, _role in roles:
        tok = tokens.issue(TokenInfo(game_id=gid, seat=seat, kind="PLAYER"))
        evs = client.get(f"/api/v1/games/{gid}/events", headers=_auth(tok)).json()
        assert all(e["actor_seat"] == seat for e in evs if e["visibility"] == "ROLE_SELF")
    spec_events = client.get(f"/api/v1/games/{gid}/events", params={"share": spec}).json()
    assert all(e["visibility"] == "PUBLIC" for e in spec_events)


def test_acceptance_authz_matrix(client: TestClient) -> None:
    """判据 4：越权矩阵。"""
    gid, created = _start_ai_game(client, seed=9)
    other_gid, other = _start_ai_game(client, seed=10)
    anon = TestClient(client.app)  # 无 cookie 的匿名访客
    assert anon.get(f"/api/v1/games/{gid}/state").status_code == 401  # 无 token 无分享
    assert anon.get(f"/api/v1/games/{gid}/state", headers=_auth("bad")).status_code == 401
    assert (
        anon.get(f"/api/v1/games/{gid}/state", params={"share": other["share_token"]}).status_code
        == 401
    )  # 他局分享 token
    assert (
        anon.get(f"/api/v1/games/{gid}/state", headers=_auth(other["gm_token"])).status_code == 403
    )  # 他局对局 token
    assert (
        anon.get(f"/api/v1/games/{gid}/state", headers=_auth(created["host_token"])).status_code
        == 403
    )  # HOST 无读权
    assert (
        anon.post(
            f"/api/v1/games/{gid}/actions",
            json={"tool": "vote", "arguments": {}},
            headers=_auth(created["gm_token"]),
        ).status_code
        == 403
    )  # GM 不可行动
    _wait_done(client, gid)
    _wait_done(client, other_gid)


def test_acceptance_reconnect_restores_view(client: TestClient) -> None:
    """判据 5：断线重连恢复视角 —— WS 补发 == REST 后缀 == 错过的可见事件。"""
    gid, created = _start_ai_game(client, seed=11)
    spec = created["share_token"]
    seen: list[int] = []
    with client.websocket_connect(f"/api/v1/ws?game_id={gid}&share={spec}") as ws:
        for _ in range(5):  # 只看前几帧就"断线"
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                seen.append(frame["event"]["seq"])
    _wait_done(client, gid)
    last = max(seen) if seen else 0
    got: list[int] = []
    with client.websocket_connect(
        f"/api/v1/ws?game_id={gid}&share={spec}&from_seq={last + 1}"
    ) as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                got.append(frame["event"]["seq"])
            if frame["type"] == "game_over":
                break
    rest_suffix = [
        e["seq"]
        for e in client.get(
            f"/api/v1/games/{gid}/events", params={"from_seq": last + 1, "share": spec}
        ).json()
    ]
    assert got == rest_suffix
    assert seen + got == sorted(set(seen + got))  # 无缝续接、无重复
