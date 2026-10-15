"""TTS 客户端（issue #103）：分句、WAV 时长、三种 kind 的请求映射、错误与 probe。"""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from app.agent.profile import VoiceSpec
from app.runtime.tts import (
    ANCHOR_TEXT,
    SENTENCE_LIMIT,
    DisabledTtsClient,
    HttpTtsClient,
    TtsConfig,
    TtsError,
    concat_wav,
    split_sentences,
    wav_duration,
)


def _wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def test_split_sentences_rules() -> None:
    text = "各位好。我是3号！昨晚平安夜；我先说一下看法？\n\n好的。"
    assert split_sentences(text) == [
        "各位好。我是3号！",
        "昨晚平安夜；",
        "我先说一下看法？",
        "好的。",
    ]
    # 短句合并到 ≥ 8 字；末尾残句照出
    assert split_sentences("嗯。对。是的。然后呢我继续说下去。尾") == [
        "嗯。对。是的。",
        "然后呢我继续说下去。",
        "尾",
    ]
    assert split_sentences("   \n ") == []
    many = "好。" * (SENTENCE_LIMIT * 10)
    assert len(split_sentences(many)) == SENTENCE_LIMIT


def test_wav_duration_and_rejects_non_wav() -> None:
    assert abs(wav_duration(_wav(1.5)) - 1.5) < 0.01
    with pytest.raises(TtsError):
        wav_duration(b"ID3 not a wav at all" + b"\x00" * 64)
    with pytest.raises(TtsError):
        wav_duration(b"RIFF\x00\x00\x00\x00WAVE")  # 无 fmt/data 块


def _client(kind: str, handler) -> HttpTtsClient:  # type: ignore[no-untyped-def]
    cfg = TtsConfig(
        url="http://tts.local",
        kind=kind,  # type: ignore[arg-type]
        model_preset="m-preset",
        model_design="m-design",
        api_key="sk-secret",
    )
    return HttpTtsClient(cfg, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_mlx_audio_request_mapping_and_parts() -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/audio/speech"
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=_wav(0.5), headers={"content-type": "audio/wav"})

    c = _client("mlx_audio", handler)
    parts = [
        p
        async for p in c.synthesize_sentences(
            "第一句话很长很长。第二句也不短啊。",
            VoiceSpec(mode="preset", speaker="dylan", style="高兴", speed=1.2),
        )
    ]
    assert [p.index for p in parts] == [0, 1] and all(
        abs(p.duration_sec - 0.5) < 0.01 for p in parts
    )
    assert seen[0] == {
        "model": "m-preset",
        "input": "第一句话很长很长。",
        "voice": "dylan",
        "speed": 1.2,
        "response_format": "wav",
        "instruct": "高兴",
        "lang_code": "chinese",
    }
    seen.clear()
    [
        p
        async for p in c.synthesize_sentences(
            "设计声线测试句子。", VoiceSpec(mode="design", style="沙哑老头")
        )
    ]
    assert (
        seen[0]["model"] == "m-design"
        and "voice" not in seen[0]
        and seen[0]["instruct"] == "沙哑老头"
    )


@pytest.mark.asyncio
async def test_openai_and_generic_mapping() -> None:
    seen: list[tuple[dict, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((json.loads(req.content), dict(req.headers)))
        return httpx.Response(200, content=_wav(0.2))

    c = _client("openai", handler)
    [
        p
        async for p in c.synthesize_sentences(
            "你好世界再见世界。", VoiceSpec(mode="design", style="温柔")
        )
    ]
    body, headers = seen[0]
    assert body == {
        "model": "m-preset",
        "input": "你好世界再见世界。",
        "voice": "alloy",
        "speed": 1.0,
        "response_format": "wav",
        "instructions": "温柔",
    }
    assert headers["authorization"] == "Bearer sk-secret"
    seen.clear()
    g = _client("generic", handler)
    [
        p
        async for p in g.synthesize_sentences(
            "你好世界再见世界。", VoiceSpec(mode="preset", speaker="eric", style="丢弃我")
        )
    ]
    body, headers = seen[0]
    assert body == {
        "model": "m-preset",
        "input": "你好世界再见世界。",
        "voice": "eric",
        "speed": 1.0,
        "response_format": "wav",
    }
    assert headers["authorization"] == "Bearer sk-secret"  # generic 网关也要鉴权（issue #108）


@pytest.mark.asyncio
async def test_errors_become_tts_error_without_leaking_key() -> None:
    def bad(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom sk-secret")

    c = _client("openai", bad)
    with pytest.raises(TtsError) as ei:
        [
            p
            async for p in c.synthesize_sentences(
                "你好世界再见世界。", VoiceSpec(mode="design", style="x")
            )
        ]
    assert "sk-secret" not in str(ei.value) and "500" in str(ei.value)

    def not_wav(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(TtsError):
        [
            p
            async for p in _client("generic", not_wav).synthesize_sentences(
                "你好世界再见世界。", VoiceSpec(mode="preset", speaker="vivian")
            )
        ]


@pytest.mark.asyncio
async def test_probe_and_disabled() -> None:
    def ok(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    st = await _client("mlx_audio", ok).probe()
    assert st.enabled and st.ok and st.supports_style and st.url == "http://tts.local"

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    st = await _client("generic", down).probe()
    assert st.enabled and not st.ok and st.detail and not st.supports_style
    d = await DisabledTtsClient().probe()
    assert not d.enabled and not d.ok and d.url is None
    with pytest.raises(TtsError):
        [
            p
            async for p in DisabledTtsClient().synthesize_sentences(
                "x", VoiceSpec(mode="design", style="y")
            )
        ]


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTHOWL_TTS_URL", raising=False)
    assert TtsConfig.from_env().url is None
    monkeypatch.setenv("AGENTHOWL_TTS_URL", "http://127.0.0.1:8880/")
    monkeypatch.setenv("AGENTHOWL_TTS_KIND", "openai")
    monkeypatch.setenv("AGENTHOWL_TTS_API_KEY", "k")
    cfg = TtsConfig.from_env()
    assert (
        cfg.url == "http://127.0.0.1:8880"
        and cfg.kind == "openai"
        and cfg.api_key is not None
        and cfg.api_key.get_secret_value() == "k"
    )
    assert cfg.model_preset.startswith("mlx-community/Qwen3-TTS") and cfg.model_design.endswith(
        "VoiceDesign-6bit"
    )


@pytest.mark.asyncio
async def test_clone_mapping_with_anchor_and_ref_dir(tmp_path: Path) -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=_wav(0.2))

    ref = tmp_path / "0123456789abcdef.wav"
    ref.write_bytes(_wav(0.1))
    c = _client("mlx_audio", handler)
    v = VoiceSpec(mode="design", style="沙哑老头", anchor="0123456789abcdef.wav")
    [p async for p in c.synthesize_sentences("这是第一句够长的话。", v, ref)]
    body = seen[0]
    assert body["ref_audio"] == str(ref.resolve()) and body["ref_text"] == ANCHOR_TEXT
    assert "instruct" not in body and "voice" not in body and body["lang_code"] == "chinese"
    assert body["model"].endswith("Base-6bit")  # 默认克隆模型
    # ref_dir：按文件名映射到 TTS 服务眼中的目录
    cfg = TtsConfig(url="http://tts.local", model_clone="m-clone", ref_dir="/host/voices/")
    c2 = HttpTtsClient(cfg, transport=httpx.MockTransport(handler))
    seen.clear()
    [p async for p in c2.synthesize_sentences("这是第一句够长的话。", v, ref)]
    assert seen[0]["ref_audio"] == "/host/voices/0123456789abcdef.wav"
    assert seen[0]["model"] == "m-clone"
    # 没有锚点：仍走设计模型 + instruct
    seen.clear()
    [p async for p in c.synthesize_sentences("这是第一句够长的话。", v)]
    assert seen[0]["model"] == "m-design" and seen[0]["instruct"] == "沙哑老头"


@pytest.mark.asyncio
async def test_design_anchor_uses_design_model_and_anchor_text() -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=_wav(0.3))

    wav = await _client("mlx_audio", handler).design_anchor("甜美少女")
    assert wav[:4] == b"RIFF" and seen[0]["model"] == "m-design" and seen[0]["input"] == ANCHOR_TEXT
    assert seen[0]["instruct"] == "甜美少女"

    def not_wav(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nope")

    with pytest.raises(TtsError):
        await _client("mlx_audio", not_wav).design_anchor("x")
    with pytest.raises(TtsError):
        await DisabledTtsClient().design_anchor("x")


def test_config_from_env_clone_and_ref_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTHOWL_TTS_URL", "http://127.0.0.1:8880")
    monkeypatch.setenv("AGENTHOWL_TTS_MODEL_CLONE", "x/clone")
    monkeypatch.setenv("AGENTHOWL_TTS_REF_DIR", "/host/voices/")
    cfg = TtsConfig.from_env()
    assert cfg.model_clone == "x/clone" and cfg.ref_dir == "/host/voices"
    monkeypatch.delenv("AGENTHOWL_TTS_MODEL_CLONE")
    monkeypatch.delenv("AGENTHOWL_TTS_REF_DIR")
    cfg = TtsConfig.from_env()
    assert cfg.model_clone.endswith("Base-6bit") and cfg.ref_dir is None


@pytest.mark.asyncio
async def test_retry_on_timeout_and_skip_failed_sentence() -> None:
    """冷启动超时再试一次；单句失败跳过不拖累整段；全部失败才抛。"""
    calls: list[str] = []

    def flaky(req: httpx.Request) -> httpx.Response:
        sentence = json.loads(req.content)["input"]
        calls.append(sentence)
        if sentence.startswith("第一句") and calls.count(sentence) == 1:
            raise httpx.ReadTimeout("slow")  # 第一次超时，重试成功
        if sentence.startswith("第二句"):
            return httpx.Response(500, text="boom")  # 两次都 5xx → 这句丢弃
        return httpx.Response(200, content=_wav(0.2))

    c = _client("generic", flaky)
    v = VoiceSpec(mode="preset", speaker="vivian")
    text = "第一句话够长了吧。第二句也够长了吧。第三句照常出声。"
    parts = [p async for p in c.synthesize_sentences(text, v)]
    assert [p.index for p in parts] == [0, 2]
    assert calls.count("第一句话够长了吧。") == 2 and calls.count("第二句也够长了吧。") == 2

    def always_400(req: httpx.Request) -> httpx.Response:
        calls.append("x")
        return httpx.Response(400)

    calls.clear()
    with pytest.raises(TtsError):
        bad = _client("generic", always_400)
        [p async for p in bad.synthesize_sentences("全军覆没的一句话。", v)]
    assert calls == ["x"]  # 4xx 不重试


def test_api_key_is_secret_and_url_strips_userinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.runtime.tts import public_url

    monkeypatch.setenv("AGENTHOWL_TTS_URL", "http://user:pw@tts.local:8880")
    monkeypatch.setenv("AGENTHOWL_TTS_API_KEY", "sk-very-secret")
    cfg = TtsConfig.from_env()
    assert "sk-very-secret" not in repr(cfg) and "sk-very-secret" not in str(cfg.model_dump())
    assert cfg.api_key is not None and cfg.api_key.get_secret_value() == "sk-very-secret"
    assert public_url(cfg.url) == "http://tts.local:8880"
    assert public_url("http://tts.local:8880/") == "http://tts.local:8880/"
    assert public_url(None) is None


@pytest.mark.asyncio
async def test_probe_echoes_url_without_userinfo() -> None:
    def ok(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    cfg = TtsConfig(url="http://u:p@tts.local", api_key=None)
    st = await HttpTtsClient(cfg, transport=httpx.MockTransport(ok)).probe()
    assert st.url == "http://tts.local" and "u:p" not in st.model_dump_json()


def test_wav_duration_from_header_only_trusts_declared_size() -> None:
    full = _wav(10.0)
    assert abs(wav_duration(full[: 64 * 1024]) - 10.0) < 0.01


def _pcm_wav(seconds: float, rate: int = 8000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)
    return buf.getvalue()


def test_concat_wav_joins_data_chunks() -> None:
    out = concat_wav([_pcm_wav(0.2), _pcm_wav(0.3)])
    assert out[:4] == b"RIFF" and wav_duration(out) == pytest.approx(0.5, abs=0.001)
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 8000 and w.getnframes() == 4000


def test_concat_wav_single_and_errors() -> None:
    one = _pcm_wav(0.1)
    assert concat_wav([one]) is one
    with pytest.raises(TtsError):
        concat_wav([])
    with pytest.raises(TtsError):
        concat_wav([_pcm_wav(0.1, rate=8000), _pcm_wav(0.1, rate=16000)])
    with pytest.raises(TtsError):
        concat_wav([one, b"not a wav"])


def _riff(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"WAVE"
    for cid, data in chunks:
        body += cid + len(data).to_bytes(4, "little") + data + (b"\x00" if len(data) & 1 else b"")
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _fmt(rate: int = 8000, channels: int = 1, width: int = 2) -> bytes:
    import struct

    return struct.pack(
        "<HHIIHH", 1, channels, rate, rate * channels * width, channels * width, width * 8
    )


def test_concat_wav_rejects_data_before_fmt() -> None:
    bad = _riff((b"data", b"\x01\x00"), (b"fmt ", _fmt()))
    with pytest.raises(TtsError):
        concat_wav([bad, _pcm_wav(0.1)])


def test_concat_wav_odd_size_padding() -> None:
    a = _riff((b"fmt ", _fmt(width=1)), (b"data", b"\x80" * 3))
    b = _riff((b"fmt ", _fmt(width=1)), (b"data", b"\x80" * 4))
    out = concat_wav([a, b])
    assert int.from_bytes(out[4:8], "little") == len(out) - 8
    with wave.open(io.BytesIO(out)) as w:
        assert w.getsampwidth() == 1 and w.getnframes() == 7
    odd = concat_wav([a, _riff((b"fmt ", _fmt(width=1)), (b"data", b"\x80"))])
    assert int.from_bytes(odd[4:8], "little") == len(odd) - 8
    with wave.open(io.BytesIO(odd)) as w:
        assert w.getnframes() == 4


def test_concat_wav_channel_mismatch_and_single_non_wav() -> None:
    with pytest.raises(TtsError):
        concat_wav([_pcm_wav(0.1), _pcm_wav(0.1, channels=2)])
    with pytest.raises(TtsError):
        concat_wav([b"not a wav"])


def test_concat_wav_three_parts_duration_sum() -> None:
    out = concat_wav([_pcm_wav(0.1), _pcm_wav(0.2), _pcm_wav(0.3)])
    assert wav_duration(out) == pytest.approx(0.6, abs=0.001)


def test_concat_wav_rejects_truncated_and_empty_data() -> None:
    full = _pcm_wav(0.1)
    with pytest.raises(TtsError):
        concat_wav([full, full[:-10]])
    stream = bytearray(full)
    stream[full.index(b"data") + 4 : full.index(b"data") + 8] = b"\xff\xff\xff\xff"
    with pytest.raises(TtsError):
        concat_wav([full, bytes(stream)])
    empty = _riff((b"fmt ", _fmt()), (b"data", b""))
    with pytest.raises(TtsError):
        concat_wav([full, empty])
