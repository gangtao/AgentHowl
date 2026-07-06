import pytest

from app.cli.bot import run_game
from app.engine.events import EventType, reduce_all
from app.engine.phases import Phase
from tests.factories import stage1_config


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42, 99, 123, 2024])
def test_random_game_terminates_with_result(seed: int) -> None:
    final, events = run_game(stage1_config(seed=seed), game_id=f"g{seed}")
    assert final.phase == Phase.GAME_OVER
    # 有胜负或达 max_rounds 判平局
    game_over = [e for e in events if e.type == EventType.GAME_OVER]
    assert len(game_over) == 1


def test_replay_equals_live() -> None:
    final, events = run_game(stage1_config(seed=5), game_id="g5")
    # 从「发牌前」的空局基态重放全部事件，应得到与实时终态一致的关键投影
    replayed = reduce_all(_blank_state(final), events)
    assert replayed.phase == final.phase
    assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
    assert replayed.winner == final.winner


def _blank_state(final):  # type: ignore[no-untyped-def]
    from app.engine.config import Faction, RoleType
    from app.engine.state import GameState, Player

    players = tuple(
        Player(
            seat=p.seat,
            display_name=p.display_name,
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for p in final.players
    )
    return GameState(
        game_id=final.game_id, config=final.config, phase=Phase.LOBBY, round=0, players=players
    )


def test_determinism_same_seed_identical_events() -> None:
    _, ev1 = run_game(stage1_config(seed=77), game_id="g")
    _, ev2 = run_game(stage1_config(seed=77), game_id="g")
    assert [e.model_dump() for e in ev1] == [e.model_dump() for e in ev2]
