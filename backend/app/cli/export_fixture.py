"""前端 reducer 金样导出（issue #26）：meta + 全部事件 + 每条事件后的完整状态。零 LLM。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import reduce
from app.store.event_store import GameMeta, SeatName, event_to_json, initial_state

_SET_FIELDS = ("acted_seats", "sheriff_declared", "sheriff_withdrawn", "sheriff_confirmed")


def _state_json(state: Any) -> dict[str, Any]:
    d: dict[str, Any] = state.model_dump(mode="json")
    for k in _SET_FIELDS:  # frozenset 序列化顺序不保证：统一升序（规格 §3）
        d[k] = sorted(d[k])
    return d


def export_fixture(preset: str, seed: int) -> dict[str, Any]:
    config = build_preset(preset).model_copy(update={"seed": seed})
    final, events = run_game(config, game_id=f"fx-{preset}-{seed}")
    roster = tuple(SeatName(seat=p.seat, display_name=p.display_name) for p in final.players)
    meta = GameMeta(game_id=final.game_id, config=config, roster=roster)
    state = initial_state(meta)
    states: list[dict[str, Any]] = []
    for e in events:
        state = reduce(state, e)
        states.append(_state_json(state))
    return {
        "preset": preset,
        "seed": seed,
        "meta": meta.model_dump(mode="json"),
        "events": [event_to_json(e) for e in events],
        "states": states,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli.export_fixture")
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    doc = export_fixture(args.preset, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{out}: {len(doc['events'])} events")


if __name__ == "__main__":
    main()
