"""头像端点（issue #102）：上传魔数/大小校验、内容寻址读取、对局座位头像映射。"""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.runtime.avatar_store import InMemoryAvatarStore
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import BotPlayerPort
from app.store.event_store import InMemoryEventStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture()
def client() -> TestClient:
    app = create_app(
        store=InMemoryEventStore(),
        agent_library=InMemoryAgentLibrary(),
        avatar_store=InMemoryAvatarStore(),
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
        # 占位档案 model="x" 不是真模型名；不给 agent_port_factory 会走
        # build_agent_port → litellm，在测试里既慢又可能触网。这里固定用
        # RandomBot 填充所有座位（含有档案的座位），只验证映射来源，不验证真调模型。
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
    )
    return TestClient(app)


def _put(client: TestClient, data: bytes, ctype: str = "image/png"):  # type: ignore[no-untyped-def]
    return client.put("/api/v1/avatars", content=data, headers={"Content-Type": ctype})


def test_upload_and_fetch_roundtrip(client: TestClient) -> None:
    r = _put(client, PNG)
    assert r.status_code == 200, r.text
    aid = r.json()["avatar_id"]
    assert aid.endswith(".png") and r.json()["bytes"] == len(PNG)
    assert _put(client, PNG).json()["avatar_id"] == aid  # 幂等
    assert _put(client, JPG, "image/jpeg").json()["avatar_id"].endswith(".jpg")
    g = client.get(f"/api/v1/avatars/{aid}")
    assert g.status_code == 200 and g.content == PNG
    assert g.headers["content-type"] == "image/png"
    assert "immutable" in g.headers["cache-control"]


def test_upload_rejects_bad_type_and_size(client: TestClient) -> None:
    assert _put(client, b"plain text here", "image/png").status_code == 415
    assert _put(client, b"GIF89a" + b"\x00" * 64, "image/gif").status_code == 415
    too_big = PNG + b"\x00" * (512 * 1024)
    assert _put(client, too_big).status_code == 413
    assert _put(client, b"").status_code == 415


def test_upload_oversize_without_content_length_still_413(client: TestClient) -> None:
    """生成器 body（httpx 不预知长度，不发 Content-Length）：只能靠逐块累积守卫兜底，
    不能靠请求头检查（issue #102 复审发现：原测试全走 bytes content，总带 Content-Length，
    从未真正跑到 request.stream() 里的那段累积判断）。"""

    def _oversize() -> Any:
        yield PNG
        yield b"\x00" * (512 * 1024)

    r = client.put("/api/v1/avatars", content=_oversize(), headers={"Content-Type": "image/png"})
    assert "content-length" not in r.request.headers  # 确认确实没发，守卫测的是对的路径
    assert r.status_code == 413


def test_upload_under_limit_without_content_length_succeeds(client: TestClient) -> None:
    """同样无 Content-Length，但未超限：不应被误拦截。"""

    def _ok() -> Any:
        yield PNG

    r = client.put("/api/v1/avatars", content=_ok(), headers={"Content-Type": "image/png"})
    assert "content-length" not in r.request.headers
    assert r.status_code == 200
    assert r.json()["bytes"] == len(PNG)


def test_fetch_missing_or_illegal_id_404(client: TestClient) -> None:
    assert client.get("/api/v1/avatars/0000000000000000.png").status_code == 404
    assert client.get("/api/v1/avatars/..%2Fsecret.png").status_code == 404
    assert client.get("/api/v1/avatars/abc.gif").status_code == 404


def test_game_avatars_map_live_and_finished(client: TestClient) -> None:
    """建局时带头像的档案 → 直播中任意本局 token 可取映射；终局后匿名可取（公开策略同 /replay）。"""
    aid = _put(client, PNG).json()["avatar_id"]
    body = client.post(
        "/api/v1/games",
        json={
            "preset": "std_9_kill_side",
            "config_override": {"seed": 1},
            "agents": {"0": {"model": "x", "avatar": aid}, "1": {"model": "x"}},
        },
    ).json()
    gid = body["game_id"]
    assert client.get(f"/api/v1/games/{gid}/avatars").status_code == 401  # 未终局匿名不可
    spect = {"Authorization": f"Bearer {body['spectator_token']}"}
    r = client.get(f"/api/v1/games/{gid}/avatars", headers=spect)
    assert r.status_code == 200 and r.json() == {"0": aid}
    # 开局（fixture 固定用 RandomBot 填充所有座位，不会真调 LLM）
    # —— 这里只验映射来源切到 GameMeta.agents 后仍一致
    client.post(
        f"/api/v1/games/{gid}/start",
        json={},
        headers={"Authorization": f"Bearer {body['host_token']}"},
    )
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done()
    assert client.get(f"/api/v1/games/{gid}/avatars").json() == {"0": aid}  # 终局匿名
    assert client.get("/api/v1/games/g_nope/avatars").status_code == 404
