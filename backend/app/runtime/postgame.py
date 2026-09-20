"""局后复盘编排（issue #59）：终局后对有 memory_id 的 Agent 端口做整局复盘并写入经验存储。

只在 GAME_OVER 后运行；单座位失败只记日志、不影响其他座位；对局中绝不写 store。
模块级不 import app.agent.agent_player（litellm 惰性加载）——端口能力用结构化协议判断。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.agent.experience import AgentExperience, GameReflection, GameReveal, build_reveal
from app.agent.profile import AgentProfiles, profile_for
from app.engine.phases import Phase
from app.engine.state import GameState
from app.runtime.experience_store import ExperienceStore
from app.runtime.player_port import PlayerPort

logger = logging.getLogger(__name__)


@runtime_checkable
class SupportsGameReflection(Protocol):
    """能做局后复盘的端口（AgentPlayerPort 实现）。"""

    async def reflect_on_game(self, reveal: GameReveal) -> GameReflection | None: ...


def seat_memory_ids(
    profiles: AgentProfiles, num_players: int, *, exclude: Collection[int] = ()
) -> dict[int, str]:
    """座位 → memory_id。exclude = 真人/外部端口占用的座位：其档案整体不生效（含 memory_id）。

    "*" 档案已被 validate_profiles 拒绝配 memory_id。
    """
    out: dict[int, str] = {}
    for seat in range(num_players):
        if seat in exclude:
            continue
        p = profile_for(profiles, seat)
        if p is not None and p.memory_id is not None:
            out[seat] = p.memory_id
    return out


def non_reflecting_seats(ports: Mapping[int, PlayerPort]) -> set[int]:
    """端口不支持局后复盘的座位（真人 / 外部端口 / 随机 bot）。"""
    return {s for s, p in ports.items() if not isinstance(p, SupportsGameReflection)}


def opponents_for(seat: int, seat_ids: Mapping[int, str]) -> dict[str, int]:
    """装配用：其他有 memory_id 的座位，memory_id → 本局座位。"""
    return {mid: s for s, mid in seat_ids.items() if s != seat}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def run_postgame(
    *,
    game_id: str,
    final_state: GameState,
    profiles: AgentProfiles,
    ports: Mapping[int, PlayerPort],
    store: ExperienceStore,
    now: Callable[[], str] = utc_now_iso,
) -> dict[str, AgentExperience]:
    """对每个有 memory_id 的 Agent 座位：揭示 → 复盘 → load → record_game → save。返回本次更新。"""
    if final_state.phase != Phase.GAME_OVER:
        raise ValueError("局后复盘只能在 GAME_OVER 后运行")
    seat_ids = seat_memory_ids(
        profiles, len(final_state.players), exclude=non_reflecting_seats(ports)
    )
    updated: dict[str, AgentExperience] = {}
    for seat, mid in seat_ids.items():
        port = ports.get(seat)
        if not isinstance(port, SupportsGameReflection):
            continue  # 真人占座 / 随机 bot：档案未生效
        try:
            notable = [s for s in seat_ids if s != seat]
            reveal = build_reveal(final_state, seat, notable_seats=notable)
            reflection = await port.reflect_on_game(reveal)
            if reflection is None:
                continue
            exp = store.load(mid)
            exp.record_game(
                game_id=game_id,
                role=reveal.my_role,
                won=reveal.my_won,
                reflection=reflection,
                seat_to_memory_id=seat_ids,
                my_seat=seat,
                ts=now(),
            )
            store.save(exp)
            updated[mid] = exp
        except Exception as exc:  # 单座位失败不影响其他座位
            logger.warning("memory_id=%s seat=%d 局后写入经验失败：%s", mid, seat, exc)
    return updated
