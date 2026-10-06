# Agent 语音实现计划（issue #103）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个 agent 有自己的声线；发言时后端逐句调本地 TTS（OpenAI `/v1/audio/speech` 兼容服务）合成、落盘、推 WS 帧，对局节奏等语音播完再轮到下一位；前端直播队列播放、回放按音频暂停/继续。

**Architecture:** 引擎零改动。`AgentProfile.voice: VoiceSpec` 描述声线；`app/runtime/tts.py` 是唯一的 TTS HTTP 客户端
（按 `AGENTHOWL_TTS_KIND` 映射扩展字段）；`app/runtime/speech_audio.py` 的 `SpeechAudioSink` 负责「逐句合成→落盘
`data/audio/<game_id>/<seq>-<k>.wav`→经 `ConnectionManager.broadcast_frame` 推 `speech_audio` 帧→停留 Σduration+0.3 s」；
`GameRunner` 在 `PLAYER_SPOKE`/`LAST_WORDS` 提交后调用 sink。`speech_audio` 是非游戏事件的 WS 帧：不进事件日志、不进 reducer、
不进 golden fixtures。前端 `useVoice` store 管 🔊 开关与播放队列；回放靠 `game.ts` 新增的 `replayGate` 在有音频的发言 seq 上暂停节拍。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / httpx（补进主依赖）/ pytest；React 18 / TS strict / Zustand / Vitest；
本地 TTS：独立 `tts/` uv 项目 + mlx-audio（macOS arm64）。

**Spec:** `docs/superpowers/specs/2026-10-05-agent-avatar-voice-design.md` §2、§4、§5、§6

## Global Constraints

- `backend/app/engine` 零 diff；`frontend/src/engine/reduce.ts`、`__fixtures__` 不变（`speech_audio` 不是事件）。
- `app/runtime`、`app/api` 不得模块级 import `app.agent.agent_player` / `app.agent.llm_client`；守卫测试 `tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm`。
- 后端不引入 MLX / 音频库；只用 `httpx` + 标准库解析 WAV 头。TTS 请求只发发言正文，不带私聊 / 角色 / 隐藏信息。
- `AGENTHOWL_TTS_API_KEY` 永不出现在响应、日志、`GameMeta`。
- 音频端点权限**同 `/replay`**（`_finished_or_handle(..., "PLAYER","SPECTATOR","HOST","GM", require_finished=False)`）。路径参数 `seq`/`part` 为 int，文件名只由它们拼出。
- 分句规则：按 `。！？；\n` 切，保留标点；连续短句合并到 ≥ 8 字；空白句丢弃；上限 40 句（截断 + WARNING）。单句 TTS 超时 20 s。
- 节奏：窗口停留 = 从**第一句推送**起 Σduration + 0.3 s；TTS 失败 → WARNING，已推句子照常等待，对局继续。无 `voice` 档案 / 真人 / 随机 bot 的座位不等待。
- `CreateGameRequest.voice` 默认 `False`：不勾语音的对局与现状逐字一致。
- 前端零信息过滤；只播服务端推来的 url；🔊 默认关（浏览器 autoplay 需手势），`localStorage` 记住。
- 中文注释 / 英文标识符；ruff 100 列 / mypy strict / `npm run check` 全绿后提交；提交带 `(issue #103)` 与 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

---

### Task 1: 后端 —— `VoiceSpec` 档案字段 + TTS 客户端（分句、WAV 时长、HTTP 映射、probe）

**Files:**
- Modify: `backend/app/agent/profile.py`（`VoiceSpec`、`PRESET_SPEAKERS`、`AgentProfile.voice`）
- Create: `backend/app/runtime/tts.py`
- Modify: `backend/pyproject.toml`（`httpx>=0.28.1` 移入 `dependencies`，dev 组可保留）
- Test: `backend/tests/test_agent_profile.py`（追加）、`backend/tests/test_tts.py`（新建）

**Interfaces:**
- Produces（后续任务逐字消费）：
  - `app.agent.profile`: `PRESET_SPEAKERS = ("vivian", "serena", "uncle_fu", "dylan", "eric")`；`class VoiceSpec(mode: Literal["preset","design"], speaker: str|None, style: str|None, speed: float=1.0)`；`AgentProfile.voice: VoiceSpec | None`。
  - `app.runtime.tts`: `TtsKind = Literal["mlx_audio","openai","generic"]`；`class TtsConfig(url: str|None, kind: TtsKind="mlx_audio", model_preset: str, model_design: str, api_key: str|None)` 带 `@classmethod from_env()`；`class TtsError(Exception)`；`class AudioPart(index:int, wav:bytes, duration_sec:float)`；`class TtsStatus(enabled:bool, ok:bool, url:str|None, detail:str|None, supports_style:bool)`；`split_sentences(text:str) -> list[str]`；`wav_duration(wav:bytes) -> float`；`class TtsClient(Protocol)` with `async synthesize_sentences(text, voice) -> AsyncIterator[AudioPart]` 与 `async probe() -> TtsStatus`；`class HttpTtsClient(config, transport: httpx.AsyncBaseTransport|None=None)`；`class DisabledTtsClient`（`probe` → `enabled=False`，`synthesize_sentences` 抛 `TtsError`）；`SENTENCE_LIMIT = 40`、`MIN_SENTENCE_CHARS = 8`、`REQUEST_TIMEOUT_SEC = 20.0`。

- [ ] **Step 1: 写档案字段的失败测试**

`backend/tests/test_agent_profile.py` 末尾追加：

```python
def test_voice_spec_validation() -> None:
    """issue #103：preset 必须有白名单 speaker；design 必须有 style 且不带 speaker；speed 0.5–2.0。"""
    from pydantic import ValidationError

    from app.agent.profile import VoiceSpec

    assert AgentProfile(model="x").voice is None
    ok = AgentProfile(model="x", voice=VoiceSpec(mode="preset", speaker="dylan"))
    assert ok.voice is not None and ok.voice.speed == 1.0
    VoiceSpec(mode="preset", speaker="eric", style="非常愤怒，语速快", speed=1.5)
    VoiceSpec(mode="design", style="沙哑低沉的老爷爷")
    for bad in (
        {"mode": "preset"},  # 缺 speaker
        {"mode": "preset", "speaker": "nobody"},
        {"mode": "preset", "speaker": "vivian", "style": "x" * 201},
        {"mode": "design"},  # 缺 style
        {"mode": "design", "style": "   "},
        {"mode": "design", "style": "ok", "speaker": "vivian"},
        {"mode": "preset", "speaker": "vivian", "speed": 0.4},
        {"mode": "preset", "speaker": "vivian", "speed": 2.1},
        {"mode": "clone", "style": "x"},
    ):
        with pytest.raises(ValidationError):
            VoiceSpec.model_validate(bad)
    # 不进 LLM 配置
    cfg = to_agent_config(ok, build_preset("std_9_kill_side"))
    assert not hasattr(cfg, "voice")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agent_profile.py::test_voice_spec_validation -q`
Expected: FAIL（ImportError: VoiceSpec）

- [ ] **Step 3: 加 `VoiceSpec`**

`backend/app/agent/profile.py`：import 加 `from typing import TYPE_CHECKING, Literal` 与 `from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator`；在 `AVATAR_ID_PATTERN` 后加：

```python
# 预置声线（issue #103）：Qwen3-TTS CustomVoice 的中文 speaker；dylan=北京话、eric=四川话
PRESET_SPEAKERS = ("vivian", "serena", "uncle_fu", "dylan", "eric")
MAX_VOICE_STYLE_CHARS = 200


class VoiceSpec(BaseModel):
    """声线描述（issue #103）。preset：预置 speaker + 可选情绪/语速指令；design：一句话描述声线。
    只影响 TTS 请求，不进 LLM 上下文。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["preset", "design"]
    speaker: str | None = None
    style: str | None = Field(default=None, max_length=MAX_VOICE_STYLE_CHARS)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)

    @field_validator("style", mode="before")
    @classmethod
    def _strip_style(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _check_mode(self) -> VoiceSpec:
        if self.mode == "preset":
            if self.speaker is None or self.speaker not in PRESET_SPEAKERS:
                raise ValueError(f"preset 声线须指定 speaker ∈ {PRESET_SPEAKERS}")
        else:
            if self.style is None:
                raise ValueError("design 声线须给出 style（声线描述）")
            if self.speaker is not None:
                raise ValueError("design 声线不能同时指定 speaker")
        return self
```

`AgentProfile` 在 `avatar` 之后加：

```python
    # 声线（issue #103）：None = 不配音；不进 LLM 上下文
    voice: VoiceSpec | None = None
```

- [ ] **Step 4: 跑档案测试**

Run: `cd backend && uv run pytest tests/test_agent_profile.py -q`
Expected: 全 PASS（含 litellm 守卫）。注意 `tests/test_api_lobby.py::test_create_legacy_ai_model_echoes_star` 的回显期望需加 `"voice": None`（紧跟 `"avatar": None`），同样在本任务里改。

- [ ] **Step 5: 写 TTS 客户端的失败测试**

新建 `backend/tests/test_tts.py`：

```python
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
    assert split_sentences(text) == ["各位好。我是3号！", "昨晚平安夜；", "我先说一下看法？", "好的。"]
    # 短句合并到 ≥ 8 字；末尾残句照出
    assert split_sentences("嗯。对。是的。然后呢我继续说下去。尾") == ["嗯。对。是的。", "然后呢我继续说下去。", "尾"]
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
    parts = [p async for p in c.synthesize_sentences("第一句话很长很长。第二句也不短啊。", VoiceSpec(mode="preset", speaker="dylan", style="高兴", speed=1.2))]
    assert [p.index for p in parts] == [0, 1] and all(abs(p.duration_sec - 0.5) < 0.01 for p in parts)
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
    [p async for p in c.synthesize_sentences("设计声线测试句子。", VoiceSpec(mode="design", style="沙哑老头"))]
    assert seen[0]["model"] == "m-design" and "voice" not in seen[0] and seen[0]["instruct"] == "沙哑老头"


@pytest.mark.asyncio
async def test_openai_and_generic_mapping() -> None:
    seen: list[tuple[dict, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((json.loads(req.content), dict(req.headers)))
        return httpx.Response(200, content=_wav(0.2))

    c = _client("openai", handler)
    [p async for p in c.synthesize_sentences("你好世界再见世界。", VoiceSpec(mode="design", style="温柔"))]
    body, headers = seen[0]
    assert body == {"model": "m-preset", "input": "你好世界再见世界。", "voice": "alloy", "speed": 1.0, "response_format": "wav", "instructions": "温柔"}
    assert headers["authorization"] == "Bearer sk-secret"
    seen.clear()
    g = _client("generic", handler)
    [p async for p in g.synthesize_sentences("你好世界再见世界。", VoiceSpec(mode="preset", speaker="eric", style="丢弃我"))]
    body, headers = seen[0]
    assert body == {"model": "m-preset", "input": "你好世界再见世界。", "voice": "eric", "speed": 1.0, "response_format": "wav"}
    assert "authorization" not in headers


@pytest.mark.asyncio
async def test_errors_become_tts_error_without_leaking_key() -> None:
    def bad(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom sk-secret")

    c = _client("openai", bad)
    with pytest.raises(TtsError) as ei:
        [p async for p in c.synthesize_sentences("你好世界再见世界。", VoiceSpec(mode="design", style="x"))]
    assert "sk-secret" not in str(ei.value) and "500" in str(ei.value)

    def not_wav(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    with pytest.raises(TtsError):
        [p async for p in _client("generic", not_wav).synthesize_sentences("你好世界再见世界。", VoiceSpec(mode="preset", speaker="vivian"))]


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
        [p async for p in DisabledTtsClient().synthesize_sentences("x", VoiceSpec(mode="design", style="y"))]


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTHOWL_TTS_URL", raising=False)
    assert TtsConfig.from_env().url is None
    monkeypatch.setenv("AGENTHOWL_TTS_URL", "http://127.0.0.1:8880/")
    monkeypatch.setenv("AGENTHOWL_TTS_KIND", "openai")
    monkeypatch.setenv("AGENTHOWL_TTS_API_KEY", "k")
    cfg = TtsConfig.from_env()
    assert cfg.url == "http://127.0.0.1:8880" and cfg.kind == "openai" and cfg.api_key == "k"
    assert cfg.model_preset.startswith("mlx-community/Qwen3-TTS") and cfg.model_design.endswith("VoiceDesign-6bit")
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_tts.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 7: 实现 `tts.py`**

先把 `httpx>=0.28.1` 加进 `pyproject.toml` 的 `dependencies`（`uv sync`）。新建 `backend/app/runtime/tts.py`：

```python
"""TTS 客户端（issue #103）：只说 OpenAI `POST /v1/audio/speech` 一种协议，按 kind 映射扩展字段。

规格 §4.1。不引入音频库：WAV 时长从 RIFF 头算。只发发言正文；api key 永不进日志 / 异常文本。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from app.agent.profile import VoiceSpec

logger = logging.getLogger(__name__)

TtsKind = Literal["mlx_audio", "openai", "generic"]
SENTENCE_LIMIT = 40
MIN_SENTENCE_CHARS = 8
REQUEST_TIMEOUT_SEC = 20.0
PROBE_TIMEOUT_SEC = 2.0
DEFAULT_MODEL_PRESET = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit"
DEFAULT_MODEL_DESIGN = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit"
_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")


class TtsError(Exception):
    """TTS 请求失败（超时 / 非 2xx / 非 WAV / 服务未配置）。"""


class TtsConfig(BaseModel):
    url: str | None = None
    kind: TtsKind = "mlx_audio"
    model_preset: str = DEFAULT_MODEL_PRESET
    model_design: str = DEFAULT_MODEL_DESIGN
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> TtsConfig:
        url = os.environ.get("AGENTHOWL_TTS_URL", "").strip().rstrip("/") or None
        kind = os.environ.get("AGENTHOWL_TTS_KIND", "mlx_audio").strip() or "mlx_audio"
        return cls(
            url=url,
            kind=kind,  # type: ignore[arg-type]  # 非法值由 pydantic 报错（fail-loud）
            model_preset=os.environ.get("AGENTHOWL_TTS_MODEL_PRESET", "").strip() or DEFAULT_MODEL_PRESET,
            model_design=os.environ.get("AGENTHOWL_TTS_MODEL_DESIGN", "").strip() or DEFAULT_MODEL_DESIGN,
            api_key=os.environ.get("AGENTHOWL_TTS_API_KEY", "").strip() or None,
        )


class AudioPart(BaseModel):
    index: int
    wav: bytes
    duration_sec: float


class TtsStatus(BaseModel):
    enabled: bool
    ok: bool
    url: str | None
    detail: str | None = None
    supports_style: bool = False


def split_sentences(text: str) -> list[str]:
    """按 。！？；换行 切句并保留标点；连续短句合并到 ≥ MIN_SENTENCE_CHARS；上限 SENTENCE_LIMIT。"""
    out: list[str] = []
    buf = ""
    for piece in _SPLIT_RE.split(text):
        s = piece.strip()
        if not s:
            continue
        buf += s
        if len(buf) >= MIN_SENTENCE_CHARS:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    if len(out) > SENTENCE_LIMIT:
        logger.warning("发言分句 %d 句超过上限 %d，截断", len(out), SENTENCE_LIMIT)
        out = out[:SENTENCE_LIMIT]
    return out


def wav_duration(wav: bytes) -> float:
    """RIFF/WAVE：fmt 块的 byte rate 与 data 块长度 → 秒；不是 WAV → TtsError。"""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise TtsError("TTS 返回的不是 WAV")
    pos = 12
    byte_rate: int | None = None
    data_len: int | None = None
    while pos + 8 <= len(wav):
        cid = wav[pos : pos + 4]
        size = int.from_bytes(wav[pos + 4 : pos + 8], "little")
        if cid == b"fmt " and pos + 20 <= len(wav):
            byte_rate = int.from_bytes(wav[pos + 16 : pos + 20], "little")
        elif cid == b"data":
            data_len = min(size, len(wav) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if not byte_rate or data_len is None:
        raise TtsError("WAV 头缺少 fmt/data 块")
    return data_len / byte_rate


class TtsClient(Protocol):
    def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]: ...

    async def probe(self) -> TtsStatus: ...


class DisabledTtsClient:
    """未配置 AGENTHOWL_TTS_URL：status 报 enabled=False；合成直接报错（调用方不该走到这）。"""

    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]:
        raise TtsError("TTS 未配置（AGENTHOWL_TTS_URL 为空）")
        yield  # pragma: no cover  # 让函数成为 async generator

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=False, ok=False, url=None, detail="未配置 AGENTHOWL_TTS_URL")


class HttpTtsClient:
    def __init__(self, config: TtsConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if config.url is None:
            raise ValueError("HttpTtsClient 需要 url；未配置请用 DisabledTtsClient")
        self._cfg = config
        self._transport = transport

    @property
    def supports_style(self) -> bool:
        return self._cfg.kind in ("mlx_audio", "openai")

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._cfg.kind == "openai" and self._cfg.api_key:
            h["Authorization"] = f"Bearer {self._cfg.api_key}"
        return h

    def _body(self, sentence: str, voice: VoiceSpec) -> dict[str, object]:
        kind = self._cfg.kind
        body: dict[str, object] = {
            "model": self._cfg.model_design if (kind == "mlx_audio" and voice.mode == "design") else self._cfg.model_preset,
            "input": sentence,
            "speed": voice.speed,
            "response_format": "wav",
        }
        if kind == "mlx_audio":
            if voice.mode == "preset":
                body["voice"] = voice.speaker
            if voice.style:
                body["instruct"] = voice.style
            body["lang_code"] = "chinese"
        else:
            body["voice"] = voice.speaker or "alloy"
            if kind == "openai" and voice.style:
                body["instructions"] = voice.style
        return body

    async def synthesize_sentences(self, text: str, voice: VoiceSpec) -> AsyncIterator[AudioPart]:
        sentences = split_sentences(text)
        async with httpx.AsyncClient(
            base_url=self._cfg.url or "", timeout=REQUEST_TIMEOUT_SEC, transport=self._transport
        ) as client:
            for i, sentence in enumerate(sentences):
                try:
                    resp = await client.post("/v1/audio/speech", json=self._body(sentence, voice), headers=self._headers())
                except httpx.HTTPError as exc:
                    raise TtsError(f"TTS 请求失败：{type(exc).__name__}") from exc
                if resp.status_code >= 300:
                    # 不回显响应正文：可能含上游错误里的敏感信息
                    raise TtsError(f"TTS 服务返回 {resp.status_code}")
                wav = resp.content
                yield AudioPart(index=i, wav=wav, duration_sec=wav_duration(wav))

    async def probe(self) -> TtsStatus:
        try:
            async with httpx.AsyncClient(
                base_url=self._cfg.url or "", timeout=PROBE_TIMEOUT_SEC, transport=self._transport
            ) as client:
                resp = await client.get("/v1/models", headers=self._headers())
            ok = resp.status_code < 300
            detail = None if ok else f"/v1/models 返回 {resp.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, f"无法连接 TTS 服务：{type(exc).__name__}"
        return TtsStatus(enabled=True, ok=ok, url=self._cfg.url, detail=detail, supports_style=self.supports_style)


def build_tts_client(config: TtsConfig) -> TtsClient:
    return HttpTtsClient(config) if config.url else DisabledTtsClient()
```

注意 `test_probe_and_disabled` 期望 `generic` 的 `supports_style` 为假、连接失败时 `detail` 非空；`test_split_sentences_rules` 的第一个断言要求「各位好。」(4 字) 与「我是3号！」合并——按实现即是。

- [ ] **Step 8: 跑测试 + 门禁**

Run: `cd backend && uv run pytest tests/test_tts.py tests/test_agent_profile.py tests/test_api_lobby.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: 全 PASS；mypy 对 `DisabledTtsClient.synthesize_sentences` 的 `raise ... ; yield` 写法无报错（若报 unreachable，改为 `if True: raise TtsError(...)` 后 `yield`）。

- [ ] **Step 9: 提交**

```bash
git add backend/app/agent/profile.py backend/app/runtime/tts.py backend/pyproject.toml backend/uv.lock backend/tests/test_tts.py backend/tests/test_agent_profile.py backend/tests/test_api_lobby.py
git commit -m "feat(runtime): VoiceSpec 声线档案字段；OpenAI-speech 兼容 TTS 客户端（分句/WAV 时长/kind 映射/probe） (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 后端 —— `ConnectionManager` 原始帧广播 + `SpeechAudioSink` + runner 节奏同步 + registry 开关

**Files:**
- Modify: `backend/app/runtime/connection.py`（`FrameSubscriber`、`subscribe_frames/unsubscribe_frames/broadcast_frame`）
- Create: `backend/app/runtime/speech_audio.py`
- Modify: `backend/app/runtime/game_runner.py`（`speech_audio` 参数、`_maybe_speak`）
- Modify: `backend/app/runtime/registry.py`（`GameHandle.voice_enabled`、`GameRegistry(speech_audio=...)`、`create(voice=...)`、`start()` 注入）
- Test: `backend/tests/test_connection.py`（追加）、`backend/tests/test_speech_audio.py`（新建）、`backend/tests/test_game_runner.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `TtsClient`、`AudioPart`、`TtsError`、`VoiceSpec`、`wav_duration`。
- Produces：
  - `ConnectionManager.subscribe_frames(cb: FrameSubscriber)` / `unsubscribe_frames(cb)` / `async broadcast_frame(frame: dict[str, Any])`（`FrameSubscriber = Callable[[dict[str, Any]], Awaitable[None]]`；坏订阅者摘除并告警，同 `broadcast`）。
  - `app.runtime.speech_audio`: `AUDIO_TAIL_SEC = 0.3`；`class SpeechAudioSink(audio_dir: Path, tts: TtsClient)` with `async speak(game_id, seq, text, voice, connections: ConnectionManager | None) -> None`、`manifest(game_id) -> dict[str, list[dict[str, float | int]]]`（`{"57": [{"part": 0, "duration": 2.3}]}`，按 seq、part 升序）、`path_for(game_id, seq: int, part: int) -> Path | None`、`delete_game(game_id) -> None`（幂等）。帧形状：`{"type": "speech_audio", "seq": N, "part": k, "url": "/api/v1/games/{gid}/audio/{N}/{k}", "duration": 2.3}`；最后一句之后再推 `{"type": "speech_audio_end", "seq": N, "parts": k_total}`（**替代规格里的 `last` 字段**——生成完才知道哪句是最后一句）。
  - `GameRunner(..., speech_audio: SpeechAudioSink | None = None)`；`GameHandle.voice_enabled: bool`；`GameRegistry(..., speech_audio: SpeechAudioSink | None = None)`；`GameRegistry.create(..., voice: bool = False)`。

- [ ] **Step 1: 写 `ConnectionManager` 帧广播测试**

`backend/tests/test_connection.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_broadcast_frame_reaches_all_and_drops_bad_subscriber() -> None:
    """issue #103：原始帧（非事件）广播给所有帧订阅者，不经可见性过滤；坏订阅者摘除。"""
    cm = ConnectionManager(state_provider=_state)
    got: list[dict] = []

    async def good(frame: dict) -> None:
        got.append(frame)

    async def bad(frame: dict) -> None:
        raise RuntimeError("boom")

    cm.subscribe_frames(good)
    cm.subscribe_frames(bad)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 1})
    await cm.broadcast_frame({"type": "speech_audio_end", "seq": 1, "parts": 1})
    assert [f["type"] for f in got] == ["speech_audio", "speech_audio_end"]
    cm.unsubscribe_frames(good)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 2})
    assert len(got) == 2
```

（文件顶部若没有 `import pytest` 则补上；`_state` 是该文件已有的 fixture 函数。）

- [ ] **Step 2: 实现帧广播**

`connection.py`：加 `from typing import Any`、`FrameSubscriber = Callable[[dict[str, Any]], Awaitable[None]]`；`__init__` 加 `self._frame_subs: list[FrameSubscriber] = []`；方法：

```python
    def subscribe_frames(self, callback: FrameSubscriber) -> None:
        """原始帧订阅（issue #103 speech_audio）：帧不是事件，不经 visible_events 过滤——
        调用方只能放公开内容。"""
        self._frame_subs.append(callback)

    def unsubscribe_frames(self, callback: FrameSubscriber) -> None:
        self._frame_subs = [cb for cb in self._frame_subs if cb is not callback]

    async def broadcast_frame(self, frame: dict[str, Any]) -> None:
        for cb in list(self._frame_subs):
            try:
                await cb(frame)
            except Exception:
                logger.warning("帧订阅者回调异常，已摘除 type=%s", frame.get("type"), exc_info=True)
                self.unsubscribe_frames(cb)
```

Run: `cd backend && uv run pytest tests/test_connection.py -q` → PASS

- [ ] **Step 3: 写 `SpeechAudioSink` 的失败测试**

新建 `backend/tests/test_speech_audio.py`：

```python
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
        for i, s in enumerate(["第一句话够长了吧。", "第二句话也够长了。"]):
            if self.fail_at == i:
                raise TtsError("合成失败")
            yield AudioPart(index=i, wav=_wav(self.per), duration_sec=self.per)

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
    assert sorted(p.name for p in (tmp_path / "audio" / "g1").glob("*.wav")) == ["57-0.wav", "57-1.wav"]
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio", "speech_audio_end"]
    assert frames[0] == {"type": "speech_audio", "seq": 57, "part": 0, "url": "/api/v1/games/g1/audio/57/0", "duration": pytest.approx(0.2, abs=0.01)}
    assert frames[2] == {"type": "speech_audio_end", "seq": 57, "parts": 2}
    m = sink.manifest("g1")
    assert list(m) == ["57"] and [p["part"] for p in m["57"]] == [0, 1]
    assert sink.path_for("g1", 57, 1) is not None and sink.path_for("g1", 57, 9) is None
    assert sink.path_for("g1", 57, 0).read_bytes()[:4] == b"RIFF"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_speak_failure_midway_keeps_pushed_parts_and_returns(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames(sub)
    sink = SpeechAudioSink(tmp_path / "audio", FakeTts(per_sentence=0.1, fail_at=1))
    await sink.speak("g1", 3, "随便说点什么都行吧。再来一句凑数的。", VOICE, cm)
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio_end"] and frames[1]["parts"] == 1
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
    assert sink.manifest("g2") == {"5": [{"part": 0, "duration": pytest.approx(0.3, abs=0.01)}, {"part": 1, "duration": pytest.approx(0.3, abs=0.01)}]}
    assert sink.manifest("g_nope") == {}
    with pytest.raises(ValueError):
        sink.path_for("../g2", 5, 0)
    sink.delete_game("g2")
    sink.delete_game("g2")
    assert not d.exists()
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_speech_audio.py -q` → FAIL（ModuleNotFoundError）

- [ ] **Step 5: 实现 `speech_audio.py`**

```python
"""发言配音 sink（issue #103）：逐句合成 → 落盘 data/audio/<game_id>/<seq>-<k>.wav → 推 WS 帧 → 停留。

帧是**非游戏事件**：不进事件日志、不进 reducer；只承载公开发言的音频引用。
停留时长 = 从第一句推送起 Σduration + AUDIO_TAIL_SEC（生成快于播放，等待由音频长度主导）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from app.agent.profile import VoiceSpec
from app.runtime.connection import ConnectionManager
from app.runtime.tts import TtsClient, TtsError, wav_duration

logger = logging.getLogger(__name__)

AUDIO_TAIL_SEC = 0.3
_PART_RE = re.compile(r"^(\d+)-(\d+)\.wav$")
_GAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_game_id(game_id: str) -> None:
    """触盘前校验（路径穿越防护）；与 event_store 同口径，但抛 ValueError 便于 API 层映射。"""
    if not _GAME_ID_RE.fullmatch(game_id):
        raise ValueError(f"非法 game_id：{game_id!r}")


class SpeechAudioSink:
    def __init__(self, audio_dir: Path, tts: TtsClient) -> None:
        self._dir = audio_dir
        self._tts = tts

    # ---------- 合成 + 推帧 + 停留 ----------

    async def speak(
        self,
        game_id: str,
        seq: int,
        text: str,
        voice: VoiceSpec,
        connections: ConnectionManager | None,
    ) -> None:
        """失败不抛：WARNING 后对已推句子照常等待，对局继续。"""
        _check_game_id(game_id)
        first_ts: float | None = None
        total = 0.0
        parts = 0
        try:
            async for part in self._tts.synthesize_sentences(text, voice):
                path = self._dir / game_id / f"{seq}-{part.index}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(part.wav)
                if first_ts is None:
                    first_ts = time.monotonic()
                total += part.duration_sec
                parts += 1
                if connections is not None:
                    await connections.broadcast_frame(
                        {
                            "type": "speech_audio",
                            "seq": seq,
                            "part": part.index,
                            "url": f"/api/v1/games/{game_id}/audio/{seq}/{part.index}",
                            "duration": round(part.duration_sec, 3),
                        }
                    )
        except TtsError as exc:
            logger.warning("game=%s seq=%d 配音失败（已推 %d 句）：%s", game_id, seq, parts, exc)
        if parts and connections is not None:
            await connections.broadcast_frame({"type": "speech_audio_end", "seq": seq, "parts": parts})
        if first_ts is not None:
            await asyncio.sleep(max(0.0, first_ts + total + AUDIO_TAIL_SEC - time.monotonic()))

    # ---------- 读取 / 清理 ----------

    def manifest(self, game_id: str) -> dict[str, list[dict[str, Any]]]:
        """{seq: [{part, duration}]}，按 seq、part 升序；坏文件 / 非法名跳过。"""
        _check_game_id(game_id)
        d = self._dir / game_id
        if not d.is_dir():
            return {}
        found: dict[int, list[tuple[int, float]]] = {}
        for p in d.iterdir():
            m = _PART_RE.match(p.name)
            if m is None:
                continue
            try:
                dur = wav_duration(p.read_bytes())
            except (TtsError, OSError):
                logger.warning("音频文件损坏，跳过：%s", p)
                continue
            found.setdefault(int(m.group(1)), []).append((int(m.group(2)), dur))
        return {
            str(seq): [{"part": k, "duration": round(dur, 3)} for k, dur in sorted(parts)]
            for seq, parts in sorted(found.items())
        }

    def path_for(self, game_id: str, seq: int, part: int) -> Path | None:
        _check_game_id(game_id)
        p = self._dir / game_id / f"{int(seq)}-{int(part)}.wav"
        return p if p.is_file() else None

    def delete_game(self, game_id: str) -> None:
        _check_game_id(game_id)
        shutil.rmtree(self._dir / game_id, ignore_errors=True)
```

本模块自带 `_check_game_id`（抛 `ValueError`），不复用 `event_store` 的版本（那个抛 `StoreError` 子类，测试期望 `ValueError`）。

Run: `cd backend && uv run pytest tests/test_speech_audio.py -q` → PASS

- [ ] **Step 6: 写 runner 节奏测试**

`backend/tests/test_game_runner.py` 末尾追加（复用文件里的 `_make_runner`、`BotPlayerPort`、`InMemoryEventStore`、`GameLobby`、`ConnectionManager`、`GameRunner`）：

```python
class _RecordingSink:
    """假 sink：记下每次 speak 的 (seq, text, voice)，并真实 sleep per_call 秒模拟音频时长。"""

    def __init__(self, per_call: float) -> None:
        self.per_call = per_call
        self.calls: list[tuple[int, str, object]] = []

    async def speak(self, game_id: str, seq: int, text: str, voice: object, connections: object) -> None:
        self.calls.append((seq, text, voice))
        await asyncio.sleep(self.per_call)


@pytest.mark.asyncio
async def test_runner_waits_for_speech_audio_only_for_voiced_seats() -> None:
    """issue #103：有 voice 档案的座位发言后调用 sink（文本=发言正文）；其它座位不调用。"""
    from app.agent.profile import AgentProfile, VoiceSpec

    store = InMemoryEventStore()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    sink = _RecordingSink(per_call=0.0)
    voiced = AgentProfile(model="x", voice=VoiceSpec(mode="preset", speaker="eric"))
    silent = AgentProfile(model="x")
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        connections=ConnectionManager(state_provider=lambda: runner.state),
        agents={"0": voiced, "1": voiced, "2": silent},
        speech_audio=sink,  # type: ignore[arg-type]
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    final = await runner.run()
    assert final.phase == Phase.GAME_OVER
    spoken = [
        e for e in store.load_events("g1") if e.type in (EventType.PLAYER_SPOKE, EventType.LAST_WORDS)
    ]
    voiced_seqs = {e.seq for e in spoken if e.actor_seat in (0, 1)}
    assert {c[0] for c in sink.calls} == voiced_seqs and voiced_seqs
    by_seq = {e.seq: e for e in spoken}
    for seq, text, voice in sink.calls:
        assert text == by_seq[seq].payload.content  # type: ignore[attr-defined]
        assert voice == voiced.voice


@pytest.mark.asyncio
async def test_runner_sink_exception_does_not_kill_game() -> None:
    from app.agent.profile import AgentProfile, VoiceSpec

    class _Boom:
        async def speak(self, *a: object, **k: object) -> None:
            raise RuntimeError("tts exploded")

    store = InMemoryEventStore()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 8})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store, config=cfg, game_id="g1", roster=lobby.roster(), ports=ports,
        agents={"*": AgentProfile(model="x", voice=VoiceSpec(mode="design", style="x"))},
        speech_audio=_Boom(),  # type: ignore[arg-type]
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    assert (await runner.run()).phase == Phase.GAME_OVER
```

`Event.actor_seat`：核对 `app/engine/events.py` 的 `Event` 信封字段名（`actor_seat` 或 `actor`）；以实际为准改测试。

- [ ] **Step 7: runner 钩子**

`game_runner.py`：
- import：`from app.agent.profile import AgentProfiles, profile_for`；`from app.engine.events import Event, EventType`；`TYPE_CHECKING` 下 `from app.runtime.speech_audio import SpeechAudioSink`（避免循环：speech_audio 不 import runner，直接 import 也行；用 TYPE_CHECKING 更稳）。
- `__init__` 加参数 `speech_audio: SpeechAudioSink | None = None` → `self._speech_audio = speech_audio`。
- `_drive_seat` 中 `await self._commit(res.events, skills=skills)` 之后、`notify_result` 之前加 `await self._maybe_speak(seat, res.events)`。
- 新方法：

```python
    async def _maybe_speak(self, seat: int, events: list[Event]) -> None:
        """发言配音（issue #103）：该座位档案有 voice 且本次提交含公开发言 → 交给 sink 合成并等待。
        sink 自身吞 TtsError；这里再兜一层任何异常，配音永远不能让对局陪葬。"""
        if self._speech_audio is None:
            return
        profile = profile_for(self._agents, seat)
        if profile is None or profile.voice is None:
            return
        for e in events:
            if e.type in (EventType.PLAYER_SPOKE, EventType.LAST_WORDS):
                text = str(e.payload.content)  # type: ignore[attr-defined]
                try:
                    await self._speech_audio.speak(
                        self._game_id, e.seq, text, profile.voice, self.connections
                    )
                except Exception:
                    logger.warning("seat=%d seq=%d 配音异常，跳过等待", seat, e.seq, exc_info=True)
                return
```

- [ ] **Step 8: registry 开关**

`registry.py`：
- `GameHandle.__init__` 加 kw `voice_enabled: bool = False` → `self.voice_enabled = voice_enabled`。
- `GameRegistry.__init__` 加 `speech_audio: SpeechAudioSink | None = None` → `self._speech_audio`。
- `create(..., voice: bool = False)` → `GameHandle(..., voice_enabled=voice)`。
- `start()` 构造 `GameRunner(..., speech_audio=self._speech_audio if handle.voice_enabled else None)`。
- import `SpeechAudioSink` 用 `TYPE_CHECKING`（registry 已有该块？若无则加）。

Run: `cd backend && uv run pytest tests/test_game_runner.py tests/test_registry.py tests/test_speech_audio.py tests/test_connection.py -q && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: 全 PASS。`test_importing_registry_does_not_load_litellm` 也跑一次（`speech_audio`/`tts` 不含 litellm）。

- [ ] **Step 9: 提交**

```bash
git add backend/app/runtime backend/tests/test_connection.py backend/tests/test_speech_audio.py backend/tests/test_game_runner.py
git commit -m "feat(runtime): 发言配音 sink（逐句落盘/推帧/停留）、ConnectionManager 原始帧广播、runner 节奏同步与 voice 开关 (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: 后端 —— API（`/tts/status`、建局 `voice`、音频清单/文件、WS 帧透传、删局清理）+ `create_app` 装配

**Files:**
- Modify: `backend/app/main.py`（`tts_config`/`tts_client`/`audio_dir` 参数；`app.state.tts`、`app.state.speech_audio`）
- Modify: `backend/app/schemas/games.py`（`CreateGameRequest.voice`、`CreateGameResponse.voice`）
- Modify: `backend/app/api/rest.py`（建局探测、`/tts/status`、`/games/{id}/audio`、`/games/{id}/audio/{seq}/{part}`、删局清理）
- Modify: `backend/app/api/ws.py`（`subscribe_frames`）
- Test: `backend/tests/test_api_voice.py`（新建）

**Interfaces:**
- Consumes: Task 1 `TtsConfig.from_env/build_tts_client/TtsStatus/TtsClient`；Task 2 `SpeechAudioSink`、`GameRegistry(speech_audio=)`、`create(voice=)`、`subscribe_frames`。
- Produces: `create_app(tts_config: TtsConfig | None = None, tts_client: TtsClient | None = None, audio_dir: Path | None = None)`；`GET /api/v1/tts/status` → `TtsStatus`；`POST /games` 接受 `voice`，回显 `voice`，探测失败 400；`GET /api/v1/games/{id}/audio` → 清单；`GET /api/v1/games/{id}/audio/{seq}/{part}` → `audio/wav`；WS 收到 `speech_audio` / `speech_audio_end` 帧；`DELETE /games/{id}` 连带删音频。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_api_voice.py`：

```python
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
        yield AudioPart(index=0, wav=_wav(0.05), duration_sec=0.05)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=self.ok, url="fake", detail=None if self.ok else "down", supports_style=True)


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


def test_tts_status_enabled_and_disabled(tmp_path: Path) -> None:
    with _app(tmp_path, FakeTts()) as c:
        s = c.get("/api/v1/tts/status").json()
        assert s["enabled"] and s["ok"] and "api_key" not in s
    with _app(tmp_path, None) as c:  # None → 按环境变量；未设 URL → DisabledTtsClient
        s = c.get("/api/v1/tts/status").json()
        assert s == {"enabled": False, "ok": False, "url": None, "detail": "未配置 AGENTHOWL_TTS_URL", "supports_style": False}


def test_create_game_voice_flag_and_probe(tmp_path: Path) -> None:
    with _app(tmp_path, FakeTts(ok=False)) as c:
        r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True})
        assert r.status_code == 400 and "TTS" in r.json()["detail"]
        r = c.post("/api/v1/games", json={"preset": "std_9_kill_side"})
        assert r.status_code == 200 and r.json()["voice"] is False
    with _app(tmp_path, FakeTts()) as c:
        assert c.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True}).json()["voice"] is True


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
    spoke_seqs = {f["event"]["seq"] for f in frames if f["type"] == "game_event" and f["event"]["type"] in ("PLAYER_SPOKE", "LAST_WORDS")}
    assert {f["seq"] for f in audio} <= spoke_seqs
    # 回放事件流里没有 speech_audio（不是事件）
    replay = client.get(f"/api/v1/games/{gid}/replay").json()
    assert all(e["type"] not in ("speech_audio", "speech_audio_end") for e in replay)
    # 清单与文件（终局公开）
    m = client.get(f"/api/v1/games/{gid}/audio").json()
    seq, part = audio[0]["seq"], audio[0]["part"]
    assert m[str(seq)][0]["part"] == 0
    r = client.get(f"/api/v1/games/{gid}/audio/{seq}/{part}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav") and r.content[:4] == b"RIFF"
    assert client.get(f"/api/v1/games/{gid}/audio/{seq}/99").status_code == 404
    assert client.get(f"/api/v1/games/{gid}/audio/abc/0").status_code == 422
    assert (tmp_path / "audio" / gid).is_dir()
    # 删局连带删音频
    assert client.delete(f"/api/v1/games/{gid}").status_code == 204
    assert not (tmp_path / "audio" / gid).exists()


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
        assert c.get(f"/api/v1/games/{gid}/audio", headers=_auth(created["spectator_token"])).status_code == 200
        other = c.post("/api/v1/games", json={"preset": "std_9_kill_side"}).json()
        assert c.get(f"/api/v1/games/{gid}/audio", headers=_auth(other["gm_token"])).status_code == 403
        handle = c.app.state.games.get(gid)  # type: ignore[attr-defined]
        deadline = time.time() + 60
        while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
            time.sleep(0.05)
        # 开关关：终局匿名仍 401
        assert c.get(f"/api/v1/games/{gid}/audio").status_code == 401
    assert c.get("/api/v1/games/g_nope/audio").status_code in (401, 404)
```

`test_voiced_game_streams_frames_and_stores_audio` 里 WS 循环要容忍 `FakeTts` 每句 0.05 s 的等待；若全局测试时长明显上升（> 30 s），把 `_wav(0.05)` 改 0.02。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_api_voice.py -q` → FAIL（`create_app` 不认 `tts_client`）

- [ ] **Step 3: schemas**

`CreateGameRequest` 加 `voice: bool = False  # 发言配音（issue #103）：需 TTS 服务可用`；`CreateGameResponse` 加 `voice: bool`。

- [ ] **Step 4: `create_app` 装配**

`main.py` 签名加 `tts_config: TtsConfig | None = None, tts_client: TtsClient | None = None, audio_dir: Path | None = None`；在 `app.state.games = GameRegistry(...)` 之前：

```python
    # 发言配音（issue #103）：TTS 客户端只认 OpenAI-speech 协议；未配置 URL → Disabled
    tts = tts_client or build_tts_client(tts_config or TtsConfig.from_env())
    app.state.tts = tts
    app.state.speech_audio = SpeechAudioSink(audio_dir or Path("data/audio"), tts)
```

并给 `GameRegistry(..., speech_audio=app.state.speech_audio)`。import：`from app.runtime.speech_audio import SpeechAudioSink`、`from app.runtime.tts import TtsClient, TtsConfig, build_tts_client`。

- [ ] **Step 5: rest.py**

- `create_game_endpoint` 改 `async def`，在 `games.create(...)` 前：

```python
    tts: TtsClient = request.app.state.tts
    if req.voice:
        status = await tts.probe()
        if not status.ok:
            raise HTTPException(status_code=400, detail=f"TTS 服务不可用，无法开启语音：{status.detail or ''}".rstrip("："))
```
  （签名加 `request: Request`；`games.create(..., voice=req.voice)`；响应加 `voice=handle.voice_enabled`。）
- 新端点（放在 `avatars_endpoint` 之后）：

```python
@router.get("/{game_id}/audio")
def audio_manifest_endpoint(
    game_id: str,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> dict[str, list[dict[str, Any]]]:
    """发言音频清单 {seq: [{part, duration}]}（issue #103）；权限同 /replay。"""
    _finished_or_handle(games, game_id, info, _public_history(request), "PLAYER", "SPECTATOR", "HOST", "GM", require_finished=False)
    sink: SpeechAudioSink = request.app.state.speech_audio
    return sink.manifest(game_id)


@router.get("/{game_id}/audio/{seq}/{part}")
def audio_part_endpoint(
    game_id: str,
    seq: int,
    part: int,
    request: Request,
    info: TokenInfo | None = Depends(optional_token),
    games: GameRegistry = Depends(get_games),
) -> FileResponse:
    _finished_or_handle(games, game_id, info, _public_history(request), "PLAYER", "SPECTATOR", "HOST", "GM", require_finished=False)
    sink: SpeechAudioSink = request.app.state.speech_audio
    path = sink.path_for(game_id, seq, part)
    if path is None:
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=31536000, immutable"})
```
  `_finished_or_handle` 对无 handle + 开关关的匿名请求返回 401，对未知对局返回 404——测试最后一行接受两者。
- `/tts/status`：新建一个小 router 放在 `rest.py` 里（`tts_router = APIRouter(prefix="/tts", tags=["tts"])`，`main.py` 一并 `include_router`）：

```python
@tts_router.get("/status")
async def tts_status_endpoint(request: Request) -> TtsStatus:
    tts: TtsClient = request.app.state.tts
    return await tts.probe()
```
- `delete_game_endpoint`：在 `games.store.delete_game(game_id)` 成功后、`games.remove` 之前加 `request.app.state.speech_audio.delete_game(game_id)`（`SpeechAudioSink.delete_game` 幂等；非法 id 已被前面的 404 分支挡住——放在 `try` 之后）。

- [ ] **Step 6: ws.py 透传帧**

在 `handle.connections.subscribe(viewer, on_events)` 旁：

```python
    async def on_frame(frame: dict[str, Any]) -> None:
        out_q.put_nowait(frame)  # speech_audio / speech_audio_end：公开内容，所有视角都收

    handle.connections.subscribe_frames(on_frame)
```
`finally` 里 `handle.connections.unsubscribe_frames(on_frame)`。

- [ ] **Step 7: 跑测试 + 门禁**

Run: `cd backend && uv run pytest -q --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format . && uv run mypy app`
Expected: 全 PASS（`test_api_history` 的删除测试仍过：`speech_audio.delete_game` 对无目录幂等）。

- [ ] **Step 8: 提交**

```bash
git add backend/app backend/tests/test_api_voice.py
git commit -m "feat(api): GET /tts/status、建局 voice 开关（探测失败 400）、发言音频清单/文件端点（权限同 /replay）、WS 帧透传、删局清理音频 (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: 前端 —— 声线表单（AgentEditor）、`PROFILE_KEYS`、建局「语音」开关、TTS 状态 API

**Files:**
- Modify: `frontend/src/api/agents.ts`（`VoiceSpec`、`AgentProfile.voice`、`PRESET_SPEAKERS` 标签表）
- Modify: `frontend/src/lib/seats.ts`（`PROFILE_KEYS` 加 `"voice"`）+ `seats.test.ts`
- Modify: `frontend/src/api/rest.ts`（`CreateGameRequest.voice`、`CreateGameResponse.voice`、`TtsStatus`、`getTtsStatus()`、`getAudioManifest()`、`audioUrl()`）+ `rest.test.ts`
- Modify: `frontend/src/components/AgentEditor/AgentEditor.tsx` + `.module.css` + `.test.tsx`
- Modify: `frontend/src/pages/Lobby.tsx`（语音复选框）

**Interfaces:**
- Produces: `export interface VoiceSpec { mode: "preset" | "design"; speaker?: string | null; style?: string | null; speed?: number }`；
  `export const PRESET_SPEAKERS: { id: string; label: string }[]`（vivian 女·明亮年轻 / serena 女·温柔 / uncle_fu 男·低沉成熟 / dylan 男·北京话 / eric 男·四川话）；
  `getTtsStatus(): Promise<TtsStatus>`；`getAudioManifest(gameId, token?): Promise<Record<string, {part:number; duration:number}[]>>`；`audioUrl(gameId, seq, part): string`（`${API_BASE}/games/${gameId}/audio/${seq}/${part}`）。

- [ ] **Step 1: 失败测试**

`seats.test.ts` 的 `toProfilePayload` 块加：`toProfilePayload({ model: "m", voice: { mode: "preset", speaker: "dylan" } })` 保留 `voice`。
`rest.test.ts` 加：`getTtsStatus` 请求 `/api/v1/tts/status`；`getAudioManifest("g_x","tok")` 带 Authorization、无 token 不带；`audioUrl("g_x", 57, 0) === "/api/v1/games/g_x/audio/57/0"`。
`AgentEditor.test.tsx` 加：
```tsx
it("声线：预置模式必须选 speaker；设计模式必须填描述；保存写入 profile.voice（issue #103）", () => {
  const onSave = vi.fn();
  renderEditor({ onSave });
  fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "preset" } });
  fireEvent.change(screen.getByLabelText(/预置声线/), { target: { value: "eric" } });
  fireEvent.change(screen.getByLabelText(/情绪 \/ 语速指令|声线描述/), { target: { value: "急躁" } });
  fireEvent.click(screen.getByRole("button", { name: /保存|创建/ }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ voice: { mode: "preset", speaker: "eric", style: "急躁", speed: 1 } }));
  fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "design" } });
  fireEvent.change(screen.getByLabelText(/声线描述/), { target: { value: "" } });
  expect(screen.getByRole("button", { name: /保存|创建/ })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/声线模式/), { target: { value: "none" } });
  fireEvent.click(screen.getByRole("button", { name: /保存|创建/ }));
  expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ voice: null }));
});
```
（对齐该文件现有 `renderEditor`、按钮文案；`getByLabelText` 的正则按最终 label 文案调整。）

- [ ] **Step 2: 跑确认失败**：`cd frontend && npx vitest run src/lib src/api src/components/AgentEditor`

- [ ] **Step 3: 实现**

`api/agents.ts`：
```ts
export interface VoiceSpec {
  mode: "preset" | "design";
  speaker?: string | null;
  style?: string | null;
  speed?: number;
}
/** 与后端 PRESET_SPEAKERS 同步（Qwen3-TTS CustomVoice 中文声线）。 */
export const PRESET_SPEAKERS: { id: string; label: string }[] = [
  { id: "vivian", label: "Vivian · 女 · 明亮年轻" },
  { id: "serena", label: "Serena · 女 · 温柔" },
  { id: "uncle_fu", label: "Uncle Fu · 男 · 低沉成熟" },
  { id: "dylan", label: "Dylan · 男 · 北京话" },
  { id: "eric", label: "Eric · 男 · 四川话" },
];
```
`AgentProfile` 加 `voice?: VoiceSpec | null;`。`seats.ts` `PROFILE_KEYS` 加 `"voice"`。

`rest.ts`：
```ts
export interface TtsStatus { enabled: boolean; ok: boolean; url: string | null; detail: string | null; supports_style: boolean; }
export function getTtsStatus(): Promise<TtsStatus> { return req<TtsStatus>("GET", "/tts/status"); }
export interface AudioPartInfo { part: number; duration: number }
export function getAudioManifest(gameId: string, token?: string): Promise<Record<string, AudioPartInfo[]>> {
  return req<Record<string, AudioPartInfo[]>>("GET", `/games/${gameId}/audio`, { token });
}
export function audioUrl(gameId: string, seq: number, part: number): string {
  return `${API_BASE}/games/${gameId}/audio/${seq}/${part}`;
}
```
`CreateGameRequest` 加 `voice?: boolean`，`CreateGameResponse` 加 `voice: boolean`。

`AgentEditor`：`FormState` 加 `voice: { mode: "none" | "preset" | "design"; speaker: string; style: string; speed: number }`；`initialForm` 从 `p?.voice` 映射（`null` → `mode:"none", speaker:"dylan", style:"", speed:1`）；新增第 5 组 `<section className={styles.group}><span className="card-kicker">5 · 声线</span>…`：
- `<label htmlFor=…-voice-mode>声线模式</label><select>`：`none`=不配音 / `preset`=预置声线 / `design`=描述声线。
- `preset`：`<label>预置声线</label><select>` 遍历 `PRESET_SPEAKERS`；`<label>情绪 / 语速指令（可选）</label><input maxLength={200}>`。
- `design`：`<label>声线描述</label><textarea maxLength={200} placeholder="沙哑低沉的中年东北男声，语速快">`。
- 两种模式都有 `<label>语速 {speed.toFixed(1)}×</label><input type="range" min=0.5 max=2 step=0.1>`。
- 提示：「需配置 TTS 服务（AGENTHOWL_TTS_URL）且建局勾选「语音」才会生效；方言只有北京话 / 四川话两个预置声线。」
- `blocked` 加 `voiceBad = form.voice.mode === "design" && form.voice.style.trim() === ""`。
- `submit()` 的 `profile.voice`：`none` → `null`；`preset` → `{ mode: "preset", speaker, style: style.trim() || null, speed }`；`design` → `{ mode: "design", style: style.trim(), speed }`。
- 现有「空人格不提交 personality」等精确形状测试需加 `voice: null`。

`Lobby.tsx`：`useEffect` 拉 `getTtsStatus()` 存 `tts` state（失败当 `enabled:false`）；`const [voice, setVoice] = useState(false)`；当 `tts.enabled` 时在建局按钮附近渲染 `<label><input type="checkbox" checked={voice} disabled={!tts.ok} onChange…/> 语音播报{tts.ok ? "" : `（TTS 不可用：${tts.detail ?? ""}）`}</label>`；`body.voice = voice`。

- [ ] **Step 4: `npm run check` 全绿；提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 档案声线表单（预置/描述/语速）、PROFILE_KEYS 含 voice、建局「语音播报」开关、TTS 状态与音频 API (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 前端 —— 语音播放：`useVoice` store + 音频播放器 + WS 帧入队 + 🔊 开关 + 回放门控

**Files:**
- Create: `frontend/src/lib/audioPlayer.ts`（`createAudioPlayer()`：`play(url): Promise<void>`、`stop()`；可注入 mock）
- Create: `frontend/src/store/voice.ts` + `voice.test.ts`
- Modify: `frontend/src/api/ws.ts`（`speech_audio` 帧 → `useVoice.enqueue`）+ `ws.test.ts`（若存在；否则在 `voice.test.ts` 直接测 enqueue）
- Modify: `frontend/src/store/game.ts`（`replayGate`、`setReplayGate`、`makeTick` 门控）+ `game.test.ts`
- Create: `frontend/src/components/VoiceToggle/VoiceToggle.tsx` + `.module.css` + `.test.tsx`
- Modify: `frontend/src/pages/GamePage.tsx`（拉清单、装 gate、渲染 `VoiceToggle`）、`SpeakerSpotlight.tsx`（播放中显示 🔊）

**Interfaces:**
- Consumes: Task 4 `getAudioManifest`、`audioUrl`、`AudioPartInfo`。
- Produces:
  - `lib/audioPlayer.ts`: `export interface AudioPlayer { play(url: string): Promise<void>; stop(): void }`；`createAudioPlayer(): AudioPlayer`（单个 `HTMLAudioElement`，`ended`/`error` → resolve；`stop()` 暂停并 resolve 挂起的 play）。
  - `store/voice.ts`: `useVoice` with `enabled: boolean`（初值读 `localStorage["agenthowl.voice"] === "1"`，try/catch）、`available: boolean`（收到过帧或清单非空）、`playing: { seq: number; part: number } | null`、`setEnabled(v)`、`enqueue(item: { seq: number; part: number; url: string; duration: number })`、`markAvailable()`、`clear()`、`playSeq(gameId, seq, parts: AudioPartInfo[], token?): Promise<void>`（回放用：顺序播放该 seq 全部 part，`enabled=false` 立即 resolve）、`setPlayer(p: AudioPlayer)`（测试注入）。
  - `store/game.ts`: `replayGate: ((seq: number) => Promise<void> | null) | null`；`setReplayGate(gate)`；`makeTick` 语义：先 `stepForward()`，再对新游标 seq 调 gate，有 Promise 则在其 resolve 前跳过后续 tick；`pause()/setCursor()/reset()` 清门控。

- [ ] **Step 1: 失败测试**

`voice.test.ts`：
```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useVoice } from "./voice";

function fakePlayer() {
  const calls: string[] = [];
  let resolvers: (() => void)[] = [];
  return {
    calls,
    finishOne() { resolvers.shift()?.(); },
    play(url: string) { calls.push(url); return new Promise<void>((r) => resolvers.push(r)); },
    stop() { resolvers.forEach((r) => r()); resolvers = []; },
  };
}

describe("useVoice", () => {
  beforeEach(() => { useVoice.setState({ enabled: false, available: false, playing: null, queue: [] }); });
  it("关闭时入队不播放但标记 available；开启后新帧按 (seq, part) 顺序播放", async () => {
    const p = fakePlayer(); useVoice.getState().setPlayer(p);
    useVoice.getState().enqueue({ seq: 5, part: 0, url: "/a/5/0", duration: 1 });
    expect(useVoice.getState().available).toBe(true); expect(p.calls).toEqual([]);
    useVoice.getState().setEnabled(true);
    useVoice.getState().enqueue({ seq: 6, part: 0, url: "/a/6/0", duration: 1 });
    useVoice.getState().enqueue({ seq: 6, part: 1, url: "/a/6/1", duration: 1 });
    await Promise.resolve();
    expect(p.calls).toEqual(["/a/6/0"]); expect(useVoice.getState().playing).toEqual({ seq: 6, part: 0 });
    p.finishOne(); await Promise.resolve(); await Promise.resolve();
    expect(p.calls).toEqual(["/a/6/0", "/a/6/1"]);
    p.finishOne(); await Promise.resolve(); await Promise.resolve();
    expect(useVoice.getState().playing).toBeNull();
  });
  it("playSeq 顺序播放全部 part；关闭时立即 resolve；clear 停止", async () => {
    const p = fakePlayer(); useVoice.getState().setPlayer(p);
    await useVoice.getState().playSeq("g", 9, [{ part: 0, duration: 1 }], undefined);
    expect(p.calls).toEqual([]);
    useVoice.getState().setEnabled(true);
    const done = useVoice.getState().playSeq("g", 9, [{ part: 0, duration: 1 }, { part: 1, duration: 1 }], undefined);
    await Promise.resolve();
    expect(p.calls).toEqual(["/api/v1/games/g/audio/9/0"]);
    p.finishOne(); await Promise.resolve(); await Promise.resolve();
    expect(p.calls[1]).toBe("/api/v1/games/g/audio/9/1");
    useVoice.getState().clear();
    await done;
  });
  it("setEnabled 写 localStorage", () => {
    useVoice.getState().setEnabled(true);
    expect(localStorage.getItem("agenthowl.voice")).toBe("1");
  });
});
```
`game.test.ts` 加：装一个 `replayGate`（seq 2 返回挂起 Promise），`load(meta, {mode:"replay"})` + `appendEvents(前 4 条 fixture 事件)` + `play()`；用 `vi.useFakeTimers()` 推进两拍：第一拍 cursor→1（无 gate），第二拍 cursor→2 并卡住，再推进多拍 cursor 仍是 2；resolve gate 后下一拍 cursor→3。`pause()` 后 gate 清空。
`VoiceToggle.test.tsx`：`available=false` 不渲染；渲染后点击切换 `enabled` 并显示「语音 开/关」。

- [ ] **Step 2: 实现**

`lib/audioPlayer.ts`：
```ts
export interface AudioPlayer { play(url: string): Promise<void>; stop(): void }
export function createAudioPlayer(): AudioPlayer {
  const el = typeof Audio !== "undefined" ? new Audio() : null;
  let pending: (() => void) | null = null;
  const settle = (): void => { const r = pending; pending = null; r?.(); };
  if (el) { el.addEventListener("ended", settle); el.addEventListener("error", settle); }
  return {
    play(url) {
      if (!el) return Promise.resolve();
      settle();
      return new Promise<void>((resolve) => { pending = resolve; el.src = url; void el.play().catch(settle); });
    },
    stop() { if (el) { el.pause(); el.removeAttribute("src"); } settle(); },
  };
}
```
`store/voice.ts`（zustand）：模块级 `let player: AudioPlayer | null = null` 懒建；`drain()`：若 `enabled` 且 `playing===null` 且队列非空 → 取队首（队列按入队顺序，服务端已保证 (seq, part) 顺序），`set({playing})`，`await player.play(url)`，`set({playing:null})`，递归 `drain()`。`setEnabled(false)` → `clear()`（停播、清队列）。`playSeq` 用 `audioUrl` 逐 part `await player.play(...)`，`clear()` 中途打断（用一个 `generation` 计数器：clear 后旧循环退出）。`enqueue` 时若 `!enabled` 只保留最近 1 条（避免开启瞬间补播一堆旧句）。
`api/ws.ts`：`WsFrame` 加 `part?: number; url?: string; duration?: number`；`onmessage` 加分支：`frame.type === "speech_audio" && frame.url !== undefined` → `useVoice.getState().enqueue({seq: frame.seq!, part: frame.part!, url: frame.url, duration: frame.duration ?? 0})`；`speech_audio_end` 忽略。
`store/game.ts`：加字段/方法，`makeTick`：
```ts
let gating = false;
function makeTick(get) {
  return () => {
    if (gating) return;
    const state = get(); const lastSeq = lastSeqOf(state.events); const cur = state.cursor ?? lastSeq;
    if (cur >= lastSeq) { get().pause(); return; }
    get().stepForward();
    const next = get().cursor;
    const p = next !== null ? (get().replayGate?.(next) ?? null) : null;
    if (p) { gating = true; void p.catch(() => undefined).finally(() => { gating = false; }); }
  };
}
```
`pause()`/`setCursor()`/`reset()` 里 `gating = false`。
`VoiceToggle.tsx`：读 `useVoice.available/enabled/playing`；`available=false` 返回 null；按钮 `🔊 语音 开` / `🔇 语音 关`，`aria-pressed`；放在 `GamePage` 左栏 `SeatCircle` 之上（`.left` 内第一项，右对齐小 pill）。
`GamePage.tsx`：三条引导路径成功后 `getAudioManifest(gameId, token || undefined).then(m => { setManifest(m); if (Object.keys(m).length) useVoice.getState().markAvailable(); }).catch(() => {})`；`useEffect` 在 `mode === "replay"` 时 `useGameStore.getState().setReplayGate((seq) => { const parts = manifest[String(seq)]; return parts ? useVoice.getState().playSeq(gameId, seq, parts, token || undefined) : null; })`，清理时 `setReplayGate(null)` + `useVoice.getState().clear()`。
`SpeakerSpotlight.tsx`：若 `useVoice((s) => s.playing)?.seq` 存在且 `playing !== null` → tag 文案 `发言中 🔊`。

- [ ] **Step 3: `npm run check && npm run build` 全绿；提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 语音播放——useVoice 队列与 🔊 开关、WS speech_audio 入队、回放按音频门控暂停/继续、聚光牌播放标记 (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 本地 TTS 服务（`tts/` 项目 + `make tts`）+ 配置与文档

**Files:**
- Create: `tts/pyproject.toml`、`tts/README.md`
- Modify: `Makefile`（`tts` 目标）、`.env.example`、`docker-compose.yml`（注释）、`README.md`（「语音」段落）、`docs/specs/requirements.md`（§5.2 四行：`GET /tts/status`、`GET /games/{id}/audio`、`GET /games/{id}/audio/{seq}/{part}`、`POST /games` 的 `voice`；§6 WS 帧 `speech_audio` / `speech_audio_end`；`AgentProfile.voice` 字段说明）、`docs/superpowers/specs/2026-10-05-agent-avatar-voice-design.md`（§4.2 把 `last` 字段改成 `speech_audio_end` 帧）
- Modify: `.gitignore`（`tts/.venv/` 已被通用 `.venv` 覆盖；确认）

- [ ] **Step 1: `tts/pyproject.toml`**

```toml
[project]
name = "agenthowl-tts"
version = "0.1.0"
description = "AgentHowl 本地 TTS 服务：mlx-audio（Apple Silicon）暴露 OpenAI /v1/audio/speech"
requires-python = ">=3.11"
dependencies = ["mlx-audio>=0.2"]
```
（版本号以 `uv add mlx-audio` 解析出的为准；`uv lock` 产物 `tts/uv.lock` 入库。）

`tts/README.md`：说明仅 macOS arm64；`make tts` 起服务（:8880）；首次请求会下载两份 6-bit 模型（约 2 GB×2）；可用环境变量换模型；Linux/NVIDIA 用户改用 vLLM-Omni 或任何 OpenAI-speech 兼容服务并设 `AGENTHOWL_TTS_KIND=generic`。

- [ ] **Step 2: Makefile**

在 `serve` 之后加：
```make
TTS_PORT ?= 8880

.PHONY: tts
tts: ## 启动本地 TTS 服务（mlx-audio，Apple Silicon；http://127.0.0.1:8880；后端设 AGENTHOWL_TTS_URL 指向它）
	cd tts && uv run python -m mlx_audio.server --host 127.0.0.1 --port $(TTS_PORT)
```
确认 `mlx_audio.server` 的 CLI 参数名（`--host/--port`，见 spike：默认 8000 与后端冲突）。

- [ ] **Step 3: 配置样例**

`.env.example` 末尾：
```
# 发言配音（issue #103）：OpenAI /v1/audio/speech 兼容服务；空 = 关闭。本机 `make tts` 起 mlx-audio 后：
#AGENTHOWL_TTS_URL=http://host.docker.internal:8880
#AGENTHOWL_TTS_KIND=mlx_audio          # mlx_audio | openai | generic
#AGENTHOWL_TTS_MODEL_PRESET=mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit
#AGENTHOWL_TTS_MODEL_DESIGN=mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit
#AGENTHOWL_TTS_API_KEY=                # 仅 openai 类服务需要
```
`docker-compose.yml` `environment` 下加注释行 `# 语音：AGENTHOWL_TTS_URL 请在 .env 里设成 http://host.docker.internal:8880（TTS 在宿主机跑）`。

- [ ] **Step 4: README 与 PRD**

README 新增「**语音播报**（issue #103）」段：怎么起 TTS（`make tts`）、后端环境变量、档案里配声线（预置 5 个 / 描述声线 / 语速；方言只有北京话、四川话）、建局勾「语音播报」、页面 🔊 开关（浏览器需点击一次）、回放按音频推进、音频存 `backend/data/audio/<game_id>/`，删局连带删除；非 Apple Silicon 的替代服务。PRD §5.2 加四行、§6 WS 帧说明、`AgentProfile.voice` 字段说明；设计规格 §4.2 的 `last` 改为 `speech_audio_end` 帧并注明原因。

- [ ] **Step 5: 自检 + 提交**

Run: `cd tts && uv lock && uv sync --dry-run`（macOS 上可实际 `uv sync` 验证可装）；`make help | grep tts`。

```bash
git add tts Makefile .env.example docker-compose.yml README.md docs/specs/requirements.md docs/superpowers/specs/2026-10-05-agent-avatar-voice-design.md
git commit -m "chore(tts): 本地 TTS 服务项目与 make tts；语音配置样例；README/PRD/设计规格 (issue #103)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## 自检

- 规格覆盖：§2 `VoiceSpec`（T1）；§4.1 客户端/配置/`/tts/status`/`httpx` 依赖/本地服务（T1、T3、T6）；§4.2 建局开关与 400、runner 停留、落盘路径、帧、清单/文件端点权限、删局清理（T2、T3）；§4.3 `useVoice`、直播队列、回放门控、🔊、聚光牌标记（T5）；§4.4 测试（各任务）；§5 安全（key 不回显、只发正文、权限同 `/replay`）；§6 兼容（`voice=False` 零变化）。
- 与规格的两处偏离（都在 T6 回写规格）：`last` 字段 → `speech_audio_end` 帧；`SeatCircle data-voicing` 动效改为聚光牌 🔊 标记（已有发言高亮，不再叠加）。
- 类型一致：`AudioPart.duration_sec` ↔ 帧 `duration` ↔ 清单 `duration` ↔ 前端 `AudioPartInfo.duration`；`speech_audio` 帧字段 `seq/part/url/duration` 在 T2 sink、T3 测试、T5 `ws.ts`/`enqueue` 中同名；`audioUrl` 与后端路由 `/games/{id}/audio/{seq}/{part}` 一致。
- 占位符扫描：T1 Step 7 关于 mypy `raise; yield` 的说明是明确的回退指令；无 TBD。
