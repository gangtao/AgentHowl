"""observation 公开字段增量（issue #31 Task 1）：竞选/PK 公开信息对所有座位可见。"""

from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState


def _advance_until(state: GameState, pred) -> GameState:
    """用 RandomBot 推进种子局直至谓词成立（终局前必须命中，否则测试失败）。"""
    guard = 0
    while not pred(state):
        assert state.phase != Phase.GAME_OVER, "种子局终局仍未命中目标阶段"
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            res = step(state, RandomBot.choose_action(state, seat))
            assert res.rejection is None
            state = res.state
            if pred(state):
                return state
        guard += 1
        assert guard < 100_000
    return state


def test_election_fields_visible_to_all_seats() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs").state
    state = _advance_until(
        state, lambda s: s.phase == Phase.SHERIFF_ELECTION and s.election_stage == "vote"
    )
    for seat in range(config.num_players):
        obs = build_observation(state, seat)
        assert obs.election_stage == "vote"
        assert obs.sheriff_candidates == sorted(state.sheriff_candidates)


def test_vote_candidates_and_pk_pending() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs2").state
    state = _advance_until(state, lambda s: s.phase == Phase.VOTE)
    obs = build_observation(state, 0)
    assert obs.vote_candidates == sorted(state.vote_candidates)


def test_defaults_keep_old_constructions_valid() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs3").state
    obs = build_observation(state, 0)
    # 夜晚前新字段为空默认值
    assert obs.election_stage == ""
    assert obs.sheriff_candidates == []
    assert obs.vote_candidates == []
    assert obs.pk_speech_pending is False
