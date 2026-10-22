"""claim CLI（issue #114）：无主数据划归指定用户；dry-run 不写。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.profile import AgentProfile
from app.agent.provider import Provider
from app.cli.claim import claim, main
from app.engine.config import build_preset
from app.runtime.agent_library import JsonFileAgentLibrary, StoredAgent
from app.runtime.provider_store import JsonFileProviderStore
from app.runtime.users import SqliteUserStore, User, hash_password, now_iso
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName


def _seed(data: Path) -> str:
    users = SqliteUserStore(data / "users.db")
    users.put(
        User(
            user_id="u_a",
            username="alice",
            email="a@x",
            password_hash=hash_password("password1"),
            created_at=now_iso(),
        )
    )
    games = JsonFileEventStore(data / "games")
    games.create_game(
        GameMeta(
            game_id="g_old",
            config=build_preset("std_9_kill_side"),
            roster=(SeatName(seat=0, display_name="P0"),),
        )
    )
    games.create_game(
        GameMeta(
            game_id="g_mine", config=build_preset("std_9_kill_side"), roster=(), owner_id="u_b"
        )
    )
    JsonFileAgentLibrary(data / "agents").put(
        StoredAgent(
            agent_id="a_old",
            profile=AgentProfile(name="x", model="m"),
            created_at="t",
            updated_at="t",
        )
    )
    JsonFileProviderStore(data / "providers").put(
        Provider(
            provider_id="p_old",
            name="p",
            kind="openai_compatible",
            api_base="http://x",
            api_key="k",
            default_model=None,
            created_at="t",
            updated_at="t",
        )
    )
    (data / "agent_memory").mkdir()
    (data / "agent_memory" / "mem1.json").write_text('{"memory_id": "mem1"}', encoding="utf-8")
    return "u_a"


def test_claim_dry_run_then_real(tmp_path: Path) -> None:
    uid = _seed(tmp_path)
    assert claim(tmp_path, "alice", dry_run=True) == {
        "games": 1,
        "agents": 1,
        "providers": 1,
        "memory": 1,
    }
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_old").owner_id is None
    assert claim(tmp_path, "alice", dry_run=False) == {
        "games": 1,
        "agents": 1,
        "providers": 1,
        "memory": 1,
    }
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_old").owner_id == uid
    assert JsonFileEventStore(tmp_path / "games").load_meta("g_mine").owner_id == "u_b"
    assert JsonFileAgentLibrary(tmp_path / "agents").get("a_old").owner_id == uid  # type: ignore[union-attr]
    assert JsonFileProviderStore(tmp_path / "providers").get("p_old").owner_id == uid  # type: ignore[union-attr]
    assert (tmp_path / "agent_memory" / uid / "mem1.json").exists()
    assert not (tmp_path / "agent_memory" / "mem1.json").exists()
    # 幂等
    assert claim(tmp_path, "alice", dry_run=False) == {
        "games": 0,
        "agents": 0,
        "providers": 0,
        "memory": 0,
    }
    # 事件文件其余行保持原样
    lines = (tmp_path / "games" / "g_old.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["kind"] == "meta" and len(lines) == 1


def test_claim_unknown_user(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(SystemExit):
        main(["--user", "ghost", "--data-dir", str(tmp_path)])
