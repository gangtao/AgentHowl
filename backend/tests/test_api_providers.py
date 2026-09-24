"""Provider API（issue #26）：CRUD、密钥语义、引用保护、test/models 经注入探测器。"""

import pytest
from fastapi.testclient import TestClient

from app.agent.provider import Provider
from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.runtime.provider_store import InMemoryProviderStore
from app.store.event_store import InMemoryEventStore


class FakeProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def test(self, provider: Provider, model: str | None) -> dict[str, object]:
        self.calls.append(("test", model))
        if provider.kind == "anthropic":
            return {
                "ok": False,
                "latency_ms": 318,
                "error": "AuthenticationError: invalid x-api-key",
            }
        return {"ok": True, "latency_ms": 142, "error": None}

    async def list_models(self, provider: Provider) -> dict[str, object]:
        self.calls.append(("models", None))
        return {"models": ["qwen2.5:14b", "qwen2.5:7b"], "error": None}


@pytest.fixture()
def env() -> tuple[TestClient, FakeProbe]:
    probe = FakeProbe()
    app = create_app(
        store=InMemoryEventStore(),
        agent_library=InMemoryAgentLibrary(),
        provider_store=InMemoryProviderStore(),
        provider_probe=probe,
    )
    return TestClient(app), probe


def test_provider_crud_key_semantics_and_reference_guard(
    env: tuple[TestClient, FakeProbe],
) -> None:
    client, _ = env
    r = client.post(
        "/api/v1/providers",
        json={"name": "本地 Ollama", "kind": "ollama", "default_model": "qwen2.5:14b"},
    )
    assert r.status_code == 201
    p = r.json()
    assert p["provider_id"].startswith("p_")
    assert p["api_base"] == "http://localhost:11434"  # ollama 默认地址
    assert p["has_key"] is False and p["key_hint"] is None and "api_key" not in p
    dup = client.post("/api/v1/providers", json={"name": "本地 Ollama", "kind": "ollama"})
    assert dup.status_code == 409
    compat = client.post("/api/v1/providers", json={"name": "x", "kind": "openai_compatible"})
    assert compat.status_code == 422  # 兼容类型 api_base 必填
    r = client.post(
        "/api/v1/providers",
        json={"name": "OpenAI", "kind": "openai", "api_key": "sk-abcd1234"},
    )
    pid = r.json()["provider_id"]
    assert r.json()["has_key"] is True and r.json()["key_hint"] == "1234"
    # PUT：省略 api_key = 保留；"" = 清除
    r = client.put(
        f"/api/v1/providers/{pid}",
        json={"name": "OpenAI", "kind": "openai", "default_model": "gpt-4o-mini"},
    )
    assert r.json()["has_key"] is True and r.json()["default_model"] == "gpt-4o-mini"
    r = client.put(
        f"/api/v1/providers/{pid}", json={"name": "OpenAI", "kind": "openai", "api_key": ""}
    )
    assert r.json()["has_key"] is False
    assert client.get(f"/api/v1/providers/{pid}").status_code == 200
    assert client.get("/api/v1/providers/p_missing").status_code == 404
    # 被档案引用时 409
    a = client.post(
        "/api/v1/agents", json={"name": "铁齿", "model": "gpt-4o-mini", "provider": pid}
    ).json()
    r = client.delete(f"/api/v1/providers/{pid}")
    assert r.status_code == 409 and "铁齿" in r.json()["detail"]
    missing = client.post(
        "/api/v1/agents", json={"name": "q", "model": "m", "provider": "p_missing"}
    )
    assert missing.status_code == 400
    client.delete(f"/api/v1/agents/{a['agent_id']}")
    assert client.delete(f"/api/v1/providers/{pid}").status_code == 204
    assert [x["name"] for x in client.get("/api/v1/providers").json()] == ["本地 Ollama"]


def test_provider_test_and_models_use_probe(env: tuple[TestClient, FakeProbe]) -> None:
    client, probe = env
    pid = client.post(
        "/api/v1/providers",
        json={"name": "本地 Ollama", "kind": "ollama", "default_model": "qwen2.5:14b"},
    ).json()["provider_id"]
    r = client.post(f"/api/v1/providers/{pid}/test", json={})
    assert r.status_code == 200 and r.json() == {"ok": True, "latency_ms": 142, "error": None}
    assert probe.calls[-1] == ("test", "qwen2.5:14b")
    r = client.post(f"/api/v1/providers/{pid}/test")  # 不带任何 JSON body（body 整体缺省）
    assert r.status_code == 200 and r.json() == {"ok": True, "latency_ms": 142, "error": None}
    assert probe.calls[-1] == ("test", "qwen2.5:14b")
    r = client.post(f"/api/v1/providers/{pid}/test", json={"model": "llama3.1:8b"})
    assert probe.calls[-1] == ("test", "llama3.1:8b")
    r = client.get(f"/api/v1/providers/{pid}/models")
    assert r.status_code == 200 and r.json()["models"] == ["qwen2.5:14b", "qwen2.5:7b"]
    aid = client.post(
        "/api/v1/providers", json={"name": "Anthropic", "kind": "anthropic", "api_key": "bad"}
    ).json()["provider_id"]
    r = client.post(f"/api/v1/providers/{aid}/test", json={"model": "claude-3-5-haiku"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and "AuthenticationError" in r.json()["error"]
    # 无 default_model 且未指定 model
    assert client.post(f"/api/v1/providers/{aid}/test", json={}).status_code == 400
