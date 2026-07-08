"""狼刀决策规则开关（issue #3）：配置、三规则语义与集成。"""

from app.engine import rng
from app.engine.config import Faction, GameConfig, RoleType, WolfKillRule, build_preset
from app.engine.phases import Phase
from app.engine.state import GameState, Player


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


def _wolf_state(proposals: dict[int, int | None], rule: WolfKillRule, seed: int = 1) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": seed, "wolf_kill_rule": rule}
    )
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i < 3 else RoleType.VILLAGER,
            faction=Faction.WOLF if i < 3 else Faction.GOOD,
        )
        for i in range(9)
    )
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.NIGHT_WEREWOLF,
        round=1,
        players=players,
        wolf_proposals=proposals,
    )


def test_unanimous_agree_kills_disagree_or_skip_no_kill() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.UNANIMOUS_OR_NO_KILL
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 5}, rule)) == 5
    assert _wolf_consensus(_wolf_state({0: 5, 1: 6, 2: 5}, rule)) is None
    assert _wolf_consensus(_wolf_state({0: 5, 1: None, 2: 5}, rule)) is None


def test_majority_plurality_wins_tie_no_kill() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.MAJORITY
    # 3-1（4 狼场景不必真实：直接构造 4 票提案）
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 5, 3: 6}, rule)) == 5
    # 2-2 并列 -> 空刀
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 6, 3: 6}, rule)) is None
    # 空刀票占多 -> 空刀
    assert _wolf_consensus(_wolf_state({0: None, 1: None, 2: 5}, rule)) is None
    # 2-1-1 -> 相对多数胜
    assert _wolf_consensus(_wolf_state({0: 5, 1: 5, 2: 6, 3: 7}, rule)) == 5
    # 目标票与空刀票并列 -> 空刀
    assert _wolf_consensus(_wolf_state({0: 5, 1: None}, rule)) is None


def test_random_proposal_weighted_and_deterministic() -> None:
    from app.engine.engine import _wolf_consensus

    rule = WolfKillRule.RANDOM_PROPOSAL
    st = _wolf_state({0: 4, 1: 4, 2: 7}, rule, seed=42)
    # 池 = sorted([4, 4, 7])；与实现同公式独立计算期望值，钉死派生契约
    pool = [4, 4, 7]
    idx = rng.derive_int(seed=42, purpose="wolf_kill", seq=st.state_version, modulo=3)
    assert _wolf_consensus(st) == pool[idx]
    # 同 seed 可复现
    assert _wolf_consensus(st) == _wolf_consensus(st)
    # 全 skip -> 空刀
    assert _wolf_consensus(_wolf_state({0: None, 1: None, 2: None}, rule, seed=42)) is None


def test_nondefault_rules_full_games_terminate() -> None:
    from app.cli.bot import run_game

    for rule in (WolfKillRule.MAJORITY, WolfKillRule.RANDOM_PROPOSAL):
        for seed in (3, 11):
            cfg = build_preset("std_9_kill_side").model_copy(
                update={"seed": seed, "wolf_kill_rule": rule}
            )
            final, _events = run_game(cfg, game_id=f"wk-{rule.value}-{seed}")
            assert final.phase == Phase.GAME_OVER
