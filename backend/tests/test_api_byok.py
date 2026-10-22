"""BYOK 强制（issue #114）：普通用户的 Agent 不得落到服务端环境密钥；admin 不受限。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login_as, make_app

PROVIDER = {"name": "mine", "kind": "openai_compatible", "api_base": "http://x", "api_key": "k"}
GAME: dict[str, Any] = {"preset": "std_9_kill_side", "config_override": {"seed": 1}}


@pytest.fixture()
def app() -> Any:
    return make_app()


def test_agents_endpoint_requires_provider_for_users(app: Any) -> None:
    with TestClient(app) as alice, TestClient(app) as root:
        login_as(alice, "alice")
        login_as(root, "root", role="admin")
        r = alice.post("/api/v1/agents", json={"name": "a", "model": "m"})
        assert r.status_code == 400 and "BYOK" in r.json()["detail"]
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()["provider_id"]
        ok = alice.post("/api/v1/agents", json={"name": "a", "model": "m", "provider": pa})
        assert ok.status_code == 201
        assert root.post("/api/v1/agents", json={"name": "r", "model": "m"}).status_code == 201


def test_games_endpoint_requires_provider_for_users(app: Any) -> None:
    with TestClient(app) as alice, TestClient(app) as root:
        login_as(alice, "alice")
        login_as(root, "root", role="admin")
        star = {"*": {"model": "m"}}
        assert alice.post("/api/v1/games", json={**GAME, "agents": star}).status_code == 400
        assert alice.post("/api/v1/games", json={**GAME, "ai_model": "m"}).status_code == 400
        pa = alice.post("/api/v1/providers", json=PROVIDER).json()["provider_id"]
        own = {"*": {"model": "m", "provider": pa}}
        assert alice.post("/api/v1/games", json={**GAME, "agents": own}).status_code == 200
        assert root.post("/api/v1/games", json={**GAME, "agents": star}).status_code == 200
        assert alice.post("/api/v1/games", json=GAME).status_code == 200  # 纯随机 bot
