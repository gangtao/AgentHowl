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
from app.engine.events import (
    Event,
    EventType,
    RoundStartedPayload,
    Visibility,
    VoteStartedPayload,
)
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.narration import DEFAULT_NARRATION_EVENTS, NarrationCache, NarrationConfig
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

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: object = None
    ) -> AsyncIterator[AudioPart]:
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

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: object = None
    ) -> AsyncIterator[AudioPart]:
        for i in range(2):
            await asyncio.sleep(self.delay)
            yield AudioPart(index=i, wav=_wav(self.duration), duration_sec=self.duration)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


def _public(seq: int, t: EventType = EventType.VOTE_STARTED) -> Event:
    payload = (
        VoteStartedPayload(candidates=(), tie_round=0)
        if t == EventType.VOTE_STARTED
        else RoundStartedPayload(round=seq)
    )
    vis = Visibility.PUBLIC if t == EventType.VOTE_STARTED else Visibility.GM_ONLY
    return Event(seq=seq, game_id="g1", ts=float(seq), type=t, payload=payload, visibility=vis)


def _state() -> GameState:
    return create_game(build_preset("std_9_kill_side").model_copy(update={"seed": 1}), "g1").state


VOICE = VoiceSpec(mode="preset", speaker="dylan")


@pytest.mark.asyncio
async def test_speak_writes_parts_pushes_frames_and_waits(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(per_sentence=0.2))
    t0 = time.monotonic()
    await sink.speak("g1", 57, "第一句话够长了吧。第二句话也够长了。", VOICE, cm, _public(57))
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
        "kind": "speech",
    }
    assert frames[2] == {"type": "speech_audio_end", "seq": 57, "parts": 2, "kind": "speech"}
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
    await sink.speak("g1", 9, "无所谓什么内容反正会被分成两句。", VOICE, None, _public(9))
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

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(per_sentence=0.1, fail_at=1))
    await sink.speak("g1", 3, "随便说点什么都行吧。再来一句凑数的。", VOICE, cm, _public(3))
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio_end"]
    assert frames[1]["parts"] == 1
    assert sink.manifest("g1") == {"3": [{"part": 0, "duration": pytest.approx(0.1, abs=0.01)}]}


@pytest.mark.asyncio
async def test_speak_total_failure_and_no_connections(tmp_path: Path) -> None:
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(fail_at=0))
    t0 = time.monotonic()
    await sink.speak("g1", 1, "完全失败的一句话。", VOICE, None, _public(1))  # 不抛、不等
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


@pytest.mark.asyncio
async def test_warm_synthesizes_each_distinct_voice_once_and_tolerates_failure(
    tmp_path: Path,
) -> None:
    from app.runtime.speech_audio import WARM_TEXT

    tts = FakeTts(per_sentence=0.0)
    sink = SpeechAudioSink(tmp_path / "audio", tts)
    a = VoiceSpec(mode="preset", speaker="dylan")
    b = VoiceSpec(mode="preset", speaker="dylan", style="高兴")  # 同 speaker 视为同一声线
    c = VoiceSpec(mode="design", style="沙哑")
    await sink.warm([a, b, c, a])
    assert tts.calls == [WARM_TEXT, WARM_TEXT]
    await SpeechAudioSink(tmp_path / "audio", FakeTts(fail_at=0)).warm([a])  # 不抛


def test_manifest_reads_only_wav_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """大局清单不整文件读入：只取头部仍算出完整时长（issue #108）。"""
    import app.runtime.speech_audio as sa

    d = tmp_path / "audio" / "g9"
    d.mkdir(parents=True)
    (d / "1-0.wav").write_bytes(_wav(10.0))  # 8 kHz 16-bit mono：160 KB > 64 KB 头
    reads: list[int] = []
    real_open = Path.open

    def spy_open(self: Path, *a: object, **k: object):  # type: ignore[no-untyped-def]
        f = real_open(self, *a, **k)
        orig = f.read

        def read(n: int = -1) -> bytes:
            reads.append(n)
            return orig(n)

        f.read = read  # type: ignore[method-assign]
        return f

    monkeypatch.setattr(Path, "open", spy_open)
    m = SpeechAudioSink(tmp_path / "audio", FakeTts()).manifest("g9")
    assert m == {"1": [{"part": 0, "duration": pytest.approx(10.0, abs=0.01)}]}
    assert reads == [sa.WAV_HEADER_BYTES]


class CountingTts:
    """每次 synthesize 产一段 0.05s；记录文本。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: object = None
    ) -> AsyncIterator[AudioPart]:
        self.calls.append(text)
        yield AudioPart(index=0, wav=_wav(0.05), duration_sec=0.05)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


def _narr(tmp_path: Path) -> NarrationConfig:
    return NarrationConfig(
        speaker="uncle_fu", events=DEFAULT_NARRATION_EVENTS, cache_dir=tmp_path / "narr"
    )


@pytest.mark.asyncio
async def test_narrate_pushes_frames_with_kind_and_caches(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    tts = CountingTts()
    cache = NarrationCache(tmp_path / "narr")
    sink = SpeechAudioSink(
        tmp_path / "audio", tts, narration=_narr(tmp_path), narration_cache=cache
    )
    await sink.narrate("g1", _public(5), cm)
    assert tts.calls == ["投票开始。"]
    assert frames[0]["kind"] == "narration" and frames[0]["seq"] == 5 and frames[0]["part"] == 0
    assert frames[-1] == {"type": "speech_audio_end", "seq": 5, "parts": 1, "kind": "narration"}
    assert sink.manifest("g1") == {"5": [{"part": 0, "duration": pytest.approx(0.05, abs=0.01)}]}
    assert cache.get("uncle_fu", "投票开始。") is not None
    # 第二次：零 TTS 调用，仍推帧、仍落到对局目录
    await sink.narrate("g1", _public(9), cm)
    assert tts.calls == ["投票开始。"]
    assert sink.path_for("g1", 9, 0) is not None


@pytest.mark.asyncio
async def test_narrate_outside_whitelist_is_noop(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    cfg = NarrationConfig(
        speaker="uncle_fu", events=frozenset({EventType.GAME_OVER}), cache_dir=tmp_path / "n"
    )
    tts = CountingTts()
    sink = SpeechAudioSink(
        tmp_path / "audio", tts, narration=cfg, narration_cache=NarrationCache(cfg.cache_dir)
    )
    t0 = time.monotonic()
    await sink.narrate("g1", _public(5), cm)
    assert tts.calls == [] and frames == [] and time.monotonic() - t0 < 0.1


@pytest.mark.asyncio
async def test_narrate_filtered_frames_follow_event_visibility(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    got: dict[str, list[str]] = {"GM": [], "SPECTATOR": []}

    def sub(name: str):  # type: ignore[no-untyped-def]
        async def cb(f: dict) -> None:
            got[name].append(f["type"])

        return cb

    cm.subscribe_frames("GM", sub("GM"))
    cm.subscribe_frames("SPECTATOR", sub("SPECTATOR"))
    sink = SpeechAudioSink(
        tmp_path / "audio",
        CountingTts(),
        narration=_narr(tmp_path),
        narration_cache=NarrationCache(tmp_path / "narr"),
    )
    await sink.narrate("g1", _public(2, EventType.ROUND_STARTED), cm)  # GM_ONLY
    assert got["GM"] == ["speech_audio", "speech_audio_end"] and got["SPECTATOR"] == []


@pytest.mark.asyncio
async def test_narrate_tts_failure_skips_and_no_frames(tmp_path: Path) -> None:
    class Boom:
        async def synthesize_sentences(
            self, text: str, voice: VoiceSpec, ref_audio: object = None
        ) -> AsyncIterator[AudioPart]:
            raise TtsError("down")
            yield  # pragma: no cover

        async def probe(self) -> TtsStatus:
            return TtsStatus(enabled=True, ok=False, url="fake")

    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(
        tmp_path / "audio",
        Boom(),
        narration=_narr(tmp_path),
        narration_cache=NarrationCache(tmp_path / "narr"),
    )
    await sink.narrate("g1", _public(5), cm)  # 不抛
    assert frames == [] and sink.manifest("g1") == {}


@pytest.mark.asyncio
async def test_narrate_plays_even_if_cache_put_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缓存目录不可写只告警，本句仍播。"""
    cache = NarrationCache(tmp_path / "narr")

    def boom(*a: object, **k: object) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(cache, "put", boom)
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(
        tmp_path / "audio", CountingTts(), narration=_narr(tmp_path), narration_cache=cache
    )
    await sink.narrate("g1", _public(5), cm)
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio_end"]


@pytest.mark.asyncio
async def test_narrate_without_config_is_noop(tmp_path: Path) -> None:
    sink = SpeechAudioSink(tmp_path / "audio", CountingTts())
    await sink.narrate("g1", _public(5), None)  # 未配置旁白：不抛、不做事


@pytest.mark.asyncio
async def test_warm_includes_narrator_voice(tmp_path: Path) -> None:
    tts = CountingTts()
    sink = SpeechAudioSink(
        tmp_path / "audio",
        tts,
        narration=_narr(tmp_path),
        narration_cache=NarrationCache(tmp_path / "narr"),
    )
    await sink.warm([VoiceSpec(mode="preset", speaker="dylan")])
    assert len(tts.calls) == 2  # dylan + uncle_fu 各一句
