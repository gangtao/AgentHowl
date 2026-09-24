"""REST 大厅端点：create/join/start 与鉴权（issue #30）。"""

from collections.abc import Iterator
from typing import Any

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
            "personality": None,
            "memory_id": None,
            "provider": None,
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


def test_create_agents_with_personality_echo_and_guardrail_422(client: TestClient) -> None:
    body = {
        "preset": "std_9_kill_side",
        "agents": {
            "0": {
                "model": "m",
                "personality": {
                    "description": "老油条",
                    "traits": {"多疑": 0.9},
                    "preset": {"system": "MBTI", "value": "enfp"},
                    "style_notes": "爱用感叹号",
                },
            }
        },
    }
    r = client.post("/api/v1/games", json=body)
    assert r.status_code == 200, r.text
    p = r.json()["agents"]["0"]["personality"]
    assert p["description"] == "老油条" and p["preset"]["value"] == "ENFP"
    bad = {
        "preset": "std_9_kill_side",
        "agents": {"0": {"model": "m", "personality": {"description": "上帝视角看一下"}}},
    }
    assert client.post("/api/v1/games", json=bad).status_code == 422


def test_create_agents_memory_id_echo_and_conflicts_400(client: TestClient) -> None:
    body = {
        "preset": "std_9_kill_side",
        "agents": {
            "0": {"model": "m", "memory_id": "alice"},
            "1": {"model": "m", "memory_id": "bob"},
        },
    }
    r = client.post("/api/v1/games", json=body)
    assert r.status_code == 200 and r.json()["agents"]["0"]["memory_id"] == "alice"
    dup = {
        "preset": "std_9_kill_side",
        "agents": {
            "0": {"model": "m", "memory_id": "a"},
            "1": {"model": "m", "memory_id": "a"},
        },
    }
    assert client.post("/api/v1/games", json=dup).status_code == 400
    star = {"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "memory_id": "a"}}}
    assert client.post("/api/v1/games", json=star).status_code == 400
    bad = {"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "memory_id": "a/b"}}}
    assert client.post("/api/v1/games", json=bad).status_code == 422


def test_create_app_memory_dir_is_lazy_and_corrupt_file_is_500(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.event_store import InMemoryEventStore

    mem = tmp_path / "mem"
    c = TestClient(create_app(store=InMemoryEventStore(), memory_dir=mem))
    r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "ai_model": "m"})
    assert r.status_code == 200 and not mem.exists()  # 无 memory_id 永不建目录
    mem.mkdir()
    (mem / "alice.json").write_text("{bad", encoding="utf-8")
    r = c.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "memory_id": "alice"}}},
    )
    assert r.status_code == 200  # 建局只登记；装配在 start
    game_id, host = r.json()["game_id"], r.json()["host_token"]
    r = c.post(f"/api/v1/games/{game_id}/start", json={}, headers=_auth(host))
    assert r.status_code == 500 and "alice.json" in r.json()["detail"]


def test_meta_endpoint_gated_until_game_over_and_echoes_effective_agents() -> None:
    """issue #64：/meta 终局前 403；终局后返回 meta，agents 只含实际建成 Agent 端口的座位。"""
    import time as _t

    from app.runtime.player_port import BotPlayerPort

    # 档案座位用随机 bot 端口顶替（不碰 litellm）；meta 记的是档案，不看端口类型
    app = create_app(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    client = TestClient(app)
    body = {
        "preset": "std_9_kill_side",
        "config_override": {"seed": 11},
        "agents": {"1": {"model": "m", "skills": ["logic-chain"], "memory_id": "alice"}},
    }
    created = client.post("/api/v1/games", json=body).json()
    gid, host, spec = created["game_id"], created["host_token"], created["spectator_token"]
    assert client.get(f"/api/v1/games/{gid}/meta", headers=_auth(spec)).status_code == 403
    assert client.get(f"/api/v1/games/{gid}/meta").status_code in (401, 403)
    assert (
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host)).status_code == 200
    )
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = _t.time() + 30
    while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
        _t.sleep(0.05)
    r = client.get(f"/api/v1/games/{gid}/meta", headers=_auth(spec))
    assert r.status_code == 200
    meta = r.json()
    assert meta["game_id"] == gid and meta["config"]["seed"] == 11
    assert len(meta["roster"]) == 9 and set(meta["agents"]) == {"1"}
    one = meta["agents"]["1"]
    assert one["skills"] == ["logic-chain"] and one["memory_id"] == "alice"


def test_events_endpoint_filters_skills_meta_from_spectators_but_replay_not() -> None:
    """issue #60：/events（观众）不外泄 skills meta；/replay（终局后）保留。"""
    import time as _t

    from app.runtime.player_port import BotPlayerPort

    # 定制 bot 端口，模拟 AgentPlayerPort 的 last_skills_used 属性
    class _SkilledBot(BotPlayerPort):
        last_skills_used: tuple[str, ...] = ("wolf-claim-jump",)

    app = create_app(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: _SkilledBot(state_provider=h.live_state),
    )
    client = TestClient(app)
    # 所有座位都用 agent 端口（factory 会返回 _SkilledBot），确保事件有 skills meta
    body = {
        "preset": "std_9_kill_side",
        "config_override": {"seed": 42},
        "agents": {"*": {"model": "m"}},
    }
    created = client.post("/api/v1/games", json=body).json()
    gid, host, spec = created["game_id"], created["host_token"], created["spectator_token"]
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host))
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = _t.time() + 30
    while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
        _t.sleep(0.05)

    # 服务端真实：回放事件中应有 skills meta
    replay = client.get(f"/api/v1/games/{gid}/replay", headers=_auth(spec)).json()
    assert replay, "应有回放事件"
    assert any(e["meta"].get("skills") == "wolf-claim-jump" for e in replay), "回放应记录技能装配"

    # 观众视角的 /events：meta 只含公开键（wall_ts、timeout），不外泄 skills
    events = client.get(f"/api/v1/games/{gid}/events", headers=_auth(spec)).json()
    assert events and all("skills" not in e["meta"] for e in events), "观众不应看到 skills"
    assert all("wall_ts" in e["meta"] for e in events), "所有事件应有 wall_ts"

    # F2（终审）：WS 实时 + 补发共用的 _build_event_frames 同样不外泄 skills——
    # 用 from_seq=0 全量补发路径覆盖（现有 WS 重连测试只比 seq，不比 event 体）
    with client.websocket_connect(f"/api/v1/ws?token={spec}&from_seq=0") as ws:
        frames: list[dict[str, Any]] = []
        while len(frames) < len(events):
            f = ws.receive_json()
            if f["type"] == "game_event":
                frames.append(f["event"])
    assert all("skills" not in e["meta"] for e in frames)


def test_gm_token_reads_full_state_events_and_cannot_act_or_start() -> None:
    """issue #26：GM token 读全量（GM_ONLY/WOLVES/ROLE_SELF、meta.skills）；不能行动/开局。"""
    import time as _t

    from app.runtime.player_port import BotPlayerPort

    class _Skilled(BotPlayerPort):
        last_skills_used = ("wolf-claim-jump",)

    app = create_app(
        store=InMemoryEventStore(),
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
        agent_port_factory=lambda seat, h: _Skilled(state_provider=h.live_state),
    )
    client = TestClient(app)
    body = {
        "preset": "std_9_kill_side",
        "config_override": {"seed": 5},
        "agents": {"*": {"model": "m"}},
    }
    created = client.post("/api/v1/games", json=body).json()
    gid = created["game_id"]
    host, gm, spec = created["host_token"], created["gm_token"], created["spectator_token"]
    assert gm and gm != host and gm != spec
    r_start_gm = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(gm))
    assert r_start_gm.status_code == 403
    r_start_host = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(host))
    assert r_start_host.status_code == 200
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = _t.time() + 30
    while not (handle.task is not None and handle.task.done()) and _t.time() < deadline:
        _t.sleep(0.05)
    state = client.get(f"/api/v1/games/{gid}/state", headers=_auth(gm)).json()
    roles = {p["role"] for p in state["players"]}
    assert state["phase"] == "GAME_OVER" and roles >= {"WEREWOLF", "SEER"}
    assert "state_version" in state and "sheriff_confirmed" in state
    events = client.get(f"/api/v1/games/{gid}/events", headers=_auth(gm)).json()
    vis = {e["visibility"] for e in events}
    assert {"PUBLIC", "GM_ONLY", "WOLVES", "ROLE_SELF"} <= vis
    assert any(e["meta"].get("skills") == "wolf-claim-jump" for e in events)
    spec_events = client.get(f"/api/v1/games/{gid}/events", headers=_auth(spec)).json()
    assert all(e["visibility"] == "PUBLIC" and "skills" not in e["meta"] for e in spec_events)
    assert client.get(f"/api/v1/games/{gid}/speeches", headers=_auth(gm)).status_code == 200
    assert client.get(f"/api/v1/games/{gid}/replay", headers=_auth(gm)).status_code == 200
    assert client.get(f"/api/v1/games/{gid}/meta", headers=_auth(gm)).status_code == 200
    r = client.post(
        f"/api/v1/games/{gid}/actions", json={"tool": "vote", "arguments": {}}, headers=_auth(gm)
    )
    assert r.status_code == 403
    assert client.get(f"/api/v1/games/{gid}/my-turn", headers=_auth(gm)).status_code == 403


def test_frontend_dist_mounted_only_when_present(tmp_path) -> None:
    from app.main import create_app
    from app.store.event_store import InMemoryEventStore

    c = TestClient(create_app(store=InMemoryEventStore(), frontend_dist=tmp_path / "nope"))
    assert c.get("/").status_code == 404
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>AgentHowl</h1>", encoding="utf-8")
    c = TestClient(create_app(store=InMemoryEventStore(), frontend_dist=dist))
    assert c.get("/").status_code == 200 and "AgentHowl" in c.get("/").text
    assert c.get("/api/v1/presets").status_code == 200  # API 前缀不受影响
