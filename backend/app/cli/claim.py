"""无主数据划归（issue #114）：把 owner_id 为空的对局 / Agent / Provider 划给某用户，
并把根目录下的跨局记忆文件移入 <owner_id>/。用法：
    python -m app.cli.claim --user alice [--data-dir data] [--dry-run]
注意：请先停止 AgentHowl 服务再运行（改写对局文件不加锁，服务端缓存也不会感知新 owner）。
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
    # issue #120：上次中断留下的 .jsonl.tmp 残件先清掉（它们从未被 os.replace 提升为正式文件）
    for stale in games_dir.glob("*.jsonl.tmp"):
        stale.unlink(missing_ok=True)
    n = 0
    for path in sorted(games_dir.glob("*.jsonl")) if games_dir.is_dir() else []:
        raw = path.read_bytes()
        head_bytes, sep, rest = raw.partition(b"\n")
        cr = b"\r" if head_bytes.endswith(b"\r") else b""
        try:
            head = json.loads(head_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            head = None
        data = head.get("data") if isinstance(head, dict) else None
        if not isinstance(head, dict) or head.get("kind") != "meta" or not isinstance(data, dict):
            print(f"跳过 {path.name}：首行不是合法 meta", file=sys.stderr)
            continue
        if data.get("owner_id") is not None:
            continue
        n += 1
        if dry_run:
            continue
        data["owner_id"] = owner_id
        new_head = json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        tmp = path.with_suffix(".jsonl.tmp")
        try:
            tmp.write_bytes(new_head + cr + sep + rest)
            os.replace(tmp, path)
        except BaseException:
            # issue #120：写一半失败不留 .jsonl.tmp 残件
            tmp.unlink(missing_ok=True)
            raise
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
    target = memory_dir / owner_id
    moved = 0
    for f in sorted(p for p in memory_dir.glob("*.json") if p.is_file()):
        if (target / f.name).exists():
            print(
                f"跳过 agent_memory/{f.name}：目标 {owner_id}/{f.name} 已存在",
                file=sys.stderr,
            )
            continue
        moved += 1
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
            os.replace(f, target / f.name)
    return moved


def users_db_path(data_dir: Path, users_db: Path | None = None) -> Path:
    """用户库路径：显式参数 > AGENTHOWL_USERS_DB > data_dir/users.db
    （与服务端 create_app 同口径）。"""
    if users_db is not None:
        return users_db
    env = os.environ.get("AGENTHOWL_USERS_DB", "").strip()
    return Path(env) if env else data_dir / "users.db"


def claim(
    data_dir: Path, username: str, *, dry_run: bool, users_db: Path | None = None
) -> dict[str, int]:
    db = users_db_path(data_dir, users_db)
    if not db.is_file():
        # issue #120：之前写死 data_dir/users.db，--data-dir 给错时会悄悄建空库再报「用户不存在」
        raise LookupError(f"用户库不存在：{db}（--data-dir / --users-db 是否正确？）")
    users = SqliteUserStore(db)
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
    parser = argparse.ArgumentParser(
        prog="app.cli.claim", description="无主数据划归某用户。请先停止 AgentHowl 服务再运行"
    )
    parser.add_argument("--user", required=True, help="目标用户名")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--users-db",
        default=None,
        help="用户库路径（默认 AGENTHOWL_USERS_DB 或 data-dir/users.db）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run:
        print("警告：请先停止 AgentHowl 服务再运行", file=sys.stderr)
    try:
        counts = claim(
            Path(args.data_dir),
            args.user,
            dry_run=args.dry_run,
            users_db=Path(args.users_db) if args.users_db else None,
        )
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    prefix = "[dry-run] " if args.dry_run else ""
    for k, v in counts.items():
        print(f"{prefix}{k}: {v}")


if __name__ == "__main__":
    main()
