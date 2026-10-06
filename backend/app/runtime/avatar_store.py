"""头像存储（issue #102）：内容寻址（sha256 前 16 位 + 扩展名）、按魔数识别类型、幂等写入。

只存公开内容（头像随 /meta 对已终局对局公开），不需要 0600；
不缩放、不做孤儿清理（规格 §3.1 非目标）。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from app.agent.profile import AVATAR_ID_PATTERN

MAX_AVATAR_BYTES = 512 * 1024
_ID_RE = re.compile(AVATAR_ID_PATTERN)


class UnsupportedImageError(ValueError):
    """字节不是 PNG / JPEG / WebP。"""


def sniff_image(data: bytes) -> str | None:
    """按魔数判类型：PNG `89 50 4E 47`、JPEG `FF D8 FF`、WebP `RIFF....WEBP`；不认识 → None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def avatar_id_for(data: bytes) -> str:
    ext = sniff_image(data)
    if ext is None:
        raise UnsupportedImageError("只支持 PNG / JPEG / WebP")
    return f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"


def check_avatar_id(avatar_id: str) -> None:
    if not _ID_RE.fullmatch(avatar_id):
        raise ValueError(f"非法 avatar_id：{avatar_id!r}")


class AvatarStore(Protocol):
    def put(self, data: bytes) -> str: ...

    def path_for(self, avatar_id: str) -> Path | None: ...


class InMemoryAvatarStore:
    """测试用：path_for 仍返回真实临时文件路径，让 FileResponse 路径可用。"""

    def __init__(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="agenthowl-avatars-"))
        self._inner = FileAvatarStore(self._dir)

    def put(self, data: bytes) -> str:
        return self._inner.put(data)

    def path_for(self, avatar_id: str) -> Path | None:
        return self._inner.path_for(avatar_id)


class FileAvatarStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 首次 put 时创建

    def put(self, data: bytes) -> str:
        avatar_id = avatar_id_for(data)
        path = self._dir / avatar_id
        if path.exists():
            return avatar_id  # 内容寻址：已存在即幂等，不重写
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return avatar_id

    def path_for(self, avatar_id: str) -> Path | None:
        check_avatar_id(avatar_id)
        path = self._dir / avatar_id
        return path if path.is_file() else None
