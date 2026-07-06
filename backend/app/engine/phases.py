"""阶段枚举与转移逻辑：夜间阶段序、角色到阶段映射、expected_actors。"""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    LOBBY = "LOBBY"
    ROLE_ASSIGN = "ROLE_ASSIGN"
    NIGHT_GUARD = "NIGHT_GUARD"
    NIGHT_WEREWOLF = "NIGHT_WEREWOLF"
    NIGHT_WITCH = "NIGHT_WITCH"
    NIGHT_SEER = "NIGHT_SEER"
    NIGHT_HUNTER_CONFIRM = "NIGHT_HUNTER_CONFIRM"
    WIN_CHECK = "WIN_CHECK"
    SHERIFF_ELECTION = "SHERIFF_ELECTION"
    SHERIFF_PK = "SHERIFF_PK"
    DEATH_ANNOUNCE = "DEATH_ANNOUNCE"
    LAST_WORDS = "LAST_WORDS"
    DAY_SPEECH = "DAY_SPEECH"
    VOTE = "VOTE"
    VOTE_PK = "VOTE_PK"
    EXILE = "EXILE"
    HUNTER_SHOOT = "HUNTER_SHOOT"
    IDIOT_FLIP = "IDIOT_FLIP"
    GAME_OVER = "GAME_OVER"


from app.engine.config import GameConfig, RoleType  # noqa: E402
from app.engine.state import (  # noqa: E402
    GameState,
    living,
    living_of_role,
    living_wolves,
)

_ROLE_TO_NIGHT_PHASE: dict[RoleType, Phase] = {
    RoleType.GUARD: Phase.NIGHT_GUARD,
    RoleType.WEREWOLF: Phase.NIGHT_WEREWOLF,
    RoleType.WITCH: Phase.NIGHT_WITCH,
    RoleType.SEER: Phase.NIGHT_SEER,
    RoleType.HUNTER: Phase.NIGHT_HUNTER_CONFIRM,
}


def phase_for_role(role: RoleType) -> Phase | None:
    """返回角色对应的夜间阶段；无夜间行动的角色返回 None。"""
    return _ROLE_TO_NIGHT_PHASE.get(role)


def night_phase_sequence(config: GameConfig) -> list[Phase]:
    """按 config.night_order 过滤出有对应夜间阶段的角色序列（去重）。"""
    seq: list[Phase] = []
    for role in config.night_order:
        ph = phase_for_role(role)
        if ph is not None and ph not in seq:
            seq.append(ph)
    return seq


def next_night_phase(config: GameConfig, current: Phase) -> Phase | None:
    """序列中 current 的下一夜间阶段；末尾或未找到返回 None。"""
    seq = night_phase_sequence(config)
    if current not in seq:
        return seq[0] if seq else None
    idx = seq.index(current)
    return seq[idx + 1] if idx + 1 < len(seq) else None


def expected_actors(state: GameState) -> set[int]:
    """当前必须行动的座位集合；系统阶段返回空集。"""
    ph = state.phase

    if ph == Phase.NIGHT_GUARD:
        return {
            p.seat for p in living_of_role(state, RoleType.GUARD) if p.seat not in state.acted_seats
        }
    if ph == Phase.NIGHT_WEREWOLF:
        return {w.seat for w in living_wolves(state) if w.seat not in state.wolf_proposals}
    if ph == Phase.NIGHT_WITCH:
        return {
            w.seat
            for w in living_of_role(state, RoleType.WITCH)
            if w.seat not in state.acted_seats and (w.witch_antidote or w.witch_poison)
        }
    if ph == Phase.NIGHT_SEER:
        return {
            p.seat for p in living_of_role(state, RoleType.SEER) if p.seat not in state.acted_seats
        }
    if ph == Phase.NIGHT_HUNTER_CONFIRM:
        # M1：猎人首夜确认无决策，作为系统直通阶段（can_shoot 在死亡时判定）
        return set()

    if ph == Phase.DAY_SPEECH:
        if state.speech_idx < len(state.speech_order):
            return {state.speech_order[state.speech_idx]}
        return set()

    if ph == Phase.VOTE:
        return {p.seat for p in living(state) if p.can_vote and p.seat not in state.votes}
    if ph == Phase.VOTE_PK:
        return {
            p.seat
            for p in living(state)
            if p.can_vote and p.seat not in state.vote_candidates and p.seat not in state.votes
        }

    if ph == Phase.HUNTER_SHOOT:
        return {state.pending_hunter} if state.pending_hunter is not None else set()

    if ph == Phase.LAST_WORDS:
        if state.speech_idx < len(state.speech_order):
            return {state.speech_order[state.speech_idx]}
        return set()

    if ph == Phase.SHERIFF_ELECTION:
        if state.election_stage == "candidacy":
            return {p.seat for p in living(state) if p.seat not in state.sheriff_declared}
        if state.election_stage == "vote":
            return {
                p.seat
                for p in living(state)
                if p.can_vote
                and p.seat not in state.sheriff_candidates
                and p.seat not in state.sheriff_votes
            }
        if state.election_stage == "direction":
            return {state.sheriff_seat} if state.sheriff_seat is not None else set()
        return set()
    if ph == Phase.SHERIFF_PK:
        return {
            p.seat
            for p in living(state)
            if p.can_vote
            and p.seat not in state.sheriff_candidates
            and p.seat not in state.sheriff_votes
        }

    # 其余为系统阶段
    return set()
