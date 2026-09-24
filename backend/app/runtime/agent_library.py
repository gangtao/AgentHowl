"""Agent 档案库（issue #26）：每个档案一份 JSON（data/agents/<agent_id>.json）。IO 层。

坏文件：list() 跳过并记 warning（一个坏文件不该让整个档案库不可用）；get() 抛 StoreCorruptionError。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agent.profile import AgentProfile
from app.store.event_store import StoreCorruptionError, StoreError

logger = logging.getLogger(__name__)


class StoredAgent(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    profile: AgentProfile
    created_at: str
    updated_at: str


class AgentLibraryStore(Protocol):
    def list(self) -> list[StoredAgent]: ...
    def get(self, agent_id: str) -> StoredAgent | None: ...
    def put(self, stored: StoredAgent) -> None: ...
    def delete(self, agent_id: str) -> bool: ...


class InMemoryAgentLibrary:
    def __init__(self) -> None:
        self._docs: dict[str, StoredAgent] = {}

    def list(self) -> list[StoredAgent]:
        return sorted(self._docs.values(), key=lambda s: s.updated_at, reverse=True)

    def get(self, agent_id: str) -> StoredAgent | None:
        return self._docs.get(agent_id)

    def put(self, stored: StoredAgent) -> None:
        self._docs[stored.agent_id] = stored

    def delete(self, agent_id: str) -> bool:
        return self._docs.pop(agent_id, None) is not None


class JsonFileAgentLibrary:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 首次 put 时创建

    def _path(self, agent_id: str) -> Path:
        return self._dir / f"{agent_id}.json"

    def _read(self, path: Path) -> StoredAgent:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StoreError(f"读取档案失败：{path}：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise StoreCorruptionError(f"档案不是合法 JSON：{path}：{exc}") from exc
        try:
            return StoredAgent.model_validate(raw)
        except ValidationError as exc:
            raise StoreCorruptionError(f"档案校验失败：{path}：{exc}") from exc

    def list(self) -> list[StoredAgent]:
        if not self._dir.is_dir():
            return []
        out: list[StoredAgent] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                out.append(self._read(path))
            except StoreCorruptionError as exc:
                logger.warning("跳过坏档案文件 %s：%s", path.name, exc)
        return sorted(out, key=lambda s: s.updated_at, reverse=True)

    def get(self, agent_id: str) -> StoredAgent | None:
        path = self._path(agent_id)
        return self._read(path) if path.exists() else None

    def put(self, stored: StoredAgent) -> None:
        path = self._path(stored.agent_id)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{stored.agent_id}.", suffix=".tmp", dir=self._dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(stored.model_dump_json(indent=2))
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise StoreError(f"写入档案失败：{path}：{exc}") from exc

    def delete(self, agent_id: str) -> bool:
        path = self._path(agent_id)
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise StoreError(f"删除档案失败：{path}：{exc}") from exc
        return True
