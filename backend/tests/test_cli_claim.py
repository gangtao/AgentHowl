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
    with pytest.raises(SystemExit) as exc:
        main(["--user", "ghost", "--data-dir", str(tmp_path)])
    assert exc.value.code == 2


def test_claim_memory_collision_not_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    uid = _seed(tmp_path)
    (tmp_path / "agent_memory" / uid).mkdir()
    (tmp_path / "agent_memory" / uid / "mem1.json").write_text("KEEP", encoding="utf-8")
    assert claim(tmp_path, "alice", dry_run=True)["memory"] == 0
    assert claim(tmp_path, "alice", dry_run=False)["memory"] == 0
    assert (tmp_path / "agent_memory" / "mem1.json").exists()
    assert (tmp_path / "agent_memory" / uid / "mem1.json").read_text(encoding="utf-8") == "KEEP"
    assert f"跳过 agent_memory/mem1.json：目标 {uid}/mem1.json 已存在" in capsys.readouterr().err


def test_claim_skips_bad_heads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    (tmp_path / "games" / "bad1.jsonl").write_text("[]\n", encoding="utf-8")
    (tmp_path / "games" / "bad2.jsonl").write_bytes(b"")
    (tmp_path / "games" / "bad3.jsonl").write_text('{"kind":"meta","data":1}\n', encoding="utf-8")
    assert claim(tmp_path, "alice", dry_run=False)["games"] == 1
    err = capsys.readouterr().err
    for name in ("bad1.jsonl", "bad2.jsonl", "bad3.jsonl"):
        assert f"跳过 {name}：首行不是合法 meta" in err


def test_claim_preserves_crlf_lines(tmp_path: Path) -> None:
    _seed(tmp_path)
    path = tmp_path / "games" / "g_old.jsonl"
    head = path.read_bytes().split(b"\n")[0]
    path.write_bytes(head + b"\n" + b'{"kind":"event"}\r\n')
    assert claim(tmp_path, "alice", dry_run=False)["games"] == 1
    assert path.read_bytes().endswith(b'\n{"kind":"event"}\r\n')
    assert json.loads(path.read_bytes().split(b"\n")[0])["data"]["owner_id"] == "u_a"


def test_main_warns_to_stop_server(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    main(["--user", "alice", "--data-dir", str(tmp_path), "--dry-run"])
    assert "请先停止 AgentHowl 服务" not in capsys.readouterr().err
    main(["--user", "alice", "--data-dir", str(tmp_path)])
    assert "请先停止 AgentHowl 服务" in capsys.readouterr().err
