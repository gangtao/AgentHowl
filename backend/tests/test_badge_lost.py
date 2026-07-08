"""全员上警裁决 + SHERIFF_BADGE_LOST（issue #9）。"""

from app.engine.actions import SheriffAction, SheriffActionType
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
from app.engine.events import (
    BadgeLostReason,
    Event,
    EventType,
    SheriffBadgeLostPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0, 1)) -> tuple[Player, ...]:
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
        "players": _players(n),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _badge_lost_events(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == EventType.SHERIFF_BADGE_LOST]


def test_badge_lost_reduce_strips_incumbent() -> None:
    # 移植 issue #19 的全化语义到新事件
    st = _state(sheriff_seat=2)
    players = tuple(
        p.model_copy(update={"is_sheriff": True}) if p.seat == 2 else p for p in st.players
    )
    st = st.model_copy(update={"players": players})
    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.SHERIFF_BADGE_LOST,
        actor_seat=None,
        payload=SheriffBadgeLostPayload(reason=BadgeLostReason.SELF_DESTRUCT.value),
        visibility=Visibility.PUBLIC,
    )
    new = reduce(st, ev)
    assert new.sheriff_seat is None
    assert not any(p.is_sheriff for p in new.players)


def _reason_of(events: list[Event]) -> str:
    lost = _badge_lost_events(events)
    assert len(lost) == 1
    return lost[0].payload.reason  # type: ignore[attr-defined]


def test_no_voters_all_run_skips_vote_stage() -> None:
    # 全员上警：withdraw 确认完毕后无警下 -> NO_VOTERS，且不进入 vote 阶段
    st = _state(
        election_stage="withdraw",
        sheriff_candidates=(0, 1, 2, 3, 4, 5),
        sheriff_confirmed=frozenset({0, 1, 2, 3, 4}),
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.RUN_FOR_SHERIFF))
    assert res.rejection is None
    assert _reason_of(res.events) == "NO_VOTERS"
    assert res.state.sheriff_seat is None
    # 从未进入投票子阶段
    assert res.state.election_stage != "vote"


def test_no_candidates_reason() -> None:
    # candidacy 全员声明完毕且无人上警 -> NO_CANDIDATES
    st = _state(
        election_stage="candidacy",
        sheriff_declared=frozenset({0, 1, 2, 3, 4}),
        sheriff_candidates=(),
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    assert _reason_of(res.events) == "NO_CANDIDATES"


def test_all_withdrew_reason() -> None:
    st = _state(election_stage="withdraw", sheriff_candidates=(1, 2))
    st = step(st, SheriffAction(actor_seat=1, action_type=SheriffActionType.WITHDRAW)).state
    res = step(st, SheriffAction(actor_seat=2, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    assert _reason_of(res.events) == "ALL_WITHDREW"


def test_tie_again_reason() -> None:
    # SHERIFF_PK 发言已尽、警下 {0,3} 再度 1-1 -> TIE_AGAIN
    st = _state(
        phase=Phase.SHERIFF_PK,
        sheriff_candidates=(1, 2),
        speech_order=(1, 2),
        speech_idx=2,
        sheriff_votes={0: 1},
    )
    res = step(
        st, SheriffAction(actor_seat=3, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=2)
    )
    # 4、5 号也是警下：先补投使全员投完并保持平票
    st = res.state
    if res.rejection is None and st.phase == Phase.SHERIFF_PK:
        st = step(
            st,
            SheriffAction(actor_seat=4, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1),
        ).state
        res = step(
            st,
            SheriffAction(actor_seat=5, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=2),
        )
    assert res.rejection is None
    assert _reason_of(res.events) == "TIE_AGAIN"


def test_self_destruct_reason() -> None:
    from app.engine.actions import SelfDestruct

    st = _state(election_stage="candidacy")
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert _reason_of(res.events) == "SELF_DESTRUCT"


def test_sheriff_elected_always_has_seat_in_full_games() -> None:
    from app.cli.bot import run_game

    for seed in range(12):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"bl{seed}")
        assert final.phase == Phase.GAME_OVER
        for e in events:
            if e.type == EventType.SHERIFF_ELECTED:
                assert isinstance(e.payload.seat, int)  # type: ignore[attr-defined]
