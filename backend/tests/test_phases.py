from app.engine.config import RoleType
from app.engine.phases import (
    Phase,
    expected_actors,
    next_night_phase,
    night_phase_sequence,
    phase_for_role,
)
from app.engine.state import GameState
from tests.factories import stage1_config
from tests.test_state import _mk_player  # 复用构造 helper


def _state(phase: Phase, **kw: object) -> GameState:
    players = (
        _mk_player(0, RoleType.WEREWOLF),
        _mk_player(1, RoleType.WEREWOLF),
        _mk_player(2, RoleType.WEREWOLF),
        _mk_player(3, RoleType.SEER),
        _mk_player(4, RoleType.WITCH),
        _mk_player(5, RoleType.GUARD),
        _mk_player(6, RoleType.VILLAGER),
        _mk_player(7, RoleType.VILLAGER),
        _mk_player(8, RoleType.VILLAGER),
    )
    base: dict[str, object] = {
        "game_id": "g",
        "config": stage1_config(seed=1),
        "phase": phase,
        "round": 1,
        "players": players,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_phase_for_role() -> None:
    assert phase_for_role(RoleType.GUARD) == Phase.NIGHT_GUARD
    assert phase_for_role(RoleType.WEREWOLF) == Phase.NIGHT_WEREWOLF
    assert phase_for_role(RoleType.WITCH) == Phase.NIGHT_WITCH
    assert phase_for_role(RoleType.SEER) == Phase.NIGHT_SEER
    assert phase_for_role(RoleType.VILLAGER) is None


def test_night_sequence_stage1() -> None:
    seq = night_phase_sequence(stage1_config(seed=1))
    assert seq == [
        Phase.NIGHT_GUARD,
        Phase.NIGHT_WEREWOLF,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
    ]
    assert next_night_phase(stage1_config(seed=1), Phase.NIGHT_WEREWOLF) == Phase.NIGHT_WITCH
    assert next_night_phase(stage1_config(seed=1), Phase.NIGHT_SEER) is None


def test_expected_guard_phase() -> None:
    assert expected_actors(_state(Phase.NIGHT_GUARD)) == {5}


def test_expected_wolves_excludes_already_proposed() -> None:
    st = _state(Phase.NIGHT_WEREWOLF, wolf_proposals={0: 6})
    assert expected_actors(st) == {1, 2}


def test_expected_witch_needs_potion() -> None:
    # 无药女巫 -> 不再期待其行动
    players = tuple(
        p.model_copy(update={"witch_antidote": False, "witch_poison": False}) if p.seat == 4 else p
        for p in _state(Phase.NIGHT_WITCH).players
    )
    st = _state(Phase.NIGHT_WITCH).model_copy(update={"players": players})
    assert expected_actors(st) == set()
    assert expected_actors(_state(Phase.NIGHT_WITCH)) == {4}


def test_expected_day_speech_current_speaker() -> None:
    st = _state(Phase.DAY_SPEECH, speech_order=(6, 7, 8), speech_idx=1)
    assert expected_actors(st) == {7}
    st_done = _state(Phase.DAY_SPEECH, speech_order=(6, 7, 8), speech_idx=3)
    assert expected_actors(st_done) == set()


def test_expected_vote_excludes_voted() -> None:
    st = _state(Phase.VOTE, votes={0: 6})
    assert 0 not in expected_actors(st)
    assert expected_actors(st) == {1, 2, 3, 4, 5, 6, 7, 8}


def test_expected_vote_pk_excludes_candidates() -> None:
    st = _state(Phase.VOTE_PK, vote_candidates=(6, 7))
    got = expected_actors(st)
    assert 6 not in got and 7 not in got
    assert got == {0, 1, 2, 3, 4, 5, 8}


def test_expected_system_phases_empty() -> None:
    for ph in (Phase.WIN_CHECK, Phase.DEATH_ANNOUNCE, Phase.EXILE, Phase.GAME_OVER):
        assert expected_actors(_state(ph)) == set()
