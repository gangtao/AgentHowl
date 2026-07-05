from app.engine.config import (
    Faction,
    RoleType,
    WinCondition,
)
from app.engine.phases import Phase
from app.engine.resolver import check_win, count_votes
from app.engine.state import GameState, Player
from tests.factories import stage1_config


def _state(alive_roles: list[tuple[RoleType, bool]], win: WinCondition) -> GameState:
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=role,
            faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
            alive=alive,
        )
        for i, (role, alive) in enumerate(alive_roles)
    )
    cfg = stage1_config(seed=1).model_copy(update={"win_condition": win})
    return GameState(
        game_id="g",
        config=cfg,
        phase=Phase.WIN_CHECK,
        round=1,
        players=players,
    )


def test_good_wins_when_all_wolves_dead() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, False),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "GOOD"


def test_kill_side_wolf_wins_when_villagers_gone() -> None:
    # 屠边：村民杀光即狼胜（神职还在也算）
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, False),
            (RoleType.SEER, True),
            (RoleType.WITCH, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "WOLF"


def test_kill_side_wolf_wins_when_gods_gone() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, False),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) == "WOLF"


def test_kill_all_wolf_needs_all_good_dead() -> None:
    # 屠城：还有任一好人存活 -> 未结束
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, False),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_ALL,
    )
    assert check_win(st) is None


def test_ongoing_returns_none() -> None:
    st = _state(
        [
            (RoleType.WEREWOLF, True),
            (RoleType.VILLAGER, True),
            (RoleType.SEER, True),
        ],
        WinCondition.KILL_SIDE,
    )
    assert check_win(st) is None


def test_count_votes_simple_majority() -> None:
    votes = {0: 3, 1: 3, 2: 4}
    weights = {0: 1.0, 1: 1.0, 2: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 3
    assert tie == ()


def test_count_votes_tie() -> None:
    votes = {0: 3, 1: 4}
    weights = {0: 1.0, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled is None
    assert tie == (3, 4)


def test_count_votes_abstain_ignored() -> None:
    votes = {0: None, 1: 5, 2: None}
    weights = {0: 1.0, 1: 1.0, 2: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 5


def test_count_votes_sheriff_weight_breaks_tie() -> None:
    # 警长 1.5 票：seat0(警长)投3，seat1投4 -> 3 得 1.5 票胜
    votes = {0: 3, 1: 4}
    weights = {0: 1.5, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled == 3
    assert tie == ()


def test_count_votes_all_abstain_no_exile() -> None:
    votes = {0: None, 1: None}
    weights = {0: 1.0, 1: 1.0}
    exiled, tie = count_votes(votes, weights)
    assert exiled is None
    assert tie == ()
