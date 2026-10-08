"""TTS 客户端（issue #103）：只说 OpenAI `POST /v1/audio/speech` 一种协议，按 kind 映射扩展字段。

规格 §4.1。不引入音频库：WAV 时长从 RIFF 头算。只发发言正文；api key 永不进日志 / 异常文本。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
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
DEFAULT_MODEL_CLONE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-6bit"
# 描述声线的锚点句：VoiceDesign 只念这一句，之后每句都用克隆模型以它为参考（音色一致）
ANCHOR_TEXT = "大家好，我是本局的玩家，接下来请听我的分析。"
_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")


class TtsError(Exception):
    """TTS 请求失败（超时 / 非 2xx / 非 WAV / 服务未配置）。"""


class TtsConfig(BaseModel):
    url: str | None = None
    kind: TtsKind = "mlx_audio"
    model_preset: str = DEFAULT_MODEL_PRESET
    model_design: str = DEFAULT_MODEL_DESIGN
    model_clone: str = DEFAULT_MODEL_CLONE
    api_key: str | None = None
    # TTS 服务眼中的锚点目录（mlx-audio 只接受服务端本地路径作 ref_audio）；None = 直接用后端的
    # 绝对路径（同机 make serve）。Docker 下设成宿主机的 backend/data/voices。
    ref_dir: str | None = None

    @classmethod
    def from_env(cls) -> TtsConfig:
        url = os.environ.get("AGENTHOWL_TTS_URL", "").strip().rstrip("/") or None
        kind = os.environ.get("AGENTHOWL_TTS_KIND", "mlx_audio").strip() or "mlx_audio"
        return cls(
            url=url,
            kind=kind,  # type: ignore[arg-type]  # 非法值由 pydantic 报错（fail-loud）
            model_preset=os.environ.get("AGENTHOWL_TTS_MODEL_PRESET", "").strip()
            or DEFAULT_MODEL_PRESET,
            model_design=os.environ.get("AGENTHOWL_TTS_MODEL_DESIGN", "").strip()
            or DEFAULT_MODEL_DESIGN,
            model_clone=os.environ.get("AGENTHOWL_TTS_MODEL_CLONE", "").strip()
            or DEFAULT_MODEL_CLONE,
            api_key=os.environ.get("AGENTHOWL_TTS_API_KEY", "").strip() or None,
            ref_dir=os.environ.get("AGENTHOWL_TTS_REF_DIR", "").strip().rstrip("/") or None,
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
    """按 。！？；换行 切句并保留标点；连续短句合并到 ≥ MIN_SENTENCE_CHARS；上限 SENTENCE_LIMIT。

    注意：单句本身已达到 MIN_SENTENCE_CHARS 时不与前面积累的短句缓冲合并——先把缓冲
    单独输出，再把这一句单独输出（否则一句本已够长的话仍会被前面的残句拖着合并，
    与测试用例 test_split_sentences_rules 的期望不符）。
    """
    out: list[str] = []
    buf = ""
    for piece in _SPLIT_RE.split(text):
        s = piece.strip()
        if not s:
            continue
        if len(s) >= MIN_SENTENCE_CHARS:
            if buf:
                out.append(buf)
                buf = ""
            out.append(s)
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
    def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: Path | None = None
    ) -> AsyncIterator[AudioPart]: ...

    async def design_anchor(self, style: str) -> bytes: ...

    async def probe(self) -> TtsStatus: ...


class DisabledTtsClient:
    """未配置 AGENTHOWL_TTS_URL：status 报 enabled=False；合成直接报错（调用方不该走到这）。"""

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: Path | None = None
    ) -> AsyncIterator[AudioPart]:
        raise TtsError("TTS 未配置（AGENTHOWL_TTS_URL 为空）")
        yield  # pragma: no cover  # 让函数成为 async generator

    async def design_anchor(self, style: str) -> bytes:
        raise TtsError("TTS 未配置（AGENTHOWL_TTS_URL 为空）")

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=False, ok=False, url=None, detail="未配置 AGENTHOWL_TTS_URL")


class HttpTtsClient:
    def __init__(
        self, config: TtsConfig, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
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

    def _ref_path(self, ref_audio: Path) -> str:
        """锚点文件在 TTS 服务眼中的路径：配置了 ref_dir 就按文件名拼到那边，否则用本机绝对路径。"""
        if self._cfg.ref_dir:
            return f"{self._cfg.ref_dir.rstrip('/')}/{ref_audio.name}"
        return str(ref_audio.resolve())

    def _body(
        self, sentence: str, voice: VoiceSpec, ref_audio: Path | None = None
    ) -> dict[str, object]:
        kind = self._cfg.kind
        body: dict[str, object] = {
            "input": sentence,
            "speed": voice.speed,
            "response_format": "wav",
        }
        if kind == "mlx_audio":
            if voice.mode == "design" and ref_audio is not None:
                # 克隆：音色完全由锚点决定，不再传描述（传了反而会让模型重新"设计"）
                body["model"] = self._cfg.model_clone
                body["ref_audio"] = self._ref_path(ref_audio)
                body["ref_text"] = ANCHOR_TEXT
            else:
                body["model"] = (
                    self._cfg.model_design if voice.mode == "design" else self._cfg.model_preset
                )
                if voice.mode == "preset":
                    body["voice"] = voice.speaker
                if voice.style:
                    body["instruct"] = voice.style
            body["lang_code"] = "chinese"
        else:
            body["model"] = self._cfg.model_preset
            body["voice"] = voice.speaker or "alloy"
            if kind == "openai" and voice.style:
                body["instructions"] = voice.style
        return body

    async def _post_speech(self, client: httpx.AsyncClient, body: dict[str, object]) -> bytes:
        try:
            resp = await client.post("/v1/audio/speech", json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise TtsError(f"TTS 请求失败：{type(exc).__name__}") from exc
        if resp.status_code >= 300:
            # 不回显响应正文：可能含上游错误里的敏感信息
            raise TtsError(f"TTS 服务返回 {resp.status_code}")
        return resp.content

    async def design_anchor(self, style: str) -> bytes:
        """按描述用 VoiceDesign 念一遍锚点句，返回 WAV——这就是这条声线以后的"本人"。"""
        voice = VoiceSpec(mode="design", style=style)
        async with httpx.AsyncClient(
            base_url=self._cfg.url or "", timeout=REQUEST_TIMEOUT_SEC, transport=self._transport
        ) as client:
            wav = await self._post_speech(client, self._body(ANCHOR_TEXT, voice))
        wav_duration(wav)  # 非 WAV → TtsError
        return wav

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: Path | None = None
    ) -> AsyncIterator[AudioPart]:
        sentences = split_sentences(text)
        async with httpx.AsyncClient(
            base_url=self._cfg.url or "", timeout=REQUEST_TIMEOUT_SEC, transport=self._transport
        ) as client:
            for i, sentence in enumerate(sentences):
                wav = await self._post_speech(client, self._body(sentence, voice, ref_audio))
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
        return TtsStatus(
            enabled=True,
            ok=ok,
            url=self._cfg.url,
            detail=detail,
            supports_style=self.supports_style,
        )


def build_tts_client(config: TtsConfig) -> TtsClient:
    return HttpTtsClient(config) if config.url else DisabledTtsClient()
