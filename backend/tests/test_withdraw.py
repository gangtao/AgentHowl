"""退水（issue #6）：SHERIFF_WITHDREW 事实、确认子阶段与投票权剥夺。"""

from app.engine.actions import SheriffAction, SheriffActionType
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    SheriffWithdrewPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0,)) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(n: int = 6, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n, wolves=(0, 1)),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_withdrew_event_reduces_out_of_candidates_into_withdrawn() -> None:
    st = _state(sheriff_candidates=(1, 2, 3), election_stage="withdraw")
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_WITHDREW,
        actor_seat=2,
        payload=SheriffWithdrewPayload(seat=2),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_candidates == (1, 3)
    assert new.sheriff_withdrawn == frozenset({2})
    assert st.sheriff_candidates == (1, 2, 3)  # 原状态不变


def test_withdraw_stage_flow_and_vote_forfeiture() -> None:
    from app.engine.actions import RejectedReason
    from app.engine.engine import step

    # 6 人，候选 (1,2,3)，withdraw 子阶段：2 退水，1/3 坚持
    st = _state(
        sheriff_candidates=(1, 2, 3),
        sheriff_declared=frozenset({0, 1, 2, 3, 4, 5}),
        election_stage="withdraw",
    )
    assert expected_actors(st) == {1, 2, 3}

    st = step(st, SheriffAction(actor_seat=1, action_type=SheriffActionType.RUN_FOR_SHERIFF)).state
    assert expected_actors(st) == {2, 3}
    res = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    assert any(e.type == EventType.SHERIFF_WITHDREW for e in res.events)
    st = res.state
    assert st.sheriff_withdrawn == frozenset({2})
    assert 2 not in st.sheriff_candidates
    assert expected_actors(st) == {3}
    st = step(st, SheriffAction(actor_seat=3, action_type=SheriffActionType.RUN_FOR_SHERIFF)).state

    # 全员确认 -> vote 阶段；退水者 2 不在投票人集合（警下 = {0,4,5}）
    assert st.election_stage == "vote"
    assert expected_actors(st) == {0, 4, 5}
    # 退水者显式投票被拒（CANNOT_VOTE）
    r = step(
        st,
        SheriffAction(actor_seat=2, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1),
    )
    assert r.rejection == RejectedReason.CANNOT_VOTE


def test_all_withdraw_badge_lost() -> None:
    from app.engine.engine import step

    st = _state(sheriff_candidates=(1, 2), election_stage="withdraw")
    st = step(st, SheriffAction(actor_seat=1, action_type=SheriffActionType.WITHDRAW)).state
    res = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    # 全员退水 -> 警徽流失并续接（离开竞选阶段）
    elected = [e for e in res.events if e.type == EventType.SHERIFF_ELECTED]
    assert len(elected) == 1 and elected[0].payload.seat is None  # type: ignore[attr-defined]
    assert res.state.sheriff_seat is None


def test_withdrawn_keeps_day_vote() -> None:
    from app.engine.actions import DayVote
    from app.engine.engine import step

    # 退水者在白天 VOTE 阶段仍可投票
    st = _state(
        phase=Phase.VOTE,
        round=1,
        sheriff_withdrawn=frozenset({2}),
        votes={},
        vote_candidates=(),
    )
    r = step(st, DayVote(actor_seat=2, target_seat=0))
    assert r.rejection is None


def test_full_games_with_withdraw_terminate() -> None:
    from app.cli.bot import run_game

    for seed in (2, 9, 27):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, _ = run_game(cfg, game_id=f"wd{seed}")
        assert final.phase == Phase.GAME_OVER
