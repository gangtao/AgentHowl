"""无主数据划归（issue #114）：把 owner_id 为空的对局 / Agent / Provider 划给某用户，
并把根目录下的跨局记忆文件移入 <owner_id>/。用法：
    python -m app.cli.claim --user alice [--data-dir data] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.runtime.agent_library import JsonFileAgentLibrary
from app.runtime.provider_store import JsonFileProviderStore
from app.runtime.users import SqliteUserStore


def _claim_games(games_dir: Path, owner_id: str, dry_run: bool) -> int:
    n = 0
    for path in sorted(games_dir.glob("*.jsonl")) if games_dir.is_dir() else []:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not lines:
            continue
        try:
            head = json.loads(lines[0])
        except json.JSONDecodeError:
            continue
        if head.get("kind") != "meta" or head.get("data", {}).get("owner_id") is not None:
            continue
        n += 1
        if dry_run:
            continue
        head["data"]["owner_id"] = owner_id
        lines[0] = json.dumps(head, ensure_ascii=False, separators=(",", ":")) + "\n"
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp, path)
    return n


def _claim_agents(agents_dir: Path, owner_id: str, dry_run: bool) -> int:
    lib = JsonFileAgentLibrary(agents_dir)
    n = 0
    for stored in lib.list():
        if stored.owner_id is not None:
            continue
        n += 1
        if not dry_run:
            lib.put(stored.model_copy(update={"owner_id": owner_id}))
    return n


def _claim_providers(providers_dir: Path, owner_id: str, dry_run: bool) -> int:
    store = JsonFileProviderStore(providers_dir)
    n = 0
    for p in store.list():
        if p.owner_id is not None:
            continue
        n += 1
        if not dry_run:
            store.put(p.model_copy(update={"owner_id": owner_id}))
    return n


def _claim_memory(memory_dir: Path, owner_id: str, dry_run: bool) -> int:
    if not memory_dir.is_dir():
        return 0
    files = sorted(p for p in memory_dir.glob("*.json") if p.is_file())
    if files and not dry_run:
        target = memory_dir / owner_id
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            os.replace(f, target / f.name)
    return len(files)


def claim(data_dir: Path, username: str, *, dry_run: bool) -> dict[str, int]:
    users = SqliteUserStore(data_dir / "users.db")
    user = users.get_by_username(username.strip().lower())
    if user is None:
        raise LookupError(f"用户不存在：{username}")
    return {
        "games": _claim_games(data_dir / "games", user.user_id, dry_run),
        "agents": _claim_agents(data_dir / "agents", user.user_id, dry_run),
        "providers": _claim_providers(data_dir / "providers", user.user_id, dry_run),
        "memory": _claim_memory(data_dir / "agent_memory", user.user_id, dry_run),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli.claim", description="无主数据划归某用户")
    parser.add_argument("--user", required=True, help="目标用户名")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        counts = claim(Path(args.data_dir), args.user, dry_run=args.dry_run)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    prefix = "[dry-run] " if args.dry_run else ""
    for k, v in counts.items():
        print(f"{prefix}{k}: {v}")


if __name__ == "__main__":
    main()
