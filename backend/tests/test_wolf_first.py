from app.engine.config import Faction, RoleType, WinCondition, build_preset
from app.engine.engine import _check_win_with_deaths
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def test_wolf_first_kill_wins_before_witch_poison() -> None:
    # 屠城：好人只剩 1 人；狼刀刀掉最后好人 -> 狼胜（即便女巫随后毒狼也无效）
    roles = [RoleType.WEREWOLF, RoleType.VILLAGER]
    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=r, faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD)
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_all").model_copy(update={"num_players": 2, "win_condition": WinCondition.KILL_ALL, "seed": 1})
    st = GameState(game_id="g", config=cfg, phase=Phase.NIGHT_SEER, round=1, players=players)
    # 狼刀掉 seat1（最后好人）
    assert _check_win_with_deaths(st, frozenset({1})) == "WOLF"
    # 未刀则未结束
    assert _check_win_with_deaths(st, frozenset()) is None
