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


def test_badge_flow_mentioned_only_in_election_speech_contexts() -> None:
    # badge_flow 仅在竞选语境发言引擎合法：SHERIFF_PK 发言回合 / 上警发言（issue #47）
    obs_pk = _obs("SHERIFF_PK", pk_speech_pending=True)
    assert "badge_flow" in build_prompt(DecisionKind.SPEECH, obs_pk, "", agent_seed=1)

    obs_campaign = _obs("SHERIFF_ELECTION", election_stage="speech")
    assert "badge_flow" in build_prompt(DecisionKind.SPEECH, obs_campaign, "", agent_seed=1)

    obs_day = _obs("DAY_SPEECH")
    assert "badge_flow" not in build_prompt(DecisionKind.SPEECH, obs_day, "", agent_seed=1)


def test_campaign_speech_guidance_only_in_campaign_speech() -> None:
    obs_campaign = _obs("SHERIFF_ELECTION", election_stage="speech")
    up = build_prompt(DecisionKind.SPEECH, obs_campaign, "", agent_seed=1)
    assert "上警发言" in up and "self_destruct" in up
    assert "两夜" not in up  # F3（终审修复）：badge_flow_max_length 可配，不应硬编码「两夜」

    for obs in (_obs("DAY_SPEECH"), _obs("SHERIFF_PK", pk_speech_pending=True)):
        assert "上警发言" not in build_prompt(DecisionKind.SPEECH, obs, "", agent_seed=1)


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


def test_wolf_prompt_lists_teammate_proposals_and_follow_guidance() -> None:
    obs = _obs(
        "NIGHT_WEREWOLF",
        private={
            "teammates": [4, 7],
            "tonight_kill_proposals": {4: 8, 7: None},
            "kill_proposal_history": [],
            "kill_vote_round": 1,
            "kill_vote_rounds_max": 2,
        },
    )
    up = build_wolf_night_prompt(obs, "", "", agent_seed=1)
    assert "4 号提议刀 8 号" in up and "7 号提议空刀" in up
    assert "跟刀" in up and "全员一致" in up
    assert "上一轮" not in up


def test_wolf_prompt_revote_round_shows_disagreement() -> None:
    obs = _obs(
        "NIGHT_WEREWOLF",
        private={
            "teammates": [4, 7],
            "tonight_kill_proposals": {},
            "kill_proposal_history": [{0: 8, 4: 3, 7: 8}],
            "kill_vote_round": 2,
            "kill_vote_rounds_max": 2,
        },
    )
    up = build_wolf_night_prompt(obs, "", "", agent_seed=1)
    assert "第 2/2 轮" in up and "上一轮" in up
    assert "0 号→8 号" in up and "4 号→3 号" in up
    assert "末轮" in up


def test_wolf_prompt_tolerates_missing_new_fields() -> None:
    up = build_wolf_night_prompt(_obs("NIGHT_WEREWOLF"), "", "", agent_seed=1)
    assert "队友" in up and "本轮队友已提案" not in up and "上一轮" not in up


def test_wolf_prompt_rule_text_follows_kill_rule() -> None:
    # F1（终审修复）：规则句须随 wolf_kill_rule 分支，避免与 --wolf-rule 矛盾
    def _rule_text(rule: str) -> str:
        obs = _obs(
            "NIGHT_WEREWOLF",
            private={"teammates": [4, 7], "kill_rule": rule},
        )
        return build_wolf_night_prompt(obs, "", "", agent_seed=1)

    unanimous = _rule_text("UNANIMOUS_OR_NO_KILL")
    assert "全员一致" in unanimous

    majority = _rule_text("MAJORITY")
    assert "相对多数" in majority and "全员一致" not in majority

    random_rule = _rule_text("RANDOM_PROPOSAL")
    assert "随机" in random_rule
    assert "全员一致" not in random_rule and "空刀" not in random_rule


def test_wolf_prompt_accepts_json_string_keys() -> None:
    # F8（deferred 回归）：跨 IO 边界（JSON 往返）后 dict 键变字符串，仍须正确渲染
    obs = _obs(
        "NIGHT_WEREWOLF",
        private={
            "teammates": [4],
            "tonight_kill_proposals": {"4": 8},
            "kill_proposal_history": [{"0": 8, "4": 3}],
            "kill_vote_round": 2,
            "kill_vote_rounds_max": 2,
        },
    )
    up = build_wolf_night_prompt(obs, "", "", agent_seed=1)
    assert "4 号提议刀 8 号" in up
    assert "0 号→8 号" in up


def test_day_prompt_and_night_situation_do_not_dump_kill_ledger() -> None:
    # F2（终审修复）：收敛账本不得原始 dict 打印进「== 局势 ==」段，也不得泄进白天 prompt
    private = {
        "teammates": [4, 7],
        "tonight_kill_proposals": {4: 8},
        "kill_proposal_history": [],
        "kill_vote_round": 1,
        "kill_vote_rounds_max": 2,
        "kill_rule": "UNANIMOUS_OR_NO_KILL",
    }
    obs_night = _obs("NIGHT_WEREWOLF", private=dict(private))
    up_night = build_wolf_night_prompt(obs_night, "", "", agent_seed=1)
    situation = up_night.split("== 你的记忆 ==")[0]
    assert "tonight_kill_proposals" not in situation

    obs_day = _obs("DAY_SPEECH", private=dict(private))
    up_day = build_prompt(DecisionKind.SPEECH, obs_day, "", agent_seed=1)
    assert "tonight_kill_proposals" not in up_day


def test_skills_text_inserted_before_decision_and_absent_when_empty() -> None:
    obs = _obs("DAY_SPEECH")
    base = build_prompt(DecisionKind.SPEECH, obs, "M", agent_seed=1)
    same = build_prompt(DecisionKind.SPEECH, obs, "M", agent_seed=1, skills_text="")
    assert base == same and "== 技能提示 ==" not in base
    with_sk = build_prompt(
        DecisionKind.SPEECH, obs, "M", agent_seed=1, skills_text="【技能：x】\n做法"
    )
    preamble = "== 技能提示 ==\n以下为备选策略，按各篇「触发条件」选用其一为主，不必全部执行。\n"
    assert f"{preamble}【技能：x】\n做法" in with_sk
    assert with_sk.index("== 技能提示 ==") < with_sk.index("== 本次决策 ==")

    wolf_obs = _obs("NIGHT_WEREWOLF")
    w0 = build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1)
    assert w0 == build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1, skills_text="")
    w1 = build_wolf_night_prompt(wolf_obs, "M", "P", agent_seed=1, skills_text="【技能：k】\n刀法")
    assert f"{preamble}【技能：k】\n刀法" in w1
    assert w1.index("== 技能提示 ==") < w1.index("== 本次决策 ==")
