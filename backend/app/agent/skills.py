"""技能包（issue #58）：SKILL.md 技巧库的解析、校验、选择与装配。

文件格式兼容 Agent Skills 规范（agentskills.io）：frontmatter 只用 name / description，
自定义项（roles / phases / priority）放在 metadata（字符串值）。加载是 IO；选择与装配是纯函数。
本模块不 import agent_player / llm_client（litellm 惰性加载纪律）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.engine.config import RoleType
from app.engine.phases import Phase

STAR = "*"
DEFAULT_SKILL_BUDGET_CHARS = 1800  # 每次决策装配的技能正文总字符预算
MAX_BODY_CHARS = 1200  # 单篇正文上限（首批约定 ≤ 600 字，留余量）
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"  # backend/skills
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class SkillError(ValueError):
    """技能文件或技能名非法（加载期 fail-loud）。"""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    roles: frozenset[RoleType]  # 空集 = 全部角色
    phases: frozenset[str]  # 空集 = 全部阶段（值为 Phase.value）
    priority: int
    body: str
    source: Path


def _split_words(raw: str) -> list[str]:
    return [w for w in raw.split() if w]


def parse_skill_md(path: Path) -> Skill:
    """解析并校验一个 SKILL.md；name 须与父目录名一致。"""
    # replace 只是防御性保底：Path.read_text 默认按 universal newlines 已将 CRLF 归一为 LF，
    # 但显式保留可避免依赖该隐式行为（终审 F7）。
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        raise SkillError(f"{path}: 缺少 YAML frontmatter（--- ... ---）")
    try:
        front = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{path}: frontmatter 解析失败：{exc}") from exc
    if not isinstance(front, dict):
        raise SkillError(f"{path}: frontmatter 须为映射")
    name = front.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= 64) or not _NAME_RE.match(name):
        raise SkillError(
            f"{path}: name 非法（1-64 字符，小写字母/数字/连字符，不得首尾或连续连字符）"
        )
    if name != path.parent.name:
        raise SkillError(f"{path}: name {name!r} 与目录名 {path.parent.name!r} 不一致")
    desc = front.get("description")
    if not isinstance(desc, str) or not (1 <= len(desc.strip()) <= 1024):
        raise SkillError(f"{path}: description 须为 1-1024 字符的非空字符串")
    meta = front.get("metadata")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict) or any(not isinstance(v, str) for v in meta.values()):
        raise SkillError(f"{path}: metadata 须为字符串到字符串的映射")
    try:
        roles = frozenset(RoleType(w) for w in _split_words(meta.get("roles", "")))
    except ValueError as exc:
        raise SkillError(f"{path}: metadata.roles 含未知角色：{exc}") from exc
    phase_words = _split_words(meta.get("phases", ""))
    valid_phases = {p.value for p in Phase}
    bad = [w for w in phase_words if w not in valid_phases]
    if bad:
        raise SkillError(f"{path}: metadata.phases 含未知阶段：{bad}")
    prio_raw = meta.get("priority", "0")
    try:
        priority = int(prio_raw)
    except ValueError as exc:
        raise SkillError(f"{path}: metadata.priority 须为整数字符串，收到 {prio_raw!r}") from exc
    body = m.group(2).strip()
    if not body:
        raise SkillError(f"{path}: 正文为空")
    if len(body) > MAX_BODY_CHARS:
        raise SkillError(f"{path}: 正文超过 {MAX_BODY_CHARS} 字（{len(body)}）")
    return Skill(
        name=name,
        description=desc.strip(),
        roles=roles,
        phases=frozenset(phase_words),
        priority=priority,
        body=body,
        source=path,
    )


class SkillLibrary:
    """按名索引的技能集合；load 依次扫描多个目录，后者同名覆盖前者。"""

    def __init__(self, skills: dict[str, Skill]) -> None:
        self._skills = dict(sorted(skills.items()))

    @classmethod
    def empty(cls) -> SkillLibrary:
        return cls({})

    @classmethod
    def load(cls, dirs: Sequence[Path]) -> SkillLibrary:
        skills: dict[str, Skill] = {}
        for d in dirs:
            if not d.is_dir():
                raise SkillError(f"技能目录不存在：{d}")
            for sub in sorted(p for p in d.iterdir() if p.is_dir()):
                md = sub / "SKILL.md"
                if md.is_file():
                    s = parse_skill_md(md)
                    skills[s.name] = s
        return cls(skills)

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Skill:
        return self._skills[name]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    def resolve(self, wanted: Sequence[str]) -> list[Skill]:
        """展开 "*"（全部，按名序）并去重；有 "*" 时按名序，无则保持顺序；未知名 → SkillError。"""
        has_star = STAR in wanted
        out: list[Skill] = []
        seen: set[str] = set()
        for w in wanted:
            names = self.names() if w == STAR else [w]
            for n in names:
                if n not in self._skills:
                    raise SkillError(f"未知技能：{n!r}（可用：{', '.join(self.names()) or '无'}）")
                if n not in seen:
                    seen.add(n)
                    out.append(self._skills[n])
        if has_star:
            out.sort(key=lambda s: s.name)
        return out


def select_skills(skills: Sequence[Skill], role: RoleType, phase: str) -> list[Skill]:
    """按角色与阶段过滤（空集 = 通配），priority 降序、name 升序。"""
    hit = [
        s
        for s in skills
        if (not s.roles or role in s.roles) and (not s.phases or phase in s.phases)
    ]
    return sorted(hit, key=lambda s: (-s.priority, s.name))


def assemble_skills(
    skills: Sequence[Skill], budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS
) -> tuple[str, tuple[str, ...]]:
    """按序整篇累加正文，超预算即停（不截断）；返回 (文本, 用到的技能名)。"""
    parts: list[str] = []
    used: list[str] = []
    total = 0
    for s in skills:
        block = f"【技能：{s.name}】\n{s.body}"
        if total + len(block) > budget_chars:
            break
        parts.append(block)
        used.append(s.name)
        total += len(block)
    return "\n\n".join(parts), tuple(used)


def skills_index_text(skills: Sequence[Skill]) -> str:
    """系统 prompt 的技能索引（渐进披露第一层）：每行「- name：description」。"""
    return "\n".join(f"- {s.name}：{s.description}" for s in skills)


_DEFAULT: SkillLibrary | None = None


def default_library() -> SkillLibrary:
    """内置库（backend/skills），进程内惰性加载一次。"""
    global _DEFAULT  # noqa: PLW0603
    if _DEFAULT is None:
        _DEFAULT = (
            SkillLibrary.load([BUILTIN_SKILLS_DIR])
            if BUILTIN_SKILLS_DIR.is_dir()
            else SkillLibrary.empty()
        )
    return _DEFAULT
