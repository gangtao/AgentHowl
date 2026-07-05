"""夜晚结算、票数统计、胜负判定 —— 全部纯函数，无 IO、无状态副作用。"""

from __future__ import annotations

from app.engine.config import Faction, GameConfig, RoleType, WinCondition, faction_of
from app.engine.state import GameState, NightActions


def resolve_night(config: GameConfig, na: NightActions) -> frozenset[int]:
    """实现规格 §3.3 结算：守卫挡刀不挡毒；同守同救按开关判死。"""
    deaths: set[int] = set()

    killed = na.wolf_target
    if killed is not None:
        protected = killed == na.guard_target
        rescued = na.witch_save
        if protected and rescued and config.guard.guard_plus_antidote_cancels:
            deaths.add(killed)  # 同守同救 -> 奶死
        elif protected or rescued:
            pass  # 活
        else:
            deaths.add(killed)

    if na.witch_poison_target is not None:
        deaths.add(na.witch_poison_target)  # 毒穿守

    return frozenset(deaths)


def count_votes(
    votes: dict[int, int | None], weights: dict[int, float]
) -> tuple[int | None, tuple[int, ...]]:
    """加权计票。返回 (唯一最高票座位 或 None, 并列最高票座位升序元组)。"""
    tally: dict[int, float] = {}
    for voter, target in votes.items():
        if target is None:
            continue
        tally[target] = tally.get(target, 0.0) + weights.get(voter, 1.0)

    if not tally:
        return None, ()

    top = max(tally.values())
    leaders = sorted(seat for seat, w in tally.items() if w == top)
    if len(leaders) == 1:
        return leaders[0], ()
    return None, tuple(leaders)


def _alive_by_faction(state: GameState) -> tuple[int, int]:
    wolves = sum(1 for p in state.players if p.alive and p.faction == Faction.WOLF)
    goods = sum(1 for p in state.players if p.alive and p.faction == Faction.GOOD)
    return wolves, goods


def check_win(state: GameState) -> str | None:
    """屠边/屠城胜负判定。GOOD/WOLF/None。"""
    wolves, goods = _alive_by_faction(state)

    if wolves == 0:
        return "GOOD"
    if goods == 0:
        return "WOLF"

    if state.config.win_condition == WinCondition.KILL_ALL:
        return None  # 屠城：好人未清光则继续

    # 屠边：村民全灭 或 神职全灭 -> 狼胜
    villagers = sum(
        1 for p in state.players if p.alive and p.role == RoleType.VILLAGER
    )
    gods = sum(
        1
        for p in state.players
        if p.alive and faction_of(p.role) == Faction.GOOD and p.role != RoleType.VILLAGER
    )
    has_villagers_in_setup = any(
        slot.role == RoleType.VILLAGER and slot.count > 0 for slot in state.config.roles
    )
    has_gods_in_setup = any(
        slot.role != RoleType.VILLAGER
        and faction_of(slot.role) == Faction.GOOD
        and slot.count > 0
        for slot in state.config.roles
    )
    if has_villagers_in_setup and villagers == 0:
        return "WOLF"
    if has_gods_in_setup and gods == 0:
        return "WOLF"
    return None
