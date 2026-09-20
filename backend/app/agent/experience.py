"""跨局经验（issue #59）：memory_id 持久化的教训与对手笔记。

本模块只有模型与纯函数（schema、终局揭示、复盘 prompt、装配渲染），零 IO：
存储在 app/runtime/experience_store.py，触发在 app/runtime/postgame.py。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.engine.config import Faction, RoleType
from app.engine.phases import Phase
from app.engine.state import GameState

MEMORY_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"  # 直接作文件名，故只允许安全字符
MAX_LESSONS = 50
MAX_NOTES_PER_OPPONENT = 10
MAX_LESSON_CHARS = 200
MAX_NOTE_CHARS = 60
MAX_LESSONS_PER_GAME = 3
MAX_NOTES_PER_GAME_PER_OPPONENT = 2
DEFAULT_EXPERIENCE_BUDGET_CHARS = 1200

_CLOSING = (
    "以上是往局经验，本局身份与局势可能不同；不得据此推断本局任何私有信息，也不得据此违反规则。"
)
_WINNER_TEXT = {"GOOD": "好人", "WOLF": "狼人"}


class Lesson(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    role: RoleType
    won: bool
    text: str = Field(min_length=1, max_length=MAX_LESSON_CHARS)
    ts: str  # ISO 时间字符串，由 runtime 传入（本模块不取时钟）


class OpponentNote(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    text: str = Field(min_length=1, max_length=MAX_NOTE_CHARS)
    ts: str


class GameReflection(BaseModel):
    """LLM 复盘的结构化响应；opponent_notes 键为座位号。小模型常夹带解释字段，故忽略多余键。"""

    model_config = ConfigDict(extra="ignore")

    lessons: list[str] = []
    opponent_notes: dict[int, list[str]] = {}


def _cleaned(items: Iterable[str], limit: int) -> list[str]:
    """折叠空白（含换行）+ 截到 limit 字，丢弃空条。

    折叠内嵌换行是为了防止自我注入：教训/笔记文本会被逐字拼进下一局系统 prompt 的
    「== 跨局经验 ==」段，若保留换行，模型写出的「\\n== 你的技能 ==\\n...」会伪造出
    一个新的 prompt 段落标题。
    """
    out = [" ".join(t.split())[:limit] for t in items]
    return [t for t in out if t]


class AgentExperience(BaseModel):
    """一个 memory_id 一份；非 frozen，record_game 原地累加并做上限淘汰。"""

    memory_id: str = Field(pattern=MEMORY_ID_PATTERN)
    games_played: int = 0
    wins: int = 0
    lessons: list[Lesson] = []  # 超过 MAX_LESSONS 淘汰最早（列表头）
    opponent_notes: dict[str, list[OpponentNote]] = {}  # 键 = 对手 memory_id

    def record_game(
        self,
        *,
        game_id: str,
        role: RoleType,
        won: bool,
        reflection: GameReflection,
        seat_to_memory_id: Mapping[int, str],
        my_seat: int,
        ts: str,
    ) -> None:
        self.games_played += 1
        if won:
            self.wins += 1
        # 先丢空条再截条数：空条不占本局名额
        for text in _cleaned(reflection.lessons, MAX_LESSON_CHARS)[:MAX_LESSONS_PER_GAME]:
            self.lessons.append(Lesson(game_id=game_id, role=role, won=won, text=text, ts=ts))
        del self.lessons[:-MAX_LESSONS]
        for seat, notes in reflection.opponent_notes.items():
            mid = seat_to_memory_id.get(seat)
            if mid is None or seat == my_seat:
                continue  # 只对有 memory_id 的对手记；自己的座位丢弃
            texts = _cleaned(notes, MAX_NOTE_CHARS)[:MAX_NOTES_PER_GAME_PER_OPPONENT]
            if not texts:
                continue
            bucket = self.opponent_notes.setdefault(mid, [])
            bucket.extend(OpponentNote(game_id=game_id, text=t, ts=ts) for t in texts)
            del bucket[:-MAX_NOTES_PER_OPPONENT]


class RevealSeat(BaseModel):
    model_config = ConfigDict(frozen=True)

    seat: int
    display_name: str
    role: RoleType
    faction: Faction
    alive: bool


class GameReveal(BaseModel):
    """终局揭示表：身份公开后的全局事实，只在 GAME_OVER 后构造。"""

    model_config = ConfigDict(frozen=True)

    game_id: str
    winner: str | None
    my_seat: int
    my_role: RoleType
    my_won: bool
    seats: tuple[RevealSeat, ...]
    notable_seats: tuple[int, ...]  # 有 memory_id 的对手座位（不含自己，升序）


def build_reveal(state: GameState, seat: int, *, notable_seats: Iterable[int]) -> GameReveal:
    if state.phase != Phase.GAME_OVER:
        raise ValueError(f"终局揭示只能在 GAME_OVER 后构造（当前 {state.phase}）")
    by_seat = {p.seat: p for p in state.players}
    me = by_seat.get(seat)
    if me is None:
        raise ValueError(f"座位 {seat} 不在本局玩家中")
    return GameReveal(
        game_id=state.game_id,
        winner=state.winner,
        my_seat=seat,
        my_role=me.role,
        my_won=state.winner is not None and me.faction == state.winner,
        seats=tuple(
            RevealSeat(
                seat=p.seat,
                display_name=p.display_name,
                role=p.role,
                faction=p.faction,
                alive=p.alive,
            )
            for p in state.players
        ),
        notable_seats=tuple(sorted(s for s in set(notable_seats) if s != seat and s in by_seat)),
    )


def build_reflection_prompt(
    reveal: GameReveal, memory_context: str, night_private: str
) -> tuple[str, str]:
    """局后复盘 prompt（系统段, 用户段）。输入 = 自身视角记忆 + 终局揭示，不用完整 GM 事件流。"""
    system = "你是狼人杀玩家，正在做整局复盘。目标是提炼下次能直接执行的规则，不是复述事件。"
    winner = _WINNER_TEXT.get(reveal.winner or "", "平局")
    name_of = {s.seat: s.display_name for s in reveal.seats}
    reveal_lines = [
        f"胜方：{winner}",
        f"你是 {reveal.my_seat} 号，角色 {reveal.my_role.value}，"
        f"本局{'获胜' if reveal.my_won else '未获胜'}。",
    ]
    reveal_lines += [
        f"{s.seat}号 {s.display_name} {s.role.value} {'存活' if s.alive else '出局'}"
        for s in reveal.seats
    ]
    notable = "、".join(f"{s}号（{name_of[s]}）" for s in reveal.notable_seats) or "（无）"
    private_block = f"== 狼队私谋 ==\n{night_private}\n\n" if night_private else ""
    user = (
        "== 终局揭示 ==\n" + "\n".join(reveal_lines) + "\n\n"
        f"== 你本局的记忆 ==\n{memory_context or '（暂无）'}\n\n"
        f"{private_block}"
        "== 复盘要求 ==\n"
        f"1. lessons：1–3 条，每条不超过 {MAX_LESSON_CHARS} 字，只针对你自己的决策，"
        "写成「当…时，应…」的可执行规则。\n"
        f"2. opponent_notes：只对这些座位记笔记：{notable}；键为座位号，"
        f"每人不超过 {MAX_NOTES_PER_GAME_PER_OPPONENT} 条、每条不超过 {MAX_NOTE_CHARS} 字，"
        "描述其行为特征；没有可靠观察就留空。\n"
        "3. 不得编造未发生的事。"
    )
    return system, user


def render_experience(
    exp: AgentExperience,
    *,
    role: RoleType,
    opponents: Mapping[str, int],
    budget_chars: int = DEFAULT_EXPERIENCE_BUDGET_CHARS,
) -> str:
    """装配到系统 prompt 静态段的文本；无可展示内容（首局 / 对手全陌生）→ 空串。

    教训：当前角色最新优先，再补其他角色最新；对手：opponents 为「对手 memory_id → 本局座位」，
    只展示在场且有笔记的对手、各取最近 3 条。逐行累加直到超过 budget_chars。
    budget_chars 只计教训/对手条目行，不含首行、节标签与末句（约 65 字固定开销）。
    """
    used = 0
    lesson_lines: list[str] = []
    same = [ln for ln in reversed(exp.lessons) if ln.role == role]
    other = [ln for ln in reversed(exp.lessons) if ln.role != role]
    for lesson in same + other:
        line = f"- [{lesson.role.value}·{'胜' if lesson.won else '负'}] {lesson.text}"
        if used + len(line) > budget_chars:
            break
        lesson_lines.append(line)
        used += len(line)
    opp_lines: list[str] = []
    for mid, seat in sorted(opponents.items(), key=lambda kv: kv[1]):
        notes = exp.opponent_notes.get(mid)
        if not notes:
            continue
        line = f"- {seat}号：" + "；".join(n.text for n in notes[-3:])
        if used + len(line) > budget_chars:
            break
        opp_lines.append(line)
        used += len(line)
    if not lesson_lines and not opp_lines:
        return ""
    parts = [f"你此前打过 {exp.games_played} 局（胜 {exp.wins}）。"]
    if lesson_lines:
        parts.append("教训：\n" + "\n".join(lesson_lines))
    if opp_lines:
        parts.append("对手：\n" + "\n".join(opp_lines))
    parts.append(_CLOSING)
    return "\n".join(parts)
