"""发言配音 sink（issue #103）：逐句合成 → 落盘 data/audio/<game_id>/<seq>-<k>.wav →
推 WS 帧 → 停留。

帧是**非游戏事件**：不进事件日志、不进 reducer；只承载公开发言的音频引用。
停留时长 = 最后一句**预计播完的时刻** + AUDIO_TAIL_SEC：每推一句，播放起点取
「当前时刻」与「前一句预计播完的时刻」的较晚者（一句不能在推送前开始播、也不能跳过
排队中的前一句）+= 本句 duration——而不是简单的「首句推送时刻 + Σduration」。
后者在 TTS 慢于实时（单句合成耗时 > 其自身播放时长）时会把等待算短，导致最后一句还没
播完就被判定「该往下走」，提前截断播放。
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
        expected_finish: float | None = None  # 最后一句预计播完的时刻
        parts = 0
        try:
            async for part in self._tts.synthesize_sentences(text, voice):
                path = self._dir / game_id / f"{seq}-{part.index}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(part.wav)
                now = time.monotonic()
                # 本句不可能在推送前开始播，也不会抢在前一句播完前开始——取两者较晚者为起点
                expected_finish = max(expected_finish if expected_finish is not None else now, now)
                expected_finish += part.duration_sec
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
            await connections.broadcast_frame(
                {"type": "speech_audio_end", "seq": seq, "parts": parts}
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
