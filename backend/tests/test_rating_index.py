"""RatingIndex（issue #123）：从事件日志推导 FinishedGame；只计已结束且带 agent_ids 的对局；
已结束对局只读一次（缓存）；坏文件跳过。"""

from __future__ import annotations

import logging
from typing import Any

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.state import GameState
from app.runtime.rating_index import RatingIndex
from app.store.event_store import GameMeta, InMemoryEventStore, SeatName, StoreCorruptionError


class _CountingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.event_loads: dict[str, int] = {}

    def load_events(self, game_id: str, from_seq: int = 0) -> list[Any]:
        self.event_loads[game_id] = self.event_loads.get(game_id, 0) + 1
        return super().load_events(game_id, from_seq)


def _finished(
    store: InMemoryEventStore,
    game_id: str,
    *,
    seed: int = 3,
    agent_ids: dict[str, str] | None = None,
    truncate: int | None = None,
    wall: bool = True,
) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id=game_id)
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(
        GameMeta(game_id=game_id, config=cfg, roster=roster, agent_ids=agent_ids or {})
    )
    kept = events if truncate is None else events[:truncate]
    for i, e in enumerate(kept):
        meta = {**e.meta, "wall_ts": f"2026-10-26T00:{i // 60:02d}:{i % 60:02d}+00:00"}
        store.append(game_id, e.model_copy(update={"meta": meta if wall else e.meta}))
    return final


def test_extract_finished_reads_factions_winner_and_ended_at() -> None:
    store = InMemoryEventStore()
    final = _finished(store, "g_a", agent_ids={"0": "a_x", "5": "a_y"})
    fg = RatingIndex(store).extract_finished("g_a")
    assert fg is not None and fg.game_id == "g_a"
    assert fg.winner == final.winner
    assert fg.seat_factions == {p.seat: p.faction for p in final.players}
    assert fg.agent_ids == {0: "a_x", 5: "a_y"}
    assert fg.ended_at == store.load_events("g_a")[-1].meta["wall_ts"]


def test_snapshot_only_counts_finished_games_with_ids() -> None:
    store = InMemoryEventStore()
    final = _finished(store, "g_ids", agent_ids={"0": "a_x", "5": "a_y"})
    _finished(store, "g_noids", seed=4)
    _finished(store, "g_cut", seed=5, agent_ids={"0": "a_z"}, truncate=40)
    index = RatingIndex(store)
    assert index.extract_finished("g_noids") is None
    assert index.extract_finished("g_cut") is None
    snap = index.snapshot()
    assert set(snap) == {"a_x", "a_y"}
    assert snap["a_x"].games == 1 and snap["a_y"].games == 1
    seat0 = final.players[0].faction
    if final.winner is None:
        assert snap["a_x"].draws == 1
    else:
        assert snap["a_x"].wins == (1 if seat0 == final.winner else 0)
    assert snap["a_x"].history[0].camp == seat0


def test_snapshot_caches_finished_games_only() -> None:
    store = _CountingStore()
    _finished(store, "g_ids", agent_ids={"0": "a_x"})
    _finished(store, "g_noids", seed=4)
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    _final, events = run_game(cfg, game_id="g_cut")
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(GameMeta(game_id="g_cut", config=cfg, roster=roster, agent_ids={"3": "a_z"}))
    for e in events[:40]:
        store.append("g_cut", e)
    index = RatingIndex(store)
    first = index.snapshot()
    second = index.snapshot()
    assert first == second and set(first) == {"a_x"}
    assert store.event_loads["g_ids"] == 1  # 已结束：缓存，只读一次
    assert "g_noids" not in store.event_loads  # 无 id：meta 判空即短路，不读事件也不缓存
    assert store.event_loads["g_cut"] == 2  # 未结束：不缓存
    for e in events[40:]:  # 补完 → 下次 snapshot 计入
        store.append("g_cut", e)
    third = index.snapshot()
    assert set(third) == {"a_x", "a_z"} and store.event_loads["g_cut"] == 3
    index.snapshot()
    assert store.event_loads["g_cut"] == 3 and store.event_loads["g_ids"] == 1


def test_ended_at_falls_back_to_ts_when_wall_ts_missing() -> None:
    store = InMemoryEventStore()
    _finished(store, "g_old", agent_ids={"0": "a_x"}, wall=False)
    fg = RatingIndex(store).extract_finished("g_old")
    assert fg is not None and fg.ended_at == str(store.load_events("g_old")[-1].ts)


def test_corrupt_game_is_skipped_with_warning(caplog) -> None:
    class _Boom(InMemoryEventStore):
        def load_meta(self, game_id: str) -> GameMeta:
            if game_id == "g_bad":
                raise StoreCorruptionError("g_bad.jsonl：meta 记录损坏")
            return super().load_meta(game_id)

    store = _Boom()
    _finished(store, "g_ok", agent_ids={"0": "a_x"})
    store._games["g_bad"] = store._games["g_ok"]  # noqa: SLF001 —— 让 list_games 列出它
    with caplog.at_level(logging.WARNING):
        snap = RatingIndex(store).snapshot()
    assert set(snap) == {"a_x"} and snap["a_x"].games == 1
    assert any("g_bad" in rec.getMessage() for rec in caplog.records)


def test_non_numeric_seat_key_in_meta_is_skipped_with_warning(caplog) -> None:
    store = InMemoryEventStore()
    _finished(store, "g_ok", agent_ids={"0": "a_x"})
    _finished(store, "g_bad", seed=4, agent_ids={"x": "a_bad"})
    with caplog.at_level(logging.WARNING):
        snap = RatingIndex(store).snapshot()
    assert "a_bad" not in snap and set(snap) == {"a_x"}
    assert any("g_bad" in rec.getMessage() for rec in caplog.records)


def test_snapshot_memoized_until_new_finished_game() -> None:
    """issue #139：已结束对局集合不变 → 复用上次快照对象；新终局 → 重算。"""
    store = InMemoryEventStore()
    _finished(store, "g_1", agent_ids={"0": "a_x"})
    index = RatingIndex(store)
    first = index.snapshot()
    assert index.snapshot() is first
    _finished(store, "g_2", seed=4, agent_ids={"0": "a_x", "3": "a_y"})
    second = index.snapshot()
    assert second is not first and second["a_x"].games == 2 and "a_y" in second
    assert index.snapshot() is second


def test_compute_ratings_is_linear_in_history_length() -> None:
    """issue #139：一个档案打 H 局，fold 不再做 O(H²) 的 history 复制。"""
    import time

    from app.engine.config import Faction
    from app.runtime.rating import FinishedGame, compute_ratings, settle_game

    def game(i: int) -> FinishedGame:
        return FinishedGame(
            game_id=f"g_{i:05d}",
            ended_at=f"2026-10-26T00:00:{i:05d}",
            winner="WOLF" if i % 2 else "GOOD",
            seat_factions={0: Faction.WOLF, 1: Faction.GOOD},
            agent_ids={0: "a_x", 1: "a_y"},
        )

    games = [game(i) for i in range(4000)]
    t0 = time.perf_counter()
    snap = compute_ratings(games)
    elapsed = time.perf_counter() - t0
    assert snap["a_x"].games == 4000 and len(snap["a_x"].history) == 4000
    assert elapsed < 3.0, elapsed  # 旧实现在此量级要复制 ~8M 条 history
    # 与逐局 settle_game 的纯函数结果一致（抽样 50 局）
    acc: dict[str, object] = {}
    for g in games[:50]:
        acc = settle_game(acc, g)  # type: ignore[arg-type]
    assert acc["a_x"].rating == compute_ratings(games[:50])["a_x"].rating  # type: ignore[union-attr]
