"""警徽流（issue #7）：结构校验、事实记录与公开暴露。只验结构，不验真实性。"""

from app.engine.actions import RejectedReason, Speak
from app.engine.config import Faction, RoleType, SheriffRule, build_preset
from app.engine.engine import step
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, dead: tuple[int, ...] = ()) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i == 0 else RoleType.VILLAGER,
            faction=Faction.WOLF if i == 0 else Faction.GOOD,
            alive=(i not in dead),
        )
        for i in range(n)
    )


def _pk_state(n: int = 6, dead: tuple[int, ...] = (), **kw: object) -> GameState:
    """SHERIFF_PK 发言回合：候选 (1,2)，轮到 1 发言。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_PK,
        "round": 1,
        "players": _players(n, dead=dead),
        "sheriff_candidates": (1, 2),
        "speech_order": (1, 2),
        "speech_idx": 0,
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_valid_claim_accepted_and_recorded() -> None:
    st = _pk_state()
    res = step(st, Speak(actor_seat=1, content="我是预言家", badge_flow=(3, 4)))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {1: (3, 4)}


def test_claim_overwritten_by_latest() -> None:
    st = _pk_state(badge_flow_claims={1: (5,)})
    res = step(st, Speak(actor_seat=1, content="改口", badge_flow=(3,)))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {1: (3,)}


def test_claim_rejected_outside_sheriff_pk() -> None:
    # DAY_SPEECH 携带非空声明 -> 拒
    st = _pk_state(phase=Phase.DAY_SPEECH, speech_order=(1, 2, 3), speech_idx=0)
    res = step(st, Speak(actor_seat=1, content="x", badge_flow=(3,)))
    assert res.rejection == RejectedReason.BADGE_FLOW_INVALID
    # 放逐 VOTE_PK 发言回合亦拒
    st2 = _pk_state(phase=Phase.VOTE_PK, vote_candidates=(1, 2), tie_round=1)
    res2 = step(st2, Speak(actor_seat=1, content="x", badge_flow=(3,)))
    assert res2.rejection == RejectedReason.BADGE_FLOW_INVALID


def test_structural_rejection_matrix() -> None:
    # 配置关闭
    cfg_off = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 6, "seed": 1, "sheriff": SheriffRule(badge_flow_enabled=False)}
    )
    st = _pk_state(config=cfg_off)
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 超长（默认 max=2）
    st = _pk_state()
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3, 4, 5))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 座位越界
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(99,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 座位已死
    st_dead = _pk_state(dead=(4,))
    assert (
        step(st_dead, Speak(actor_seat=1, content="x", badge_flow=(4,))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )
    # 重复座位
    assert (
        step(st, Speak(actor_seat=1, content="x", badge_flow=(3, 3))).rejection
        == RejectedReason.BADGE_FLOW_INVALID
    )


def test_empty_claim_unchanged() -> None:
    st = _pk_state()
    res = step(st, Speak(actor_seat=1, content="普通发言"))
    assert res.rejection is None
    assert res.state.badge_flow_claims == {}
