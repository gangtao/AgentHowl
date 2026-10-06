"""SpeechAudioSink（issue #103）：逐句落盘 + 推帧 + 停留时长；失败不炸；清单/删除。"""

import asyncio
import io
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.agent.profile import VoiceSpec
from app.engine.config import build_preset
from app.engine.engine import create_game
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.speech_audio import AUDIO_TAIL_SEC, SpeechAudioSink
from app.runtime.tts import AudioPart, TtsError, TtsStatus


def _wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


class FakeTts:
    """每句固定时长；fail_at 指定第几句抛 TtsError。"""

    def __init__(self, per_sentence: float = 0.2, fail_at: int | None = None) -> None:
        self.per = per_sentence
        self.fail_at = fail_at
        self.calls: list[str] = []

    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]:
        self.calls.append(text)
        for i, _s in enumerate(["第一句话够长了吧。", "第二句话也够长了。"]):
            if self.fail_at == i:
                raise TtsError("合成失败")
            yield AudioPart(index=i, wav=_wav(self.per), duration_sec=self.per)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


class SlowTts:
    """合成本身比播放慢：每句先 sleep delay 秒再吐出一个 duration 更短的 part。"""

    def __init__(self, delay: float, duration: float) -> None:
        self.delay = delay
        self.duration = duration

    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]:
        for i in range(2):
            await asyncio.sleep(self.delay)
            yield AudioPart(index=i, wav=_wav(self.duration), duration_sec=self.duration)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


def _state() -> GameState:
    return create_game(build_preset("std_9_kill_side").model_copy(update={"seed": 1}), "g1").state


VOICE = VoiceSpec(mode="preset", speaker="dylan")


@pytest.mark.asyncio
async def test_speak_writes_parts_pushes_frames_and_waits(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames(sub)
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(per_sentence=0.2))
    t0 = time.monotonic()
    await sink.speak("g1", 57, "第一句话够长了吧。第二句话也够长了。", VOICE, cm)
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.4 + AUDIO_TAIL_SEC - 0.05  # Σduration + 尾巴
    names = sorted(p.name for p in (tmp_path / "audio" / "g1").glob("*.wav"))
    assert names == ["57-0.wav", "57-1.wav"]
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio", "speech_audio_end"]
    assert frames[0] == {
        "type": "speech_audio",
        "seq": 57,
        "part": 0,
        "url": "/api/v1/games/g1/audio/57/0",
        "duration": pytest.approx(0.2, abs=0.01),
    }
    assert frames[2] == {"type": "speech_audio_end", "seq": 57, "parts": 2}
    m = sink.manifest("g1")
    assert list(m) == ["57"] and [p["part"] for p in m["57"]] == [0, 1]
    assert sink.path_for("g1", 57, 1) is not None and sink.path_for("g1", 57, 9) is None
    assert sink.path_for("g1", 57, 0).read_bytes()[:4] == b"RIFF"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_speak_waits_past_last_part_when_tts_slower_than_realtime(tmp_path: Path) -> None:
    """issue #103 review：TTS 合成比播放慢时，等待须按「最后一句预计播完时刻」算，
    不能按「首句推送时刻 + Σduration」算（否则会在最后一句播完前提前截断）。"""
    sink = SpeechAudioSink(tmp_path / "audio", SlowTts(delay=0.2, duration=0.05))
    t0 = time.monotonic()
    await sink.speak("g1", 9, "无所谓什么内容反正会被分成两句。", VOICE, None)
    elapsed = time.monotonic() - t0
    # 第二句约在 0.4s 推送，播 0.05s 到 0.45s，再加尾巴
    assert elapsed >= 0.2 + 0.2 + 0.05 + AUDIO_TAIL_SEC - 0.05
    # 旧公式（首句推送时刻 0.2 + Σduration 0.1 + 尾巴 0.3 ≈ 0.6）必须被打破
    assert elapsed > 0.2 + 0.1 + AUDIO_TAIL_SEC


@pytest.mark.asyncio
async def test_speak_failure_midway_keeps_pushed_parts_and_returns(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames(sub)
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(per_sentence=0.1, fail_at=1))
    await sink.speak("g1", 3, "随便说点什么都行吧。再来一句凑数的。", VOICE, cm)
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio_end"]
    assert frames[1]["parts"] == 1
    assert sink.manifest("g1") == {"3": [{"part": 0, "duration": pytest.approx(0.1, abs=0.01)}]}


@pytest.mark.asyncio
async def test_speak_total_failure_and_no_connections(tmp_path: Path) -> None:
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(fail_at=0))
    t0 = time.monotonic()
    await sink.speak("g1", 1, "完全失败的一句话。", VOICE, None)  # 不抛、不等
    assert time.monotonic() - t0 < 0.2
    assert sink.manifest("g1") == {}


def test_manifest_ignores_junk_and_delete_is_idempotent(tmp_path: Path) -> None:
    d = tmp_path / "audio" / "g2"
    d.mkdir(parents=True)
    (d / "5-0.wav").write_bytes(_wav(0.3))
    (d / "5-1.wav").write_bytes(_wav(0.3))
    (d / "junk.txt").write_text("x")
    (d / "x-y.wav").write_bytes(b"RIFF")  # 名字非法
    (d / "7-0.wav").write_bytes(b"not wav")  # 坏文件：跳过
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts())
    assert sink.manifest("g2") == {
        "5": [
            {"part": 0, "duration": pytest.approx(0.3, abs=0.01)},
            {"part": 1, "duration": pytest.approx(0.3, abs=0.01)},
        ]
    }
    assert sink.manifest("g_nope") == {}
    with pytest.raises(ValueError):
        sink.path_for("../g2", 5, 0)
    sink.delete_game("g2")
    sink.delete_game("g2")
    assert not d.exists()
