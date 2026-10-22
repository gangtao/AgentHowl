"""归属隔离（issue #114）：两个普通用户 + admin。跨 owner 一律 404。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.profile import AgentProfile
from app.agent.provider import Provider
from app.runtime.agent_library import InMemoryAgentLibrary, StoredAgent
from app.runtime.provider_store import InMemoryProviderStore
from tests.conftest import login_as, make_app

PROVIDER = {"name": "mine", "kind": "openai_compatible", "api_base": "http://x", "api_key": "k"}


def _agent(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "model": "m", **extra}


@pytest.fixture()
def app() -> Any:
    return make_app(agent_library=InMemoryAgentLibrary(), provider_store=InMemoryProviderStore())


def _client(app: Any) -> TestClient:
    return TestClient(app)


def test_anonymous_401(app: Any) -> None:
    with _client(app) as c:
        assert c.get("/api/v1/agents").status_code == 401
        assert c.post("/api/v1/agents", json=_agent("a")).status_code == 401
        assert c.get("/api/v1/providers").status_code == 401
        assert c.put("/api/v1/avatars", content=b"x").status_code == 401
        assert c.post("/api/v1/voices/design", json={"style": "x"}).status_code == 401
        assert c.get("/api/v1/presets").status_code == 401
        assert c.get("/api/v1/skills").status_code == 401
        assert c.get("/api/v1/tts/status").status_code == 401


def test_agents_isolated_between_users(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        a = alice.post("/api/v1/agents", json=_agent("a1")).json()
        assert a["owner_id"] == alice.get("/api/v1/auth/me").json()["user_id"]
        b = bob.post("/api/v1/agents", json=_agent("b1")).json()
        assert [x["agent_id"] for x in alice.get("/api/v1/agents").json()] == [a["agent_id"]]
        assert [x["agent_id"] for x in bob.get("/api/v1/agents").json()] == [b["agent_id"]]
        assert {x["agent_id"] for x in root.get("/api/v1/agents").json()} == {
            a["agent_id"],
            b["agent_id"],
        }
        # 跨 owner 全 404
        assert bob.get(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert bob.put(f"/api/v1/agents/{a['agent_id']}", json=_agent("x")).status_code == 404
        assert bob.delete(f"/api/v1/agents/{a['agent_id']}").status_code == 404
        assert root.get(f"/api/v1/agents/{a['agent_id']}").status_code == 200
        # 同名按 owner 唯一：bob 可以也叫 a1，alice 自己不能重复
        assert bob.post("/api/v1/agents", json=_agent("a1")).status_code == 201
        assert alice.post("/api/v1/agents", json=_agent("a1")).status_code == 409
        # memory_id 同理
        assert alice.post("/api/v1/agents", json=_agent("m1", memory_id="mem")).status_code == 201
        assert bob.post("/api/v1/agents", json=_agent("m2", memory_id="mem")).status_code == 201
        assert alice.post("/api/v1/agents", json=_agent("m3", memory_id="mem")).status_code == 409


def test_agent_can_only_reference_own_provider(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()["provider_id"]
        assert alice.post("/api/v1/agents", json=_agent("ok", provider=pa)).status_code == 201
        r = bob.post("/api/v1/agents", json=_agent("no", provider=pa))
        assert r.status_code == 400 and "provider" in r.json()["detail"]
        assert root.post("/api/v1/agents", json=_agent("adm", provider=pa)).status_code == 201


def test_providers_isolated_and_public_never_has_key(app: Any) -> None:
    with _client(app) as alice, _client(app) as bob, _client(app) as root:
        login_as(alice, "alice")
        login_as(bob, "bob")
        login_as(root, "root", role="admin")
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()
        assert "api_key" not in pa and pa["has_key"] is True
        assert bob.get("/api/v1/providers").json() == []
        assert bob.get(f"/api/v1/providers/{pa['provider_id']}").status_code == 404
        assert bob.put(f"/api/v1/providers/{pa['provider_id']}", json=PROVIDER).status_code == 404
        assert bob.delete(f"/api/v1/providers/{pa['provider_id']}").status_code == 404
        assert bob.post(f"/api/v1/providers/{pa['provider_id']}/test", json={}).status_code == 404
        assert bob.get(f"/api/v1/providers/{pa['provider_id']}/models").status_code == 404
        assert bob.post("/api/v1/providers", json=PROVIDER).status_code == 201  # 同名跨 owner 允许
        assert alice.post("/api/v1/providers", json=PROVIDER).status_code == 409
        assert len(root.get("/api/v1/providers").json()) == 2
        assert root.delete(f"/api/v1/providers/{pa['provider_id']}").status_code == 204


def test_legacy_ownerless_only_admin(app: Any) -> None:
    lib = app.state.agent_library
    lib.put(
        StoredAgent(
            agent_id="a_old",
            profile=AgentProfile(name="old", model="m"),
            created_at="t",
            updated_at="t",
        )
    )
    app.state.provider_store.put(
        Provider(
            provider_id="p_old",
            name="old",
            kind="openai_compatible",
            api_base="http://x",
            api_key=None,
            default_model=None,
            created_at="t",
            updated_at="t",
        )
    )
    with _client(app) as alice, _client(app) as root:
        login_as(alice, "alice")
        login_as(root, "root", role="admin")
        assert alice.get("/api/v1/agents").json() == []
        assert alice.get("/api/v1/agents/a_old").status_code == 404
        assert alice.get("/api/v1/providers").json() == []
        assert root.get("/api/v1/agents/a_old").status_code == 200
        assert root.get("/api/v1/providers/p_old").status_code == 200
        # 普通用户可以用与无主档案相同的名字（唯一性只在自己的集合里）
        assert alice.post("/api/v1/agents", json=_agent("old")).status_code == 201


def test_avatar_and_voice_require_login_but_get_public(app: Any) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with _client(app) as alice, _client(app) as anon:
        login_as(alice, "alice")
        r = alice.put("/api/v1/avatars", content=png, headers={"Content-Type": "image/png"})
        assert r.status_code == 200
        aid = r.json()["avatar_id"]
        assert anon.get(f"/api/v1/avatars/{aid}").status_code == 200
