"""TTS 客户端（issue #103）：分句、WAV 时长、三种 kind 的请求映射、错误与 probe。"""

import io
import json
import wave

import httpx
import pytest

from app.agent.profile import VoiceSpec
from app.runtime.tts import (
    SENTENCE_LIMIT,
    DisabledTtsClient,
    HttpTtsClient,
    TtsConfig,
    TtsError,
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
        api_key="sk-secret" if kind == "openai" else None,
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
    assert "authorization" not in headers


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
    assert cfg.url == "http://127.0.0.1:8880" and cfg.kind == "openai" and cfg.api_key == "k"
    assert cfg.model_preset.startswith("mlx-community/Qwen3-TTS") and cfg.model_design.endswith(
        "VoiceDesign-6bit"
    )
