"""跨局经验存储（issue #59）：每个 memory_id 一份 JSON 文档。IO 层；引擎与 agent 层不感知。

损坏口径与 event_store 一致：真损坏（坏 JSON / 顶层非对象 / 校验失败 / memory_id 与文件名不符）
fail-loud 抛 StoreCorruptionError（信息含路径），不静默丢弃；写入用临时文件 + os.replace 原子替换，
因此不存在「残尾」需要修复。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.agent.experience import AgentExperience
from app.store.event_store import StoreCorruptionError, StoreError


class ExperienceStore(Protocol):
    def load(self, memory_id: str) -> AgentExperience:
        """不存在 → 全新 AgentExperience(memory_id=...)；不得有副作用（不建目录）。"""
        ...

    def save(self, exp: AgentExperience) -> None: ...


class InMemoryExperienceStore:
    """测试 / 不落盘运行用；saves 计数供「对局中不得写入」断言。"""

    def __init__(self) -> None:
        self._docs: dict[str, AgentExperience] = {}
        self.saves = 0

    def load(self, memory_id: str) -> AgentExperience:
        doc = self._docs.get(memory_id)
        if doc is not None:
            return doc.model_copy(deep=True)
        return AgentExperience(memory_id=memory_id)

    def save(self, exp: AgentExperience) -> None:
        self._docs[exp.memory_id] = exp.model_copy(deep=True)
        self.saves += 1


class JsonFileExperienceStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 目录在首次 save 时创建；无 memory_id 的运行永不落盘

    def path_for(self, memory_id: str) -> Path:
        return self._dir / f"{memory_id}.json"  # MEMORY_ID_PATTERN 保证无路径穿越

    def load(self, memory_id: str) -> AgentExperience:
        path = self.path_for(memory_id)
        if not path.exists():
            return AgentExperience(memory_id=memory_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StoreError(f"读取经验文件失败：{path}：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise StoreCorruptionError(f"经验文件不是合法 JSON：{path}：{exc}") from exc
        if not isinstance(raw, dict):
            raise StoreCorruptionError(f"经验文件顶层须为对象：{path}")
        try:
            exp = AgentExperience.model_validate(raw)
        except ValidationError as exc:
            raise StoreCorruptionError(f"经验文件校验失败：{path}：{exc}") from exc
        if exp.memory_id != memory_id:
            raise StoreCorruptionError(
                f"经验文件 memory_id 与文件名不符：{path}（文件内为 {exp.memory_id!r}）"
            )
        return exp

    def save(self, exp: AgentExperience) -> None:
        path = self.path_for(exp.memory_id)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{exp.memory_id}.", suffix=".tmp", dir=self._dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(exp.model_dump_json(indent=2))
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise StoreError(f"写入经验文件失败：{path}：{exc}") from exc
