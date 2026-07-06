"""游戏状态模型（frozen Pydantic）与只读查询 helper。

reduce 用 model_copy(update=...) 返回副本；本模块不含任何转移逻辑。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.config import Faction, GameConfig, RoleType
from app.engine.phases import Phase


class Player(BaseModel):
    model_config = ConfigDict(frozen=True)

    seat: int
    display_name: str
    player_type: Literal["HUMAN", "AGENT"] = "AGENT"
    role: RoleType
    faction: Faction
    alive: bool = True
    is_sheriff: bool = False
    idiot_revealed: bool = False
    can_vote: bool = True
    # 角色专属状态
    witch_antidote: bool = True
    witch_poison: bool = True
    hunter_can_shoot: bool = True
    last_guard_target: int | None = None


class NightActions(BaseModel):
    model_config = ConfigDict(frozen=True)

    guard_target: int | None = None
    wolf_target: int | None = None
    witch_save: bool = False
    witch_poison_target: int | None = None
    seer_check: int | None = None


class GameState(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    config: GameConfig
    phase: Phase
    round: int = 0
    players: tuple[Player, ...]
    sheriff_seat: int | None = None
    seer_log: dict[int, list[dict[str, int | str]]] = Field(default_factory=dict)
    # seat -> [{"round": r, "seat": s, "result": "GOOD"/"WOLF"}]

    # 发言与投票收集
    speech_order: tuple[int, ...] = ()
    speech_idx: int = 0
    votes: dict[int, int | None] = Field(default_factory=dict)
    vote_candidates: tuple[int, ...] = ()  # 空=全体存活；PK 时限定
    tie_round: int = 0  # 0=首轮投票，1=PK 轮

    # 夜晚收集
    pending_night: NightActions = Field(default_factory=NightActions)
    wolf_proposals: dict[int, int | None] = Field(default_factory=dict)  # seat->target(None=空刀)
    acted_seats: frozenset[int] = frozenset()  # 本夜已提交夜间行动的座位（含狼）
    night_deaths: tuple[int, ...] = ()  # 本夜结算出的死者（供公布/遗言）
    resolved_first_night: bool = False

    # 待处理技能 / 出局
    pending_hunter: int | None = None
    day_exiled: int | None = None

    winner: str | None = None
    rng_state: int = 0
    state_version: int = 0
    resume_token: str | None = None  # 中断（猎人开枪/遗言）处理完后的续接标记

    # 警长竞选
    sheriff_candidates: tuple[int, ...] = ()
    sheriff_declared: frozenset[int] = frozenset()
    sheriff_votes: dict[int, int | None] = Field(default_factory=dict)
    election_stage: str = (
        ""  # ""/"candidacy"/"vote"/"direction"/"announce"（PK 由 phase==SHERIFF_PK 区分）
    )
    sheriff_speech_direction: str | None = None  # 警长方向 "LEFT"/"RIGHT"（事实，经事件写入）


def player_at(state: GameState, seat: int) -> Player:
    for p in state.players:
        if p.seat == seat:
            return p
    raise KeyError(f"座位 {seat} 不存在")


def living(state: GameState) -> list[Player]:
    return [p for p in state.players if p.alive]


def living_seats(state: GameState) -> list[int]:
    return [p.seat for p in state.players if p.alive]


def living_wolves(state: GameState) -> list[Player]:
    return [p for p in state.players if p.alive and p.faction == Faction.WOLF]


def living_of_role(state: GameState, role: RoleType) -> list[Player]:
    return [p for p in state.players if p.alive and p.role == role]
