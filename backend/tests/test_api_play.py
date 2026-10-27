"""REST 数据/行动端点：视角、隔离、信封、长轮询（issue #30）。"""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.cli.bot import RandomBot
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore
from tests.conftest import bearer, login_as, make_app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = make_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0)
    )
    with TestClient(app) as c:
        login_as(c, "host")
        yield c


_auth = bearer


def _wait_done(client: TestClient, gid: str, timeout: float = 30.0) -> None:
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + timeout
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()


def _start_ai_game(client: TestClient, seed: int = 42) -> tuple[str, dict[str, Any]]:
    created = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": seed}}
    ).json()
    r = client.post(
        f"/api/v1/games/{created['game_id']}/start", json={}, headers=_auth(created["host_token"])
    )
    assert r.status_code == 200
    return created["game_id"], created


class TestReadEndpoints:
    def test_spectator_state_events_replay_gating(self, client: TestClient) -> None:
        gid, created = _start_ai_game(client)
        spec = created["share_token"]
        r = client.get(f"/api/v1/games/{gid}/state", params={"share": spec})
        assert r.status_code == 200 and r.json()["game_id"] == gid  # SpectatorView
        _wait_done(client, gid)
        # 观众事件流：只有 PUBLIC
        events = client.get(f"/api/v1/games/{gid}/events", params={"share": spec}).json()
        assert events and all(e["visibility"] == "PUBLIC" for e in events)
        # GM 回放：局终开放且含 GM_ONLY
        replay = client.get(f"/api/v1/games/{gid}/replay", params={"share": spec}).json()
        assert any(e["visibility"] == "GM_ONLY" for e in replay)
        assert replay[0]["type"] == "GAME_CREATED"

    def test_replay_forbidden_before_game_over(self, client: TestClient) -> None:
        created = client.post("/api/v1/games", json={"config_override": {"seed": 7}}).json()
        gid = created["game_id"]
        host = _auth(created["host_token"])
        client.cookies.clear()  # 走 host_token 外部客户端路径；同账号二次入座会被拒（issue #115）
        client.post(f"/api/v1/games/{gid}/join", json={"display_name": "A"}, headers=host)
        # 未开局：replay 409（未开局），state 玩家 409
        tok = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "B"}, headers=host)
        tok = tok.json()["player_token"]
        assert client.get(f"/api/v1/games/{gid}/state", headers=_auth(tok)).status_code == 409

    def test_speeches_public_only_with_filters(self, client: TestClient) -> None:
        gid, created = _start_ai_game(client, seed=7)
        _wait_done(client, gid)
        spec = created["share_token"]
        all_speeches = client.get(f"/api/v1/games/{gid}/speeches", params={"share": spec}).json()
        assert all_speeches and all(s["kind"] in ("speech", "last_words") for s in all_speeches)
        r1 = client.get(f"/api/v1/games/{gid}/speeches", params={"round": 1, "share": spec}).json()
        assert r1 and all(s["round"] == 1 for s in r1)

    def test_events_isolation_between_seats(self, client: TestClient) -> None:
        gid, created = _start_ai_game(client, seed=3)
        _wait_done(client, gid)
        # 局终后按 GM 回放找出狼座与民座
        replay = client.get(
            f"/api/v1/games/{gid}/replay", params={"share": created["share_token"]}
        ).json()
        roles = next(e for e in replay if e["type"] == "ROLES_ASSIGNED")["payload"]["assignments"]
        wolf_seat = next(s for s, r in roles if r == "WEREWOLF")
        good_seat = next(s for s, r in roles if r != "WEREWOLF")
        # 补发座位 token（测试直接向 TokenRegistry 索发——白盒，等价于 join 时签发）
        from app.api.deps import TokenInfo

        tokens = client.app.state.tokens  # type: ignore[attr-defined]
        wolf_tok = tokens.issue(TokenInfo(game_id=gid, seat=wolf_seat, kind="PLAYER"))
        good_tok = tokens.issue(TokenInfo(game_id=gid, seat=good_seat, kind="PLAYER"))
        wolf_events = client.get(f"/api/v1/games/{gid}/events", headers=_auth(wolf_tok)).json()
        good_events = client.get(f"/api/v1/games/{gid}/events", headers=_auth(good_tok)).json()
        assert any(e["visibility"] == "WOLVES" for e in wolf_events)
        assert not any(e["visibility"] == "WOLVES" for e in good_events)
        assert not any(e["visibility"] == "GM_ONLY" for e in wolf_events + good_events)

    def test_from_seq_suffix(self, client: TestClient) -> None:
        gid, created = _start_ai_game(client, seed=9)
        _wait_done(client, gid)
        spec = created["share_token"]
        full = client.get(f"/api/v1/games/{gid}/events", params={"share": spec}).json()
        mid = full[len(full) // 2]["seq"]
        suffix = client.get(
            f"/api/v1/games/{gid}/events", params={"from_seq": mid, "share": spec}
        ).json()
        assert suffix == [e for e in full if e["seq"] >= mid]

    def test_my_turn_returns_promptly_after_game_over(self, client: TestClient) -> None:
        # 白盒注入端口，仅为复现终局后的长轮询路径
        from app.api.deps import TokenInfo
        from app.runtime.player_port import HumanPlayerPort

        gid, created = _start_ai_game(client, seed=5)
        _wait_done(client, gid)
        # 全AI对局已结束；在座位0注入真人端口
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
        handle.human_ports[0] = HumanPlayerPort()
        # 补发座位0的token
        tokens = client.app.state.tokens  # type: ignore[attr-defined]
        tok = tokens.issue(TokenInfo(game_id=gid, seat=0, kind="PLAYER"))
        # 长轮询应在终局后立即返回204，而非等满wait时间
        t0 = time.time()
        r = client.get(f"/api/v1/games/{gid}/my-turn?wait=10", headers=_auth(tok))
        elapsed = time.time() - t0
        assert r.status_code == 204
        assert elapsed < 2.0  # 终局后立即返回，而非等满 wait


class TestActions:
    def test_human_seat_plays_via_rest(self, client: TestClient) -> None:
        created = client.post("/api/v1/games", json={"config_override": {"seed": 42}}).json()
        gid = created["game_id"]
        joined = client.post(
            f"/api/v1/games/{gid}/join",
            json={"display_name": "Alice"},
            headers=_auth(created["host_token"]),
        ).json()
        tok, seat = joined["player_token"], joined["seat"]
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]

        # 未开窗提交 → 409（在 my-turn 到来前立刻提交大概率未开窗；若恰已开窗则跳过该断言）
        while not (handle.task is not None and handle.task.done()):
            r = client.get(f"/api/v1/games/{gid}/my-turn?wait=5", headers=_auth(tok))
            if r.status_code == 204:
                continue
            body = r.json()
            assert body["available_tools"] and body["deadline_ts"] > time.time()
            assert body["observation"]["my_seat"] == seat
            action = RandomBot.choose_action(handle.runner.state, seat)  # 白盒选合法行动
            tool_call = _to_tool_call(action)
            resp = client.post(
                f"/api/v1/games/{gid}/actions", json=tool_call, headers=_auth(tok)
            ).json()
            assert resp["ok"], resp["rejected_reason"]
            assert resp["event_id"] is None or resp["event_id"].startswith("evt_")
        assert handle.task.result().winner is not None

    def test_reject_then_retry_and_not_your_turn(self, client: TestClient) -> None:
        created = client.post("/api/v1/games", json={"config_override": {"seed": 7}}).json()
        gid = created["game_id"]
        joined = client.post(
            f"/api/v1/games/{gid}/join",
            json={"display_name": "A"},
            headers=_auth(created["host_token"]),
        ).json()
        tok = joined["player_token"]
        # 未开局提交 → 409
        r = client.post(
            f"/api/v1/games/{gid}/actions",
            json={"tool": "vote", "arguments": {"abstain": True}},
            headers=_auth(tok),
        )
        assert r.status_code == 409
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
        # 等到开窗后提交一个必被引擎拒绝的 intent（白天工具在夜里）
        # → ok:false + 拒因；同窗重试合法行动成功
        r = client.get(f"/api/v1/games/{gid}/my-turn?wait=10", headers=_auth(tok))
        assert r.status_code == 200
        bad = client.post(
            f"/api/v1/games/{gid}/actions",
            json={"tool": "speak", "arguments": {"content": "夜里说话"}},
            headers=_auth(tok),
        ).json()
        assert bad["ok"] is False and bad["rejected_reason"]
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
        good_action = RandomBot.choose_action(handle.runner.state, joined["seat"])
        ok = client.post(
            f"/api/v1/games/{gid}/actions", json=_to_tool_call(good_action), headers=_auth(tok)
        ).json()
        assert ok["ok"], ok["rejected_reason"]
        # 后台放完剩余对局
        _drain(client, gid, tok, joined["seat"])

    def test_gm_token_cannot_act_and_wrong_game_403(self, client: TestClient) -> None:
        gid, created = _start_ai_game(client, seed=3)
        r = client.post(
            f"/api/v1/games/{gid}/actions",
            json={"tool": "vote", "arguments": {}},
            headers=_auth(created["gm_token"]),
        )
        assert r.status_code == 403
        # 分享 token 不是 Bearer token：当作无效 token → 401
        r = client.post(
            f"/api/v1/games/{gid}/actions",
            json={"tool": "vote", "arguments": {}},
            headers=_auth(created["share_token"]),
        )
        assert r.status_code == 401
        gid2, _ = _start_ai_game(client, seed=4)
        # 用 gid 的 gm token 查 gid2 → 403
        assert (
            client.get(
                f"/api/v1/games/{gid2}/events", headers=_auth(created["gm_token"])
            ).status_code
            == 403
        )


def _to_tool_call(action: Any) -> dict[str, Any]:
    """引擎 Action → 工具调用 body（测试辅助，覆盖 bot 会产生的类型）。"""
    from app.engine.actions import DayVote, NightAction, SelfDestruct, SheriffAction, Speak

    if isinstance(action, Speak):
        args: dict[str, Any] = {"content": action.content}
        if action.claim_role is not None:
            args["claim_role"] = str(action.claim_role)
        if action.badge_flow:
            args["badge_flow"] = list(action.badge_flow)
        return {"tool": "speak", "arguments": args}
    if isinstance(action, DayVote):
        return {
            "tool": "vote",
            "arguments": {"target_seat": action.target_seat, "abstain": action.abstain},
        }
    if isinstance(action, NightAction):
        return {
            "tool": "night_action",
            "arguments": {
                "action_type": str(action.action_type),
                "target_seat": action.target_seat,
            },
        }
    if isinstance(action, SheriffAction):
        return {
            "tool": "sheriff_action",
            "arguments": {
                "action_type": str(action.action_type),
                "target_seat": action.target_seat,
                "direction": None if action.direction is None else str(action.direction),
            },
        }
    assert isinstance(action, SelfDestruct)
    return {"tool": "self_destruct", "arguments": {}}


def _drain(client: TestClient, gid: str, tok: str, seat: int, timeout: float = 30.0) -> None:
    """把带真人座的对局推进到终局（my-turn 轮询 + 白盒选行动）。"""
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + timeout
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        r = client.get(f"/api/v1/games/{gid}/my-turn?wait=3", headers=_auth(tok))
        if r.status_code != 200:
            continue
        action = RandomBot.choose_action(handle.runner.state, seat)
        client.post(f"/api/v1/games/{gid}/actions", json=_to_tool_call(action), headers=_auth(tok))
    assert handle.task is not None and handle.task.done()


class TestActionsAccepted:
    def test_slow_adjudication_returns_202_accepted(
        self, client: TestClient, monkeypatch: Any
    ) -> None:
        """issue #134：同步窗口裁决可能迟到整个时限；REST 与 WS 一样超过 ACCEPT_WAIT_SEC
        先回 202 + accepted:true，而不是 409「行动窗口已关闭」。阈值压到 0 让每次提交都走该路径。
        """
        from app.api import rest as rest_mod

        monkeypatch.setattr(rest_mod, "ACCEPT_WAIT_SEC", 0.0)
        created = client.post("/api/v1/games", json={"config_override": {"seed": 42}}).json()
        gid = created["game_id"]
        joined = client.post(
            f"/api/v1/games/{gid}/join",
            json={"display_name": "Alice"},
            headers=_auth(created["host_token"]),
        ).json()
        tok, seat = joined["player_token"], joined["seat"]
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
        statuses: list[int] = []
        while not (handle.task is not None and handle.task.done()):
            r = client.get(f"/api/v1/games/{gid}/my-turn?wait=5", headers=_auth(tok))
            if r.status_code == 204:
                continue
            sv = r.json()["observation"]["state_version"]
            action = RandomBot.choose_action(handle.runner.state, seat)
            resp = client.post(
                f"/api/v1/games/{gid}/actions", json=_to_tool_call(action), headers=_auth(tok)
            )
            statuses.append(resp.status_code)
            body = resp.json()
            assert body["ok"], body
            if resp.status_code == 202:
                assert body["accepted"] is True
                assert body["event_id"] is None and body["rejected_reason"] is None
                assert body["state_version"] == sv
            else:
                assert body["accepted"] is False
        assert 202 in statuses, statuses
        assert handle.task.result().winner is not None


def test_state_carries_public_sheriff_config(client: TestClient) -> None:
    """issue #80：观众 / 玩家视角的 /state 带公开规则 config.sheriff，前端计票不再猜 1.5。"""
    created = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "config_override": {"seed": 5, "sheriff": {"vote_weight": 2.0}},
        },
    ).json()
    gid = created["game_id"]
    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    assert r.status_code == 200
    spec = client.get(f"/api/v1/games/{gid}/state", params={"share": created["share_token"]})
    assert spec.status_code == 200
    cfg = spec.json()["config"]
    assert cfg["sheriff"]["vote_weight"] == 2.0 and cfg["num_players"] == 9
    assert "roles" not in cfg  # 只给公开子集
    from app.api.deps import TokenInfo

    tokens = client.app.state.tokens  # type: ignore[attr-defined]
    tok = tokens.issue(TokenInfo(game_id=gid, seat=0, kind="PLAYER"))
    me = client.get(f"/api/v1/games/{gid}/state", headers=_auth(tok))
    assert me.status_code == 200
    assert me.json()["config"]["sheriff"]["vote_weight"] == 2.0
    assert me.json()["viewer"] == 0
    _wait_done(client, gid)
