"""评估报告（issue #60）：表格对齐、N/A、Δ 行、JSON 结构。"""

import json

from app.engine.config import RoleType
from app.eval.metrics import RANDOM_BOT_LABEL, ProfileStats, RoleStats, SeatStats
from app.eval.report import _fmt_delta, ordered, render_table, to_json


def _stats(games: int, wins: int, **totals: int) -> ProfileStats:
    ps = ProfileStats(summary="m", games=games, wins=wins, sheriff_games=games)
    ps.totals = SeatStats(**totals)
    ps.by_role[RoleType.SEER] = RoleStats(games=1, wins=1)
    return ps


def test_render_table_columns_na_and_delta_row() -> None:
    a = _stats(
        4,
        3,
        alive_at_end=2,
        rounds_alive=10,
        speeches=8,
        speech_chars=80,
        claims=2,
        votes=6,
        pk_votes_eligible=2,
        vote_changes=1,
    )
    b = _stats(4, 1, alive_at_end=1, rounds_alive=6, speeches=4, speech_chars=20, votes=4)
    bots = ProfileStats(summary=RANDOM_BOT_LABEL, games=8, wins=4)
    text = render_table({"fa": a, "fb": b, None: bots}, {"fa": "A", "fb": "B"})
    lines = text.splitlines()
    assert lines[0].startswith("档案") and "胜率" in lines[0] and "改票率" in lines[0]
    assert (
        lines[1].startswith("A ") and "75.0%" in lines[1] and "10.0" in lines[1]
    )  # 胜率、发言均长
    assert lines[2].startswith("B ") and "N/A" in lines[2]  # B 无 PK 票 → 改票率 N/A
    assert lines[3].startswith(RANDOM_BOT_LABEL)
    assert lines[4].startswith("Δ(A−B)") and "+50.0pp" in lines[4] and "N/A" in lines[4]
    # 列对齐：每行按东亚宽度等宽（去尾空格前）
    from app.eval.report import _width

    assert len({_width(line.rstrip()) for line in lines[:4]}) <= 2  # 最后一列不补齐也允许


def test_render_table_without_labels_uses_summary_and_no_delta() -> None:
    a, b = _stats(1, 1), _stats(1, 0)
    a.summary, b.summary = "ollama/a · 技能 x", "ollama/b"
    text = render_table({"fa": a, "fb": b}, {})
    assert "ollama/a · 技能 x" in text and "Δ(" not in text


def test_ordered_and_to_json() -> None:
    a, b = _stats(2, 1), _stats(2, 2)
    bots = ProfileStats(summary=RANDOM_BOT_LABEL, games=1)
    order = [k for k, _ in ordered({None: bots, "fb": b, "fa": a}, {"fa": "A", "fb": "B"})]
    assert order == ["fa", "fb", None]  # 有标签的按标签排，随机 bot 最后
    doc = to_json({"fa": a, "fb": b, None: bots}, {"fa": "A", "fb": "B"})
    json.dumps(doc)  # 可序列化
    profiles = doc["profiles"]
    assert [p["label"] for p in profiles] == ["A", "B", RANDOM_BOT_LABEL]
    assert profiles[0]["fingerprint"] == "fa" and profiles[0]["games"] == 2
    assert profiles[0]["rates"]["win_rate"] == 0.5 and profiles[0]["by_role"]["SEER"] == {
        "games": 1,
        "wins": 1,
    }
    assert profiles[2]["fingerprint"] is None and profiles[2]["rates"]["win_rate"] == 0.0
    assert doc["diff"]["win_rate"] == -0.5 and doc["diff_labels"] == ["A", "B"]
    assert to_json({"fa": a}, {})["diff"] is None


def test_fmt_delta_normalizes_negative_zero() -> None:
    """F4（终审）：浮点减法产生的 -1e-9 不应展示成 -0.0pp（字符串归一化，非数值加 0.0）。"""
    assert _fmt_delta("win_rate", -1e-9) == "+0.0pp"


def test_render_table_duplicate_summary_suffix() -> None:
    """两个 ProfileStats 同 summary、不同指纹、无标签 → 两行显示名不同且各含 [。"""
    a = _stats(1, 1)
    b = _stats(1, 0)
    a.summary = b.summary = "same_summary"
    # 无标签，fingerprint 分别为 abcdef1234 和 fedcba9876
    text = render_table({"abcdef1234": a, "fedcba9876": b}, {})
    lines = text.splitlines()
    # 跳过表头和尾部空行
    body_lines = [line for line in lines[1:] if line.strip()]
    assert len(body_lines) >= 2
    # 两行都应该包含 summary
    assert "same_summary" in body_lines[0] and "same_summary" in body_lines[1]
    # 由于同 summary、无标签、有重复，应该追加指纹前 6 位
    assert "[" in body_lines[0] and "[" in body_lines[1]
    # 两行显示名应该不同，且各含指纹前 6 位
    assert "[abcdef]" in body_lines[0] and "[fedcba]" in body_lines[1]
