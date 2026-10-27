"""Agent 积分与战绩纯函数（issue #123）：Elo 风格阵营评分 + 胜/负/平，零 IO。

规则见 docs/superpowers/specs/2026-10-26-agent-rating-design.md §3.2。积分完全由已结束
对局推导（与 state = reduce(events) 同一思路），本模块不持有任何状态；只依赖 pydantic 与
app.engine.config.Faction。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.config import Faction

INITIAL_RATING = 1000.0
K_FACTOR = 32.0
HISTORY_LIMIT = 200  # API 输出截取最近 N 条；内存里全量

Result = Literal["WIN", "LOSS", "DRAW"]


class FinishedGame(BaseModel):
    """一局已结束对局的计分输入（RatingIndex 从事件日志提取）。"""

    model_config = ConfigDict(frozen=True)

    game_id: str
    ended_at: str  # GAME_OVER 事件的 meta.wall_ts（ISO 8601），缺失时退回事件 ts
    winner: str | None  # "GOOD" | "WOLF" | None（平局）
    seat_factions: dict[int, Faction]
    agent_ids: dict[int, str]  # 已展开：座位 → agent_id（只含库内档案座位）


class CampRecord(BaseModel):
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


class RatingEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    ended_at: str
    camp: Faction
    result: Result
    delta: float


def _empty_camps() -> dict[Faction, CampRecord]:
    return {Faction.GOOD: CampRecord(), Faction.WOLF: CampRecord()}


class AgentRating(BaseModel):
    rating: float = INITIAL_RATING
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    by_camp: dict[Faction, CampRecord] = Field(default_factory=_empty_camps)
    history: list[RatingEntry] = Field(default_factory=list)  # 时间顺序，全量


def expected_score(own: float, other: float) -> float:
    """Elo 期望得分：own 对 other 的期望胜率。"""
    return 1.0 / (1.0 + 10 ** ((other - own) / 400.0))


def _result_for(camp: Faction, winner: str | None) -> Result:
    if winner is None:
        return "DRAW"
    return "WIN" if winner == camp else "LOSS"


class _Acc:
    """compute_ratings 的可变累加器（issue #139）：history 用 list 原地追加，整段 fold 线性；
    最后一次性构造不可变的 AgentRating。settle_game 的纯函数接口不变。"""

    __slots__ = ("by_camp", "draws", "games", "history", "losses", "rating", "wins")

    def __init__(self, base: AgentRating | None = None) -> None:
        b = base or AgentRating()
        self.rating = b.rating
        self.games, self.wins, self.losses, self.draws = b.games, b.wins, b.losses, b.draws
        self.by_camp: dict[Faction, CampRecord] = dict(b.by_camp)
        self.history: list[RatingEntry] = list(b.history)

    def to_rating(self) -> AgentRating:
        return AgentRating(
            rating=self.rating,
            games=self.games,
            wins=self.wins,
            losses=self.losses,
            draws=self.draws,
            by_camp=dict(self.by_camp),
            history=list(self.history),
        )


def _settle_into(acc: dict[str, _Acc], game: FinishedGame) -> None:
    """把一局结果累加进 acc（原地）。规则见 settle_game 文档。"""

    def rating_of(seat: int) -> float:
        aid = game.agent_ids.get(seat)
        return acc[aid].rating if aid is not None and aid in acc else INITIAL_RATING

    seats = sorted(game.seat_factions)
    wolves = [s for s in seats if game.seat_factions[s] == Faction.WOLF]
    goods = [s for s in seats if game.seat_factions[s] == Faction.GOOD]
    if not wolves or not goods:
        return
    r_wolf = fmean(rating_of(s) for s in wolves)
    r_good = fmean(rating_of(s) for s in goods)
    s_wolf = 0.5 if game.winner is None else (1.0 if game.winner == Faction.WOLF else 0.0)
    delta_wolf = K_FACTOR * (s_wolf - expected_score(r_wolf, r_good))
    deltas = {Faction.WOLF: delta_wolf, Faction.GOOD: -delta_wolf}

    touched: list[tuple[str, Faction]] = []  # 按座位顺序去重，保证 history 顺序确定
    for seat in seats:
        aid = game.agent_ids.get(seat)
        if aid is None:
            continue
        key = (aid, game.seat_factions[seat])
        if key not in touched:
            touched.append(key)

    for aid, camp in touched:
        a = acc.get(aid)
        if a is None:
            a = acc[aid] = _Acc()
        result = _result_for(camp, game.winner)
        delta = deltas[camp]
        won, lost, drew = result == "WIN", result == "LOSS", result == "DRAW"
        rec = a.by_camp[camp]
        a.by_camp[camp] = rec.model_copy(
            update={
                "games": rec.games + 1,
                "wins": rec.wins + int(won),
                "losses": rec.losses + int(lost),
                "draws": rec.draws + int(drew),
            }
        )
        a.history.append(
            RatingEntry(
                game_id=game.game_id, ended_at=game.ended_at, camp=camp, result=result, delta=delta
            )
        )
        a.rating += delta
        a.games += 1
        a.wins += int(won)
        a.losses += int(lost)
        a.draws += int(drew)


def settle_game(ratings: Mapping[str, AgentRating], game: FinishedGame) -> dict[str, AgentRating]:
    """把一局结果记到各档案上，返回新 dict（不改入参）。

    队伍均分按座位算（无 id 的座位按 INITIAL_RATING 代入，参与均值但不落账）；记账粒度是
    「档案 × 阵营」：同阵营多座位只记一条，两个阵营都占则记两条（Δ 相抵）。全员同阵营的
    坏数据对局原样返回。
    """
    acc = {aid: _Acc(r) for aid, r in ratings.items()}
    _settle_into(acc, game)
    return {aid: a.to_rating() for aid, a in acc.items()}


def compute_ratings(games: Iterable[FinishedGame]) -> dict[str, AgentRating]:
    """按 (ended_at, game_id) 升序逐局 fold；输入顺序不影响结果；无 agent_ids 的对局跳过。"""
    acc: dict[str, _Acc] = {}
    for game in sorted(games, key=lambda g: (g.ended_at, g.game_id)):
        if not game.agent_ids:
            continue
        _settle_into(acc, game)
    return {aid: a.to_rating() for aid, a in acc.items()}
