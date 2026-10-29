"""发言配音 sink（issue #103）：逐句合成 → 落盘 data/audio/<game_id>/<seq>-<k>.wav →
推 WS 帧 → 停留。

帧是**非游戏事件**：不进事件日志、不进 reducer；只承载公开发言的音频引用。
停留时长 = 最后一句**预计播完的时刻** + AUDIO_TAIL_SEC：每推一句，播放起点取
「当前时刻」与「前一句预计播完的时刻」的较晚者（一句不能在推送前开始播、也不能跳过
排队中的前一句）+= 本句 duration——而不是简单的「首句推送时刻 + Σduration」。
后者在 TTS 慢于实时（单句合成耗时 > 其自身播放时长）时会把等待算短，导致最后一句还没
播完就被判定「该往下走」，提前截断播放。

issue #110：旁白走同一内核 `_emit`，帧带 `kind`，并随来源事件按视角过滤。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from app.agent.profile import VoiceSpec
from app.engine.events import Event
from app.runtime.connection import ConnectionManager
from app.runtime.narration import NARRATOR_WARM_TEXT, NarrationCache, NarrationConfig, narrate
from app.runtime.tts import (
    AudioPart,
    TtsClient,
    TtsError,
    concat_wav,
    normalize_for_tts,
    wav_duration,
)
from app.runtime.voice_anchors import VoiceAnchorStore

logger = logging.getLogger(__name__)

AUDIO_TAIL_SEC = 0.3
WAV_HEADER_BYTES = 64 * 1024  # 清单读时长只取文件头（fmt/data 块都在最前面）
WARM_TEXT = NARRATOR_WARM_TEXT  # 旧名保留给既有测试 import
AudioKind = Literal["speech", "narration"]
_PART_RE = re.compile(r"^(\d+)-(\d+)\.wav$")
_GAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_game_id(game_id: str) -> None:
    """触盘前校验（路径穿越防护）；与 event_store 同口径，但抛 ValueError 便于 API 层映射。"""
    if not _GAME_ID_RE.fullmatch(game_id):
        raise ValueError(f"非法 game_id：{game_id!r}")


class SpeechAudioSink:
    def __init__(
        self,
        audio_dir: Path,
        tts: TtsClient,
        anchors: VoiceAnchorStore | None = None,
        *,
        narration: NarrationConfig | None = None,
        narration_cache: NarrationCache | None = None,
    ) -> None:
        self._dir = audio_dir
        self._tts = tts
        self._anchors = anchors
        self._narration = narration
        self._cache = narration_cache
        if narration is not None and narration_cache is None:
            raise ValueError("配置了旁白必须同时给 narration_cache")

    # ---------- 预热 ----------

    async def warm(self, voices: list[VoiceSpec]) -> None:
        """开局时把本局用到的声线各合成一句短话（丢弃结果）：让 TTS 把模型装进内存、设计声线的锚点
        提前生成——否则第一轮上警发言会撞上冷启动。失败只告警（真正发言时还会再试）。
        配置了旁白时把旁白声线一起预热（issue #110）。"""
        if self._narration is not None:
            voices = [*voices, self._narration.voice]
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for voice in voices:
            # 预置声线只看 speaker（情绪指令不影响装载）；描述声线看锚点 / 描述
            key = (
                (voice.mode, voice.speaker, None)
                if voice.mode == "preset"
                else (voice.mode, None, voice.anchor or voice.style)
            )
            if key in seen:
                continue
            seen.add(key)
            try:
                ref = await self._anchors.ensure_for(voice, self._tts) if self._anchors else None
                async for _ in self._tts.synthesize_sentences(WARM_TEXT, voice, ref):
                    pass
            except TtsError as exc:
                logger.warning("声线预热失败（%s）：%s", key, exc)

    # ---------- 发言 ----------

    async def speak(
        self,
        game_id: str,
        seq: int,
        text: str,
        voice: VoiceSpec,
        connections: ConnectionManager | None,
        event: Event,
    ) -> None:
        """失败不抛：WARNING 后对已推句子照常等待，对局继续。"""
        ref_audio: Path | None = None
        if voice.mode == "design" and self._anchors is not None:
            try:
                ref_audio = await self._anchors.ensure_for(voice, self._tts)
            except TtsError as exc:
                # 拿不到锚点就退回每句单独设计（音色可能不一致，但不至于没声）
                logger.warning("game=%s seq=%d 锚点生成失败，退回逐句设计：%s", game_id, seq, exc)
        await self._emit(
            game_id,
            seq,
            # 英文角色枚举（WOLF / GOOD…）换成中文读法，否则中文声线逐字母念
            self._tts.synthesize_sentences(normalize_for_tts(text), voice, ref_audio),
            connections,
            event,
            "speech",
        )

    # ---------- 旁白 ----------

    async def narrate(
        self, game_id: str, event: Event, connections: ConnectionManager | None
    ) -> None:
        """白名单事件 → 逐句（缓存优先）→ 同一内核推帧等待；未配置旁白 / 无句子 → 直接返回。"""
        if self._narration is None or self._cache is None:
            return
        sentences = narrate(event, self._narration.events)
        if not sentences:
            return
        await self._emit(
            game_id, event.seq, self._narration_parts(sentences), connections, event, "narration"
        )

    async def _narration_parts(self, sentences: list[str]) -> AsyncIterator[AudioPart]:
        """逐句产出音频：缓存命中直接用，未命中合成后写缓存。单句失败只告警并跳过该句。"""
        assert self._narration is not None and self._cache is not None
        speaker, voice = self._narration.speaker, self._narration.voice
        k = 0
        for sentence in sentences:
            try:
                wav = self._cache.get(speaker, sentence)
                if wav is None:
                    pieces = [p.wav async for p in self._tts.synthesize_sentences(sentence, voice)]
                    wav = concat_wav(pieces)
                    try:
                        self._cache.put(speaker, sentence, wav)
                    except OSError as exc:
                        logger.warning("旁白缓存写入失败（本句仍播）：%s", exc)
                part = AudioPart(index=k, wav=wav, duration_sec=wav_duration(wav))
            except TtsError as exc:
                logger.warning("旁白合成失败，跳过：%r %s", sentence, exc)
                continue
            yield part
            k += 1

    # ---------- 内核：落盘 + 推帧 + 等待 ----------

    async def _emit(
        self,
        game_id: str,
        seq: int,
        parts: AsyncIterator[AudioPart],
        connections: ConnectionManager | None,
        event: Event,
        kind: AudioKind,
    ) -> None:
        _check_game_id(game_id)
        expected_finish: float | None = None  # 最后一句预计播完的时刻
        count = 0
        try:
            async for part in parts:
                path = self._dir / game_id / f"{seq}-{part.index}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(part.wav)
                now = time.monotonic()
                # 本句不可能在推送前开始播，也不会抢在前一句播完前开始——取两者较晚者为起点
                expected_finish = max(expected_finish if expected_finish is not None else now, now)
                expected_finish += part.duration_sec
                count += 1
                if connections is not None:
                    await connections.broadcast_frame(
                        {
                            "type": "speech_audio",
                            "seq": seq,
                            "part": part.index,
                            "url": f"/api/v1/games/{game_id}/audio/{seq}/{part.index}",
                            "duration": round(part.duration_sec, 3),
                            "kind": kind,
                        },
                        event,
                    )
        except TtsError as exc:
            logger.warning(
                "game=%s seq=%d %s 配音失败（已推 %d 句）：%s", game_id, seq, kind, count, exc
            )
        if count and connections is not None:
            await connections.broadcast_frame(
                {"type": "speech_audio_end", "seq": seq, "parts": count, "kind": kind}, event
            )
        if expected_finish is not None:
            await asyncio.sleep(max(0.0, expected_finish + AUDIO_TAIL_SEC - time.monotonic()))

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
                with p.open("rb") as f:
                    dur = wav_duration(f.read(WAV_HEADER_BYTES))  # 只读头部：时长来自 data 块声明
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
