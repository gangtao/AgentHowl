"""狼刀决策规则开关（issue #3）：配置、三规则语义与集成。"""

from app.engine.config import GameConfig, WolfKillRule, build_preset


def test_wolf_kill_rule_enum_members() -> None:
    assert WolfKillRule.UNANIMOUS_OR_NO_KILL.value == "UNANIMOUS_OR_NO_KILL"
    assert WolfKillRule.MAJORITY.value == "MAJORITY"
    assert WolfKillRule.RANDOM_PROPOSAL.value == "RANDOM_PROPOSAL"


def test_default_is_unanimous_and_presets_inherit() -> None:
    assert GameConfig(config_id="x").wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
    for name in (
        "std_12_yn_hunter_idiot",
        "std_12_yn_hunter_guard",
        "std_9_kill_side",
        "std_9_kill_all",
    ):
        assert build_preset(name).wolf_kill_rule == WolfKillRule.UNANIMOUS_OR_NO_KILL
