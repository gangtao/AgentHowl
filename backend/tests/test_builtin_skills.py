"""内置技能库守卫（issue #58）：14 篇齐全、结构合规、正文长度与措辞约束。"""

from app.agent.skills import BUILTIN_SKILLS_DIR, SkillLibrary, default_library
from app.engine.config import RoleType

EXPECTED = {
    "seer-badge-flow": ({RoleType.SEER}, {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH"}),
    "seer-vs-claim-jump": (
        {RoleType.SEER},
        {"SHERIFF_ELECTION", "SHERIFF_PK", "DAY_SPEECH", "VOTE"},
    ),
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
        assert "触发" in s.body and "做法" in s.body and ("风险" in s.body or "反例" in s.body), (
            name
        )


def test_wolf_skills_do_not_instruct_leaking_night_plans() -> None:
    lib = default_library()
    for name in ("wolf-claim-jump", "wolf-counter-hook", "wolf-charge", "wolf-lay-low"):
        body = lib.get(name).body
        assert "不要" in body or "不得" in body or "避免" in body, name  # 至少有一条禁止性提醒
        assert "公开" in body or "发言" in body, name


def test_default_library_is_cached_singleton() -> None:
    assert default_library() is default_library()
    assert len(default_library()) == len(EXPECTED)
