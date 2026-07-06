from app.engine.actions import NightAction, NightActionType
from app.engine.config import RoleType, build_preset
from app.engine.engine import step
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player, player_at


def _hunter_at_shoot(cause_poison: bool) -> GameState:
    """构造一个「猎人刚出局、待开枪」的最小态。"""
    from app.engine.config import Faction

    roles = [
        RoleType.HUNTER,
        RoleType.WEREWOLF,
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.SEER,
    ]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0),  # 猎人已死
            hunter_can_shoot=not cause_poison,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.HUNTER_SHOOT,
        round=1,
        players=players,
        pending_hunter=0,
        resume_token="day_after_hunter",
    )


def test_hunter_shoots_takes_victim() -> None:
    st = _hunter_at_shoot(cause_poison=False)
    assert expected_actors(st) == {0}
    res = step(st, NightAction(actor_seat=0, action_type=NightActionType.SHOOT, target_seat=1))
    assert res.rejection is None
    assert player_at(res.state, 1).alive is False


def test_hunter_poisoned_cannot_reach_shoot() -> None:
    # 被毒 -> hunter_can_shoot False -> 引擎不应进入 HUNTER_SHOOT（见集成测试）
    st = _hunter_at_shoot(cause_poison=True)
    # 直接构造到 HUNTER_SHOOT 但 can_shoot=False：开枪应被拒
    res = step(st, NightAction(actor_seat=0, action_type=NightActionType.SHOOT, target_seat=1))
    assert res.rejection is not None
