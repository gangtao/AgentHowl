from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.phases import Phase


def _preset_with_sheriff(seed: int):
    return build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})


def test_full_game_with_sheriff_terminates() -> None:
    final, events = run_game(_preset_with_sheriff(2024), game_id="g")
    assert final.phase == Phase.GAME_OVER
    # 竞选发生过：存在 SHERIFF_ELECTED 事件（当选或流失）
    from app.engine.events import EventType

    assert any(e.type == EventType.SHERIFF_ELECTED for e in events)


def test_sheriff_vote_weight_is_1_5() -> None:
    # 单元层已由 resolver.test_count_votes_sheriff_weight_breaks_tie 覆盖；
    # 此处断言 engine 用了 is_sheriff 权重
    from app.engine.config import Faction, RoleType
    from app.engine.engine import _tally_and_continue
    from app.engine.state import GameState, Player

    roles = [RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    # seat0(警长,1.5票)投1；seat2投2 -> 1 以 1.5 vs 1.0 胜
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE,
        round=2,
        players=players,
        votes={0: 1, 2: 2},
    )
    new, _ = _tally_and_continue(st)
    assert new.day_exiled == 1
