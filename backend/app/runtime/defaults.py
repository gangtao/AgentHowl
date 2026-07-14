"""超时默认行动表（PRD §5.5）：纯函数、零 IO，保证对局永不因玩家挂起而停摆。

随机分支走引擎 seeded RNG（purpose 前缀 default:），与 bot 同口径，可复现。
"""

from __future__ import annotations

from app.engine import rng
from app.engine.actions import (
    Action,
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import Faction
from app.engine.phases import ElectionStage, Phase
from app.engine.state import GameState, living_seats, player_at

TIMEOUT_SPEECH = "（超时，未发言）"


def default_action(state: GameState, seat: int) -> Action:
    """座位 seat 在当前窗口的默认行动（PRD §5.5 表）。"""
    ph = state.phase
    pl = player_at(state, seat)
    seed = state.config.seed if state.config.seed is not None else 0

    def pick(items: list[int], salt: str) -> int:
        idx = rng.derive_int(
            seed=seed,
            purpose=f"default:{seat}:{salt}",
            seq=state.state_version,
            modulo=len(items),
        )
        return items[idx]

    # PK 发言期（VOTE_PK / SHERIFF_PK 的发言队列）：空发言跳过
    if ph in (Phase.VOTE_PK, Phase.SHERIFF_PK) and state.speech_idx < len(state.speech_order):
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)

    if ph in (Phase.NIGHT_GUARD, Phase.NIGHT_WITCH):
        # 守卫=空守；女巫=不用药
        return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
    if ph == Phase.NIGHT_WEREWOLF:
        if state.config.allow_wolf_empty_knife:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        targets = [s for s in living_seats(state) if player_at(state, s).faction != Faction.WOLF]
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.KILL,
            target_seat=pick(targets, "kill"),
        )
    if ph == Phase.NIGHT_SEER:
        # 验一名未验过的存活他人（不浪费夜信息）；无可验者才 skip
        checked = {int(rec["seat"]) for rec in state.seer_log.get(seat, [])}
        targets = [s for s in living_seats(state) if s != seat and s not in checked]
        if not targets:
            return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)
        return NightAction(
            actor_seat=seat,
            action_type=NightActionType.CHECK,
            target_seat=pick(targets, "check"),
        )
    if ph == Phase.HUNTER_SHOOT:
        return NightAction(actor_seat=seat, action_type=NightActionType.SKIP)

    if ph == Phase.DAY_SPEECH:
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)
    if ph == Phase.LAST_WORDS:
        if pl.is_sheriff:
            # 警长遗言窗口的期望行动是警徽处置：默认撕掉（警徽流失）
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.TEAR_BADGE)
        return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)

    if ph in (Phase.VOTE, Phase.VOTE_PK):
        return DayVote(actor_seat=seat, abstain=True)

    if ph == Phase.SHERIFF_ELECTION:
        stage = state.election_stage
        if stage == ElectionStage.CANDIDACY:
            # 不上警
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.WITHDRAW)
        if stage == ElectionStage.WITHDRAW:
            # 退水确认窗口：默认留任
            return SheriffAction(actor_seat=seat, action_type=SheriffActionType.RUN_FOR_SHERIFF)
        if stage == ElectionStage.DIRECTION:
            return SheriffAction(
                actor_seat=seat,
                action_type=SheriffActionType.SET_SPEECH_DIRECTION,
                direction=Direction.LEFT,
            )
        # vote 子阶段：引擎无警上弃票语义，确定性投最小座位号候选人
        cands = sorted(state.sheriff_candidates) or living_seats(state)
        return SheriffAction(
            actor_seat=seat,
            action_type=SheriffActionType.VOTE_SHERIFF,
            target_seat=cands[0],
        )
    if ph == Phase.SHERIFF_PK:
        cands = sorted(state.sheriff_candidates) or living_seats(state)
        return SheriffAction(
            actor_seat=seat,
            action_type=SheriffActionType.VOTE_SHERIFF,
            target_seat=cands[0],
        )

    # 兜底：一切发言型窗口空发言（与 bot 的兜底同构）
    return Speak(actor_seat=seat, content=TIMEOUT_SPEECH)
