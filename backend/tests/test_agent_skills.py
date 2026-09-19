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
    meta_lines = "".join(f'  {k}: "{v}"\n' for k, v in meta.items())
    text = (
        f"---\nname: {name}\ndescription: 描述 {name}\n"
        + (f"metadata:\n{meta_lines}" if meta_lines else "")
        + f"---\n{body}\n"
    )
    p = d / "SKILL.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_minimal_and_metadata(tmp_path: Path) -> None:
    p = _write(
        tmp_path, "seer-x", body="做法一。", roles="SEER", phases="DAY_SPEECH VOTE", priority="5"
    )
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
        (
            "bad-role",
            '---\nname: bad-role\ndescription: d\nmetadata:\n  roles: "KING"\n---\nb\n',
            "roles",
        ),
        (
            "bad-phase",
            '---\nname: bad-phase\ndescription: d\nmetadata:\n  phases: "NOON"\n---\nb\n',
            "phases",
        ),
        (
            "bad-prio",
            '---\nname: bad-prio\ndescription: d\nmetadata:\n  priority: "high"\n---\nb\n',
            "priority",
        ),
        (
            "non-str-meta",
            "---\nname: non-str-meta\ndescription: d\nmetadata:\n  priority: 3\n---\nb\n",
            "字符串",
        ),
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


def _sk(
    name: str,
    roles: set[RoleType] | None = None,
    phases: set[str] | None = None,
    prio: int = 0,
    body: str = "b",
) -> Skill:
    if roles is None:
        roles = set()
    if phases is None:
        phases = set()
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
    assert [s.name for s in select_skills(skills, RoleType.WEREWOLF, "NIGHT_WEREWOLF")] == [
        "wolf-night",
        "any-any",
    ]
    assert [s.name for s in select_skills(skills, RoleType.SEER, "DAY_SPEECH")] == [
        "any-day",
        "seer-day",
        "any-any",
    ]
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
