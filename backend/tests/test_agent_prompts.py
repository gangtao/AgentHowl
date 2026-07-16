"""prompt 三段式装配（issue #31 Task 5）：洗牌确定性、角色注入、私有分区只进狼夜 prompt。"""

import inspect

from app.agent.decisions import DecisionKind
from app.agent.prompts import (
    build_prompt,
    build_wolf_night_prompt,
    candidates_for,
    shuffle_candidates,
    static_system_prompt,
)
from app.engine.config import RoleType, build_preset
from app.engine.observation import PlayerObservation


def _obs(phase: str = "DAY_SPEECH", **kw) -> PlayerObservation:
    return PlayerObservation(
        game_id="g_p",
        state_version=kw.pop("state_version", 42),
        my_seat=kw.pop("my_seat", 0),
        my_role=kw.pop("my_role", RoleType.WEREWOLF),
        my_status="ALIVE",
        phase=phase,
        round=2,
        seats=[{"seat": i, "alive": i != 5, "is_sheriff": i == 3} for i in range(9)],
        sheriff_seat=3,
        badge_flow_claims={},
        private=kw.pop("private", {"teammates": [4, 7]}),
        available_actions=[0],
        **kw,
    )


def test_shuffle_deterministic_permutation() -> None:
    cands = [1, 2, 3, 4, 5, 6]
    a = shuffle_candidates(cands, agent_seed=9, seat=0, state_version=42)
    b = shuffle_candidates(cands, agent_seed=9, seat=0, state_version=42)
    c = shuffle_candidates(cands, agent_seed=9, seat=1, state_version=42)
    assert a == b  # 同键确定性
    assert sorted(a) == cands  # 是置换
    assert cands == [1, 2, 3, 4, 5, 6]  # 不改原列表
    # 不同座位大概率不同序（弱断言：至少键参与了派生）
    assert (a != c) or (shuffle_candidates(cands, agent_seed=9, seat=1, state_version=43) != c)


def test_static_prompt_contains_role_and_config() -> None:
    config = build_preset("std_9_kill_side")
    sp = static_system_prompt(config, seat=2, role=RoleType.SEER)
    assert "预言家" in sp and "2" in sp
    assert "屠边" in sp or "KILL_SIDE" in sp  # 胜利条件入静态段


def test_candidates_for_vote_and_sheriff() -> None:
    obs = _obs("VOTE", vote_candidates=[3, 1])
    assert set(candidates_for(DecisionKind.VOTE, obs)) == {3, 1}
    obs2 = _obs("SHERIFF_ELECTION", election_stage="vote", sheriff_candidates=[2, 6])
    assert set(candidates_for(DecisionKind.SHERIFF, obs2)) == {2, 6}
    # 无显式候选 → 存活他人
    obs3 = _obs("VOTE")
    assert set(candidates_for(DecisionKind.VOTE, obs3)) == {1, 2, 3, 4, 6, 7, 8}


def test_day_prompt_builder_has_no_private_param() -> None:
    # 公私分离的类型落点：昼间装配函数签名上不存在私有分区参数
    params = inspect.signature(build_prompt).parameters
    assert "night_private_context" not in params
    assert "night_private" not in params


def test_prompts_carry_memory_and_self_check() -> None:
    up = build_prompt(DecisionKind.SPEECH, _obs(), "记忆内容ABC", agent_seed=1)
    assert "记忆内容ABC" in up
    assert "当前" in up and "角色" in up  # 反幻觉自检问句
    wolf = build_wolf_night_prompt(
        _obs("NIGHT_WEREWOLF"), "记忆内容ABC", "[第1夜私谋] 刀3号", agent_seed=1
    )
    assert "刀3号" in wolf and "记忆内容ABC" in wolf
    assert "队友" in wolf and "4" in wolf  # teammates 进狼夜动态段


def test_badge_flow_mentioned_only_in_sheriff_pk() -> None:
    # 评审修正：badge_flow 仅在 SHERIFF_PK 发言引擎合法，其它阶段 → BADGE_FLOW_INVALID
    obs_pk = _obs("SHERIFF_PK", pk_speech_pending=True)
    up_pk = build_prompt(DecisionKind.SPEECH, obs_pk, "", agent_seed=1)
    assert "badge_flow" in up_pk

    obs_day = _obs("DAY_SPEECH")
    up_day = build_prompt(DecisionKind.SPEECH, obs_day, "", agent_seed=1)
    assert "badge_flow" not in up_day


def test_self_destruct_mentioned_only_in_legal_phases() -> None:
    # 评审修正：self_destruct 仅在 DAY_SPEECH/SHERIFF_ELECTION/SHERIFF_PK 引擎合法
    obs_day = _obs("DAY_SPEECH")
    up_day = build_prompt(DecisionKind.SPEECH, obs_day, "", agent_seed=1)
    assert "self_destruct" in up_day

    obs_last_words = _obs("LAST_WORDS")
    up_lw = build_prompt(DecisionKind.SPEECH, obs_last_words, "", agent_seed=1)
    assert "self_destruct" not in up_lw

    obs_election = _obs("SHERIFF_ELECTION", election_stage="run")
    up_election = build_prompt(DecisionKind.SHERIFF, obs_election, "", agent_seed=1)
    assert "self_destruct" in up_election

    obs_pk_sheriff = _obs("SHERIFF_PK", pk_speech_pending=False)
    up_pk_sheriff = build_prompt(DecisionKind.SHERIFF, obs_pk_sheriff, "", agent_seed=1)
    assert "self_destruct" in up_pk_sheriff
