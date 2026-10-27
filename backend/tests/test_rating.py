"""积分纯函数（issue #123）：Elo 阵营评分 + 胜/负/平战绩；零 IO、零 mock。"""

from __future__ import annotations

import pytest

from app.engine.config import Faction
from app.runtime.rating import (
    INITIAL_RATING,
    K_FACTOR,
    AgentRating,
    FinishedGame,
    compute_ratings,
    expected_score,
    settle_game,
)

W, G = Faction.WOLF, Faction.GOOD
# 9 人局：0-2 狼，3-8 好人
FACTIONS = {s: (W if s < 3 else G) for s in range(9)}
T0 = "2026-10-26T10:00:00+00:00"


def _game(
    game_id: str, winner: str | None, agent_ids: dict[int, str], ended_at: str = T0
) -> FinishedGame:
    return FinishedGame(
        game_id=game_id,
        ended_at=ended_at,
        winner=winner,
        seat_factions=FACTIONS,
        agent_ids=agent_ids,
    )


def test_expected_score_symmetry_and_known_values() -> None:
    assert expected_score(1000.0, 1000.0) == 0.5
    assert expected_score(1100.0, 1000.0) == pytest.approx(0.640065, abs=1e-6)
    assert expected_score(1000.0, 1100.0) + expected_score(1100.0, 1000.0) == pytest.approx(1.0)


def test_wolf_win_from_equal_ratings_gives_plus_minus_16() -> None:
    out = compute_ratings([_game("g1", "WOLF", {0: "wolf_a", 3: "good_a"})])
    wolf, good = out["wolf_a"], out["good_a"]
    assert wolf.rating == pytest.approx(INITIAL_RATING + 16.0)
    assert good.rating == pytest.approx(INITIAL_RATING - 16.0)
    assert (wolf.games, wolf.wins, wolf.losses, wolf.draws) == (1, 1, 0, 0)
    assert (good.games, good.wins, good.losses, good.draws) == (1, 0, 1, 0)
    assert wolf.by_camp[W].wins == 1 and wolf.by_camp[G].games == 0
    assert good.by_camp[G].losses == 1 and good.by_camp[W].games == 0
    entry = wolf.history[0]
    assert (entry.game_id, entry.camp, entry.result, entry.ended_at) == ("g1", W, "WIN", T0)
    assert entry.delta == pytest.approx(16.0)


def test_good_win_and_draw() -> None:
    good = compute_ratings([_game("g1", "GOOD", {0: "w", 3: "g"})])
    assert good["w"].rating == pytest.approx(984.0) and good["g"].rating == pytest.approx(1016.0)
    assert good["w"].losses == 1 and good["g"].wins == 1
    draw = compute_ratings([_game("g1", None, {0: "w", 3: "g"})])
    assert draw["w"].rating == pytest.approx(1000.0) and draw["g"].rating == pytest.approx(1000.0)
    assert draw["w"].draws == 1 and draw["g"].draws == 1
    assert draw["w"].history[0].result == "DRAW" and draw["w"].history[0].delta == 0.0


def test_team_average_uses_seats_and_initial_for_seats_without_id() -> None:
    # 狼队：座位 0 档案 1300 分，座位 1、2 无 id（按 1000 代入）→ Rw = 1100；好人全 1000
    prior = {"strong": AgentRating(rating=1300.0)}
    after = settle_game(prior, _game("g1", "WOLF", {0: "strong", 3: "g"}))
    e_w = expected_score(1100.0, 1000.0)
    assert after["strong"].rating == pytest.approx(1300.0 + K_FACTOR * (1.0 - e_w))
    assert after["g"].rating == pytest.approx(1000.0 - K_FACTOR * (1.0 - e_w))
    # 平局对强队是负增量（刻意：Elo 平局语义）
    drawn = settle_game(prior, _game("g1", None, {0: "strong", 3: "g"}))
    assert drawn["strong"].rating == pytest.approx(1300.0 + K_FACTOR * (0.5 - e_w))
    assert drawn["strong"].rating < 1300.0 and drawn["strong"].draws == 1


def test_same_camp_delta_shared_and_opposite_camps_negate() -> None:
    out = compute_ratings([_game("g1", "GOOD", {0: "w1", 1: "w2", 3: "g1", 4: "g2"})])
    assert out["w1"].history[0].delta == out["w2"].history[0].delta
    assert out["g1"].history[0].delta == out["g2"].history[0].delta
    assert out["w1"].history[0].delta == pytest.approx(-out["g1"].history[0].delta)


def test_same_agent_multiple_seats_same_camp_counts_once() -> None:
    # 同档案占 3 个狼座：均分里权重 3（全 1000 时仍是 1000），但 games / Δ 只记一次
    out = compute_ratings([_game("g1", "WOLF", {0: "a", 1: "a", 2: "a"})])
    assert out["a"].games == 1 and out["a"].wins == 1 and len(out["a"].history) == 1
    assert out["a"].rating == pytest.approx(1016.0)


def test_same_agent_in_both_camps_gets_two_entries_that_cancel() -> None:
    out = compute_ratings([_game("g1", "WOLF", {0: "a", 3: "a"})])
    a = out["a"]
    assert a.games == 2 and a.wins == 1 and a.losses == 1
    assert [e.camp for e in a.history] == [W, G]
    assert [e.result for e in a.history] == ["WIN", "LOSS"]
    assert a.rating == pytest.approx(INITIAL_RATING)
    assert a.by_camp[W].wins == 1 and a.by_camp[G].losses == 1


def test_order_by_ended_at_then_game_id_regardless_of_input_order() -> None:
    t1 = "2026-10-26T11:00:00+00:00"
    g1 = _game("g1", "WOLF", {0: "a", 3: "b"}, ended_at=T0)
    g2 = _game("g2", "GOOD", {0: "a", 3: "b"}, ended_at=t1)
    g0 = _game("g0", "GOOD", {0: "a", 3: "b"}, ended_at=t1)  # 同时刻：按 game_id 决胜
    forward = compute_ratings([g1, g2, g0])
    backward = compute_ratings([g0, g2, g1])
    assert forward == backward
    assert [e.game_id for e in forward["a"].history] == ["g1", "g0", "g2"]


def test_games_without_agent_ids_are_skipped() -> None:
    assert compute_ratings([_game("g1", "WOLF", {})]) == {}


def test_settle_game_does_not_mutate_input() -> None:
    prior = {"a": AgentRating(rating=1200.0)}
    snapshot = prior["a"].model_copy(deep=True)
    settle_game(prior, _game("g1", "WOLF", {0: "a", 3: "b"}))
    assert prior == {"a": snapshot} and "b" not in prior


def test_single_faction_game_is_ignored() -> None:
    # 坏数据兜底：全员同阵营（均分无法计算）→ 原样返回，不除零
    g = FinishedGame(
        game_id="g", ended_at=T0, winner="WOLF", seat_factions={0: W, 1: W}, agent_ids={0: "a"}
    )
    assert settle_game({}, g) == {}
