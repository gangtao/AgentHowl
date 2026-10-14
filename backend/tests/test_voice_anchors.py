"""描述声线锚点（issue #103 跟进）：显式/自动锚点、幂等、非法 id、
sink 把锚点作为 ref_audio 传给 TTS。"""

import io
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.agent.profile import VoiceSpec
from app.runtime.speech_audio import SpeechAudioSink
from app.runtime.tts import ANCHOR_TEXT, AudioPart, TtsError, TtsStatus
from app.runtime.voice_anchors import VoiceAnchorStore


def _wav(seconds: float = 0.05) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


class RecTts:
    """记录每次合成收到的 ref_audio；design_anchor 返回带描述长度标记的 WAV（可区分）。"""

    def __init__(self, fail_design: bool = False) -> None:
        self.refs: list[Path | None] = []
        self.designed: list[str] = []
        self.fail_design = fail_design

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: Path | None = None
    ) -> AsyncIterator[AudioPart]:
        self.refs.append(ref_audio)
        yield AudioPart(index=0, wav=_wav(), duration_sec=0.05)

    async def design_anchor(self, style: str) -> bytes:
        if self.fail_design:
            raise TtsError("design down")
        self.designed.append(style)
        return _wav(0.05 + 0.01 * len(style))

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


def test_put_is_content_addressed_and_validates(tmp_path: Path) -> None:
    store = VoiceAnchorStore(tmp_path / "voices")
    a = store.put(_wav())
    assert a == store.put(_wav()) and a.endswith(".wav") and len(a) == 20
    assert store.path_for(a) is not None
    assert store.path_for("0000000000000000.wav") is None
    for bad in ("../x.wav", "x.wav", "auto-0000000000000000.wav"):
        with pytest.raises(ValueError):
            store.path_for(bad)
    with pytest.raises(TtsError):
        store.put(b"not a wav")


@pytest.mark.asyncio
async def test_ensure_for_explicit_auto_and_preset(tmp_path: Path) -> None:
    store = VoiceAnchorStore(tmp_path / "voices")
    tts = RecTts()
    assert await store.ensure_for(VoiceSpec(mode="preset", speaker="dylan"), tts) is None
    # 自动锚点：同一描述只生成一次
    v = VoiceSpec(mode="design", style="沙哑老头")
    p1 = await store.ensure_for(v, tts)
    p2 = await store.ensure_for(v, tts)
    assert p1 == p2 and p1 is not None and p1.name.startswith("auto-")
    assert tts.designed == ["沙哑老头"]
    # 显式锚点优先；文件丢了退回自动
    explicit = store.put(_wav(0.2))
    ve = VoiceSpec(mode="design", style="沙哑老头", anchor=explicit)
    assert (await store.ensure_for(ve, tts)) == store.path_for(explicit)
    missing = VoiceSpec(mode="design", style="沙哑老头", anchor="0000000000000000.wav")
    assert (await store.ensure_for(missing, tts)) == p1
    assert tts.designed == ["沙哑老头"]
    with pytest.raises(TtsError):
        await store.ensure_for(VoiceSpec(mode="design", style="新描述"), RecTts(fail_design=True))


@pytest.mark.asyncio
async def test_sink_passes_anchor_as_ref_and_falls_back(tmp_path: Path) -> None:
    store = VoiceAnchorStore(tmp_path / "voices")
    tts = RecTts()
    sink = SpeechAudioSink(tmp_path / "audio", tts, store)
    text = "这是一句够长的发言内容。"
    await sink.speak("g1", 1, text, VoiceSpec(mode="design", style="甜美少女"), None)
    await sink.speak("g1", 2, text, VoiceSpec(mode="preset", speaker="eric"), None)
    assert tts.refs[0] is not None and tts.refs[0].name.startswith("auto-") and tts.refs[1] is None
    # 锚点生成失败：退回逐句设计（ref=None），对局继续
    bad = RecTts(fail_design=True)
    sink2 = SpeechAudioSink(tmp_path / "audio", bad, store)
    await sink2.speak("g1", 3, text, VoiceSpec(mode="design", style="另一种"), None)
    assert bad.refs == [None]
    assert ANCHOR_TEXT  # 常量存在且非空
