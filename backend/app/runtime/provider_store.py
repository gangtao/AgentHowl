"""Provider 存储（issue #26）：每个 provider 一份 JSON（data/providers/<provider_id>.json）。IO 层。

含密钥明文，故文件权限收紧到 0600（README 明示：本地单用户部署）。
坏文件：list() 跳过并记 warning（一个坏文件不该让整个存储不可用）；get() 抛 StoreCorruptionError。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.agent.provider import Provider
from app.store.event_store import StoreCorruptionError, StoreError

logger = logging.getLogger(__name__)


class ProviderStore(Protocol):
    def list(self) -> list[Provider]: ...
    def get(self, provider_id: str) -> Provider | None: ...
    def put(self, provider: Provider) -> None: ...
    def delete(self, provider_id: str) -> bool: ...


class InMemoryProviderStore:
    def __init__(self) -> None:
        self._docs: dict[str, Provider] = {}

    def list(self) -> list[Provider]:
        return sorted(self._docs.values(), key=lambda p: p.updated_at, reverse=True)

    def get(self, provider_id: str) -> Provider | None:
        return self._docs.get(provider_id)

    def put(self, provider: Provider) -> None:
        self._docs[provider.provider_id] = provider

    def delete(self, provider_id: str) -> bool:
        return self._docs.pop(provider_id, None) is not None


class JsonFileProviderStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 首次 put 时创建

    def _path(self, provider_id: str) -> Path:
        return self._dir / f"{provider_id}.json"

    def _read(self, path: Path) -> Provider:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StoreError(f"读取 provider 失败：{path}：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise StoreCorruptionError(f"provider 不是合法 JSON：{path}：{exc}") from exc
        try:
            return Provider.model_validate(raw)
        except ValidationError as exc:
            # pydantic 的错误文本含 input_value=…，可能回显坏文件里的明文密钥片段；
            # 完整异常只记日志（后端本地文件，非用户可读响应），抛给调用方（可能经 API 500
            # 回显给客户端）的消息只带文件名，不带 pydantic 原文。
            logger.warning("provider 文件校验失败 %s：%s", path.name, exc)
            raise StoreCorruptionError(f"provider 校验失败：{path.name}") from exc

    def list(self) -> list[Provider]:
        if not self._dir.is_dir():
            return []
        out: list[Provider] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                out.append(self._read(path))
            except StoreCorruptionError as exc:
                logger.warning("跳过坏 provider 文件 %s：%s", path.name, exc)
        return sorted(out, key=lambda p: p.updated_at, reverse=True)

    def get(self, provider_id: str) -> Provider | None:
        path = self._path(provider_id)
        return self._read(path) if path.exists() else None

    def put(self, provider: Provider) -> None:
        path = self._path(provider.provider_id)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                prefix=f".{provider.provider_id}.", suffix=".tmp", dir=self._dir
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(provider.model_dump_json(indent=2))
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise StoreError(f"写入 provider 失败：{path}：{exc}") from exc

    def delete(self, provider_id: str) -> bool:
        path = self._path(provider_id)
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise StoreError(f"删除 provider 失败：{path}：{exc}") from exc
        return True
