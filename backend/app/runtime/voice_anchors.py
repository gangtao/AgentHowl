"""描述声线的锚点音频存储（issue #103 跟进）。

VoiceDesign 每次请求都会按描述重新"设计"一个人，逐句合成就会句句换人。锚点 = 用描述只念一遍
固定的锚点句（tts.ANCHOR_TEXT），之后每句都以这段音频为参考克隆——音色由锚点定死。

两类文件，同在 voices_dir：
- 显式锚点 `<sha256(bytes)[:16]>.wav`：用户在档案编辑器里"生成试听"后保存进 VoiceSpec.anchor；
- 自动锚点 `auto-<sha256(style)[:16]>.wav`：老档案没配 anchor 时运行期按描述生成一次并复用。
锚点只是公开的声音样本，不含任何对局信息；不做孤儿清理。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

from app.agent.profile import ANCHOR_ID_PATTERN, VoiceSpec
from app.runtime.tts import TtsClient, wav_duration

logger = logging.getLogger(__name__)

_ID_RE = re.compile(ANCHOR_ID_PATTERN)


def check_anchor_id(anchor_id: str) -> None:
    if not _ID_RE.fullmatch(anchor_id):
        raise ValueError(f"非法 anchor_id：{anchor_id!r}")


class VoiceAnchorStore:
    def __init__(self, voices_dir: Path) -> None:
        self._dir = voices_dir  # 首次写入时创建

    def _write(self, name: str, wav: bytes) -> Path:
        path = self._dir / name
        if path.exists():
            return path
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def put(self, wav: bytes) -> str:
        """显式锚点：内容寻址、幂等；非 WAV → TtsError。"""
        wav_duration(wav)
        anchor_id = f"{hashlib.sha256(wav).hexdigest()[:16]}.wav"
        self._write(anchor_id, wav)
        return anchor_id

    def path_for(self, anchor_id: str) -> Path | None:
        check_anchor_id(anchor_id)
        path = self._dir / anchor_id
        return path if path.is_file() else None

    async def ensure_for(self, voice: VoiceSpec, tts: TtsClient) -> Path | None:
        """design 声线 → 可用的锚点路径：优先档案里的 anchor；缺失/文件不在 → 按描述自动生成一次。
        preset 声线 → None。生成失败抛 TtsError（调用方决定是否退回逐句设计）。"""
        if voice.mode != "design" or voice.style is None:
            return None
        if voice.anchor is not None:
            path = self.path_for(voice.anchor)
            if path is not None:
                return path
            logger.warning("档案锚点 %s 文件不存在，改用按描述自动生成", voice.anchor)
        name = f"auto-{hashlib.sha256(voice.style.encode('utf-8')).hexdigest()[:16]}.wav"
        path = self._dir / name
        if path.is_file():
            return path
        wav = await tts.design_anchor(voice.style)
        return self._write(name, wav)
