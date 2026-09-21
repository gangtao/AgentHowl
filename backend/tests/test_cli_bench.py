"""A/B bench 驱动（issue #60）：座位分配、标签、零 LLM 端到端、--report-only、--json、参数错误。"""

import json

import pytest

from app.agent.profile import AgentProfile
from app.cli.bench import assign_seats, label_map, main
from app.engine.config import build_preset
from app.eval.fingerprint import profile_fingerprint
from app.eval.metrics import RANDOM_BOT_LABEL
from app.store.event_store import GameMeta, JsonFileEventStore, SeatName


def test_assign_seats_interleaves_rotates_and_resolves_star() -> None:
    a = {"*": AgentProfile(model="a"), "0": AgentProfile(model="a0")}
    b = {"*": AgentProfile(model="b")}
    g0 = assign_seats(9, 0, a, b)
    g1 = assign_seats(9, 1, a, b)
    assert g0["0"].model == "a0" and g0["1"].model == "b" and g0["2"].model == "a"
    assert g1["0"].model == "b" and g1["1"].model == "a" and g1["2"].model == "b"
    assert set(g0) == {str(s) for s in range(9)} and "*" not in g0
    only_a = assign_seats(9, 1, a, None)
    assert all(p.model in ("a", "a0") for p in only_a.values()) and len(only_a) == 9
    sparse = assign_seats(9, 0, {"3": AgentProfile(model="x")}, None)
    assert set(sparse) == {"3"}  # 其余座位随机 bot
    assert assign_seats(9, 0, a, b) == g0  # 确定性


def test_label_map() -> None:
    a = {"*": AgentProfile(model="a")}
    b = {"0": AgentProfile(model="b0"), "*": AgentProfile(model="b")}
    labels = label_map(a, b, "甲", "乙")
    assert labels[None] == "随机 bot"
    assert labels[profile_fingerprint(a["*"])] == "甲"
    assert (
        labels[profile_fingerprint(b["0"])] == "乙/0"
        and labels[profile_fingerprint(b["*"])] == "乙/*"
    )
    assert label_map(a, None, "A", "B") == {None: "随机 bot", profile_fingerprint(a["*"]): "A"}


def _table(out: str) -> str:
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("档案"))
    return "\n".join(lines[start:])


def test_main_zero_llm_writes_logs_reports_and_report_only_matches(tmp_path, capsys) -> None:
    out_dir = tmp_path / "run"
    js = tmp_path / "r.json"
    main(
        [
            "--games",
            "2",
            "--seed",
            "3",
            "--preset",
            "std_9_kill_side",
            "--out",
            str(out_dir),
            "--json",
            str(js),
        ]
    )
    out = capsys.readouterr().out
    assert sorted(p.name for p in out_dir.iterdir()) == ["bench-3.jsonl", "bench-4.jsonl"]
    assert "seed=3 winner=" in out and "seed=4 winner=" in out
    table = _table(out)
    assert "随机 bot" in table and "Δ(" not in table
    row = next(line for line in table.splitlines() if line.startswith("随机 bot"))
    assert row.removeprefix(RANDOM_BOT_LABEL).split()[0] == "18"  # 2 局 × 9 座位
    doc = json.loads(js.read_text(encoding="utf-8"))
    assert doc["profiles"][0]["label"] == "随机 bot" and doc["profiles"][0]["games"] == 18
    assert doc["diff"] is None
    main(["--report-only", str(out_dir)])
    assert _table(capsys.readouterr().out) == table


def test_report_only_skips_unfinished_games_and_reports_count(tmp_path, capsys) -> None:
    """F1（终审）：目录里只有 meta 行（未终局，API 建局后中断的常态）→ 不计入分母，报个数。"""
    out_dir = tmp_path / "run"
    main(["--games", "2", "--seed", "3", "--out", str(out_dir)])
    capsys.readouterr()
    # 只写 meta 行、不写任何事件——模拟服务重启中断 / 仍在进行的 API 日志文件
    store = JsonFileEventStore(out_dir)
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 99})
    roster = tuple(SeatName(seat=s, display_name=f"P{s}") for s in range(cfg.num_players))
    store.create_game(GameMeta(game_id="bench-99", config=cfg, roster=roster))

    js = tmp_path / "r.json"
    main(["--report-only", str(out_dir), "--json", str(js)])
    out, err = capsys.readouterr()
    table = _table(out)
    row = next(line for line in table.splitlines() if line.startswith(RANDOM_BOT_LABEL))
    assert row.removeprefix(RANDOM_BOT_LABEL).split()[0] == "18"  # 只计入 2 个终局 × 9 座位
    assert "跳过未终局 1 局" in err
    doc = json.loads(js.read_text(encoding="utf-8"))
    assert doc["skipped_unfinished"] == 1


def test_report_only_bad_jsonl_is_argument_error_not_traceback(tmp_path) -> None:
    """F6（终审）：坏 JSONL → parser.error（SystemExit），不是裸 traceback。"""
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "broken.jsonl").write_text("not json\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--report-only", str(bad_dir)])


def test_main_ab_with_bot_ports_records_profiles_and_delta(tmp_path, capsys, monkeypatch) -> None:
    """A/B 端到端（零 LLM）：用随机 bot 端口顶替 Agent 端口，验证 meta.agents → 指纹 → 标签 → Δ 行。

    （行宽：docstring 折为两行以满足 ruff 100 列限制）
    """
    import app.agent.agent_player as ap
    from app.runtime.player_port import BotPlayerPort

    holder: dict[str, object] = {}

    def fake_build_agent_port(
        seat, game_config, profile, *, library=None, experience=None, opponents=None
    ):
        return BotPlayerPort(state_provider=lambda: holder["runner"].state)  # type: ignore[attr-defined]

    monkeypatch.setattr(ap, "build_agent_port", fake_build_agent_port)
    import app.cli.bench as bench_mod

    orig = bench_mod._wire_game

    def wire(config, **kw):
        out = orig(config, **kw)
        holder["runner"] = out[0]
        return out

    monkeypatch.setattr(bench_mod, "_wire_game", wire)
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text('seats:\n  "*": {model: ollama/a, skills: [logic-chain]}\n', encoding="utf-8")
    b.write_text(
        'seats:\n  "*": {model: ollama/b, personality: {traits: {从众: 0.9}}}\n', encoding="utf-8"
    )
    out_dir = tmp_path / "ab"
    main(
        [
            "--games",
            "2",
            "--seed",
            "3",
            "--out",
            str(out_dir),
            "--agents",
            str(a),
            "--agents-b",
            str(b),
        ]
    )
    table = _table(capsys.readouterr().out)
    lines = table.splitlines()
    assert lines[1].startswith("A ") and lines[2].startswith("B ") and lines[3].startswith("Δ(A−B)")
    assert lines[1].split()[1] == "9" and lines[2].split()[1] == "9"  # 2 局各 9 座位交错 → 各 9
    store = JsonFileEventStore(out_dir)
    m3, m4 = store.load_meta("bench-3"), store.load_meta("bench-4")
    assert m3.agents["0"].model == "ollama/a" and m3.agents["1"].model == "ollama/b"
    assert m4.agents["0"].model == "ollama/b" and m4.agents["1"].model == "ollama/a"
    # M1 修复：端口须真正被 wire 包装顶替驱动，不能全程超时落默认行动
    for gid in ("bench-3", "bench-4"):
        events = store.load_events(gid)
        assert events and not any(e.meta.get("timeout") == "true" for e in events)


def test_main_argument_errors(tmp_path, capsys) -> None:
    b = tmp_path / "b.yaml"
    b.write_text('seats:\n  "*": {model: m}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--games", "1", "--agents-b", str(b), "--out", str(tmp_path / "x")])
    assert "--agents-b" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--report-only", str(tmp_path), "--games", "2"])
    assert "--report-only" in capsys.readouterr().err
    # m2：--report-only 互斥检查须识别 --flag=value 形式，不能被静默绕过
    with pytest.raises(SystemExit):
        main(["--report-only", str(tmp_path), "--games=2"])
    assert "--report-only" in capsys.readouterr().err
    # m3：--report-only 指向不存在的目录 → 明确报错，且不把目录建出来
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit):
        main(["--report-only", str(missing)])
    assert "不存在" in capsys.readouterr().err
    assert not missing.exists()
    # m4：--out 指向已存在且非空的目录 → 明确报错，不与旧局混算
    out2 = tmp_path / "out2"
    main(["--games", "1", "--seed", "9", "--out", str(out2)])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["--games", "1", "--seed", "9", "--out", str(out2)])
    assert "已存在" in capsys.readouterr().err


def test_main_rejects_ab_with_identical_profile_content(tmp_path, capsys) -> None:
    """m1：A/B 内容相同（指纹撞车）时无意义，须明确报错而非静默让 B 覆盖 A。"""
    same_a, same_b = tmp_path / "same_a.yaml", tmp_path / "same_b.yaml"
    same_a.write_text('seats:\n  "*": {model: dup, name: 甲}\n', encoding="utf-8")
    same_b.write_text('seats:\n  "*": {model: dup, name: 乙}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(
            [
                "--games",
                "1",
                "--agents",
                str(same_a),
                "--agents-b",
                str(same_b),
                "--out",
                str(tmp_path / "dup"),
            ]
        )
    assert "指纹" in capsys.readouterr().err
