"""跨局经验（issue #59）：schema 上限、终局揭示、复盘 prompt、装配渲染——零 IO。"""

import pytest
from pydantic import ValidationError

from app.agent.experience import (
    MAX_LESSONS,
    MAX_NOTES_PER_OPPONENT,
    AgentExperience,
    GameReflection,
    Lesson,
    build_reflection_prompt,
    build_reveal,
    render_experience,
)
from app.agent.profile import AgentProfile, validate_profiles
from app.cli.bot import run_game
from app.engine.config import RoleType, build_preset
from app.engine.phases import Phase


def _finished_state():
    state, _events = run_game(build_preset("std_9_kill_side").model_copy(update={"seed": 3}), "g1")
    assert state.phase == Phase.GAME_OVER
    return state


def test_memory_id_pattern() -> None:
    assert AgentProfile(model="m", memory_id="alice_01-x").memory_id == "alice_01-x"
    for bad in ("", "a/b", "a b", "中文", "x" * 65):
        with pytest.raises(ValidationError):
            AgentProfile(model="m", memory_id=bad)
    with pytest.raises(ValidationError):
        AgentExperience(memory_id="a/b")


def test_validate_profiles_rejects_star_and_duplicate_memory_id() -> None:
    with pytest.raises(ValueError, match="'\\*'"):
        validate_profiles({"*": AgentProfile(model="m", memory_id="a")}, 9)
    with pytest.raises(ValueError, match="memory_id 'a'"):
        validate_profiles(
            {
                "0": AgentProfile(model="m", memory_id="a"),
                "3": AgentProfile(model="m", memory_id="a"),
            },
            9,
        )
    validate_profiles(
        {"0": AgentProfile(model="m", memory_id="a"), "3": AgentProfile(model="m", memory_id="b")},
        9,
    )


def test_record_game_filters_truncates_and_caps() -> None:
    exp = AgentExperience(memory_id="me")
    refl = GameReflection(
        lessons=["  一 ", "", "二", "三", "四"],
        opponent_notes={0: ["自己"], 3: ["a", "b", "c"], 5: ["无记忆座位"], 7: ["x" * 100]},
    )
    exp.record_game(
        game_id="g1",
        role=RoleType.SEER,
        won=True,
        reflection=refl,
        seat_to_memory_id={0: "me", 3: "bob", 7: "carol"},
        my_seat=0,
        ts="2026-09-20T00:00:00+00:00",
    )
    assert exp.games_played == 1 and exp.wins == 1
    assert [ln.text for ln in exp.lessons] == ["一", "二", "三"]  # 空条丢弃、strip、每局最多 3 条
    first = exp.lessons[0]
    assert first.role == RoleType.SEER and first.won and first.game_id == "g1"
    assert set(exp.opponent_notes) == {"bob", "carol"}  # 自己与无 memory_id 座位丢弃
    assert [n.text for n in exp.opponent_notes["bob"]] == ["a", "b"]  # 每局每人最多 2 条
    assert len(exp.opponent_notes["carol"][0].text) == 60  # 截到 60 字


def test_caps_evict_oldest() -> None:
    exp = AgentExperience(memory_id="me")
    for i in range(MAX_LESSONS + 5):
        exp.record_game(
            game_id=f"g{i}",
            role=RoleType.VILLAGER,
            won=False,
            reflection=GameReflection(lessons=[f"L{i}"], opponent_notes={1: [f"N{i}"]}),
            seat_to_memory_id={0: "me", 1: "bob"},
            my_seat=0,
            ts="t",
        )
    assert len(exp.lessons) == MAX_LESSONS and exp.lessons[0].text == "L5"
    assert len(exp.opponent_notes["bob"]) == MAX_NOTES_PER_OPPONENT
    assert exp.opponent_notes["bob"][-1].text == f"N{MAX_LESSONS + 4}"
    assert exp.games_played == MAX_LESSONS + 5


def test_reflection_response_ignores_extra_and_coerces_seat_keys() -> None:
    r = GameReflection.model_validate(
        {"lessons": ["a"], "opponent_notes": {"3": ["x"]}, "why": "…"}
    )
    assert r.opponent_notes == {3: ["x"]}


def test_build_reveal_requires_game_over_and_derives_won() -> None:
    state = _finished_state()
    me = state.players[2]
    reveal = build_reveal(state, 2, notable_seats=[2, 5, 7])
    assert reveal.game_id == "g1" and reveal.my_seat == 2 and reveal.my_role == me.role
    assert reveal.my_won == (state.winner is not None and me.faction == state.winner)
    assert reveal.notable_seats == (5, 7)  # 自己被剔除、排序
    assert len(reveal.seats) == 9 and reveal.seats[2].role == me.role
    lobby = state.model_copy(update={"phase": Phase.DAY_SPEECH})
    with pytest.raises(ValueError, match="GAME_OVER"):
        build_reveal(lobby, 2, notable_seats=[])
    draw = state.model_copy(update={"winner": None})
    assert build_reveal(draw, 2, notable_seats=[]).my_won is False


def test_reflection_prompt_sections() -> None:
    state = _finished_state()
    reveal = build_reveal(state, 0, notable_seats=[3])
    system, user = build_reflection_prompt(reveal, "记忆A", "")
    assert "整局复盘" in system
    idx_reveal = user.index("== 终局揭示 ==")
    idx_memory = user.index("== 你本局的记忆 ==")
    idx_ask = user.index("== 复盘要求 ==")
    assert idx_reveal < idx_memory < idx_ask
    assert "记忆A" in user and "== 狼队私谋 ==" not in user
    assert f"3号（{state.players[3].display_name}）" in user
    _s, user2 = build_reflection_prompt(reveal, "", "私谋B")
    assert "== 狼队私谋 ==\n私谋B" in user2 and "（暂无）" in user2


def _exp_with(*lessons: tuple[RoleType, bool, str]) -> AgentExperience:
    exp = AgentExperience(memory_id="me", games_played=len(lessons), wins=1)
    exp.lessons = [
        Lesson(game_id=f"g{i}", role=r, won=w, text=t, ts="t")
        for i, (r, w, t) in enumerate(lessons)
    ]
    return exp


def test_render_experience_role_first_recent_first_and_closing() -> None:
    exp = _exp_with(
        (RoleType.SEER, False, "S1"),
        (RoleType.VILLAGER, True, "V1"),
        (RoleType.SEER, True, "S2"),
    )
    text = render_experience(exp, role=RoleType.SEER, opponents={})
    assert text.startswith("你此前打过 3 局（胜 1）。")
    assert text.index("[SEER·胜] S2") < text.index("[SEER·负] S1") < text.index("[VILLAGER·胜] V1")
    assert text.rstrip().endswith("不得据此违反规则。")
    assert "对手：" not in text


def test_render_experience_opponents_mapped_to_seats_and_recent_three() -> None:
    exp = _exp_with((RoleType.SEER, True, "S"))
    exp.record_game(
        game_id="g9",
        role=RoleType.SEER,
        won=True,
        reflection=GameReflection(opponent_notes={1: ["n1", "n2"]}),
        seat_to_memory_id={0: "me", 1: "bob"},
        my_seat=0,
        ts="t",
    )
    exp.record_game(
        game_id="g10",
        role=RoleType.SEER,
        won=True,
        reflection=GameReflection(opponent_notes={4: ["n3", "n4"]}),
        seat_to_memory_id={0: "me", 4: "bob"},
        my_seat=0,
        ts="t",
    )
    text = render_experience(exp, role=RoleType.SEER, opponents={"bob": 6, "zed": 2})
    assert "对手：\n- 6号：n2；n3；n4" in text  # 最近 3 条、映射到本局座位；无笔记的 zed 不出现
    assert "2号" not in text


def test_render_experience_empty_and_budget() -> None:
    empty = AgentExperience(memory_id="me")
    assert render_experience(empty, role=RoleType.SEER, opponents={}) == ""
    only_notes = AgentExperience(memory_id="me")
    only_notes.record_game(
        game_id="g",
        role=RoleType.SEER,
        won=False,
        reflection=GameReflection(opponent_notes={1: ["x"]}),
        seat_to_memory_id={0: "me", 1: "bob"},
        my_seat=0,
        ts="t",
    )
    assert render_experience(only_notes, role=RoleType.SEER, opponents={}) == ""  # 对手不在场
    assert "1号：x" in render_experience(only_notes, role=RoleType.SEER, opponents={"bob": 1})
    exp = _exp_with(*[(RoleType.SEER, True, "x" * 100) for _ in range(20)])
    text = render_experience(exp, role=RoleType.SEER, opponents={}, budget_chars=350)
    assert text.count("- [SEER·胜]") == 3  # 每条约 113 字符，预算 350 装 3 条
