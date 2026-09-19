# Agent 技能包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `SKILL.md` 格式的狼人杀技巧库（内置 14 篇 + 可选外部目录），按 `AgentProfile.skills` 配置、按 `(角色, 阶段)` 渐进装配进 prompt（issue #58）。

**Architecture:** 新模块 `app/agent/skills.py`（加载/校验/选择/装配，不 import agent_player）；`AgentPlayerPort` 持已解析技能列表，系统 prompt 列索引、每次决策装正文；`AgentProfile.skills` + `validate_profiles(…, library)`；registry / API / CLI 三个入口注入 `SkillLibrary`。任务顺序：模块 → 内置库 → 端口与档案 → registry/API → CLI/文档。

**Tech Stack:** Python 3.11、Pydantic v2、pyyaml（已有）、FastAPI、pytest；`uv`。Python 命令在 `backend/` 下执行。

**Spec:** `docs/superpowers/specs/2026-09-19-agent-skills-design.md`（执行者须同时阅读）

## Global Constraints

- 引擎（`backend/app/engine/`）不改。
- `app/agent/skills.py`、`app/runtime`、`app/api`、`app/cli` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`（CLAUDE.md 惰性加载纪律；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫）。
- 公私分离：狼夜私有调用只装 `phases` 含 `NIGHT_WEREWOLF` 的技能；昼间公开调用只装昼间阶段技能；`build_prompt` 签名仍无私有分区参数。
- `skills_text=""` 时两个 prompt 装配函数输出与现状逐字相同；不配技能的 Agent 行为零变化。
- 技能文件兼容 Agent Skills 规范：顶层仅 `name` / `description`（+ 规范允许的可选字段），自定义项全在 `metadata`（字符串值）。
- 文档与代码注释用中文；标识符用英文；注释密度与周边一致；ruff 行宽 100 且中文按宽 2 计。
- 测试零 IO、零 mock；技能目录用 `tmp_path`。
- 每任务结束：`uv run pytest -q -x --ignore=tests/test_api_e2e.py` 全绿、`uv run ruff check .`（All checks passed!）、`uv run ruff format --check .`、`uv run mypy app` 全过；最后一个任务跑含 E2E 的 `uv run pytest -q`。
- commit 风格 `feat(agent): … (issue #58)`，结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `backend/app/agent/skills.py`（新） | `Skill`、`SkillLibrary`、解析/校验/选择/装配、`default_library()` | 1 |
| `backend/tests/test_agent_skills.py`（新） | 模块测试 | 1 |
| `backend/skills/<name>/SKILL.md` ×14（新） | 内置技能库 | 2 |
| `backend/tests/test_builtin_skills.py`（新） | 内置库结构/内容守卫 | 2 |
| `backend/app/agent/prompts.py`、`agent_player.py`、`profile.py` | `skills_text` 参数；端口装配；`AgentProfile.skills`、`validate_profiles(library)`、`build_agent_port(library)` | 3 |
| `backend/app/runtime/registry.py`、`app/main.py` | `skill_library` 注入、`create_app(skills_dir)`、env | 4 |
| `backend/app/cli/play.py`、`render.py`、`Makefile`、`README.md`、`docs/specs/requirements.md` | `--skills-dir`、档案表技能列、文档 | 5 |
| `backend/tests/test_agent_bench.py` | env 门控 A/B 冒烟 | 5 |

---

### Task 1: `app/agent/skills.py`——解析、校验、库、选择、装配

**Files:**
- Create: `backend/app/agent/skills.py`
- Create: `backend/tests/test_agent_skills.py`

**Interfaces:**
- Produces（后续任务逐字依赖）：
  - `Skill(name, description, roles: frozenset[RoleType], phases: frozenset[str], priority: int, body: str, source: Path)`（frozen dataclass）
  - `class SkillError(ValueError)`；`STAR = "*"`；`DEFAULT_SKILL_BUDGET_CHARS = 1800`；`MAX_BODY_CHARS = 1200`；`BUILTIN_SKILLS_DIR: Path`
  - `parse_skill_md(path: Path) -> Skill`
  - `SkillLibrary.load(dirs: Sequence[Path]) -> SkillLibrary`、`.empty()`、`.names() -> list[str]`、`.get(name) -> Skill`、`.resolve(wanted: Sequence[str]) -> list[Skill]`、`.__len__`、`.__contains__`
  - `select_skills(skills, role: RoleType, phase: str) -> list[Skill]`
  - `assemble_skills(skills, budget_chars=DEFAULT_SKILL_BUDGET_CHARS) -> tuple[str, tuple[str, ...]]`
  - `skills_index_text(skills) -> str`
  - `default_library() -> SkillLibrary`（进程内缓存）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_skills.py`：

```python
"""技能包模块（issue #58）：SKILL.md 解析/校验、库加载与覆盖、按角色阶段选择、预算装配。"""

from pathlib import Path

import pytest

from app.agent.skills import (
    DEFAULT_SKILL_BUDGET_CHARS,
    MAX_BODY_CHARS,
    Skill,
    SkillError,
    SkillLibrary,
    assemble_skills,
    parse_skill_md,
    select_skills,
    skills_index_text,
)
from app.engine.config import RoleType


def _write(root: Path, name: str, body: str = "正文。", **meta: str) -> Path:
    """在 root/name/SKILL.md 写一个技能；meta 进 frontmatter 的 metadata。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta_lines = "".join(f"  {k}: \"{v}\"\n" for k, v in meta.items())
    text = (
        f"---\nname: {name}\ndescription: 描述 {name}\n"
        + (f"metadata:\n{meta_lines}" if meta_lines else "")
        + f"---\n{body}\n"
    )
    p = d / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_minimal_and_metadata(tmp_path: Path) -> None:
    p = _write(tmp_path, "seer-x", body="做法一。", roles="SEER", phases="DAY_SPEECH VOTE", priority="5")
    s = parse_skill_md(p)
    assert s.name == "seer-x" and s.description == "描述 seer-x"
    assert s.roles == frozenset({RoleType.SEER})
    assert s.phases == frozenset({"DAY_SPEECH", "VOTE"})
    assert s.priority == 5 and s.body == "做法一。" and s.source == p
    # 无 metadata → 全角色全阶段、priority 0
    s2 = parse_skill_md(_write(tmp_path, "generic"))
    assert s2.roles == frozenset() and s2.phases == frozenset() and s2.priority == 0


@pytest.mark.parametrize(
    ("dirname", "text", "match"),
    [
        ("Bad-Name", "---\nname: Bad-Name\ndescription: d\n---\nb\n", "name"),
        ("a--b", "---\nname: a--b\ndescription: d\n---\nb\n", "name"),
        ("mismatch", "---\nname: other\ndescription: d\n---\nb\n", "目录"),
        ("no-desc", "---\nname: no-desc\n---\nb\n", "description"),
        ("no-front", "just text\n", "frontmatter"),
        ("bad-role", '---\nname: bad-role\ndescription: d\nmetadata:\n  roles: "KING"\n---\nb\n', "roles"),
        ("bad-phase", '---\nname: bad-phase\ndescription: d\nmetadata:\n  phases: "NOON"\n---\nb\n', "phases"),
        ("bad-prio", '---\nname: bad-prio\ndescription: d\nmetadata:\n  priority: "high"\n---\nb\n', "priority"),
        ("non-str-meta", "---\nname: non-str-meta\ndescription: d\nmetadata:\n  priority: 3\n---\nb\n", "字符串"),
        ("empty-body", "---\nname: empty-body\ndescription: d\n---\n\n", "正文"),
    ],
)
def test_parse_errors(tmp_path: Path, dirname: str, text: str, match: str) -> None:
    d = tmp_path / dirname
    d.mkdir()
    p = d / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(SkillError, match=match):
        parse_skill_md(p)


def test_parse_body_too_long(tmp_path: Path) -> None:
    p = _write(tmp_path, "long", body="字" * (MAX_BODY_CHARS + 1))
    with pytest.raises(SkillError, match="正文"):
        parse_skill_md(p)


def test_library_load_override_resolve(tmp_path: Path) -> None:
    builtin, ext = tmp_path / "builtin", tmp_path / "ext"
    _write(builtin, "a", body="内置 a")
    _write(builtin, "b", body="内置 b")
    _write(ext, "b", body="外部 b")  # 同名覆盖
    _write(ext, "c", body="外部 c")
    (ext / "not-a-skill").mkdir()  # 无 SKILL.md 的目录 → 忽略
    (ext / "README.md").write_text("x", encoding="utf-8")  # 散文件 → 忽略
    lib = SkillLibrary.load([builtin, ext])
    assert lib.names() == ["a", "b", "c"]
    assert lib.get("b").body == "外部 b"
    assert len(lib) == 3 and "a" in lib and "zzz" not in lib
    assert [s.name for s in lib.resolve(["c", "a"])] == ["c", "a"]  # 保持给定顺序
    assert [s.name for s in lib.resolve(["*"])] == ["a", "b", "c"]
    assert [s.name for s in lib.resolve(["b", "*"])] == ["a", "b", "c"]  # "*" 展开去重
    with pytest.raises(SkillError, match="zzz"):
        lib.resolve(["a", "zzz"])
    with pytest.raises(KeyError):
        lib.get("zzz")
    assert SkillLibrary.empty().names() == [] and SkillLibrary.empty().resolve(["*"]) == []


def test_library_load_missing_dir_is_error(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="目录"):
        SkillLibrary.load([tmp_path / "nope"])


def _sk(name: str, roles: set[RoleType] = set(), phases: set[str] = set(), prio: int = 0, body: str = "b") -> Skill:
    return Skill(
        name=name,
        description=f"d-{name}",
        roles=frozenset(roles),
        phases=frozenset(phases),
        priority=prio,
        body=body,
        source=Path(f"/x/{name}/SKILL.md"),
    )


def test_select_filters_and_sorts() -> None:
    skills = [
        _sk("wolf-night", {RoleType.WEREWOLF}, {"NIGHT_WEREWOLF"}, 5),
        _sk("wolf-day", {RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}, 1),
        _sk("seer-day", {RoleType.SEER}, {"DAY_SPEECH"}, 9),
        _sk("any-any"),  # 全角色全阶段
        _sk("any-day", set(), {"DAY_SPEECH"}, 9),
    ]
    got = [s.name for s in select_skills(skills, RoleType.WEREWOLF, "DAY_SPEECH")]
    assert got == ["any-day", "wolf-day", "any-any"]  # priority 降序，同分 name 升序
    assert [s.name for s in select_skills(skills, RoleType.WEREWOLF, "NIGHT_WEREWOLF")] == ["wolf-night", "any-any"]
    assert [s.name for s in select_skills(skills, RoleType.SEER, "DAY_SPEECH")] == ["any-day", "seer-day", "any-any"]
    assert [s.name for s in select_skills(skills, RoleType.VILLAGER, "VOTE")] == ["any-any"]


def test_assemble_budget_whole_skills_only() -> None:
    a, b, c = _sk("a", body="甲" * 100), _sk("b", body="乙" * 100), _sk("c", body="丙" * 100)
    text, used = assemble_skills([a, b, c], budget_chars=250)
    assert used == ("a", "b")  # c 放不下则整篇跳过，不截断
    assert "【技能：a】\n" + "甲" * 100 in text and "【技能：b】" in text and "丙" not in text
    assert assemble_skills([], 100) == ("", ())
    text_all, used_all = assemble_skills([a, b, c])  # 默认预算足够
    assert used_all == ("a", "b", "c") and DEFAULT_SKILL_BUDGET_CHARS >= 300
    # 第一篇就超预算 → 什么都不装
    assert assemble_skills([a], budget_chars=10) == ("", ())


def test_index_text() -> None:
    assert skills_index_text([_sk("a"), _sk("b")]) == "- a：d-a\n- b：d-b"
    assert skills_index_text([]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_skills.py -q`
Expected: 收集期 `ModuleNotFoundError: No module named 'app.agent.skills'`

- [ ] **Step 3: 实现**

新建 `backend/app/agent/skills.py`：

```python
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
    text = path.read_text(encoding="utf-8")
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
        raise SkillError(f"{path}: name 非法（1-64 字符，小写字母/数字/连字符，不得首尾或连续连字符）")
    if name != path.parent.name:
        raise SkillError(f"{path}: name {name!r} 与目录名 {path.parent.name!r} 不一致")
    desc = front.get("description")
    if not isinstance(desc, str) or not (1 <= len(desc.strip()) <= 1024):
        raise SkillError(f"{path}: description 须为 1-1024 字符的非空字符串")
    meta = front.get("metadata") or {}
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
        """展开 "*"（全部，按名序）并去重，保持给定顺序；未知名 → SkillError。"""
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
        return out


def select_skills(skills: Sequence[Skill], role: RoleType, phase: str) -> list[Skill]:
    """按角色与阶段过滤（空集 = 通配），priority 降序、name 升序。"""
    hit = [s for s in skills if (not s.roles or role in s.roles) and (not s.phases or phase in s.phases)]
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
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SkillLibrary.load([BUILTIN_SKILLS_DIR]) if BUILTIN_SKILLS_DIR.is_dir() else SkillLibrary.empty()
    return _DEFAULT
```

- [ ] **Step 4: 跑测试确认通过 + 无回归**

Run: `uv run pytest tests/test_agent_skills.py -q`
Expected: 全部 PASS（`test_assemble_budget_whole_skills_only` 里 250 预算：块 = 6+1+100=107 字符，两篇 214，三篇 321 > 250 → `("a","b")`）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/skills.py backend/tests/test_agent_skills.py
git commit -m "feat(agent): 技能包模块——SKILL.md 解析校验、库加载覆盖、按角色阶段选择与预算装配 (issue #58)"
```

---

### Task 2: 内置技能库（14 篇）与结构守卫测试

**Files:**
- Create: `backend/skills/<name>/SKILL.md` ×14
- Create: `backend/tests/test_builtin_skills.py`

**Interfaces:**
- Consumes: Task 1 `SkillLibrary.load`、`BUILTIN_SKILLS_DIR`、`parse_skill_md`。
- Produces: `default_library()` 含下列 14 个名字：`seer-badge-flow`、`seer-vs-claim-jump`、`wolf-claim-jump`、`wolf-counter-hook`、`wolf-charge`、`wolf-lay-low`、`wolf-team-kill`、`witch-potion-timing`、`hunter-shot-target`、`sheriff-herding`、`vote-discipline`、`logic-chain`、`side-taking`、`strategy-adaptation`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_builtin_skills.py`：

```python
"""内置技能库守卫（issue #58）：14 篇齐全、结构合规、正文长度与措辞约束。"""

from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary, default_library
from app.engine.config import RoleType

EXPECTED = {
    "seer-badge-flow": ({RoleType.SEER}, {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH"}),
    "seer-vs-claim-jump": ({RoleType.SEER}, {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH", "VOTE"}),
    "wolf-claim-jump": ({RoleType.WEREWOLF}, {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH"}),
    "wolf-counter-hook": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}),
    "wolf-charge": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}),
    "wolf-lay-low": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}),
    "wolf-team-kill": ({RoleType.WEREWOLF}, {"NIGHT_WEREWOLF"}),
    "witch-potion-timing": ({RoleType.WITCH}, {"NIGHT_WITCH", "DAY_SPEECH"}),
    "hunter-shot-target": ({RoleType.HUNTER}, {"HUNTER_SHOOT", "DAY_SPEECH"}),
    "sheriff-herding": (set(), {"SHERIFF_ELECTION", "DAY_SPEECH", "VOTE", "LAST_WORDS"}),
    "vote-discipline": (set(), {"VOTE", "VOTE_PK"}),
    "logic-chain": (set(), {"DAY_SPEECH", "VOTE"}),
    "side-taking": (set(), {"DAY_SPEECH", "VOTE", "SHERIFF_ELECTION"}),
    "strategy-adaptation": (set(), {"DAY_SPEECH", "VOTE"}),
}
FORBIDDEN = ("你知道", "上帝视角", "无视规则", "绕过", "作弊")


def test_builtin_library_complete_and_wellformed() -> None:
    lib = SkillLibrary.load([BUILTIN_SKILLS_DIR])
    assert set(lib.names()) == set(EXPECTED)
    for name, (roles, phases) in EXPECTED.items():
        s = lib.get(name)
        assert s.roles == frozenset(roles), name
        assert s.phases == frozenset(phases), name
        assert 80 <= len(s.body) <= 600, f"{name}: 正文 {len(s.body)} 字"
        assert all(w not in s.body for w in FORBIDDEN), name
        assert "触发" in s.body and "做法" in s.body and ("风险" in s.body or "反例" in s.body), name


def test_wolf_skills_do_not_instruct_leaking_night_plans() -> None:
    lib = default_library()
    for name in ("wolf-claim-jump", "wolf-counter-hook", "wolf-charge", "wolf-lay-low"):
        body = lib.get(name).body
        assert "不要" in body or "不得" in body or "避免" in body, name  # 至少有一条禁止性提醒
        assert "公开" in body or "发言" in body, name


def test_default_library_is_cached_singleton() -> None:
    assert default_library() is default_library()
    assert len(default_library()) == len(EXPECTED)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_builtin_skills.py -q`
Expected: FAIL（`SkillError: 技能目录不存在` 或名字集合为空）

- [ ] **Step 3: 写 14 篇 SKILL.md**

每篇位于 `backend/skills/<name>/SKILL.md`，frontmatter 的 `roles` / `phases` 严格按上表（用空格分隔、加引号；`roles` 为空集的技能**不写** `roles` 键），`priority` 按下表；正文 **80–600 字**、中文、三段固定小标题 `触发条件：` / `做法：` / `风险与反例：`（守卫测试检查「触发」「做法」「风险/反例」字样）。写作约束：只给策略；不诱导非法行动（合法性由引擎裁决）；不得出现 `你知道`、`上帝视角`、`无视规则`、`绕过`、`作弊`；狼人昼间技能必须含一条禁止性提醒（如「不要在公开发言里提及夜间的刀口讨论」）。

各篇要点与 priority：

| name | priority | 正文要点 |
|---|---|---|
| seer-badge-flow | 10 | 触发：你是预言家、进入竞选或首日发言。做法：上警报首夜查验结果（金水/查杀）；用 badge_flow 报未来两夜验人顺序，优先验发言可疑、位置关键的人；被查杀者若不上警要点名。风险：不报警徽流会让警徽失去传递价值；报太多目标反而被狼针对。 |
| seer-vs-claim-jump | 10 | 触发：有人与你对跳预言家。做法：先陈述自己的查验与警徽流，再指出对方查验的逻辑漏洞（如给悍跳狼金水）；请警下按警徽流验证；投票优先归票对方而非其金水。风险：情绪化对喷降低可信度；不要为了压过对方编造查验。 |
| wolf-claim-jump | 8 | 触发：你是狼，真预言家可能没上警或你有队友配合。做法：报一个可信的查验（给队友金水或给强势好人查杀）、报警徽流；发言逻辑要自洽；队友站台但不要过于整齐。风险：与真预言家查验矛盾时容易暴露；**不要在公开发言中提及夜间刀口讨论或队友身份**。 |
| wolf-counter-hook | 6 | 触发：你是狼，队友已被查杀或真预言家明显可信。做法：公开站真预言家、甚至投票出局队友以换取信任；后期关键票再反水。风险：卖队友过早会输掉狼队；**不要用夜间私谋里的信息解释你的站边**。 |
| wolf-charge | 6 | 触发：队友悍跳预言家。做法：给悍跳队友背书、把票带向其查杀目标；用逻辑而非情绪。风险：站台过猛会被一起带走；**不要泄露你与悍跳者的关系或夜间讨论**。 |
| wolf-lay-low | 4 | 触发：你是狼，局势不需要你冒头。做法：发言简短、跟随多数、不主动出逻辑；投票跟大票。风险：过分沉默也会被怀疑；**不要因为紧张在公开发言里透露夜间信息**。 |
| wolf-team-kill | 9 | 触发：夜间提议刀口。做法：优先真预言家/警徽流指向的下一位/带节奏的好人；避免刀可能被守卫守的目标（如刚被点名要守的人）；队友已提案且无强理由就跟刀（全员一致才出刀）。风险：分散提案等于空刀。 |
| witch-potion-timing | 8 | 触发：夜间用药决策或白天决定是否报银水。做法：首夜若死者是可信神职可救，否则留药；毒药留给查杀或悍跳者；报银水（救过谁）能给对方背书但暴露自己。风险：同夜不能双开；毒错好人代价极大。 |
| hunter-shot-target | 8 | 触发：你是猎人，被放逐或被刀时可开枪；或白天考虑是否跳猎人。做法：枪口优先查杀 > 悍跳者 > 明显划水/逻辑矛盾者；不要枪金水；跳猎人可保护自己但会被针对。风险：被毒死不能开枪，所以别过早暴露。 |
| sheriff-herding | 5 | 触发：竞选或你已是警长。做法：争警长时说明理由（信息量/神职）；发言方向选择让可疑者后置；发言末尾归票；临死移交警徽给最可信的好人。风险：归票错误会带走好人信任。 |
| vote-discipline | 5 | 触发：投票或 PK 投票。做法：有真预言家查杀就跟；不弃票；平票时选择逻辑更差的一方。风险：跟风投票被狼利用带节奏。 |
| logic-chain | 7 | 触发：白天发言与投票。做法：记录每人前后发言矛盾与票型（谁跟谁投）；金水链、查杀链交叉验证；被查杀者的辩解是否针对逻辑。风险：单一证据不足以定论。 |
| side-taking | 7 | 触发：两位预言家对跳。做法：比较查验的可验证性（金水是否可信、警徽流是否被兑现）；选边后行动一致；新证据出现时可改站边但要说明理由。风险：反复横跳会失去信任。 |
| strategy-adaptation | 3 | 触发：每次白天发言或投票前。做法：对每位玩家估计其身份可能性（好人/狼/神职，0–4 分）；自己被怀疑时采用 Support（附和可信者、为自己辩解不过度）；锁定目标时采用 Attack（提出具体怀疑与证据）；每轮重估。风险：策略切换太频繁显得摇摆。 |

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_builtin_skills.py tests/test_agent_skills.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/skills backend/tests/test_builtin_skills.py
git commit -m "feat(agent): 内置技能库首批 14 篇（预言家/狼人/女巫/猎人/警长/通用/策略适配）+ 结构守卫 (issue #58)"
```

---

### Task 3: prompt、端口与档案——技能装配进决策；`AgentProfile.skills`

**Files:**
- Modify: `backend/app/agent/prompts.py`（`build_prompt` 约 line 152；`build_wolf_night_prompt` 约 line 233）
- Modify: `backend/app/agent/agent_player.py`（`AgentConfig`、`__init__`、`_system_for`、`act`、`build_agent_port`）
- Modify: `backend/app/agent/profile.py`（`AgentProfile.skills`、`validate_profiles(…, library)`）
- Test: `backend/tests/test_agent_prompts.py`、`test_agent_player.py`、`test_agent_profile.py`

**Interfaces:**
- Consumes: Task 1 全部；Task 2 内置库（端口测试用 tmp 库或 `_sk` 构造，不依赖内置）。
- Produces:
  - `build_prompt(kind, obs, memory_context, *, agent_seed, skills_text: str = "")`、`build_wolf_night_prompt(obs, memory_context, night_private_context, *, agent_seed, skills_text: str = "")`
  - `AgentConfig.skill_budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS`
  - `AgentPlayerPort(..., skills: Sequence[Skill] = ())`、`AgentPlayerPort.last_skills_used: tuple[str, ...]`
  - `AgentProfile.skills: list[str] = []`；`validate_profiles(agents, num_players, library: SkillLibrary | None = None)`
  - `build_agent_port(seat, game_config, profile, library: SkillLibrary | None = None)`

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_agent_prompts.py` 末尾：

```python
def test_skills_text_inserted_before_decision_and_absent_when_empty() -> None:
    obs = _obs("DAY_SPEECH")
    base = build_prompt(DecisionKind.SPEECH, obs, "M", agent_seed=1)
    same = build_prompt(DecisionKind.SPEECH, obs, "M", agent_seed=1, skills_text="")
    assert base == same and "== 技能提示 ==" not in base
    with_sk = build_prompt(DecisionKind.SPEECH, obs, "M", agent_seed=1, skills_text="【技能：x】\n做法")
    assert "== 技能提示 ==\n【技能：x】\n做法" in with_sk
    assert with_sk.index("== 技能提示 ==") < with_sk.index("== 本次决策 ==")

    wolf_obs = _obs("NIGHT_WEREWOLF")
    w0 = build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1)
    assert w0 == build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1, skills_text="")
    w1 = build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1, skills_text="【技能：k】\n刀法")
    assert "== 技能提示 ==\n【技能：k】\n刀法" in w1 and w1.index("== 技能提示 ==") < w1.index("== 本次决策 ==")
```

追加到 `backend/tests/test_agent_player.py` 末尾（复用该文件的 `_obs`、`SECRET`；`ScriptedLLMClient` 记录 `(model, system, user)`）：

```python
def _skill(name: str, roles: set[RoleType], phases: set[str], body: str):
    from pathlib import Path

    from app.agent.skills import Skill

    return Skill(
        name=name,
        description=f"描述 {name}",
        roles=frozenset(roles),
        phases=frozenset(phases),
        priority=0,
        body=body,
        source=Path(f"/x/{name}/SKILL.md"),
    )


_SKILLS = [
    _skill("seer-badge-flow", {RoleType.SEER}, {"DAY_SPEECH"}, "报警徽流。"),
    _skill("wolf-claim-jump", {RoleType.WEREWOLF}, {"DAY_SPEECH"}, "悍跳要自洽。"),
    _skill("wolf-team-kill", {RoleType.WEREWOLF}, {"NIGHT_WEREWOLF"}, "优先刀预言家。"),
]


def _skilled_port(script, *, seat: int = 0) -> tuple[AgentPlayerPort, ScriptedLLMClient]:
    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=seat,
        game_config=build_preset("std_9_kill_side"),
        agent_config=AgentConfig(model="scripted"),
        client=client,
        skills=_SKILLS,
    )
    return port, client


async def test_skills_index_in_system_and_bodies_assembled_by_role_phase() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is WolfDeliberation:
            return WolfDeliberation(analysis="a", proposed_target=3)
        return SpeechDecision(reasoning="r", content="c")

    # 狼：夜间私有调用只装 NIGHT_WEREWOLF 技能
    port, client = _skilled_port(script)
    await port.act(_obs("NIGHT_WEREWOLF"), time.time() + 60)
    _m, system, user = client.calls[-1]
    assert "== 你的技能 ==" in system and "- wolf-team-kill：描述 wolf-team-kill" in system
    assert "优先刀预言家" in user and "悍跳要自洽" not in user and "报警徽流" not in user
    assert port.last_skills_used == ("wolf-team-kill",)
    # 狼：白天公开调用只装白天狼技能
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    _m, _s, user = client.calls[-1]
    assert "悍跳要自洽" in user and "优先刀预言家" not in user
    assert port.last_skills_used == ("wolf-claim-jump",)
    # 预言家：白天只装 seer 技能
    port2, client2 = _skilled_port(script)
    await port2.act(_obs("DAY_SPEECH", role=RoleType.SEER, private={}), time.time() + 60)
    _m, _s, user2 = client2.calls[-1]
    assert "报警徽流" in user2 and "悍跳" not in user2 and port2.last_skills_used == ("seer-badge-flow",)


async def test_no_skills_means_no_skill_sections() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        return SpeechDecision(reasoning="r", content="c")

    port, client = _port(script)
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    _m, system, user = client.calls[-1]
    assert "你的技能" not in system and "技能提示" not in user and port.last_skills_used == ()


async def test_skill_budget_limits_assembly() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        return SpeechDecision(reasoning="r", content="c")

    big = _skill("big", {RoleType.WEREWOLF}, {"DAY_SPEECH"}, "字" * 500)
    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side"),
        agent_config=AgentConfig(model="scripted", skill_budget_chars=100),
        client=client,
        skills=[big],
    )
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    assert port.last_skills_used == () and "技能提示" not in client.calls[-1][2]
```

追加到 `backend/tests/test_agent_profile.py` 末尾：

```python
def test_profile_skills_field_and_validation_against_library(tmp_path) -> None:
    from app.agent.skills import SkillLibrary

    assert AgentProfile(model="m").skills == []
    p = AgentProfile(model="m", skills=["a", "*"])
    d = tmp_path / "a"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: a\ndescription: d\n---\n正文\n", encoding="utf-8")
    lib = SkillLibrary.load([tmp_path])
    validate_profiles({"0": p}, num_players=9, library=lib)  # 通过
    validate_profiles({"0": AgentProfile(model="m", skills=["zzz"])}, num_players=9)  # 无库不校验技能
    with pytest.raises(ValueError, match="zzz"):
        validate_profiles({"0": AgentProfile(model="m", skills=["zzz"])}, num_players=9, library=lib)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py tests/test_agent_profile.py -q`
Expected: 新用例 FAIL（`skills_text` 未知参数 / `AgentPlayerPort` 无 `skills` 参数 / `AgentProfile` 拒绝 `skills` 键）

- [ ] **Step 3: 实现**

`app/agent/prompts.py`：
- `build_prompt(..., *, agent_seed: int, skills_text: str = "")`：返回串在 `f"== 本次决策 ==\n…"` 之前插入 `skills_block`，其中

```python
    skills_block = f"== 技能提示 ==\n{skills_text}\n\n" if skills_text else ""
```

（即 `f"== 局势 ==…\n\n== 你的记忆 ==…\n\n{skills_block}== 本次决策 ==…"`。）
- `build_wolf_night_prompt(..., *, agent_seed: int, skills_text: str = "")` 同样在 `== 本次决策 ==` 之前插入 `skills_block`（放在「狼队私有」段之后）。

`app/agent/agent_player.py`：
- import：`import logging`；`from collections.abc import Sequence`；`from app.agent.skills import DEFAULT_SKILL_BUDGET_CHARS, Skill, assemble_skills, select_skills, skills_index_text`（`skills.py` 不反向 import 本模块，无环）；`if TYPE_CHECKING: from app.agent.skills import SkillLibrary`。`logger = logging.getLogger(__name__)`。
- `AgentConfig` 加 `skill_budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS  # 每次决策装配技能正文的字符预算（issue #58）`。
- `__init__(..., memory=None, skills: Sequence[Skill] = ())`：`self._skills = tuple(skills)`；`self.last_skills_used: tuple[str, ...] = ()`。
- `_system_for`：生成静态段后，若 `self._skills`：追加 `"\n== 你的技能 ==\n" + skills_index_text(self._skills)`。
- `act`：在装配 prompt 之前

```python
        selected = select_skills(self._skills, observation.my_role, observation.phase)
        skills_text, used = assemble_skills(selected, self._cfg.skill_budget_chars)
        self.last_skills_used = used
        if used:
            logger.info("seat=%d phase=%s skills=%s", self._seat, observation.phase, ",".join(used))
```

两个装配调用都传 `skills_text=skills_text`。
- `build_agent_port(seat, game_config, profile, library: SkillLibrary | None = None)`：`skills = library.resolve(profile.skills) if (library is not None and profile.skills) else ()`；传 `skills=skills`。（`library` 为 `None` 而 `profile.skills` 非空 → 用 `default_library()`，函数内 import。）

`app/agent/profile.py`：
- `AgentProfile` 加 `skills: list[str] = Field(default_factory=list)  # 技能名或 "*"（issue #58）`。
- `validate_profiles(agents, num_players, library: SkillLibrary | None = None)`：键校验后，若 `library is not None`：对每个档案 `library.resolve(profile.skills)`，`SkillError` → `ValueError(str(exc))`。（`from app.agent.skills import SkillError`；类型注解经 `TYPE_CHECKING` 或直接 import——`skills.py` 只依赖 engine，直接 import 安全。）

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py tests/test_agent_profile.py tests/test_agent_integration.py tests/test_acceptance_m25.py -q`
Expected: 全部 PASS

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿。注意 `tests/test_api_lobby.py::test_create_legacy_ai_model_echoes_star` 断言回显 dict 的**精确相等**——`AgentProfile` 多了 `skills` 字段后该断言需加 `"skills": []`（本任务顺手改，属契约随字段增量的必然变化）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts.py backend/app/agent/agent_player.py backend/app/agent/profile.py backend/tests/test_agent_prompts.py backend/tests/test_agent_player.py backend/tests/test_agent_profile.py backend/tests/test_api_lobby.py
git commit -m "feat(agent): 技能按角色/阶段装配进 prompt；AgentProfile.skills 与库校验 (issue #58)"
```

---

### Task 4: registry 与 API——`SkillLibrary` 注入、`create_app(skills_dir)`、环境变量

**Files:**
- Modify: `backend/app/runtime/registry.py`（`__init__`、`create`、`_build_agent_port`）
- Modify: `backend/app/main.py`（`create_app(skills_dir=…)`、`AGENTHOWL_SKILLS_DIR`）
- Test: `backend/tests/test_registry.py`、`backend/tests/test_api_lobby.py`

**Interfaces:**
- Consumes: Task 1 `SkillLibrary`、`default_library`、`BUILTIN_SKILLS_DIR`；Task 3 `validate_profiles(library=)`、`build_agent_port(library=)`。
- Produces: `GameRegistry(store, timeouts=None, agent_port_factory=None, skill_library: SkillLibrary | None = None)`；`create_app(..., skills_dir: Path | None = None)`；`app.state.games` 持库。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registry.py` 末尾：

```python
def test_create_validates_skills_against_library(tmp_path) -> None:
    from app.agent.profile import AgentProfile
    from app.agent.skills import SkillLibrary
    from app.store.event_store import InMemoryEventStore

    d = tmp_path / "custom-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: custom-skill\ndescription: d\n---\n正文\n", encoding="utf-8")
    reg = GameRegistry(store=InMemoryEventStore(), skill_library=SkillLibrary.load([tmp_path]))
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    handle = reg.create(cfg, allow_spectators=False, agents={"*": AgentProfile(model="m", skills=["custom-skill"])})
    assert handle.profile_for(0) is not None
    with pytest.raises(ValueError, match="nope"):
        reg.create(cfg, allow_spectators=False, agents={"*": AgentProfile(model="m", skills=["nope"])})


def test_create_without_library_uses_builtin(tmp_path) -> None:
    from app.agent.profile import AgentProfile

    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    reg.create(cfg, allow_spectators=False, agents={"*": AgentProfile(model="m", skills=["vote-discipline"])})
    with pytest.raises(ValueError, match="no-such-skill"):
        reg.create(cfg, allow_spectators=False, agents={"*": AgentProfile(model="m", skills=["no-such-skill"])})
```

追加到 `backend/tests/test_api_lobby.py` 末尾：

```python
def test_create_agents_with_skills_echo_and_unknown_400(client: TestClient) -> None:
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "skills": ["vote-discipline", "logic-chain"]}}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["agents"]["*"]["skills"] == ["vote-discipline", "logic-chain"]
    r = client.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "skills": ["nope"]}}},
    )
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_create_app_with_external_skills_dir(tmp_path) -> None:
    from app.main import create_app
    from app.runtime.game_runner import RunnerTimeouts
    from app.store.event_store import InMemoryEventStore

    d = tmp_path / "house-rule"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: house-rule\ndescription: d\n---\n正文\n", encoding="utf-8")
    app = create_app(store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0), skills_dir=tmp_path)
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/games",
            json={"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "skills": ["house-rule", "vote-discipline"]}}},
        )
        assert r.status_code == 200, r.text  # 外部 + 内置都可用
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_registry.py tests/test_api_lobby.py -q`
Expected: 新用例 FAIL（`GameRegistry` 无 `skill_library` / `create_app` 无 `skills_dir` / 未知技能未报 400）

- [ ] **Step 3: 实现**

`app/runtime/registry.py`：
- import `from app.agent.skills import SkillLibrary, default_library`（`skills.py` 不 import agent_player，惰性纪律不破）。
- `__init__(..., agent_port_factory=None, skill_library: SkillLibrary | None = None)`：`self._skill_library = skill_library`；加 property

```python
    @property
    def skill_library(self) -> SkillLibrary:
        return self._skill_library if self._skill_library is not None else default_library()
```

- `create`：`validate_profiles(resolved, config.num_players, self.skill_library)`。
- `_build_agent_port`：`build_agent_port(seat, handle.config, profile, self.skill_library)`。

`app/main.py`：
- import `import os`、`from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary`。
- `create_app(..., agent_port_factory=None, skills_dir: Path | None = None)`：

```python
    dirs = [BUILTIN_SKILLS_DIR] + ([skills_dir] if skills_dir is not None else [])
    skill_library = SkillLibrary.load([d for d in dirs if d.is_dir()]) if any(d.is_dir() for d in dirs) else SkillLibrary.empty()
```

传 `skill_library=skill_library` 给 `GameRegistry`。模块末尾 `app = create_app()` 改为

```python
_env_skills = os.environ.get("AGENTHOWL_SKILLS_DIR")
app = create_app(skills_dir=Path(_env_skills) if _env_skills else None)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `uv run pytest tests/test_registry.py tests/test_api_lobby.py tests/test_agent_profile.py tests/test_agent_integration.py -q`
Expected: 全部 PASS（含 `test_importing_registry_does_not_load_litellm`——`skills.py` 只 import engine + yaml）

Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/registry.py backend/app/main.py backend/tests/test_registry.py backend/tests/test_api_lobby.py
git commit -m "feat(runtime,api): registry 注入技能库校验档案技能；create_app(skills_dir) 与 AGENTHOWL_SKILLS_DIR (issue #58)"
```

---

### Task 5: CLI `--skills-dir`、档案表技能列、Makefile / README / PRD、A/B 冒烟

**Files:**
- Modify: `backend/app/cli/play.py`（`_wire_game`、`main`、`run_watch`）、`backend/app/cli/play_human.py`（`run_play`）、`backend/app/cli/render.py`（`render_agent_roster`）
- Modify: `Makefile`、`README.md`、`docs/specs/requirements.md`（§4.4 或 §5.2 附近补一段「技能包」）
- Modify: `backend/tests/test_cli_play_watch.py`、`test_cli_render.py`、`test_agent_bench.py`

**Interfaces:**
- Consumes: Task 1 `SkillLibrary`、`BUILTIN_SKILLS_DIR`、`default_library`；Task 3 `build_agent_port(library=)`、`validate_profiles(library=)`。
- Produces: `_wire_game(config, *, human_seat=None, agents=None, library: SkillLibrary | None = None)`；`run_watch(..., library=None)`、`run_play(..., library=None)`；CLI `--skills-dir PATH`；`render_agent_roster` 技能列。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_cli_play_watch.py` 末尾：

```python
def test_wire_game_passes_skills_to_agent_ports(tmp_path) -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.profile import AgentProfile
    from app.agent.skills import SkillLibrary

    d = tmp_path / "ext-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: ext-skill\ndescription: d\n---\n外部正文\n", encoding="utf-8")
    lib = SkillLibrary.load([tmp_path])
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _r, _c, ports = _wire_game(config, agents={"*": AgentProfile(model="m", skills=["ext-skill"])}, library=lib)
    p = ports[0]
    assert isinstance(p, AgentPlayerPort) and [s.name for s in p._skills] == ["ext-skill"]


def test_main_rejects_unknown_skill_and_accepts_skills_dir(tmp_path, capsys) -> None:
    from app.cli.play import main

    d = tmp_path / "skills" / "house"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: house\ndescription: d\n---\n正文\n", encoding="utf-8")
    agents = tmp_path / "agents.yaml"
    agents.write_text('seats:\n  "*": {model: ollama/a, skills: [house]}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as e:  # 未指定 --skills-dir → house 未知
        main(["--agents", str(agents)])
    assert e.value.code == 2 and "house" in capsys.readouterr().err
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit) as e:
        main(["--agents", str(agents), "--skills-dir", str(missing)])
    assert e.value.code == 2 and "目录" in capsys.readouterr().err
```

`backend/tests/test_cli_render.py::test_render_agent_roster` 追加断言（在现有断言之后）：

```python
    with_skills = render_agent_roster(
        {"0": AgentProfile(model="m", skills=["logic-chain", "vote-discipline"])}, num_players=1, human_seat=None
    )
    assert "技能 logic-chain,vote-discipline" in with_skills
    assert "技能" not in render_agent_roster({"0": AgentProfile(model="m")}, num_players=1, human_seat=None)
```

`backend/tests/test_agent_bench.py` 末尾追加（沿用文件里既有的 env 门控 `SMOKE_MODEL`、`pytest.mark.smoke` 与 skip 逻辑；照既有 bench 用例的写法驱动一局）：

```python
@pytest.mark.smoke
async def test_wolf_team_kill_skill_ab_smoke() -> None:
    """A/B 冒烟：wolf-team-kill 开/关各一局，打印狼队空刀率（不断言方向）。"""
    if not SMOKE_MODEL:
        pytest.skip("AGENTHOWL_SMOKE_MODEL 未设置")
    from app.agent.profile import AgentProfile
    from app.engine.events import EventType, WolfKillDecidedPayload

    rates: dict[str, float] = {}
    for label, skills in (("off", []), ("on", ["wolf-team-kill"])):
        registry = GameRegistry(InMemoryEventStore(), TIMEOUTS)
        config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
        handle = registry.create(config, allow_spectators=False, agents={"*": AgentProfile(model=SMOKE_MODEL, skills=skills)})
        registry.start(handle, fill_with_bots=True)
        assert handle.task is not None
        await asyncio.wait_for(handle.task, timeout=1800)
        decided = [e for e in registry.store.load_events(handle.game_id) if e.type == EventType.WOLF_KILL_DECIDED]
        empties = sum(1 for e in decided if isinstance(e.payload, WolfKillDecidedPayload) and e.payload.target is None)
        rates[label] = empties / max(1, len(decided))
    print(f"wolf-team-kill A/B 空刀率: {rates}")
```

（`registry.store.load_events` / `TIMEOUTS` / `GameRegistry` / `InMemoryEventStore` 等名字按该文件既有 import 与 store API 核对；若 store 读事件的方法名不同，用该文件里既有 bench 已用的读法。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_play_watch.py tests/test_cli_render.py -q`
Expected: 新用例 FAIL（`_wire_game` 无 `library` 参数；`main` 不认 `--skills-dir`；档案表无技能列）

- [ ] **Step 3: 实现**

`app/cli/render.py` `render_agent_roster`：在 `parts.append(f"T={p.temperature}")` 之后加

```python
        if p.skills:
            parts.append("技能 " + ",".join(p.skills))
```

`app/cli/play.py`：
- import `from app.agent.skills import BUILTIN_SKILLS_DIR, SkillError, SkillLibrary, default_library`。
- `_wire_game(config, *, human_seat=None, agents=None, library: SkillLibrary | None = None)`：`build_agent_port(seat, config, profile, library)`。
- `run_watch(..., agents=None, library: SkillLibrary | None = None, read_line=…)` 与 `run_play(..., agents=None, library=None, …)`：透传给 `_wire_game`。
- `main`：`parser.add_argument("--skills-dir", default=None, help="外部技能目录（SKILL.md 子目录；同名覆盖内置）")`；解析后：

```python
    try:
        library = (
            SkillLibrary.load([BUILTIN_SKILLS_DIR, Path(args.skills_dir)])
            if args.skills_dir
            else default_library()
        )
        agents = merge_profiles(args.agents, legacy)
        validate_profiles(agents, config.num_players, library)
    except (ValueError, SkillError) as exc:  # SkillError 是 ValueError 子类，列出以示意图
        parser.error(str(exc))
```

（`from pathlib import Path`；`BUILTIN_SKILLS_DIR` 不存在时 `SkillLibrary.load` 会报错——内置目录随代码发布、恒存在，测试守卫。）`run_watch(...)` / `run_play(...)` 传 `library=library`。

`Makefile`：变量 `SKILLS_DIR ?=     # 外部技能目录（SKILL.md 子目录；同名覆盖内置）`；`_AIFLAGS` 加 `$(if $(SKILLS_DIR),--skills-dir $(SKILLS_DIR),)`；`watch`/`play` help 补 `SKILLS_DIR=`。

`README.md`：「每座位 Agent 档案」一节的 YAML 样例给某座位加 `skills: [seer-badge-flow, logic-chain]`，并新增小节「技能包 / Skill packs」：内置目录 `backend/skills/`、`SKILL.md` 格式（frontmatter 示例）、`"*"` 含义、`--skills-dir` / `SKILLS_DIR=` / `AGENTHOWL_SKILLS_DIR`、渐进装配规则（按角色阶段、优先级、预算）、列出 14 篇名字与一句话说明。

`docs/specs/requirements.md` §4.4.2（三段式 prompt）末尾补一段：「**技能包**：`AgentProfile.skills` 指定的 `SKILL.md` 技巧按 `(角色, 阶段)` 装配到指令段之前（`== 技能提示 ==`），系统 prompt 只列名称与描述；格式兼容 Agent Skills 规范，自定义字段在 `metadata`。」；§5.2 `agents` 说明补 `skills` 字段。

- [ ] **Step 4: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_cli_play_watch.py tests/test_cli_render.py tests/test_cli_play_human.py tests/test_agent_bench.py -q`
Expected: 全部 PASS（bench 用例 skip）

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全量（含 E2E）全绿；lint/type 全过

- [ ] **Step 5: 真机看一眼**

Run（`backend/`）：

```bash
printf 'seats:\n  "0": {name: 老张, model: ollama/a, skills: [seer-badge-flow, logic-chain]}\n  "*": {model: ollama/b, skills: ["*"]}\n' > /tmp/agents-skills.yaml
PYTHONUNBUFFERED=1 uv run python -m app.cli.play --preset std_9_kill_side --seed 3 --view gm --delay 0 --no-color --agents /tmp/agents-skills.yaml 2>/dev/null | head -3
```

Expected: `0号 老张 · ollama/a · T=0.3 · 技能 seer-badge-flow,logic-chain` 与 `1号 Bot1 · ollama/b · T=0.3 · 技能 *`（进程随后因模型不可达而空转，`head` 关管道后退出）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli/ backend/tests/test_cli_play_watch.py backend/tests/test_cli_render.py backend/tests/test_agent_bench.py Makefile README.md docs/specs/requirements.md
git commit -m "feat(cli): --skills-dir 外部技能目录、档案表技能列；Makefile/README/PRD；A/B 冒烟 (issue #58)"
```

---

## Self-Review

- **Spec 覆盖**：§2 格式/校验→T1（`parse_skill_md`）+ T2（内置文件）；§3 模块→T1；§4 档案与装配链→T3；§5 入口 registry/API→T4、CLI/Makefile→T5；§6 首批 14 篇→T2；§7 测试逐条：`test_agent_skills`→T1、`test_builtin_skills`→T2、prompts/player/profile→T3、`test_api_lobby`/`test_registry`→T4、CLI/render/bench→T5；§8 不在范围无任务。
- **占位符扫描**：T5 bench 用例对 store 读事件方法名给出「按文件既有写法核对」的明确指令；无 TBD/TODO。
- **类型一致性**：`Skill` 字段、`SkillLibrary.load/resolve/get/names`、`select_skills(skills, role, phase)`、`assemble_skills(skills, budget_chars) -> (str, tuple[str,...])`、`skills_index_text`、`skills_text=""` 关键字、`AgentPlayerPort(skills=)`、`last_skills_used`、`AgentConfig.skill_budget_chars`、`validate_profiles(agents, num_players, library=None)`、`build_agent_port(seat, config, profile, library=None)`、`GameRegistry(skill_library=)`、`create_app(skills_dir=)`、`_wire_game(library=)` 在各任务间一致。
- **惰性加载**：`skills.py` 只 import engine + yaml；registry/main/cli 直接 import `skills.py` 安全；`agent_player.py` 模块级 import `skills.py` 安全（方向为 agent_player → skills）。
- **契约变更连带**：`AgentProfile` 新增 `skills` 字段 → `test_api_lobby.py::test_create_legacy_ai_model_echoes_star` 的精确相等断言需补 `"skills": []`（T3 Step 4 已注明）。
