"""随机抽取去相关（issue #12）：同池不同 state_version → 抽取结果可不同，且恒可重放。"""

from app.engine import rng
from app.engine.config import Faction, RoleType, TieRule, WolfKillRule, build_preset
from app.engine.events import EventType, PlayerExiledPayload
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _wolf_state(state_version: int) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": 42, "wolf_kill_rule": WolfKillRule.RANDOM_PROPOSAL}
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
        wolf_proposals={0: 4, 1: 6, 2: 7},  # 池 [4, 6, 7]，无重复值：下标不同 ⇒ 座位不同
        state_version=state_version,
    )


def test_random_proposal_decorrelates_across_state_versions() -> None:
    from app.engine.engine import _wolf_consensus

    pool = [4, 6, 7]
    # 独立公式预算各 state_version 的下标，找一对不同者——证明差异非巧合而是派生契约
    picks = {sv: rng.derive_int(seed=42, purpose="wolf_kill", seq=sv, modulo=3) for sv in range(20)}
    sv_b = next(sv for sv in range(1, 20) if picks[sv] != picks[0])
    assert _wolf_consensus(_wolf_state(0)) == pool[picks[0]]
    assert _wolf_consensus(_wolf_state(sv_b)) == pool[picks[sv_b]]
    assert pool[picks[0]] != pool[picks[sv_b]]
    # 同状态重复调用恒同（可重放）
    assert _wolf_consensus(_wolf_state(sv_b)) == _wolf_consensus(_wolf_state(sv_b))


def _tie_state(state_version: int) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 9, "seed": 42, "tie_rule": TieRule.PK_THEN_RANDOM}
    )
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(9)
    )
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE_PK,
        round=1,
        players=players,
        votes={0: 3, 1: 3, 2: 4, 5: 4},  # 3、4 各两票：PK 轮再平票 → 随机放逐
        tie_round=1,
        state_version=state_version,
    )


def _exiled_of(state_version: int) -> int:
    from app.engine.engine import _tally_and_continue

    _, events = _tally_and_continue(_tie_state(state_version))
    exiled = [e for e in events if e.type == EventType.PLAYER_EXILED]
    assert len(exiled) == 1
    p = exiled[0].payload
    assert isinstance(p, PlayerExiledPayload)
    assert p.seat is not None  # mypy 收窄：随机放逐分支必有座位
    assert p.seat in (3, 4)
    return p.seat


def test_pk_then_random_decorrelates_across_state_versions() -> None:
    # 同一平票池、只有 state_version 不同：两个候选都应被抽中过（不再整局恒定同一下标）
    picks = {sv: _exiled_of(sv) for sv in range(20)}
    assert set(picks.values()) == {3, 4}
    # 同状态重复调用恒同（可重放）
    assert _exiled_of(0) == _exiled_of(0)
