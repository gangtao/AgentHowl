"""对局摘要（issue #98）：从事件流派生 finished / live / aborted 三态；坏文件跳过。"""

import asyncio
import logging

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import EventType
from app.runtime.history import is_finished, list_history, summarize_game
from app.runtime.registry import GameRegistry
from app.store.event_store import GameMeta, InMemoryEventStore, SeatName


def _finished_game(store: InMemoryEventStore, game_id: str, seed: int = 3) -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    _final, events = run_game(cfg, game_id=game_id)
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    store.create_game(GameMeta(game_id=game_id, config=cfg, roster=roster, agents={}))
    for i, e in enumerate(events):
        wall = f"2026-10-02T00:00:{i % 60:02d}+00:00"
        store.append(game_id, e.model_copy(update={"meta": {**e.meta, "wall_ts": wall}}))


def test_summarize_finished_game() -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_done")
    meta, events = store.load_meta("g_done"), store.load_events("g_done")
    s = summarize_game(meta, events, live=False)
    assert s.status == "finished" and is_finished(events)
    assert s.preset == "std_9_kill_side" and s.num_players == 9
    assert s.winner in ("GOOD", "WOLF")
    assert s.rounds == max(
        int(e.payload.round)  # type: ignore[attr-defined]
        for e in events
        if e.type == EventType.ROUND_STARTED
    )
    assert s.started_at == events[0].meta["wall_ts"] and s.ended_at == events[-1].meta["wall_ts"]
    assert s.seq == events[-1].seq
    assert [x.seat for x in s.seats] == list(range(9)) and not any(x.agent for x in s.seats)


def test_summarize_aborted_and_live() -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_cut")
    meta, events = store.load_meta("g_cut"), store.load_events("g_cut")
    partial = events[:40]  # 截断：没有 GAME_OVER
    assert not is_finished(partial)
    assert summarize_game(meta, partial, live=False).status == "aborted"
    assert summarize_game(meta, partial, live=True).status == "live"
    s = summarize_game(meta, partial, live=False)
    assert s.ended_at is None and s.winner is None and s.seq == partial[-1].seq


def test_seats_mark_agents_from_meta() -> None:
    from app.agent.profile import AgentProfile

    store = InMemoryEventStore()
    _finished_game(store, "g_a")
    meta = store.load_meta("g_a").model_copy(
        update={"agents": {"2": AgentProfile(name="夜枭", model="ollama/x")}}
    )
    s = summarize_game(meta, store.load_events("g_a"), live=False)
    assert s.seats[2].agent is True and s.seats[0].agent is False


async def test_list_history_sorts_desc_and_skips_corrupt(caplog) -> None:
    store = InMemoryEventStore()
    _finished_game(store, "g_old", seed=1)
    _finished_game(store, "g_new", seed=2)
    # 让 g_new 的首条事件更晚
    old = store.load_events("g_new")
    new_wall = "2026-10-03T00:00:00+00:00"
    store._games["g_new"] = (  # noqa: SLF001 —— 测试直写内存实现
        store.load_meta("g_new"),
        [e.model_copy(update={"meta": {**e.meta, "wall_ts": new_wall}}) for e in old],
    )
    # 坏记录：有 meta 但事件为空也能列出（started_at None 排最后）；load 抛错的要跳过
    store._games["g_bad"] = (store.load_meta("g_old"), [])  # noqa: SLF001

    class _Boom(InMemoryEventStore):
        def load_events(self, game_id: str, from_seq: int = 0):  # type: ignore[override]
            if game_id == "g_bad":
                raise RuntimeError("坏文件")
            return super().load_events(game_id, from_seq)

    boom = _Boom()
    boom._games = store._games  # noqa: SLF001
    registry = GameRegistry(boom, None, None, None, None)  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="app.runtime.history"):
        out = list_history(boom, registry)
    assert [s.game_id for s in out] == ["g_new", "g_old"]
    assert any("g_bad" in r.getMessage() for r in caplog.records)
    await asyncio.sleep(0)  # 保持 async 用例形态（asyncio_mode=auto）
