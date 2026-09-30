"""死亡警长的警徽处置两步制（issue #90）：遗言回合只能发言，随后开只能 pass/tear 的窗口；
放逐与夜刀同源；规则关闭时回到一步制。"""

from collections.abc import Callable

from app.engine.actions import (
    Action,
    DayVote,
    NightAction,
    NightActionType,
    RejectedReason,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import Faction, GameConfig, LastWordsRule, RoleType, build_preset
from app.engine.engine import create_game, step
from app.engine.events import Event, EventType
from app.engine.phases import BADGE_ONLY_PREFIX, ElectionStage, Phase, expected_actors
from app.engine.state import GameState, living_seats, player_at
from app.runtime.defaults import default_action


def _cfg(window: bool) -> GameConfig:
    base = build_preset("std_9_kill_side").model_copy(
        update={"seed": 5, "last_words": LastWordsRule.FIRST_NIGHT_ONLY}
    )
    return base.model_copy(
        update={"sheriff": base.sheriff.model_copy(update={"night_death_badge_window": window})}
    )


def _drive(
    cfg: GameConfig, stop: Callable[[GameState], bool]
) -> tuple[GameState, list[Event], int]:
    """座位最大的村民独自上警当选；白天全场把他票出去。"""
    res = create_game(cfg, "g")
    state, events = res.state, list(res.events)
    cand = max(p.seat for p in state.players if p.role == RoleType.VILLAGER)

    def choose(s: GameState, seat: int) -> Action:
        if s.phase == Phase.NIGHT_WEREWOLF:
            target = min(
                x for x in living_seats(s) if player_at(s, x).faction != Faction.WOLF and x != cand
            )
            return NightAction(
                actor_seat=seat, action_type=NightActionType.KILL, target_seat=target
            )
        if s.phase == Phase.SHERIFF_ELECTION and s.election_stage == ElectionStage.CANDIDACY:
            at = SheriffActionType.RUN_FOR_SHERIFF if seat == cand else SheriffActionType.WITHDRAW
            return SheriffAction(actor_seat=seat, action_type=at)
        if s.phase == Phase.VOTE and s.sheriff_seat == cand and player_at(s, cand).alive:
            if seat == cand:
                return DayVote(actor_seat=seat, abstain=True)
            return DayVote(actor_seat=seat, target_seat=cand)
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


def _at_sheriff_last_words(s: GameState) -> bool:
    return (
        s.phase == Phase.LAST_WORDS
        and s.sheriff_seat is not None
        and not player_at(s, s.sheriff_seat).alive
        and s.speech_order[s.speech_idx :] != ()
        and s.speech_order[s.speech_idx] == s.sheriff_seat
        and not (s.resume_token or "").startswith(BADGE_ONLY_PREFIX)
    )


def test_exiled_sheriff_speaks_then_gets_badge_window() -> None:
    state, _ev, cand = _drive(_cfg(True), _at_sheriff_last_words)
    # 遗言回合：警徽动作被拒，发言合法
    tear = step(state, SheriffAction(actor_seat=cand, action_type=SheriffActionType.TEAR_BADGE))
    assert tear.rejection == RejectedReason.WRONG_PHASE
    spoke = step(state, Speak(actor_seat=cand, content="我是好人，警徽给能带票的人"))
    assert spoke.rejection is None
    assert any(e.type == EventType.LAST_WORDS for e in spoke.events)
    # 遗言说完自动开警徽窗口
    s2 = spoke.state
    assert s2.phase == Phase.LAST_WORDS
    assert (s2.resume_token or "").startswith(BADGE_ONLY_PREFIX)
    assert s2.speech_order == (cand,) and expected_actors(s2) == {cand}
    assert (
        step(s2, Speak(actor_seat=cand, content="再说两句")).rejection == RejectedReason.WRONG_PHASE
    )
    # 移交后按「白天死亡」续接：入夜
    heir = next(s for s in living_seats(s2) if s != cand)
    passed = step(
        s2,
        SheriffAction(actor_seat=cand, action_type=SheriffActionType.PASS_BADGE, target_seat=heir),
    )
    assert passed.rejection is None
    assert passed.state.sheriff_seat == heir and player_at(passed.state, heir).is_sheriff
    assert passed.state.round == 2 and passed.state.phase.name.startswith("NIGHT_")
    # 超时默认 = 撕徽
    dflt = step(s2, default_action(s2, cand))
    assert dflt.rejection is None and dflt.state.sheriff_seat is None


def test_legacy_single_step_when_window_disabled() -> None:
    state, _ev, cand = _drive(_cfg(False), _at_sheriff_last_words)
    # 旧行为：遗言回合里可直接撕徽 / 移交（顶替发言），无第二窗口
    tear = step(state, SheriffAction(actor_seat=cand, action_type=SheriffActionType.TEAR_BADGE))
    assert tear.rejection is None and tear.state.sheriff_seat is None
    assert not (tear.state.resume_token or "").startswith(BADGE_ONLY_PREFIX)
    spoke = step(state, Speak(actor_seat=cand, content="遗言"))
    assert spoke.rejection is None  # 旧行为：说了遗言就没有第二个窗口（警徽悬空）
    assert not (spoke.state.resume_token or "").startswith(BADGE_ONLY_PREFIX)
    assert spoke.state.phase != Phase.LAST_WORDS
