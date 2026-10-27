"""app.cli.rating（issue #123）：从 data/games 推导积分表，积分降序；已删除档案显示 (已删除)。"""

from __future__ import annotations

from pathlib import Path

from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.cli.rating import main
from app.engine.config import build_preset
from app.runtime.agent_library import JsonFileAgentLibrary, StoredAgent
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName


def test_rating_cli_prints_table_sorted_by_rating(tmp_path: Path) -> None:
    store = JsonFileEventStore(tmp_path / "games")
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, game_id="g_1")
    roster = tuple(SeatName(seat=i, display_name=f"P{i}") for i in range(9))
    ids = {"0": "a_kept", "4": "a_gone"}
    store.create_game(GameMeta(game_id="g_1", config=cfg, roster=roster, agent_ids=ids))
    for i, e in enumerate(events):
        wall = f"2026-10-26T00:00:{i % 60:02d}+00:00"
        store.append("g_1", e.model_copy(update={"meta": {**e.meta, "wall_ts": wall}}))
    JsonFileAgentLibrary(tmp_path / "agents").put(
        StoredAgent(
            agent_id="a_kept",
            profile=AgentProfile(name="夜枭", model="m"),
            created_at="t",
            updated_at="t",
        )
    )
    lines: list[str] = []
    main(["--data-dir", str(tmp_path)], out=lines.append)
    text = "\n".join(lines)
    assert "夜枭" in text and "(已删除)" in text and "a_gone" in text and "a_kept" in text
    # 顺序：积分降序；同分按场次再按 id（两者都 1 局，于是按 id：a_gone < a_kept）
    f0, f4 = final.players[0].faction, final.players[4].faction
    if final.winner is None or f0 == f4:
        expected = ["a_gone", "a_kept"]
    else:
        expected = ["a_kept", "a_gone"] if f0 == final.winner else ["a_gone", "a_kept"]
    idx = {aid: next(i for i, line in enumerate(lines) if aid in line) for aid in expected}
    assert idx[expected[0]] < idx[expected[1]]
    assert lines[0].startswith("档案")  # 表头


def test_rating_cli_empty_data_dir(tmp_path: Path) -> None:
    lines: list[str] = []
    main(["--data-dir", str(tmp_path / "empty")], out=lines.append)
    assert lines == ["没有带 agent_ids 的已结束对局；积分表为空"]
