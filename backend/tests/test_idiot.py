from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import _tally_and_continue  # 内部函数直测分流
from app.engine.phases import Phase
from app.engine.state import GameState, Player, player_at


def _vote_state(idiot_revealed: bool) -> GameState:
    roles = [RoleType.IDIOT, RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            idiot_revealed=idiot_revealed if r == RoleType.IDIOT else False,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    # 所有票投 idiot(0)
    votes = {1: 0, 2: 0, 3: 0, 4: 0}
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE,
        round=2,
        players=players,
        votes=votes,
    )


def test_idiot_first_flip_survives_and_voids_vote() -> None:
    st = _vote_state(idiot_revealed=False)
    new, events = _tally_and_continue(st)
    idiot = player_at(new, 0)
    assert idiot.alive is True  # 免死
    assert idiot.idiot_revealed is True
    assert idiot.can_vote is False  # 失投票权
    # 当天投票作废：无人被放逐
    assert new.day_exiled is None


def test_idiot_after_reveal_can_be_exiled() -> None:
    st = _vote_state(idiot_revealed=True)
    new, events = _tally_and_continue(st)
    # 已翻过牌，再被票则正常出局
    assert player_at(new, 0).alive is False
