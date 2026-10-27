"""Agent 档案 API 的响应模型（issue #123）：档案 + 积分摘要。"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from app.runtime.agent_library import StoredAgent
from app.runtime.rating import INITIAL_RATING, AgentRating


class RatingSummary(BaseModel):
    """档案卡片用的积分摘要；没打过 = 1000 / 0。"""

    rating: float = INITIAL_RATING
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


class StoredAgentWithRating(StoredAgent):
    rating: RatingSummary = RatingSummary()


def with_rating(stored: StoredAgent, ratings: Mapping[str, AgentRating]) -> StoredAgentWithRating:
    r = ratings.get(stored.agent_id)
    summary = (
        RatingSummary()
        if r is None
        else RatingSummary(
            rating=r.rating, games=r.games, wins=r.wins, losses=r.losses, draws=r.draws
        )
    )
    return StoredAgentWithRating(**stored.model_dump(), rating=summary)
