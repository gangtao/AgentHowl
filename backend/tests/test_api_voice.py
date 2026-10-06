"""语音 API（issue #103）：status、建局 voice 探测、音频清单/文件权限、WS 帧、删局清理。"""

import io
import time
import wave
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.profile import VoiceSpec
from app.main import create_app
from app.runtime.agent_library import InMemoryAgentLibrary
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import BotPlayerPort
from app.runtime.tts import AudioPart, TtsStatus
from app.store.event_store import InMemoryEventStore


def _wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


class FakeTts:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]:
        yield AudioPart(index=0, wav=_wav(0.02), duration_sec=0.02)

    async def probe(self) -> TtsStatus:
        return TtsStatus(
            enabled=True,
            ok=self.ok,
            url="fake",
            detail=None if self.ok else "down",
            supports_style=True,
        )


def _app(tmp_path: Path, tts: Any, public_history: bool | None = None) -> TestClient:
    app = create_app(
        store=InMemoryEventStore(),
        agent_library=InMemoryAgentLibrary(),
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
        tts_client=tts,
        audio_dir=tmp_path / "audio",
        public_history=public_history,
    )
    return TestClient(app)


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _app(tmp_path, FakeTts()) as c:
        yield c


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _voiced_game(client: TestClient, voice: bool = True) -> dict:
    body = {
        "preset": "std_9_kill_side",
        "config_override": {"seed": 3},
        "voice": voice,
        "agents": {"*": {"model": "x", "voice": {"mode": "preset", "speaker": "dylan"}}},
    }
    r = client.post("/api/v1/games", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _finish(client: TestClient, created: dict) -> None:
    gid = created["game_id"]
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 60
    while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
        time.sleep(0.05)
    assert handle.task is not None and handle.task.done() and handle.task.exception() is None


def test_tts_status_enabled_and_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTHOWL_TTS_URL", raising=False)
    with _app(tmp_path, FakeTts()) as c:
        s = c.get("/api/v1/tts/status").json()
        assert s["enabled"] and s["ok"] and "api_key" not in s
    with _app(tmp_path, None) as c:  # None → 按环境变量；未设 URL → DisabledTtsClient
        s = c.get("/api/v1/tts/status").json()
        assert s == {
            "enabled": False,
            "ok": False,
            "url": None,
            "detail": "未配置 AGENTHOWL_TTS_URL",
            "supports_style": False,
        }


def test_create_game_voice_flag_and_probe(tmp_path: Path) -> None:
    with _app(tmp_path, FakeTts(ok=False)) as c:
        r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True})
        assert r.status_code == 400 and "TTS" in r.json()["detail"]
        r = c.post("/api/v1/games", json={"preset": "std_9_kill_side"})
        assert r.status_code == 200 and r.json()["voice"] is False
    with _app(tmp_path, FakeTts()) as c:
        assert (
            c.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True}).json()[
                "voice"
            ]
            is True
        )


def test_voiced_game_streams_frames_and_stores_audio(client: TestClient, tmp_path: Path) -> None:
    created = _voiced_game(client)
    gid = created["game_id"]
    frames: list[dict[str, Any]] = []
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    with client.websocket_connect(f"/api/v1/ws?token={created['spectator_token']}") as ws:
        while True:
            f = ws.receive_json()
            frames.append(f)
            if f["type"] == "game_over":
                break
    audio = [f for f in frames if f["type"] == "speech_audio"]
    ends = [f for f in frames if f["type"] == "speech_audio_end"]
    assert audio and ends and audio[0]["url"].startswith(f"/api/v1/games/{gid}/audio/")
    spoke_seqs = {
        f["event"]["seq"]
        for f in frames
        if f["type"] == "game_event" and f["event"]["type"] in ("PLAYER_SPOKE", "LAST_WORDS")
    }
    assert {f["seq"] for f in audio} <= spoke_seqs
    # 回放事件流里没有 speech_audio（不是事件）
    replay = client.get(f"/api/v1/games/{gid}/replay").json()
    assert all(e["type"] not in ("speech_audio", "speech_audio_end") for e in replay)
    # 清单与文件（终局公开）
    m = client.get(f"/api/v1/games/{gid}/audio").json()
    seq, part = audio[0]["seq"], audio[0]["part"]
    assert m[str(seq)][0]["part"] == 0
    r = client.get(f"/api/v1/games/{gid}/audio/{seq}/{part}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    assert r.content[:4] == b"RIFF"
    assert client.get(f"/api/v1/games/{gid}/audio/{seq}/99").status_code == 404
    assert client.get(f"/api/v1/games/{gid}/audio/abc/0").status_code == 422
    assert (tmp_path / "audio" / gid).is_dir()
    # 删局连带删音频
    assert client.delete(f"/api/v1/games/{gid}").status_code == 204
    assert not (tmp_path / "audio" / gid).exists()


def test_audio_part_endpoint_accepts_query_token_during_live_game(client: TestClient) -> None:
    """fix round 1（issue #103）：`<audio>` 元素发不出 Authorization 头，直播期间（未终局）
    这个端点原先只认 Bearer，匿名必 401——配音一句都放不出来。现在额外接受 `?token=`，
    等价于 WS 端点早有的先例（`/api/v1/ws?token=`）。"""
    created = _voiced_game(client)
    gid = created["game_id"]
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    url: str | None = None
    with client.websocket_connect(f"/api/v1/ws?token={created['spectator_token']}") as ws:
        while url is None:
            f = ws.receive_json()
            if f["type"] == "speech_audio":
                url = f["url"]
    assert url is not None and url.startswith(f"/api/v1/games/{gid}/audio/")

    # 匿名：未终局，_finished_or_handle 的无 token 分支必 401
    assert client.get(url).status_code == 401
    # ?token=<spectator_token>：按 query token 解析出合法 info，放行
    r = client.get(url, params={"token": created["spectator_token"]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
    # ?token=garbage：解析不出 info，401（而不是被悄悄当成匿名）
    assert client.get(url, params={"token": "garbage"}).status_code == 401


def test_unvoiced_game_has_no_audio(client: TestClient) -> None:
    created = _voiced_game(client, voice=False)
    _finish(client, created)
    gid = created["game_id"]
    assert client.get(f"/api/v1/games/{gid}/audio").json() == {}


def test_audio_endpoints_follow_replay_policy(tmp_path: Path) -> None:
    with _app(tmp_path, FakeTts(), public_history=False) as c:
        created = _voiced_game(c)
        gid = created["game_id"]
        # 进行中：匿名 401；本局观众 200
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
        assert c.get(f"/api/v1/games/{gid}/audio").status_code == 401
        assert (
            c.get(
                f"/api/v1/games/{gid}/audio", headers=_auth(created["spectator_token"])
            ).status_code
            == 200
        )
        other = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        assert (
            c.get(f"/api/v1/games/{gid}/audio", headers=_auth(other["gm_token"])).status_code == 403
        )
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        deadline = time.time() + 60
        while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
            time.sleep(0.05)
        # 开关关：终局匿名仍 401
        assert c.get(f"/api/v1/games/{gid}/audio").status_code == 401
    assert c.get("/api/v1/games/g_nope/audio").status_code in (401, 404)
