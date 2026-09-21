"""A/B bench 驱动（issue #60）：N 局交错分配两份档案、落盘事件日志、离线汇总指标。

零 LLM 路径：不给 --agents 即全随机 bot（验收与测试用）。不做跨局记忆、不跑 postgame。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.agent.profile import AgentProfiles, profile_for, validate_profiles
from app.agent.skills import BUILTIN_SKILLS_DIR, SkillError, SkillLibrary, default_library
from app.cli.play import _wire_game, load_agent_profiles
from app.engine.config import build_preset
from app.eval.fingerprint import profile_fingerprint
from app.eval.metrics import RANDOM_BOT_LABEL, aggregate, analyze_game, collect_profiles
from app.eval.report import render_table, to_json
from app.store.event_store import EventStore, JsonFileEventStore

Printer = Callable[[str], None]


def assign_seats(
    num_players: int, game_index: int, a: AgentProfiles, b: AgentProfiles | None
) -> AgentProfiles:
    """第 game_index 局的座位档案：交错 + 逐局轮转；解析为 None 的座位留给随机 bot。"""
    out: AgentProfiles = {}
    for seat in range(num_players):
        chosen = a if b is None or (seat + game_index) % 2 == 0 else b
        p = profile_for(chosen, seat)
        if p is not None:
            out[str(seat)] = p
    return out


def shared_fingerprints(a: AgentProfiles, b: AgentProfiles | None) -> set[str]:
    """A、B 两份档案集里指纹相交的部分（内容相同即撞车，`name`/`memory_id` 不参与指纹）。"""
    if not a or not b:
        return set()
    fp_a = {profile_fingerprint(p) for p in a.values()}
    fp_b = {profile_fingerprint(p) for p in b.values()}
    return fp_a & fp_b


def label_map(
    a: AgentProfiles, b: AgentProfiles | None, label_a: str, label_b: str
) -> dict[str | None, str]:
    """指纹 → 显示标签；一份档案集含多个不同档案时用「标签/座位键」区分。"""
    labels: dict[str | None, str] = {None: RANDOM_BOT_LABEL}
    for agents, label in ((a, label_a), (b, label_b)):
        if not agents:
            continue
        keyed: dict[str, str] = {}
        for key, p in agents.items():
            keyed.setdefault(profile_fingerprint(p), key)
        for fp, key in keyed.items():
            labels[fp] = label if len(keyed) == 1 else f"{label}/{key}"
    return labels


async def run_bench(
    *,
    preset: str,
    seed: int,
    games: int,
    a: AgentProfiles,
    b: AgentProfiles | None,
    library: SkillLibrary,
    store: EventStore,
    out: Printer = print,
) -> None:
    base = build_preset(preset)
    for i in range(games):
        s = seed + i
        config = base.model_copy(update={"seed": s})
        agents = assign_seats(config.num_players, i, a, b)
        runner, _conns, _ports = _wire_game(
            config, agents=agents, library=library, store=store, game_id=f"bench-{s}"
        )
        state = await runner.run()
        out(f"seed={s} winner={state.winner or 'DRAW'} rounds={state.round}")


def report(store: EventStore, labels: dict[str | None, str]) -> tuple[str, dict[str, object]]:
    """对 store 里全部对局做分析；返回 (表格文本, JSON 文档)。"""
    ids = store.list_games()
    metas = [store.load_meta(g) for g in ids]
    analyses = [analyze_game(m, store.load_events(m.game_id)) for m in metas]
    stats = aggregate(analyses, collect_profiles(metas))
    return render_table(stats, labels), to_json(stats, labels)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="app.cli.bench", description="AgentHowl 档案 A/B bench")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", type=load_agent_profiles, default=None, help="档案 A（YAML）")
    parser.add_argument("--agents-b", type=load_agent_profiles, default=None, help="档案 B（YAML）")
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--skills-dir", default=None)
    parser.add_argument("--out", default=None, help="事件日志目录（默认 data/bench/<时间戳>）")
    parser.add_argument("--json", default=None, help="把报告 JSON 写到该路径")
    parser.add_argument("--report-only", default=None, metavar="DIR", help="只分析已有日志目录")
    args = parser.parse_args(argv)

    if args.report_only is not None:
        _mutex_flags = ("--games", "--agents", "--agents-b", "--out")
        if any(arg == flag or arg.startswith(flag + "=") for flag in _mutex_flags for arg in argv):
            parser.error("--report-only 不能与 --games/--agents/--agents-b/--out 同时给出")
        report_dir = Path(args.report_only)
        if not report_dir.is_dir():
            parser.error(f"--report-only 目录不存在：{report_dir}")
        store: EventStore = JsonFileEventStore(report_dir)
        labels: dict[str | None, str] = {None: RANDOM_BOT_LABEL}
        table, doc = report(store, labels)
        print(table)
        if args.json:
            Path(args.json).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return

    if args.agents_b is not None and args.agents is None:
        parser.error("--agents-b 须与 --agents 同时给出")
    a: AgentProfiles = args.agents or {}
    b: AgentProfiles | None = args.agents_b
    try:
        library = (
            SkillLibrary.load([BUILTIN_SKILLS_DIR, Path(args.skills_dir)])
            if args.skills_dir
            else default_library()
        )
        n = build_preset(args.preset).num_players
        validate_profiles(a, n, library)
        if b is not None:
            validate_profiles(b, n, library)
    except (ValueError, SkillError) as exc:
        parser.error(str(exc))
    shared = shared_fingerprints(a, b)
    if shared:
        parser.error(
            f"--agents 与 --agents-b 含内容相同的档案（指纹 {sorted(shared)}），A/B 无意义"
        )
    out_dir = (
        Path(args.out)
        if args.out
        else Path("data/bench") / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    if out_dir.is_dir() and any(out_dir.iterdir()):
        parser.error(f"--out 目录已存在且非空：{out_dir}（避免与旧局混算）")
    store = JsonFileEventStore(out_dir)
    asyncio.run(
        run_bench(
            preset=args.preset,
            seed=args.seed,
            games=args.games,
            a=a,
            b=b,
            library=library,
            store=store,
        )
    )
    labels = label_map(a, b, args.label_a, args.label_b)
    table, doc = report(store, labels)
    print(f"日志目录：{out_dir}")
    print(table)
    if args.json:
        Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
