"""Agent 档案库 API + /skills + /presets（issue #26）。"""

import pytest
from fastapi.testclient import TestClient

from app.runtime.agent_library import InMemoryAgentLibrary
from app.store.event_store import InMemoryEventStore
from tests.conftest import login_as, make_app, wait_game_done


@pytest.fixture()
def client() -> TestClient:
    app = make_app(store=InMemoryEventStore(), agent_library=InMemoryAgentLibrary())
    c = TestClient(app)
    login_as(c, "tester", role="admin")
    return c


def test_agents_crud_and_uniqueness(client: TestClient) -> None:
    body = {"name": "夜枭", "model": "ollama/a", "memory_id": "night-owl"}
    r = client.post("/api/v1/agents", json=body)
    assert r.status_code == 201
    a = r.json()
    assert a["agent_id"].startswith("a_") and a["profile"]["name"] == "夜枭" and a["created_at"]
    assert client.post("/api/v1/agents", json={"name": "夜枭", "model": "x"}).status_code == 409
    dup_memory = {"name": "另", "model": "x", "memory_id": "night-owl"}
    assert client.post("/api/v1/agents", json=dup_memory).status_code == 409
    assert client.post("/api/v1/agents", json={"model": "x"}).status_code == 422  # name 必填
    bad_skill = {"name": "z", "model": "x", "skills": ["nope"]}
    assert client.post("/api/v1/agents", json=bad_skill).status_code == 400
    bad_p = {"name": "z", "model": "x", "personality": {"description": "上帝视角"}}
    assert client.post("/api/v1/agents", json=bad_p).status_code == 422
    aid = a["agent_id"]
    assert client.get(f"/api/v1/agents/{aid}").json()["profile"]["memory_id"] == "night-owl"
    update = {"name": "夜枭", "model": "ollama/b", "memory_id": "night-owl"}
    r = client.put(f"/api/v1/agents/{aid}", json=update)
    assert r.status_code == 200 and r.json()["profile"]["model"] == "ollama/b"
    assert r.json()["updated_at"] >= a["updated_at"]
    missing = {"name": "q", "model": "x"}
    assert client.put("/api/v1/agents/a_missing", json=missing).status_code == 404
    lst = client.get("/api/v1/agents").json()
    assert [x["agent_id"] for x in lst] == [aid]
    assert client.delete(f"/api/v1/agents/{aid}").status_code == 204
    assert client.delete(f"/api/v1/agents/{aid}").status_code == 404


def test_skills_and_presets(client: TestClient) -> None:
    skills = client.get("/api/v1/skills").json()
    names = {s["name"] for s in skills}
    assert {"logic-chain", "wolf-claim-jump", "seer-badge-flow"} <= names and len(names) >= 14
    s = next(x for x in skills if x["name"] == "wolf-claim-jump")
    assert s["description"] and "WEREWOLF" in s["roles"] and isinstance(s["phases"], list)
    presets = client.get("/api/v1/presets").json()
    assert [p["name"] for p in presets] == [
        "std_12_yn_hunter_idiot",
        "std_12_yn_hunter_guard",
        "std_9_kill_side",
        "std_9_kill_all",
    ]
    nine = next(p for p in presets if p["name"] == "std_9_kill_side")
    assert nine["num_players"] == 9
    assert nine["sheriff"] is True and nine["win_condition"] == "KILL_SIDE"
    assert sum(r["count"] for r in nine["roles"]) == 9 and nine["description_zh"]


def test_rating_accumulates_after_finished_game_and_is_owner_scoped() -> None:
    """issue #123：建局带 agent_ids → 终局后 /agents 两条档案 games=1、胜负与 winner 一致；
    /agents/{id}/rating 一条 history；他人 404；删除档案后 404 但索引仍有其积分。"""

    from app.runtime.game_runner import RunnerTimeouts
    from app.runtime.player_port import BotPlayerPort
    from tests.conftest import bearer

    app = make_app(
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    with TestClient(app) as c, TestClient(app) as bob:
        login_as(c, "host", role="admin")
        login_as(bob, "bob")
        a = c.post("/api/v1/agents", json={"name": "甲", "model": "m"}).json()
        b = c.post("/api/v1/agents", json={"name": "乙", "model": "m"}).json()
        assert "rating" not in a  # POST 响应保持 StoredAgent
        fresh = {x["agent_id"]: x for x in c.get("/api/v1/agents").json()}
        assert fresh[a["agent_id"]]["rating"] == {
            "rating": 1000.0,
            "games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }
        assert c.get(f"/api/v1/agents/{a['agent_id']}").json()["rating"]["games"] == 0

        created = c.post(
            "/api/v1/games",
            json={
                "preset": "std_9_kill_side",
                "config_override": {"seed": 11},
                "agents": {"0": {"model": "m"}, "5": {"model": "m"}},
                "agent_ids": {"0": a["agent_id"], "5": b["agent_id"]},
            },
        ).json()
        gid, host = created["game_id"], created["host_token"]
        assert (
            c.post(f"/api/v1/games/{gid}/start", json={}, headers=bearer(host)).status_code == 200
        )
        handle = wait_game_done(c, gid)  # 事件驱动等待（issue #74）
        final = handle.task.result()

        by_id = {x["agent_id"]: x["rating"] for x in c.get("/api/v1/agents").json()}
        for aid, seat in ((a["agent_id"], 0), (b["agent_id"], 5)):
            r = by_id[aid]
            assert r["games"] == 1
            if final.winner is None:
                assert r["draws"] == 1 and r["rating"] == 1000.0
            elif final.players[seat].faction == final.winner:
                assert r["wins"] == 1 and r["rating"] > 1000.0
            else:
                assert r["losses"] == 1 and r["rating"] < 1000.0
        full = c.get(f"/api/v1/agents/{a['agent_id']}/rating").json()
        assert full["games"] == 1 and len(full["history"]) == 1
        assert full["history"][0]["game_id"] == gid
        assert full["history"][0]["camp"] == final.players[0].faction.value
        assert set(full["by_camp"]) == {"GOOD", "WOLF"}

        # 可见性：bob 看不到 host 的档案与积分
        assert bob.get(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert bob.get(f"/api/v1/agents/{a['agent_id']}/rating").status_code == 404
        assert bob.get("/api/v1/agents").json() == []
        # 删除档案：API 404，索引里的积分仍由历史对局推导得出（CLI 仍能打印）
        assert c.delete(f"/api/v1/agents/{b['agent_id']}").status_code == 204
        assert c.get(f"/api/v1/agents/{b['agent_id']}/rating").status_code == 404
        index = c.app.state.rating_index  # type: ignore[attr-defined]
        assert index.snapshot()[b["agent_id"]].games == 1


def test_admin_editing_others_profile_checks_uniqueness_in_owner_scope() -> None:
    """issue #120：admin 改 bob 的档案时，唯一性按 bob 的集合判定——与 admin 自己的同名不冲突，
    与 bob 的另一档案同名才 409。"""
    app = make_app()
    with TestClient(app) as root, TestClient(app) as bob:
        login_as(root, "root", role="admin")
        login_as(bob, "bob", role="admin")  # 普通用户建档须带 provider；这里只测作用域
        assert root.post("/api/v1/agents", json={"name": "同名", "model": "x"}).status_code == 201
        b1 = bob.post("/api/v1/agents", json={"name": "甲", "model": "x"}).json()
        assert bob.post("/api/v1/agents", json={"name": "乙", "model": "x"}).status_code == 201
        # admin 把 bob 的「甲」改名为「同名」：admin 自己有「同名」不算冲突
        r = root.put(f"/api/v1/agents/{b1['agent_id']}", json={"name": "同名", "model": "x"})
        assert r.status_code == 200, r.text
        # 改成 bob 的「乙」→ 409
        r = root.put(f"/api/v1/agents/{b1['agent_id']}", json={"name": "乙", "model": "x"})
        assert r.status_code == 409
