"""女巫用药必须落成事件（回归：曾经 _consume_witch_potion 只取 state 丢掉事件，
state_version 前进而事件缺号，JsonFileEventStore 拒绝后续追加，对局在夜间结算处卡死；
随机 bot 从不用药，故金样与全局 sweep 都没覆盖到）。"""

from app.engine.actions import NightAction, NightActionType
from app.engine.config import Faction, RoleType
from app.engine.engine import create_game, step
from app.engine.events import Event, EventType, WitchPotionConsumedPayload, reduce_all
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_of_role, living_seats, player_at
from tests.factories import stage1_config


def _to_night_witch(seed: int) -> tuple[GameState, list[Event]]:
    """开局后推进到首夜女巫窗口：守卫空守、狼队一致刀首个存活好人。"""
    res = create_game(stage1_config(seed=seed), "g")
    state, events = res.state, list(res.events)
    guard = 0
    while state.phase != Phase.NIGHT_WITCH:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            if state.phase == Phase.NIGHT_WEREWOLF:
                target = next(
                    s for s in living_seats(state) if player_at(state, s).faction != Faction.WOLF
                )
                act = NightAction(
                    actor_seat=seat, action_type=NightActionType.KILL, target_seat=target
                )
            else:
                act = NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
            r = step(state, act)
            assert r.rejection is None, r.rejection
            state, events = r.state, [*events, *r.events]
        guard += 1
        assert guard < 50, "未能推进到女巫窗口"
    return state, events


def _assert_contiguous(before: int, events: list[Event], after: int) -> None:
    assert [e.seq for e in events] == list(range(before + 1, after + 1))


def test_witch_save_emits_potion_consumed_and_replays() -> None:
    state, history = _to_night_witch(seed=1)
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    before = state.state_version
    r = step(state, NightAction(actor_seat=witch, action_type=NightActionType.SAVE))
    assert r.rejection is None, r.rejection
    cur, emitted = r.state, list(r.events)
    # 解药在夜间结算时才扣（_resolve_night_and_continue）：把剩余夜间窗口（预言家等）走完
    guard = 0
    while cur.phase.name.startswith("NIGHT_"):
        for seat in sorted(expected_actors(cur)):
            if seat not in expected_actors(cur):
                continue
            r = step(cur, NightAction(actor_seat=seat, action_type=NightActionType.SKIP))
            assert r.rejection is None, r.rejection
            cur, emitted = r.state, [*emitted, *r.events]
        guard += 1
        assert guard < 20, "夜间未收敛"

    _assert_contiguous(before, emitted, cur.state_version)
    consumed = [e for e in emitted if e.type == EventType.WITCH_POTION_CONSUMED]
    assert len(consumed) == 1 and consumed[0].actor_seat == witch
    assert isinstance(consumed[0].payload, WitchPotionConsumedPayload)
    assert consumed[0].payload.antidote is True and consumed[0].payload.poison is False
    assert player_at(cur, witch).witch_antidote is False
    # 事件流必须完整解释状态：从女巫窗口前的状态只靠这些事件 reduce 出同一终态
    assert reduce_all(state, emitted) == cur


def test_witch_poison_emits_potion_consumed_in_same_step() -> None:
    state, _history = _to_night_witch(seed=1)
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    victim = next(s for s in living_seats(state) if s != witch)
    before = state.state_version
    r = step(
        state,
        NightAction(actor_seat=witch, action_type=NightActionType.POISON, target_seat=victim),
    )
    assert r.rejection is None, r.rejection

    _assert_contiguous(before, r.events, r.state.state_version)
    types = [e.type for e in r.events[:2]]
    assert types == [EventType.WITCH_POISONED, EventType.WITCH_POTION_CONSUMED]
    assert player_at(r.state, witch).witch_poison is False
    assert reduce_all(state, r.events) == r.state
