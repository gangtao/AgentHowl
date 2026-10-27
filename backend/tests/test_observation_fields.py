"""observation 公开字段增量（issue #31 Task 1）：竞选/PK 公开信息对所有座位可见。"""

from app.cli.bot import RandomBot
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import create_game, step
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player


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
    # seed=11：issue #46 激活狼队重提后 RandomBot 轨迹改变，该种子局不再经过竞选投票阶段
    # （狼夜多消耗随机步数，下游随机序列整体偏移）；换用仍命中目标阶段的种子，断言不变。
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 1})
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


def test_pk_speech_pending_during_vote_pk() -> None:
    """pk_speech_pending 在 VOTE_PK 阶段当存在待发言时为 True（行为驱动测试）。"""
    # seed 5：#50 改 PK 投票人口径后原 seed 4 不再经过 VOTE_PK，换一个仍命中 VOTE_PK 待发言态的种子
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    state = create_game(config, "g_obs_pk_test").state
    state = _advance_until(
        state,
        lambda s: s.phase == Phase.VOTE_PK and s.speech_idx < len(s.speech_order),
    )
    obs = build_observation(state, 0)
    assert obs.pk_speech_pending is True


def test_defaults_keep_old_constructions_valid() -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 11})
    state = create_game(config, "g_obs3").state
    obs = build_observation(state, 0)
    # 夜晚前新字段为空默认值
    assert obs.election_stage == ""
    assert obs.sheriff_candidates == []
    assert obs.vote_candidates == []
    assert obs.pk_speech_pending is False


def _six(sheriff: int | None = None, dead: tuple[int, ...] = ()) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
            alive=i not in dead,
            is_sheriff=i == sheriff,
        )
        for i in range(6)
    )


def _st(**kw: object) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 6, "seed": 1})
    cfg = cfg.model_copy(
        update={"sheriff": cfg.sheriff.model_copy(update={"night_death_badge_window": True})}
    )
    base: dict[str, object] = {"game_id": "g", "config": cfg, "round": 2, "players": _six()}
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def test_sheriff_options_follow_engine_validation() -> None:
    """issue #126：观测里的 sheriff_options 由服务端按引擎校验给出，前端只渲染这个集合。"""
    # 报名阶段：未表态座位可上警 / 不上
    st = _st(phase=Phase.SHERIFF_ELECTION, election_stage="candidacy")
    assert build_observation(st, 0).sheriff_options == ["run_for_sheriff", "withdraw"]
    # 警下投票：非候选人只能投；候选人没有警长行动
    st = _st(phase=Phase.SHERIFF_ELECTION, election_stage="vote", sheriff_candidates=(1, 2))
    assert build_observation(st, 0).sheriff_options == ["vote_sheriff"]
    assert build_observation(st, 1).sheriff_options == []
    # 发言方向：只有警长本人
    st = _st(
        phase=Phase.SHERIFF_ELECTION,
        election_stage="direction",
        sheriff_seat=2,
        players=_six(sheriff=2),
    )
    assert build_observation(st, 2).sheriff_options == ["set_speech_direction"]
    assert build_observation(st, 0).sheriff_options == []
    # 两步制遗言：普通遗言回合死亡警长没有任何警长行动（曾误显示发言方向按钮）
    st = _st(
        phase=Phase.LAST_WORDS,
        sheriff_seat=2,
        players=_six(sheriff=2, dead=(2,)),
        speech_order=(2,),
        speech_idx=0,
        resume_token="day_speech",
    )
    assert build_observation(st, 2).sheriff_options == []
    # 警徽处置窗口：只有移交 / 撕
    st = _st(
        phase=Phase.LAST_WORDS,
        sheriff_seat=2,
        players=_six(sheriff=2, dead=(2,)),
        speech_order=(2,),
        speech_idx=0,
        resume_token="badge_only:day_speech",
    )
    assert build_observation(st, 2).sheriff_options == ["pass_badge", "tear_badge"]


def test_badge_window_is_not_pk_speech_pending() -> None:
    """issue #141：警徽处置窗口 speech_order=(警长,) 不是「待发言」，
    pk_speech_pending 必须为 False，否则前端默认落在发言页签、发言被 WRONG_PHASE 拒绝。"""
    from app.schemas.actions import available_tools_for

    st = _st(
        phase=Phase.LAST_WORDS,
        sheriff_seat=2,
        players=_six(sheriff=2, dead=(2,)),
        speech_order=(2,),
        speech_idx=0,
        resume_token="badge_only:after_day",
    )
    obs = build_observation(st, 2)
    assert obs.badge_only is True
    assert obs.pk_speech_pending is False
    # 窗口内引擎只接受 pass_badge / tear_badge，工具列表不得再给 speak
    tools = available_tools_for(obs)
    assert "sheriff_action" in tools
    assert "speak" not in tools
    # 普通遗言窗口不受影响：仍可发言
    st2 = st.model_copy(update={"resume_token": "day_speech"})
    obs2 = build_observation(st2, 2)
    assert obs2.badge_only is False and obs2.pk_speech_pending is True
    assert available_tools_for(obs2)[0] == "speak"
