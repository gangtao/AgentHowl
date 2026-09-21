"""评估报告（issue #60）：终端表格（东亚宽度对齐）与 JSON。"""

from __future__ import annotations

from collections.abc import Mapping
from unicodedata import east_asian_width

from app.eval.metrics import RANDOM_BOT_LABEL, ProfileStats, diff

# (表头, 取值名)；取值名为 ProfileStats 的比率属性、"games" 或 "skills_assembled"
COLUMNS: tuple[tuple[str, str], ...] = (
    ("局数", "games"),
    ("胜率", "win_rate"),
    ("狼胜", "wolf_win_rate"),
    ("好人胜", "good_win_rate"),
    ("存活率", "survive_rate"),
    ("均存活轮", "avg_rounds_alive"),
    ("放逐率", "exiled_rate"),
    ("发言均长", "avg_speech_chars"),
    ("声称率", "claim_rate"),
    ("上警率", "candidacy_rate"),
    ("改票率", "vote_change_rate"),
    ("空刀率", "no_kill_proposal_rate"),
    ("重提率", "revote_night_rate"),
    ("技能次数", "skills_assembled"),
)
_COUNT_FIELDS = {"games", "skills_assembled"}


def _width(s: str) -> int:
    return sum(2 if east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _width(s))


def _value(ps: ProfileStats, name: str) -> float | None:
    if name == "games":
        return float(ps.games)
    if name == "skills_assembled":
        return float(ps.totals.skills_assembled)
    v: float | None = getattr(ps, name)
    return v


def _fmt(name: str, v: float | None) -> str:
    if v is None:
        return "N/A"
    if name in _COUNT_FIELDS:
        return str(int(v))
    if name.startswith("avg_"):
        return f"{v:.1f}"
    return f"{v * 100:.1f}%"


def _fmt_delta(name: str, d: float | None) -> str:
    if name in _COUNT_FIELDS:
        return "—"
    if d is None:
        return "N/A"
    if name.startswith("avg_"):
        return f"{d:+.1f}"
    return f"{d * 100:+.1f}pp"


def ordered(
    stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]
) -> list[tuple[str | None, ProfileStats]]:
    """有标签的按标签排，其余按摘要排，随机 bot 最后。"""

    def key(item: tuple[str | None, ProfileStats]) -> tuple[int, str]:
        fp, ps = item
        if fp is None:
            return (2, "")
        if fp in labels:
            return (0, labels[fp])
        return (1, ps.summary)

    return sorted(stats.items(), key=key)


def _get_duplicate_summaries(
    rows: list[tuple[str | None, ProfileStats]], labels: Mapping[str | None, str]
) -> set[str]:
    """找出在无标签档案中重复的 summary。"""
    summary_counts: dict[str, int] = {}
    for fp, ps in rows:
        if fp is None or fp not in labels:
            # 无标签或随机 bot
            if fp is None:
                continue
            summary_counts[ps.summary] = summary_counts.get(ps.summary, 0) + 1
    return {s for s, count in summary_counts.items() if count > 1}


def _display(
    fp: str | None,
    ps: ProfileStats,
    labels: Mapping[str | None, str],
    duplicate_summaries: set[str] | None = None,
) -> str:
    """生成显示名；如有重复摘要且无标签，追加指纹前 6 位。"""
    if fp is None:
        return RANDOM_BOT_LABEL
    if fp in labels:
        return labels[fp]
    # 无标签的档案：显示摘要
    display_name = ps.summary
    if duplicate_summaries and ps.summary in duplicate_summaries:
        display_name = f"{ps.summary} [{fp[:6]}]"
    return display_name


def render_table(stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]) -> str:
    rows = ordered(stats, labels)
    duplicate_summaries = _get_duplicate_summaries(rows, labels)
    header = ["档案", *(h for h, _ in COLUMNS)]
    body = [
        [
            _display(fp, ps, labels, duplicate_summaries),
            *(_fmt(name, _value(ps, name)) for _, name in COLUMNS),
        ]
        for fp, ps in rows
    ]
    labeled = [(fp, ps) for fp, ps in rows if fp is not None and fp in labels]
    delta: list[str] | None = None
    if len(labeled) == 2:
        (fa, a), (fb, b) = labeled
        d = diff(a, b)
        delta = [
            f"Δ({labels[fa]}−{labels[fb]})",
            *(_fmt_delta(name, d.get(name)) for _, name in COLUMNS),
        ]
    table = [header, *body, *([delta] if delta else [])]
    widths = [max(_width(r[i]) for r in table) for i in range(len(header))]
    lines = [
        "  ".join(
            _pad(c, widths[i] if i < len(widths) - 1 else 0) for i, c in enumerate(r)
        ).rstrip()
        for r in table
    ]
    return "\n".join(lines)


def to_json(
    stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]
) -> dict[str, object]:
    rows = ordered(stats, labels)
    duplicate_summaries = _get_duplicate_summaries(rows, labels)
    profiles: list[dict[str, object]] = []
    for fp, ps in rows:
        profiles.append(
            {
                "label": _display(fp, ps, labels, duplicate_summaries),
                "fingerprint": fp,
                "summary": ps.summary,
                "games": ps.games,
                "wins": ps.wins,
                "wolf_games": ps.wolf_games,
                "wolf_wins": ps.wolf_wins,
                "good_games": ps.good_games,
                "good_wins": ps.good_wins,
                "sheriff_games": ps.sheriff_games,
                "totals": ps.totals.model_dump(),
                "rates": ps.rates(),
                "by_role": {r.value: rs.model_dump() for r, rs in ps.by_role.items()},
                "skill_counts": dict(ps.totals.skill_counts),
            }
        )
    labeled = [(fp, ps) for fp, ps in rows if fp is not None and fp in labels]
    out: dict[str, object] = {"profiles": profiles, "diff": None, "diff_labels": None}
    if len(labeled) == 2:
        (fa, a), (fb, b) = labeled
        out["diff"] = diff(a, b)
        out["diff_labels"] = [labels[fa], labels[fb]]
    return out
