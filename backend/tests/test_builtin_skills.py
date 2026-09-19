"""内置技能库守卫（issue #58）：14 篇齐全、结构合规、正文长度与措辞约束。"""

import re

from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary, default_library
from app.engine.config import RoleType

EXPECTED = {
    "seer-badge-flow": (
        {RoleType.SEER},
        {"NIGHT_SEER", "SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH"},
        10,
    ),
    "seer-vs-claim-jump": (
        {RoleType.SEER},
        {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH", "VOTE"},
        10,
    ),
    "wolf-claim-jump": (
        {RoleType.WEREWOLF},
        {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH"},
        8,
    ),
    "wolf-counter-hook": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}, 6),
    "wolf-charge": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}, 6),
    "wolf-lay-low": ({RoleType.WEREWOLF}, {"DAY_SPEECH", "VOTE"}, 4),
    "wolf-team-kill": ({RoleType.WEREWOLF}, {"NIGHT_WEREWOLF"}, 9),
    "witch-potion-timing": ({RoleType.WITCH}, {"NIGHT_WITCH", "DAY_SPEECH"}, 8),
    "hunter-shot-target": ({RoleType.HUNTER}, {"HUNTER_SHOOT", "DAY_SPEECH"}, 8),
    "sheriff-herding": (set(), {"SHERIFF_ELECTION", "DAY_SPEECH", "VOTE", "LAST_WORDS"}, 5),
    "vote-discipline": (set(), {"VOTE", "VOTE_PK"}, 5),
    "logic-chain": (set(), {"DAY_SPEECH", "VOTE"}, 7),
    "side-taking": (set(), {"DAY_SPEECH", "VOTE", "SHERIFF_ELECTION"}, 7),
    "strategy-adaptation": (set(), {"DAY_SPEECH", "VOTE"}, 3),
}
FORBIDDEN = ("你知道", "上帝视角", "无视规则", "绕过", "作弊")

# 禁止性提醒须落在同一句（逗号可以，句号/分号断句），且明确指向夜间私谋/队友身份，
# 而不是宽泛的「不要……」（终审 F6 收紧）。
_LEAK_GUARD_RE = re.compile(r"(不要|不得|避免)[^。；]*(夜间|夜晚|私下|队友身份)")


def test_builtin_library_complete_and_wellformed() -> None:
    lib = SkillLibrary.load([BUILTIN_SKILLS_DIR])
    assert set(lib.names()) == set(EXPECTED)
    for name, (roles, phases, priority) in EXPECTED.items():
        s = lib.get(name)
        assert s.roles == frozenset(roles), name
        assert s.phases == frozenset(phases), name
        assert s.priority == priority, name
        assert 80 <= len(s.body) <= 600, f"{name}: 正文 {len(s.body)} 字"
        assert all(w not in s.body for w in FORBIDDEN), name
        assert "触发" in s.body and "做法" in s.body and ("风险" in s.body or "反例" in s.body), (
            name
        )


def test_wolf_skills_do_not_instruct_leaking_night_plans() -> None:
    lib = default_library()
    for name in ("wolf-claim-jump", "wolf-counter-hook", "wolf-charge", "wolf-lay-low"):
        body = lib.get(name).body
        assert _LEAK_GUARD_RE.search(body), name  # 需有一句「不要/不得/避免…夜间/私下/队友身份」


def test_default_library_is_cached_singleton() -> None:
    assert default_library() is default_library()
    assert len(default_library()) == len(EXPECTED)
