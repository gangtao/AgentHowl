"""默认行动表测试：全对局扫描证明任意可达窗口的默认行动必被引擎接受（issue #29）。"""

import pytest

from app.cli.bot import RandomBot
from app.engine.actions import (
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import Faction, build_preset
from app.engine.engine import create_game, step
from app.engine.phases import ElectionStage, Phase, expected_actors
from app.engine.state import living_seats, player_at
from app.runtime.defaults import TIMEOUT_SPEECH, default_action

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


def _sweep(preset: str, seed: int, **cfg_override: object) -> set[Phase]:
    """bot 驱动整局；每个待行动座位先探测默认行动可被接受，再用 bot 行动推进。"""
    cfg = build_preset(preset).model_copy(update={"seed": seed, **cfg_override})
    state = create_game(cfg, game_id="g").state
    seen: set[Phase] = set()
    guard = 0
    while state.phase != Phase.GAME_OVER:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            seen.add(state.phase)
            d = default_action(state, seat)
            probe = step(state, d)
            assert probe.rejection is None, (
                f"默认行动被拒：{probe.rejection} @ {state.phase}/{state.election_stage}"
            )
            # 关键分支的内容断言（在真实可达状态上验证表格语义）
            if state.phase == Phase.NIGHT_GUARD:
                assert isinstance(d, NightAction) and d.action_type == NightActionType.SKIP
            if state.phase == Phase.NIGHT_WITCH:
                assert isinstance(d, NightAction) and d.action_type == NightActionType.SKIP
            if state.phase == Phase.NIGHT_SEER:
                assert isinstance(d, NightAction)
                assert d.action_type in (NightActionType.CHECK, NightActionType.SKIP)
                if d.action_type == NightActionType.CHECK:
                    # 验证目标存活、不是自己、未验过
                    assert d.target_seat is not None
                    assert d.target_seat != seat
                    target_player = player_at(state, d.target_seat)
                    assert target_player.alive
                    checked = {int(rec["seat"]) for rec in state.seer_log.get(seat, [])}
                    assert d.target_seat not in checked
            if state.phase == Phase.NIGHT_WEREWOLF:
                assert isinstance(d, NightAction)
                if state.config.allow_wolf_empty_knife:
                    assert d.action_type == NightActionType.SKIP
                else:
                    assert d.action_type == NightActionType.KILL
                    assert d.target_seat is not None
                    target_player = player_at(state, d.target_seat)
                    assert target_player.alive
                    assert target_player.faction != Faction.WOLF
            if state.phase == Phase.HUNTER_SHOOT:
                assert isinstance(d, NightAction)
                assert d.action_type == NightActionType.SKIP
            if state.phase == Phase.VOTE and isinstance(d, DayVote):
                assert d.abstain
            if state.phase == Phase.DAY_SPEECH and isinstance(d, Speak):
                assert d.content == TIMEOUT_SPEECH
            if state.phase == Phase.LAST_WORDS:
                pl = player_at(state, seat)
                if pl.is_sheriff:
                    assert isinstance(d, SheriffAction)
                    assert d.action_type == SheriffActionType.TEAR_BADGE
                else:
                    assert isinstance(d, Speak)
                    assert d.content == TIMEOUT_SPEECH
            if (
                state.phase == Phase.SHERIFF_ELECTION
                and state.election_stage == ElectionStage.CANDIDACY
            ):
                assert isinstance(d, SheriffAction)
                assert d.action_type == SheriffActionType.WITHDRAW
            if (
                state.phase == Phase.SHERIFF_ELECTION
                and state.election_stage == ElectionStage.DIRECTION
            ):
                assert isinstance(d, SheriffAction)
                assert d.action_type == SheriffActionType.SET_SPEECH_DIRECTION
                assert d.direction == Direction.LEFT
            if (
                state.phase == Phase.SHERIFF_ELECTION
                and state.election_stage == ElectionStage.WITHDRAW
            ):
                # 退水确认窗口默认留任
                assert isinstance(d, SheriffAction)
                assert d.action_type == SheriffActionType.RUN_FOR_SHERIFF
            if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == ElectionStage.VOTE:
                assert isinstance(d, SheriffAction)
                assert d.action_type == SheriffActionType.VOTE_SHERIFF
                cands = sorted(state.sheriff_candidates) or living_seats(state)
                assert d.target_seat == cands[0]
            if state.phase == Phase.SHERIFF_PK and state.speech_idx >= len(state.speech_order):
                # 非发言窗口的 PK 投票
                assert isinstance(d, SheriffAction)
                assert d.action_type == SheriffActionType.VOTE_SHERIFF
                cands = sorted(state.sheriff_candidates) or living_seats(state)
                assert d.target_seat == cands[0]
            if state.phase == Phase.VOTE_PK and state.speech_idx >= len(state.speech_order):
                # 非发言窗口的普通 PK 投票
                assert isinstance(d, DayVote)
                assert d.abstain
            if (
                state.phase == Phase.VOTE_PK or state.phase == Phase.SHERIFF_PK
            ) and state.speech_idx < len(state.speech_order):
                # PK 发言期默认空发言，不得落投票分支
                assert isinstance(d, Speak)
                assert d.content == TIMEOUT_SPEECH
            # 推进沿用 bot（保持既有对局形态的覆盖广度）
            res = step(state, RandomBot.choose_action(state, seat))
            assert res.rejection is None
            state = res.state
        guard += 1
        assert guard < 100_000, "对局未收敛"
    return seen


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [3, 42])
def test_default_action_accepted_at_every_window(preset: str, seed: int) -> None:
    seen = _sweep(preset, seed)
    assert {Phase.NIGHT_WEREWOLF, Phase.DAY_SPEECH, Phase.VOTE} <= seen


@pytest.mark.parametrize("seed", [3, 42])
def test_default_action_with_empty_knife_disabled(seed: int) -> None:
    # 空刀被禁时狼的默认行动是确定性刀非狼目标，仍必被接受
    seen = _sweep("std_9_kill_side", seed, allow_wolf_empty_knife=False)
    assert Phase.NIGHT_WEREWOLF in seen


def test_default_is_deterministic() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    seat = sorted(expected_actors(state))[0]
    assert default_action(state, seat) == default_action(state, seat)
