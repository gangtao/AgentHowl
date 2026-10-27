"""CLI：uv run python -m app.cli.rating [--data-dir data] —— 打印 Agent 积分表（issue #123）。

只读核对工具：从 data/games 的事件日志推导（与 API 同一条 RatingIndex 路径），不落盘；
模块级不加载 litellm。库里已删除但历史对局仍有 id 的档案照样打印，名字显示 (已删除)。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from app.engine.config import Faction
from app.runtime.agent_library import JsonFileAgentLibrary
from app.runtime.rating import AgentRating
from app.runtime.rating_index import RatingIndex
from app.store.event_store import JsonFileEventStore

Printer = Callable[[str], None]
DELETED_LABEL = "(已删除)"
EMPTY_MSG = "没有带 agent_ids 的已结束对局；积分表为空"


def render_table(ratings: Mapping[str, AgentRating], names: Mapping[str, str]) -> list[str]:
    """积分降序，同分按场次降序，再按 agent_id；列：档案/id/积分/场次/胜负平/狼/好人。"""
    header = (
        f"{'档案':<12}{'id':<12}{'积分':>6}{'场次':>6}"
        f"{'胜/负/平':>10}{'狼 场/胜':>10}{'好人 场/胜':>12}"
    )
    rows = [header]
    ordered = sorted(ratings.items(), key=lambda kv: (-kv[1].rating, -kv[1].games, kv[0]))
    for aid, r in ordered:
        wolf, good = r.by_camp[Faction.WOLF], r.by_camp[Faction.GOOD]
        name = names.get(aid, DELETED_LABEL)
        record = f"{r.wins}/{r.losses}/{r.draws}"
        as_wolf = f"{wolf.games}/{wolf.wins}"
        as_good = f"{good.games}/{good.wins}"
        rows.append(
            f"{name:<12}{aid[:8]:<12}{round(r.rating):>6}{r.games:>6}"
            f"{record:>10}{as_wolf:>10}{as_good:>12}"
        )
    return rows


def main(argv: list[str] | None = None, out: Printer = print) -> None:
    parser = argparse.ArgumentParser(description="AgentHowl Agent 积分表（由已结束对局推导，只读）")
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="数据目录（含 games/ 与 agents/）"
    )
    args = parser.parse_args(argv)
    ratings = RatingIndex(JsonFileEventStore(args.data_dir / "games")).snapshot()
    if not ratings:
        out(EMPTY_MSG)
        return
    library = JsonFileAgentLibrary(args.data_dir / "agents")
    names = {s.agent_id: (s.profile.name or s.agent_id) for s in library.list()}
    for line in render_table(ratings, names):
        out(line)


if __name__ == "__main__":
    main()
