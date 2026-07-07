"""PK 发言轮（issue #5）：平票者先发言，未平票者后投票。"""

from app.engine.actions import DayVote, Speak
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
from app.engine.events import EventType
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


def _state(n: int = 4, **kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.VOTE_PK,
        "round": 2,
        "players": _players(n),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_pk_expected_speaker_first_then_voters() -> None:
    # 队列未耗尽 -> 当前平票发言者；耗尽 -> 未平票投票人
    st = _state(vote_candidates=(2, 3), speech_order=(2, 3), speech_idx=0, tie_round=1)
    assert expected_actors(st) == {2}
    st2 = st.model_copy(update={"speech_idx": 1})
    assert expected_actors(st2) == {3}
    st3 = st.model_copy(update={"speech_idx": 2})
    assert expected_actors(st3) == {0, 1}


def test_sheriff_pk_expected_speaker_first() -> None:
    st = _state(
        n=5,
        phase=Phase.SHERIFF_PK,
        round=1,
        sheriff_candidates=(1, 2),
        speech_order=(1, 2),
        speech_idx=0,
    )
    assert expected_actors(st) == {1}
    st2 = st.model_copy(update={"speech_idx": 2})
    assert expected_actors(st2) == {0, 3, 4}


def test_pk_speak_validation() -> None:
    st = _state(vote_candidates=(2, 3), speech_order=(2, 3), speech_idx=0, tie_round=1)
    # 当前发言者可发言
    assert step(st, Speak(actor_seat=2, content="pk")).rejection is None
    # 非当前发言者 -> NOT_YOUR_TURN
    assert step(st, Speak(actor_seat=3, content="pk")).rejection is not None
    # 发言期投票 -> 拒（投票人不在 expected）
    assert step(st, DayVote(actor_seat=0, target_seat=2)).rejection is not None
    # 队列耗尽后 Speak -> 拒（WRONG_PHASE）
    st_done = st.model_copy(update={"speech_idx": 2})
    assert step(st_done, Speak(actor_seat=2, content="late")).rejection is not None


def test_exile_pk_full_flow() -> None:
    # 4 人：构造 2-2 平票 -> PK 发言（升序）-> 未平票者重投 -> 放逐
    st = _state(
        phase=Phase.VOTE,
        votes={0: 2, 1: 3, 2: 3},
        vote_candidates=(),
        tie_round=0,
    )
    res = step(st, DayVote(actor_seat=3, target_seat=2))  # 2-2：{2:2, 3:2}
    assert res.rejection is None
    st = res.state
    assert st.phase == Phase.VOTE_PK
    assert st.speech_order == (2, 3)  # 平票者按座号升序上 PK 台
    assert st.speech_idx == 0
    assert expected_actors(st) == {2}

    st = step(st, Speak(actor_seat=2, content="pk-2")).state
    assert expected_actors(st) == {3}
    st = step(st, Speak(actor_seat=3, content="pk-3")).state
    # 发言完毕 -> 仅未平票者投票
    assert expected_actors(st) == {0, 1}
    st = step(st, DayVote(actor_seat=0, target_seat=2)).state
    res = step(st, DayVote(actor_seat=1, target_seat=2))
    assert res.rejection is None
    # 2 被放逐（事件流含 PLAYER_EXILED(seat=2)）
    exiled = [
        e
        for e in res.events
        if e.type == EventType.PLAYER_EXILED and getattr(e.payload, "seat", None) == 2
    ]
    assert exiled


def test_sheriff_pk_full_flow() -> None:
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.config import SpeechOrderRule

    # 6 人竞选：候选 (1,2)，警下 {0,3,4,5}；0投1、3投2、4投2，5号最后投1 -> 2-2平票入PK
    cfg = build_preset("std_9_kill_side").model_copy(
        update={
            "num_players": 6,
            "seed": 1,
            "speech_order_rule": SpeechOrderRule.FIXED_CLOCKWISE,  # 绕开当选后的方向决策子阶段
        }
    )
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.SHERIFF_ELECTION,
        round=1,
        players=_players(6, wolves=(1,)),  # 1 狼 5 民，避免结算即终局
        election_stage="vote",
        sheriff_candidates=(1, 2),
        sheriff_votes={0: 1, 3: 2, 4: 2},  # 1票vs2票，5号最后一票决平手
        night_deaths=(),
        resolved_first_night=True,
    )
    res = step(
        st, SheriffAction(actor_seat=5, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    )
    assert res.rejection is None
    stp = res.state
    # 经 _advance_election 进入 SHERIFF_PK，且入口携带发言队列
    assert stp.phase == Phase.SHERIFF_PK
    assert stp.speech_order == (1, 2)
    assert expected_actors(stp) == {1}

    stp = step(stp, Speak(actor_seat=1, content="pk")).state
    stp = step(stp, Speak(actor_seat=2, content="pk")).state
    # 警下重投（候选人不投）
    assert expected_actors(stp) == {0, 3, 4, 5}
    stp = step(
        stp, SheriffAction(actor_seat=0, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    ).state
    stp = step(
        stp, SheriffAction(actor_seat=3, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    ).state
    stp = step(
        stp, SheriffAction(actor_seat=4, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    ).state
    res = step(
        stp, SheriffAction(actor_seat=5, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    )
    assert res.rejection is None
    assert res.state.sheriff_seat == 1


def test_full_games_with_pk_still_terminate() -> None:
    from app.cli.bot import run_game

    for seed in (5, 21, 34):
        cfg = build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})
        final, _ = run_game(cfg, game_id=f"pk{seed}")
        assert final.phase == Phase.GAME_OVER
