"""Agent 档案库 API + /skills + /presets（issue #26）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.store.event_store import InMemoryEventStore


@pytest.fixture()
def client() -> TestClient:
    app = create_app(store=InMemoryEventStore(), agent_library=InMemoryAgentLibrary())
    return TestClient(app)


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
