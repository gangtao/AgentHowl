"""REST 大厅端点：create/join/start 与鉴权（issue #30）。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.store.event_store import InMemoryEventStore


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
    )
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_join_start_all_ai(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 42}}
    )
    assert r.status_code == 200
    body = r.json()
    gid, host = body["game_id"], body["host_token"]
    assert body["spectator_token"] and body["config"]["seed"] == 42

    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host))
    assert r.status_code == 200 and r.json()["num_players"] == 9

    # 全 AI 局在后台事件循环中跑完（TestClient 事件循环在后台线程，轮询 task 即可）
    registry = client.app.state.games  # type: ignore[attr-defined]
    handle = registry.get(gid)
    import time as _t

    deadline = _t.time() + 30
    while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
        _t.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    assert handle.task.result().winner is not None


def test_join_assigns_seats_and_tokens(client: TestClient) -> None:
    gid = client.post("/api/v1/games", json={"config_override": {"seed": 7}}).json()["game_id"]
    r1 = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Alice"})
    r2 = client.post(
        f"/api/v1/games/{gid}/join", json={"display_name": "Bot 客户端", "player_type": "AGENT"}
    )
    assert r1.json()["seat"] == 0 and r2.json()["seat"] == 1
    assert r1.json()["player_token"] != r2.json()["player_token"]
    assert r1.json()["ws_url"].startswith("/api/v1/ws?token=")


def test_start_requires_host_token(client: TestClient) -> None:
    created = client.post("/api/v1/games", json={"config_override": {"seed": 3}}).json()
    gid = created["game_id"]
    player = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "A"}).json()

    assert client.post(f"/api/v1/games/{gid}/start", json={}).status_code == 401  # 无 token
    assert (
        client.post(
            f"/api/v1/games/{gid}/start", json={}, headers=_auth(player["player_token"])
        ).status_code
        == 403
    )  # 玩家 token 非 HOST
    assert (
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth("garbage")).status_code
        == 401
    )
    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    assert r.status_code == 200
    # 重复开局 → 409；开局后加入 → 409
    assert (
        client.post(
            f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"])
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Late"}).status_code == 409
    )


def test_bad_preset_400_unknown_game_404(client: TestClient) -> None:
    assert client.post("/api/v1/games", json={"preset": "no_such"}).status_code == 400
    created = client.post("/api/v1/games", json={}).json()
    assert (
        client.post(
            "/api/v1/games/g_nope/start", json={}, headers=_auth(created["host_token"])
        ).status_code
        == 404
    )


def test_no_spectator_token_when_disabled(client: TestClient) -> None:
    body = client.post("/api/v1/games", json={"allow_spectators": False}).json()
    assert body["spectator_token"] is None


def test_create_with_agents_echoes_resolved_profiles(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "agents": {"0": {"name": "老张", "model": "ollama/a"}, "*": {"model": "ollama/b"}},
        },
    )
    assert r.status_code == 200, r.text
    agents = r.json()["agents"]
    assert agents["0"]["name"] == "老张" and agents["0"]["model"] == "ollama/a"
    assert agents["*"]["model"] == "ollama/b" and agents["*"]["temperature"] == 0.3


def test_create_legacy_ai_model_echoes_star(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "ai_model": "ollama/a", "ai_model_speech": "ollama/b"},
    )
    assert r.status_code == 200
    assert r.json()["agents"] == {
        "*": {
            "name": None,
            "model": "ollama/a",
            "model_speech": "ollama/b",
            "reflection_model": None,
            "thinking": False,
            "temperature": 0.3,
            "skills": [],
        }
    }
    r2 = client.post("/api/v1/games", json={"preset": "std_9_kill_side"})
    assert r2.status_code == 200 and r2.json()["agents"] == {}


def test_create_agents_errors(client: TestClient) -> None:
    # 新旧冲突 → 400
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "ai_model": "x", "agents": {"*": {"model": "y"}}},
    )
    assert r.status_code == 400 and "agents" in r.json()["detail"]
    # 座位键越界 → 400
    r = client.post(
        "/api/v1/games", json={"preset": "std_9_kill_side", "agents": {"9": {"model": "y"}}}
    )
    assert r.status_code == 400 and "座位" in r.json()["detail"]
    # 档案未知键 → 422（请求体校验）
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"0": {"model": "y", "modle_speech": "z"}}},
    )
    assert r.status_code == 422


def test_create_agents_with_skills_echo_and_unknown_400(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "agents": {
                "*": {
                    "model": "m",
                    "skills": ["vote-discipline", "logic-chain"],
                }
            },
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["agents"]["*"]["skills"] == ["vote-discipline", "logic-chain"]
    r = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "agents": {"*": {"model": "m", "skills": ["nope"]}},
        },
    )
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_create_app_with_external_skills_dir(tmp_path) -> None:
    from app.main import create_app
    from app.runtime.game_runner import RunnerTimeouts
    from app.store.event_store import InMemoryEventStore

    d = tmp_path / "house-rule"
    d.mkdir()
    text = "---\nname: house-rule\ndescription: d\n---\n正文\n"
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    app = create_app(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        skills_dir=tmp_path,
    )
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/games",
            json={
                "preset": "std_9_kill_side",
                "agents": {
                    "*": {
                        "model": "m",
                        "skills": ["house-rule", "vote-discipline"],
                    }
                },
            },
        )
        assert r.status_code == 200, r.text  # 外部 + 内置都可用


def test_create_app_with_missing_skills_dir_fails_loud(tmp_path) -> None:
    """终审 F3：显式给出的 skills_dir 不存在时不再静默过滤，应在启动时 fail-loud。"""
    from app.agent.skills import SkillError
    from app.main import create_app
    from app.runtime.game_runner import RunnerTimeouts
    from app.store.event_store import InMemoryEventStore

    with pytest.raises(SkillError, match="目录"):
        create_app(
            store=InMemoryEventStore(),
            timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
            skills_dir=tmp_path / "nope",
        )
