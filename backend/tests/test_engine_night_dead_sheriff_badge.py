"""夜死警长的警徽处置窗口（issue #85）：无遗言的夜晚死亡后，天亮前只能 pass/tear、不能发言；
规则关闭时保持旧行为（自动撕徽）。"""

from collections.abc import Callable

from app.engine.actions import (
    Action,
    NightAction,
    NightActionType,
    RejectedReason,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import Faction, GameConfig, LastWordsRule, RoleType, build_preset
from app.engine.engine import NIGHT_BADGE_ONLY, create_game, step
from app.engine.events import Event, EventType
from app.engine.phases import ElectionStage, Phase, expected_actors
from app.engine.state import GameState, living_seats, player_at
from app.runtime.defaults import default_action


def _cfg(window: bool) -> GameConfig:
    base = build_preset("std_9_kill_side").model_copy(
        update={"seed": 11, "last_words": LastWordsRule.FIRST_NIGHT_ONLY}
    )
    return base.model_copy(
        update={"sheriff": base.sheriff.model_copy(update={"night_death_badge_window": window})}
    )


def _drive(
    cfg: GameConfig, stop: Callable[[GameState], bool]
) -> tuple[GameState, list[Event], int]:
    """狼队首夜刀座位最小的好人；候选警长 = 座位最大的村民，只有他上警；第二夜起狼刀警长。"""
    res = create_game(cfg, "g")
    state, events = res.state, list(res.events)
    villagers = [p.seat for p in state.players if p.role == RoleType.VILLAGER]
    cand = max(villagers)

    def choose(s: GameState, seat: int) -> Action:
        if s.phase == Phase.NIGHT_WEREWOLF:
            if s.sheriff_seat is not None and player_at(s, s.sheriff_seat).alive:
                target = s.sheriff_seat
            else:
                target = min(
                    x
                    for x in living_seats(s)
                    if player_at(s, x).faction != Faction.WOLF and x != cand
                )
            return NightAction(
                actor_seat=seat, action_type=NightActionType.KILL, target_seat=target
            )
        if s.phase == Phase.SHERIFF_ELECTION and s.election_stage == ElectionStage.CANDIDACY:
            at = SheriffActionType.RUN_FOR_SHERIFF if seat == cand else SheriffActionType.WITHDRAW
            return SheriffAction(actor_seat=seat, action_type=at)
        return default_action(s, seat)

    guard = 0
    while not stop(state) and state.phase != Phase.GAME_OVER:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state) or stop(state):
                continue
            r = step(state, choose(state, seat))
            assert r.rejection is None, f"{r.rejection} @ {state.phase}/{state.election_stage}"
            state, events = r.state, [*events, *r.events]
        guard += 1
        assert guard < 300, "对局未推进到目标状态"
    return state, events, cand


def test_night_dead_sheriff_gets_badge_only_window() -> None:
    state, _events, cand = _drive(
        _cfg(True), lambda s: s.phase == Phase.LAST_WORDS and s.resume_token == NIGHT_BADGE_ONLY
    )
    assert state.sheriff_seat == cand and not player_at(state, cand).alive
    assert state.speech_order == (cand,) and expected_actors(state) == {cand}

    # 不能发言
    rej = step(state, Speak(actor_seat=cand, content="遗言")).rejection
    assert rej == RejectedReason.WRONG_PHASE

    # 移交给存活玩家 → 警徽易主、直接进入白天发言
    heir = next(s for s in living_seats(state) if s != cand)
    r = step(
        state,
        SheriffAction(actor_seat=cand, action_type=SheriffActionType.PASS_BADGE, target_seat=heir),
    )
    assert r.rejection is None
    passed = [e for e in r.events if e.type == EventType.BADGE_PASSED]
    assert len(passed) == 1 and passed[0].payload.to_seat == heir  # type: ignore[attr-defined]
    assert r.state.sheriff_seat == heir and player_at(r.state, heir).is_sheriff
    assert r.state.phase == Phase.DAY_SPEECH

    # 撕徽 / 超时默认（撕徽）同样合法
    tear = step(state, SheriffAction(actor_seat=cand, action_type=SheriffActionType.TEAR_BADGE))
    assert tear.rejection is None and tear.state.sheriff_seat is None
    dflt = step(state, default_action(state, cand))
    assert dflt.rejection is None and dflt.state.sheriff_seat is None


def test_window_disabled_keeps_auto_tear() -> None:
    state, events, cand = _drive(
        _cfg(False), lambda s: s.round >= 2 and s.phase == Phase.DAY_SPEECH
    )
    assert state.sheriff_seat is None and not player_at(state, cand).alive
    auto = [e for e in events if e.type == EventType.BADGE_PASSED]
    assert len(auto) == 1
    assert auto[0].payload.to_seat is None and auto[0].payload.consumed_turn is False  # type: ignore[attr-defined]
    assert not any(
        e.type == EventType.PHASE_CHANGED and e.payload.resume_token == NIGHT_BADGE_ONLY  # type: ignore[attr-defined]
        for e in events
    )
