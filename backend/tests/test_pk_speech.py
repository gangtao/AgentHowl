"""PK 发言轮（issue #5）：平票者先发言，未平票者后投票。"""

from app.engine.actions import DayVote, Speak
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
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
