"""狼队刀口收敛（issue #46）：可见提案、收敛轮、末轮兜底、回放保真。"""

import pytest

from app.engine.config import (
    ConfigError,
    Faction,
    GameConfig,
    RoleType,
    WolfKillRule,
    build_preset,
    validate_config,
)
from app.engine.events import (
    Event,
    EventType,
    RoundStartedPayload,
    Visibility,
    WolfKillRevotePayload,
    reduce,
)
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player

WOLVES = (0, 1, 2)


def _players(n: int = 9, wolves: tuple[int, ...] = WOLVES) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(
    proposals: dict[int, int | None] | None = None,
    rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL,
    rounds: int = 2,
    seed: int = 1,
    **kw: object,
) -> GameState:
    """夜间狼阶段状态：3 狼 6 民；proposals 为本轮已提交的提案。"""
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"seed": seed, "wolf_kill_rule": rule, "wolf_consensus_rounds": rounds}
    )
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.NIGHT_WEREWOLF,
        "round": 1,
        "players": _players(),
        "wolf_proposals": dict(proposals or {}),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _evt(etype: EventType, payload: object, vis: Visibility = Visibility.WOLVES) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=etype,
        actor_seat=None,
        payload=payload,  # type: ignore[arg-type]
        visibility=vis,
    )


# ---------- Task 1：契约 ----------


def test_config_default_and_validation() -> None:
    assert GameConfig(config_id="x").wolf_consensus_rounds == 2
    for name in ("std_12_yn_hunter_idiot", "std_9_kill_side"):
        assert build_preset(name).wolf_consensus_rounds == 2
    with pytest.raises(ConfigError, match="wolf_consensus_rounds"):
        validate_config(
            build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 0})
        )
    validate_config(build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 1}))


def test_state_defaults() -> None:
    st = _state()
    assert st.wolf_kill_round == 1
    assert st.wolf_proposal_history == ()


def test_reduce_revote_clears_proposals_and_records_history() -> None:
    st = _state({0: 8, 1: 3, 2: 8})
    snapshot = ((0, 8), (1, 3), (2, 8))
    new = reduce(
        st,
        _evt(
            EventType.WOLF_KILL_REVOTE,
            WolfKillRevotePayload(round_no=1, proposals=snapshot),
        ),
    )
    assert new.wolf_proposals == {}
    assert new.wolf_kill_round == 2
    assert new.wolf_proposal_history == (snapshot,)
    assert new.acted_seats == st.acted_seats  # 其他角色的已行动记录不受影响
    assert st.wolf_proposals == {0: 8, 1: 3, 2: 8}  # 纯函数：原状态不变
    # 狼重新成为行动者
    assert expected_actors(new) == set(WOLVES)


def test_reduce_round_started_resets_round_and_history() -> None:
    st = _state(wolf_kill_round=3, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    new = reduce(st, _evt(EventType.ROUND_STARTED, RoundStartedPayload(round=2), Visibility.PUBLIC))
    assert new.wolf_kill_round == 1
    assert new.wolf_proposal_history == ()
    assert new.wolf_proposals == {}


def test_revote_payload_is_mapped_for_fail_loud_reduce() -> None:
    from app.engine.events import EVENT_PAYLOAD_TYPES

    assert EVENT_PAYLOAD_TYPES[EventType.WOLF_KILL_REVOTE] is WolfKillRevotePayload


# ---------- Task 2：引擎重提 ----------


def _propose(st: GameState, seat: int, target: int | None):
    from app.engine.actions import NightAction, NightActionType
    from app.engine.engine import step

    if target is None:
        a = NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
    else:
        a = NightAction(actor_seat=seat, action_type=NightActionType.KILL, target_seat=target)
    res = step(st, a)
    assert res.rejection is None, res.rejection
    return res


def _types(events: list[Event]) -> list[EventType]:
    return [e.type for e in events]


def test_unanimous_first_round_decides_without_revote() -> None:
    st = _state({0: 8, 1: 8})
    res = _propose(st, 2, 8)
    types = _types(res.events)
    assert EventType.WOLF_KILL_REVOTE not in types
    assert EventType.WOLF_KILL_DECIDED in types
    assert res.state.pending_night.wolf_target == 8
    assert res.state.phase != Phase.NIGHT_WEREWOLF


def test_disagreement_triggers_revote_then_second_round_decides() -> None:
    st = _state({0: 8, 1: 3})
    res = _propose(st, 2, 8)  # 8,3,8 -> UNANIMOUS 不一致
    revotes = [e for e in res.events if e.type == EventType.WOLF_KILL_REVOTE]
    assert len(revotes) == 1
    p = revotes[0].payload
    assert isinstance(p, WolfKillRevotePayload)
    assert p.round_no == 1 and p.proposals == ((0, 8), (1, 3), (2, 8))
    assert revotes[0].visibility == Visibility.WOLVES
    assert EventType.WOLF_KILL_DECIDED not in _types(res.events)
    st2 = res.state
    assert st2.phase == Phase.NIGHT_WEREWOLF
    assert st2.wolf_proposals == {} and st2.wolf_kill_round == 2
    assert st2.wolf_proposal_history == (((0, 8), (1, 3), (2, 8)),)
    assert expected_actors(st2) == set(WOLVES)
    # 第二轮统一 -> 出刀
    st2 = _propose(st2, 0, 8).state
    st2 = _propose(st2, 1, 8).state
    res2 = _propose(st2, 2, 8)
    assert EventType.WOLF_KILL_DECIDED in _types(res2.events)
    assert res2.state.pending_night.wolf_target == 8


def test_last_round_disagreement_falls_back_to_rule() -> None:
    # rounds=2：第二轮仍不一致 -> 空刀，不再重提
    st = _state({0: 8, 1: 3}, wolf_kill_round=2, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    res = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    decided = [e for e in res.events if e.type == EventType.WOLF_KILL_DECIDED]
    assert len(decided) == 1 and decided[0].payload.target is None  # type: ignore[attr-defined]


def test_three_rounds_allow_two_revotes() -> None:
    st = _state({0: 8, 1: 3}, rounds=3)
    r1 = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE in _types(r1.events)
    s = r1.state
    s = _propose(s, 0, 8).state
    s = _propose(s, 1, 3).state
    r2 = _propose(s, 2, 8)
    assert EventType.WOLF_KILL_REVOTE in _types(r2.events)
    assert r2.state.wolf_kill_round == 3
    assert len(r2.state.wolf_proposal_history) == 2
    s = r2.state
    s = _propose(s, 0, 8).state
    s = _propose(s, 1, 3).state
    r3 = _propose(s, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(r3.events)
    assert EventType.WOLF_KILL_DECIDED in _types(r3.events)


def test_all_skip_is_not_disagreement() -> None:
    st = _state({0: None, 1: None})
    res = _propose(st, 2, None)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target is None


def test_rounds_one_matches_legacy_behavior() -> None:
    st = _state({0: 8, 1: 3}, rounds=1)
    res = _propose(st, 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target is None


def test_random_rule_never_revotes_and_majority_only_on_tie() -> None:
    res = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.RANDOM_PROPOSAL), 2, 5)
    assert EventType.WOLF_KILL_REVOTE not in _types(res.events)
    assert res.state.pending_night.wolf_target in (3, 5, 8)

    clear = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.MAJORITY), 2, 8)
    assert EventType.WOLF_KILL_REVOTE not in _types(clear.events)
    assert clear.state.pending_night.wolf_target == 8

    tie = _propose(_state({0: 8, 1: 3}, rule=WolfKillRule.MAJORITY), 2, 5)  # 8,3,5 三方并列
    assert EventType.WOLF_KILL_REVOTE in _types(tie.events)


def test_stepwise_replay_equals_live_across_revote() -> None:
    from app.engine.events import reduce_all

    st = _state({0: 8, 1: 3})
    blank = st.model_copy(update={"wolf_proposals": {}})
    events: list[Event] = []
    # 让 blank 与 st 起点一致：先把 0/1 的提案作为事件重放进 blank
    from app.engine.events import WolfKillProposedPayload

    for seat, tgt in ((0, 8), (1, 3)):
        e = Event(
            seq=len(events) + 1,
            game_id="g",
            ts=1.0,
            type=EventType.WOLF_KILL_PROPOSED,
            actor_seat=seat,
            payload=WolfKillProposedPayload(wolf_seat=seat, target=tgt),
            visibility=Visibility.WOLVES,
        )
        events.append(e)
    live = reduce_all(blank, events)
    assert live.wolf_proposals == st.wolf_proposals
    for seat, tgt in ((2, 8), (0, 8), (1, 8), (2, 8)):
        r = _propose(live, seat, tgt)
        live, events = r.state, [*events, *r.events]
        replayed = reduce_all(blank, events)
        assert replayed.wolf_proposals == live.wolf_proposals
        assert replayed.wolf_kill_round == live.wolf_kill_round
        assert replayed.wolf_proposal_history == live.wolf_proposal_history
        assert replayed.pending_night.wolf_target == live.pending_night.wolf_target


def test_full_games_terminate_and_revote_occurs() -> None:
    from app.cli.bot import run_game

    saw_revote = False
    for preset in ("std_12_yn_hunter_idiot", "std_9_kill_side", "std_9_kill_all"):
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            final, events = run_game(cfg, "g")
            assert final.phase == Phase.GAME_OVER
            saw_revote = saw_revote or any(e.type == EventType.WOLF_KILL_REVOTE for e in events)
    assert saw_revote  # 随机 bot 几乎必然出现分歧


# ---------- Task 3：observation ----------


def test_wolf_sees_current_round_proposals_history_and_round() -> None:
    from app.engine.observation import build_observation

    st = _state({0: 8}, wolf_kill_round=2, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    obs = build_observation(st, 1)
    priv = obs.private
    assert priv["tonight_kill_proposals"] == {0: 8}
    assert priv["kill_proposal_history"] == [{0: 8, 1: 3, 2: 8}]
    assert priv["kill_vote_round"] == 2 and priv["kill_vote_rounds_max"] == 2
    assert "tonight_kill_proposal" not in priv  # 裁决前无刀口


def test_wolf_fields_present_even_when_no_proposal_yet() -> None:
    from app.engine.observation import build_observation

    priv = build_observation(_state(), 0).private
    assert priv["tonight_kill_proposals"] == {}
    assert priv["kill_proposal_history"] == []
    assert priv["kill_vote_round"] == 1


def test_wolf_fields_absent_outside_night() -> None:
    """规格 §5：收敛字段只在狼存活且处于夜间时可见（终审 F2）。"""
    from app.engine.observation import build_observation

    day_keys = (
        "tonight_kill_proposals",
        "kill_proposal_history",
        "kill_vote_round",
        "kill_vote_rounds_max",
        "kill_rule",
    )
    st_day = _state(phase=Phase.DAY_SPEECH, wolf_proposals={0: 8})
    priv_day = build_observation(st_day, 1).private
    for key in day_keys:
        assert key not in priv_day

    # 夜间其他子阶段（非 NIGHT_WEREWOLF）仍可见——供跟刀/收敛引导使用
    st_witch = _state(phase=Phase.NIGHT_WITCH, wolf_proposals={0: 8, 1: 8, 2: 8})
    priv_witch = build_observation(st_witch, 1).private
    for key in day_keys:
        assert key in priv_witch


def test_non_wolf_and_dead_wolf_do_not_see_proposals() -> None:
    from app.engine.observation import build_observation

    st = _state({0: 8, 1: 3})
    for seat in (3, 4, 8):
        priv = build_observation(st, seat).private
        for key in ("tonight_kill_proposals", "kill_proposal_history", "kill_vote_round"):
            assert key not in priv
    dead = st.model_copy(
        update={
            "players": tuple(
                p.model_copy(update={"alive": False}) if p.seat == 2 else p for p in st.players
            )
        }
    )
    priv = build_observation(dead, 2).private
    assert "tonight_kill_proposals" not in priv and "teammates" not in priv
