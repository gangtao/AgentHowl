# Agent 跨局独立记忆（issue #59）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 配置了 `memory_id` 的 Agent 在局后由 LLM 复盘生成教训与对手笔记并持久化到 `data/agent_memory/<memory_id>.json`，下一局建局时装配进该 Agent 自己的系统 prompt 静态段「== 跨局经验 ==」。

**Architecture:** 纯模型/函数（`app/agent/experience.py`：schema、终局揭示、复盘 prompt、装配渲染）+ IO 层存储（`app/runtime/experience_store.py`：内存 / JSON 文件原子写）+ 局后编排（`app/runtime/postgame.py`）。端口新增 `reflect_on_game(reveal)`（只用自己的记忆分区）与 `experience/opponents` 注入（与 #57 人格同一「首次行动渲染一次并缓存」模式）。触发点两处：registry 的 runner task 完成回调、CLI 结束前 await。引擎零改动。

**Tech Stack:** Python 3.11、Pydantic v2、asyncio、pytest（零 IO 零 mock；文件 store 用 `tmp_path`）、uv、ruff（行宽 100，中文宽 2）、mypy strict。

**Spec:** `docs/superpowers/specs/2026-09-20-agent-experience-design.md`

## Global Constraints

- 引擎（`app/engine/`）零改动；无 RNG。
- `memory_id` 缺省 `None` → 整条链路零变化：系统 prompt 逐字不变、不建目录、不写文件、`postgame_task is None`。
- 跨局经验只进该端口自己的系统 prompt 静态段；不进 `build_prompt` / `build_wolf_night_prompt` / `memory.reflect`。
- 对局中 store 不被写入；`build_reveal` 只接受 `GAME_OVER` 状态；复盘失败只记 `logger.warning`，不影响对局与其他座位。
- 对手笔记只对有 `memory_id` 的对手记录，键为对手 `memory_id`；自己的座位与无 `memory_id` 的座位丢弃。
- `app/runtime`、`app/api`、`app/cli` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`（litellm 惰性加载；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫）。`app/agent/experience.py` 只依赖 pydantic 与 `app.engine`。
- 常量：`MAX_LESSONS=50`、`MAX_NOTES_PER_OPPONENT=10`、`MAX_LESSON_CHARS=200`、`MAX_NOTE_CHARS=60`、`MAX_LESSONS_PER_GAME=3`、`MAX_NOTES_PER_GAME_PER_OPPONENT=2`、`DEFAULT_EXPERIENCE_BUDGET_CHARS=1200`、`MEMORY_ID_PATTERN=r"^[A-Za-z0-9_\-]{1,64}$"`、复盘超时 120s。
- 文档与代码注释中文；标识符英文；ruff 行宽 100（中文宽 2，计划里超宽行按 ruff 折行）；测试零 IO 零 mock。
- 每个任务结束前全绿：`uv run pytest -q -x --ignore=tests/test_api_e2e.py`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`（均在 `backend/` 下）。
- 规格附注（实现期）：§4 渲染里「== 教训 ==」「== 对手 ==」改为行首「教训：」「对手：」——嵌套在「== 跨局经验 ==」段内的二级「==」标题会与一级段落混淆。

---

### Task 1: 经验 schema、终局揭示、复盘 prompt、装配渲染 + `AgentProfile.memory_id`

**Files:**
- Create: `backend/app/agent/experience.py`
- Modify: `backend/app/agent/profile.py`（`memory_id` 字段；`validate_profiles` 两条新规则；docstring）
- Test: `backend/tests/test_agent_experience.py`（新）、`backend/tests/test_agent_profile.py`（追加）

**Interfaces:**
- Produces: `Lesson`、`OpponentNote`、`GameReflection`、`AgentExperience.record_game(...)`、`RevealSeat`、`GameReveal`、`build_reveal(state, seat, *, notable_seats)`、`build_reflection_prompt(reveal, memory_context, night_private) -> (system, user)`、`render_experience(exp, *, role, opponents, budget_chars=1200) -> str`、常量；`AgentProfile.memory_id: str | None`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_agent_experience.py`：

```python
"""跨局经验（issue #59）：schema 上限、终局揭示、复盘 prompt、装配渲染——零 IO。"""

import pytest
from pydantic import ValidationError

from app.agent.experience import (
    MAX_LESSONS,
    MAX_NOTES_PER_OPPONENT,
    AgentExperience,
    GameReflection,
    Lesson,
    build_reflection_prompt,
    build_reveal,
    render_experience,
)
from app.agent.profile import AgentProfile, validate_profiles
from app.cli.bot import run_game
from app.engine.config import RoleType, build_preset
from app.engine.phases import Phase


def _finished_state():
    state, _events = run_game(build_preset("std_9_kill_side").model_copy(update={"seed": 3}), "g1")
    assert state.phase == Phase.GAME_OVER
    return state


def test_memory_id_pattern() -> None:
    assert AgentProfile(model="m", memory_id="alice_01-x").memory_id == "alice_01-x"
    for bad in ("", "a/b", "a b", "中文", "x" * 65):
        with pytest.raises(ValidationError):
            AgentProfile(model="m", memory_id=bad)
    with pytest.raises(ValidationError):
        AgentExperience(memory_id="a/b")


def test_validate_profiles_rejects_star_and_duplicate_memory_id() -> None:
    with pytest.raises(ValueError, match="'\\*'"):
        validate_profiles({"*": AgentProfile(model="m", memory_id="a")}, 9)
    with pytest.raises(ValueError, match="memory_id 'a'"):
        validate_profiles(
            {"0": AgentProfile(model="m", memory_id="a"), "3": AgentProfile(model="m", memory_id="a")},
            9,
        )
    validate_profiles(
        {"0": AgentProfile(model="m", memory_id="a"), "3": AgentProfile(model="m", memory_id="b")}, 9
    )


def test_record_game_filters_truncates_and_caps() -> None:
    exp = AgentExperience(memory_id="me")
    refl = GameReflection(
        lessons=["  一 ", "", "二", "三", "四"],
        opponent_notes={0: ["自己"], 3: ["a", "b", "c"], 5: ["无记忆座位"], 7: ["x" * 100]},
    )
    exp.record_game(
        game_id="g1",
        role=RoleType.SEER,
        won=True,
        reflection=refl,
        seat_to_memory_id={0: "me", 3: "bob", 7: "carol"},
        my_seat=0,
        ts="2026-09-20T00:00:00+00:00",
    )
    assert exp.games_played == 1 and exp.wins == 1
    assert [l.text for l in exp.lessons] == ["一", "二", "三"]  # 空条丢弃、strip、每局最多 3 条
    assert exp.lessons[0].role == RoleType.SEER and exp.lessons[0].won and exp.lessons[0].game_id == "g1"
    assert set(exp.opponent_notes) == {"bob", "carol"}  # 自己与无 memory_id 座位丢弃
    assert [n.text for n in exp.opponent_notes["bob"]] == ["a", "b"]  # 每局每人最多 2 条
    assert len(exp.opponent_notes["carol"][0].text) == 60  # 截到 60 字


def test_caps_evict_oldest() -> None:
    exp = AgentExperience(memory_id="me")
    for i in range(MAX_LESSONS + 5):
        exp.record_game(
            game_id=f"g{i}",
            role=RoleType.VILLAGER,
            won=False,
            reflection=GameReflection(lessons=[f"L{i}"], opponent_notes={1: [f"N{i}"]}),
            seat_to_memory_id={0: "me", 1: "bob"},
            my_seat=0,
            ts="t",
        )
    assert len(exp.lessons) == MAX_LESSONS and exp.lessons[0].text == "L5"
    assert len(exp.opponent_notes["bob"]) == MAX_NOTES_PER_OPPONENT
    assert exp.opponent_notes["bob"][-1].text == f"N{MAX_LESSONS + 4}"
    assert exp.games_played == MAX_LESSONS + 5


def test_reflection_response_ignores_extra_and_coerces_seat_keys() -> None:
    r = GameReflection.model_validate({"lessons": ["a"], "opponent_notes": {"3": ["x"]}, "why": "…"})
    assert r.opponent_notes == {3: ["x"]}


def test_build_reveal_requires_game_over_and_derives_won() -> None:
    state = _finished_state()
    me = state.players[2]
    reveal = build_reveal(state, 2, notable_seats=[2, 5, 7])
    assert reveal.game_id == "g1" and reveal.my_seat == 2 and reveal.my_role == me.role
    assert reveal.my_won == (state.winner is not None and me.faction == state.winner)
    assert reveal.notable_seats == (5, 7)  # 自己被剔除、排序
    assert len(reveal.seats) == 9 and reveal.seats[2].role == me.role
    lobby = state.model_copy(update={"phase": Phase.DAY_SPEECH})
    with pytest.raises(ValueError, match="GAME_OVER"):
        build_reveal(lobby, 2, notable_seats=[])
    draw = state.model_copy(update={"winner": None})
    assert build_reveal(draw, 2, notable_seats=[]).my_won is False


def test_reflection_prompt_sections() -> None:
    state = _finished_state()
    reveal = build_reveal(state, 0, notable_seats=[3])
    system, user = build_reflection_prompt(reveal, "记忆A", "")
    assert "整局复盘" in system
    assert user.index("== 终局揭示 ==") < user.index("== 你本局的记忆 ==") < user.index("== 复盘要求 ==")
    assert "记忆A" in user and "== 狼队私谋 ==" not in user
    assert f"3号（{state.players[3].display_name}）" in user
    _s, user2 = build_reflection_prompt(reveal, "", "私谋B")
    assert "== 狼队私谋 ==\n私谋B" in user2 and "（暂无）" in user2


def _exp_with(*lessons: tuple[RoleType, bool, str]) -> AgentExperience:
    exp = AgentExperience(memory_id="me", games_played=len(lessons), wins=1)
    exp.lessons = [
        Lesson(game_id=f"g{i}", role=r, won=w, text=t, ts="t") for i, (r, w, t) in enumerate(lessons)
    ]
    return exp


def test_render_experience_role_first_recent_first_and_closing() -> None:
    exp = _exp_with(
        (RoleType.SEER, False, "S1"),
        (RoleType.VILLAGER, True, "V1"),
        (RoleType.SEER, True, "S2"),
    )
    text = render_experience(exp, role=RoleType.SEER, opponents={})
    assert text.startswith("你此前打过 3 局（胜 1）。")
    assert text.index("[SEER·胜] S2") < text.index("[SEER·负] S1") < text.index("[VILLAGER·胜] V1")
    assert text.rstrip().endswith("不得据此违反规则。")
    assert "对手：" not in text


def test_render_experience_opponents_mapped_to_seats_and_recent_three() -> None:
    exp = _exp_with((RoleType.SEER, True, "S"))
    exp.record_game(
        game_id="g9",
        role=RoleType.SEER,
        won=True,
        reflection=GameReflection(opponent_notes={1: ["n1", "n2"]}),
        seat_to_memory_id={0: "me", 1: "bob"},
        my_seat=0,
        ts="t",
    )
    exp.record_game(
        game_id="g10",
        role=RoleType.SEER,
        won=True,
        reflection=GameReflection(opponent_notes={4: ["n3", "n4"]}),
        seat_to_memory_id={0: "me", 4: "bob"},
        my_seat=0,
        ts="t",
    )
    text = render_experience(exp, role=RoleType.SEER, opponents={"bob": 6, "zed": 2})
    assert "对手：\n- 6号：n2；n3；n4" in text  # 最近 3 条、映射到本局座位；无笔记的 zed 不出现
    assert "2号" not in text


def test_render_experience_empty_and_budget() -> None:
    assert render_experience(AgentExperience(memory_id="me"), role=RoleType.SEER, opponents={}) == ""
    only_notes = AgentExperience(memory_id="me")
    only_notes.record_game(
        game_id="g", role=RoleType.SEER, won=False,
        reflection=GameReflection(opponent_notes={1: ["x"]}),
        seat_to_memory_id={0: "me", 1: "bob"}, my_seat=0, ts="t",
    )
    assert render_experience(only_notes, role=RoleType.SEER, opponents={}) == ""  # 对手不在场
    assert "1号：x" in render_experience(only_notes, role=RoleType.SEER, opponents={"bob": 1})
    exp = _exp_with(*[(RoleType.SEER, True, "x" * 100) for _ in range(20)])
    text = render_experience(exp, role=RoleType.SEER, opponents={}, budget_chars=350)
    assert text.count("- [SEER·胜]") == 3  # 每条约 113 字符，预算 350 装 3 条
```

追加到 `backend/tests/test_agent_profile.py` 末尾：

```python
def test_profile_memory_id_field_and_echo_shape() -> None:
    p = AgentProfile.model_validate({"model": "m", "memory_id": "alice"})
    assert p.memory_id == "alice"
    assert AgentProfile(model="m").memory_id is None
    assert "memory_id" in AgentProfile(model="m").model_dump()
```

- [ ] **Step 2: 跑测试确认失败**

Run（`backend/`）: `uv run pytest tests/test_agent_experience.py tests/test_agent_profile.py -q`
Expected: `ModuleNotFoundError: app.agent.experience`；profile 用例 `memory_id` extra_forbidden。

- [ ] **Step 3: 实现 `backend/app/agent/experience.py`**

```python
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

_CLOSING = "以上是往局经验，本局身份与局势可能不同；不得据此推断本局任何私有信息，也不得据此违反规则。"
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
    """strip + 截到 limit 字，丢弃空条。"""
    out = [t.strip()[:limit] for t in items]
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
    me = next(p for p in state.players if p.seat == seat)
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
        notable_seats=tuple(sorted(s for s in set(notable_seats) if s != seat)),
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
        f"你是 {reveal.my_seat} 号，角色 {reveal.my_role.value}，本局{'获胜' if reveal.my_won else '未获胜'}。",
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
    """
    used = 0
    lesson_lines: list[str] = []
    same = [l for l in reversed(exp.lessons) if l.role == role]
    other = [l for l in reversed(exp.lessons) if l.role != role]
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
```

`backend/app/agent/profile.py`：
- import：`from app.agent.experience import MEMORY_ID_PATTERN`。
- docstring 第 5 行「（#56 模型路由、#58 skills、#57 personality）」→「（#56 模型路由、#58 skills、#57 personality、#59 memory_id）」。
- `AgentProfile` 在 `personality` 之后加：
  ```python
      # 跨局记忆标识（issue #59）：None=不持久化；同一局内须唯一，"*" 档案不得配置
      memory_id: str | None = Field(default=None, pattern=MEMORY_ID_PATTERN)
  ```
- `validate_profiles` 的座位键循环之后、`if library is not None` 之前插入：
  ```python
      seen: dict[str, str] = {}
      for key, profile in agents.items():
          mid = profile.memory_id
          if mid is None:
              continue
          if key == STAR:
              raise ValueError("agents['*'] 不能配置 memory_id：通配档案会展开成多个座位共用一份记忆")
          if mid in seen:
              raise ValueError(f"memory_id {mid!r} 被座位 {seen[mid]} 与 {key} 重复使用：同一局内须唯一")
          seen[mid] = key
  ```
  docstring 补「；memory_id 须座位唯一且不得配在 "*"」。

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_agent_experience.py tests/test_agent_profile.py -q` → 全 PASS。
Run: `uv run pytest -q -x --ignore=tests/test_api_e2e.py && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 全绿。注意 `test_api_lobby.py::test_create_legacy_ai_model_echoes_star` 的精确相等 dict 需补 `"memory_id": None,`（在 `"personality": None,` 之后）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/experience.py backend/app/agent/profile.py backend/tests/test_agent_experience.py backend/tests/test_agent_profile.py backend/tests/test_api_lobby.py
git commit -m "feat(agent): 跨局经验 schema/终局揭示/复盘 prompt/装配渲染；AgentProfile.memory_id (issue #59)"
```

---

### Task 2: 经验存储（内存 + JSON 文件原子写）

**Files:**
- Create: `backend/app/runtime/experience_store.py`
- Test: `backend/tests/test_experience_store.py`（新）

**Interfaces:**
- Consumes: Task 1 `AgentExperience`；`app.store.event_store.StoreError / StoreCorruptionError`。
- Produces: `ExperienceStore`（Protocol：`load(memory_id) -> AgentExperience`、`save(exp) -> None`）、`InMemoryExperienceStore`（`.saves: int`）、`JsonFileExperienceStore(data_dir: Path)`（`.path_for(memory_id) -> Path`）。

- [ ] **Step 1: 写失败测试**

```python
"""经验存储（issue #59）：round-trip、缺失即新、原子写、损坏 fail-loud——文件用 tmp_path。"""

import json

import pytest

from app.agent.experience import AgentExperience, GameReflection
from app.engine.config import RoleType
from app.runtime.experience_store import InMemoryExperienceStore, JsonFileExperienceStore
from app.store.event_store import StoreCorruptionError


def _sample(mid: str = "alice") -> AgentExperience:
    exp = AgentExperience(memory_id=mid)
    exp.record_game(
        game_id="g1", role=RoleType.SEER, won=True,
        reflection=GameReflection(lessons=["早报警徽流"], opponent_notes={3: ["爱跟票"]}),
        seat_to_memory_id={0: mid, 3: "bob"}, my_seat=0, ts="2026-09-20T00:00:00+00:00",
    )
    return exp


def test_in_memory_roundtrip_counts_saves_and_isolates_copies() -> None:
    store = InMemoryExperienceStore()
    fresh = store.load("alice")
    assert fresh.memory_id == "alice" and fresh.games_played == 0 and store.saves == 0
    exp = _sample()
    store.save(exp)
    exp.games_played = 99  # 保存后改原对象不得影响 store
    got = store.load("alice")
    assert got.games_played == 1 and got.lessons[0].text == "早报警徽流" and store.saves == 1


def test_json_file_missing_is_fresh_and_does_not_create_dir(tmp_path) -> None:
    d = tmp_path / "mem"
    store = JsonFileExperienceStore(d)
    assert store.load("alice").games_played == 0
    assert not d.exists()


def test_json_file_save_creates_dir_roundtrips_and_leaves_no_temp(tmp_path) -> None:
    d = tmp_path / "mem"
    store = JsonFileExperienceStore(d)
    store.save(_sample())
    assert store.path_for("alice") == d / "alice.json"
    assert sorted(p.name for p in d.iterdir()) == ["alice.json"]
    got = store.load("alice")
    assert got.games_played == 1 and got.opponent_notes["bob"][0].text == "爱跟票"
    raw = json.loads((d / "alice.json").read_text(encoding="utf-8"))
    assert raw["memory_id"] == "alice" and raw["lessons"][0]["role"] == "SEER"


@pytest.mark.parametrize(
    ("content", "hint"),
    [
        ("{not json", "合法 JSON"),
        ("[1, 2]", "顶层"),
        ('{"memory_id": "alice", "games_played": "many"}', "校验失败"),
        ('{"memory_id": "bob"}', "文件名不符"),
    ],
)
def test_json_file_corruption_is_loud_and_names_path(tmp_path, content, hint) -> None:
    d = tmp_path / "mem"
    d.mkdir()
    (d / "alice.json").write_text(content, encoding="utf-8")
    with pytest.raises(StoreCorruptionError, match=hint) as ei:
        JsonFileExperienceStore(d).load("alice")
    assert "alice.json" in str(ei.value)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_experience_store.py -q` → `ModuleNotFoundError: app.runtime.experience_store`。

- [ ] **Step 3: 实现 `backend/app/runtime/experience_store.py`**

```python
"""跨局经验存储（issue #59）：每个 memory_id 一份 JSON 文档。IO 层；引擎与 agent 层不感知。

损坏口径与 event_store 一致：真损坏（坏 JSON / 顶层非对象 / 校验失败 / memory_id 与文件名不符）
fail-loud 抛 StoreCorruptionError（信息含路径），不静默丢弃；写入用临时文件 + os.replace 原子替换，
因此不存在「残尾」需要修复。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.agent.experience import AgentExperience
from app.store.event_store import StoreCorruptionError, StoreError


class ExperienceStore(Protocol):
    def load(self, memory_id: str) -> AgentExperience:
        """不存在 → 全新 AgentExperience(memory_id=...)；不得有副作用（不建目录）。"""
        ...

    def save(self, exp: AgentExperience) -> None: ...


class InMemoryExperienceStore:
    """测试 / 不落盘运行用；saves 计数供「对局中不得写入」断言。"""

    def __init__(self) -> None:
        self._docs: dict[str, AgentExperience] = {}
        self.saves = 0

    def load(self, memory_id: str) -> AgentExperience:
        doc = self._docs.get(memory_id)
        return doc.model_copy(deep=True) if doc is not None else AgentExperience(memory_id=memory_id)

    def save(self, exp: AgentExperience) -> None:
        self._docs[exp.memory_id] = exp.model_copy(deep=True)
        self.saves += 1


class JsonFileExperienceStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir  # 目录在首次 save 时创建；无 memory_id 的运行永不落盘

    def path_for(self, memory_id: str) -> Path:
        return self._dir / f"{memory_id}.json"  # MEMORY_ID_PATTERN 保证无路径穿越

    def load(self, memory_id: str) -> AgentExperience:
        path = self.path_for(memory_id)
        if not path.exists():
            return AgentExperience(memory_id=memory_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StoreError(f"读取经验文件失败：{path}：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise StoreCorruptionError(f"经验文件不是合法 JSON：{path}：{exc}") from exc
        if not isinstance(raw, dict):
            raise StoreCorruptionError(f"经验文件顶层须为对象：{path}")
        try:
            exp = AgentExperience.model_validate(raw)
        except ValidationError as exc:
            raise StoreCorruptionError(f"经验文件校验失败：{path}：{exc}") from exc
        if exp.memory_id != memory_id:
            raise StoreCorruptionError(
                f"经验文件 memory_id 与文件名不符：{path}（文件内为 {exp.memory_id!r}）"
            )
        return exp

    def save(self, exp: AgentExperience) -> None:
        path = self.path_for(exp.memory_id)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{exp.memory_id}.", suffix=".tmp", dir=self._dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(exp.model_dump_json(indent=2))
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise StoreError(f"写入经验文件失败：{path}：{exc}") from exc
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_experience_store.py -q` → PASS；全量四条命令全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/experience_store.py backend/tests/test_experience_store.py
git commit -m "feat(runtime): 跨局经验存储——内存 store 与 JSON 文件原子写，损坏 fail-loud (issue #59)"
```

---

### Task 3: 端口接入——`static_system_prompt(experience_text=)`、`AgentPlayerPort(experience=, opponents=)`、`reflect_on_game`

**Files:**
- Modify: `backend/app/agent/prompts.py`（`static_system_prompt`）、`backend/app/agent/agent_player.py`（`AgentConfig`、`AgentPlayerPort.__init__/_system_for/reflect_on_game`、`build_agent_port`）
- Test: `backend/tests/test_agent_prompts.py`、`backend/tests/test_agent_player.py`（追加）

**Interfaces:**
- Consumes: Task 1 `AgentExperience`、`GameReveal`、`GameReflection`、`build_reflection_prompt`、`render_experience`、`DEFAULT_EXPERIENCE_BUDGET_CHARS`。
- Produces: `static_system_prompt(config, seat, role, personality_text="", experience_text="")`；`AgentConfig.experience_budget_chars`；`AgentPlayerPort(..., experience: AgentExperience | None = None, opponents: Mapping[str, int] | None = None)`；`async AgentPlayerPort.reflect_on_game(reveal, *, timeout_s=120.0) -> GameReflection | None`；`build_agent_port(seat, game_config, profile, *, library=None, experience=None, opponents=None)`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_agent_prompts.py` 末尾：

```python
def test_static_prompt_experience_block_after_personality_and_identity_when_empty() -> None:
    config = build_preset("std_9_kill_side")
    base = static_system_prompt(config, seat=2, role=RoleType.SEER)
    assert base == static_system_prompt(config, seat=2, role=RoleType.SEER, experience_text="")
    assert "== 跨局经验 ==" not in base
    sp = static_system_prompt(
        config, seat=2, role=RoleType.SEER, personality_text="P", experience_text="你此前打过 2 局。"
    )
    assert "== 跨局经验 ==\n你此前打过 2 局。" in sp
    assert sp.index("== 你的性格 ==") < sp.index("== 跨局经验 ==") < sp.index("发言用中文")
```

追加到 `backend/tests/test_agent_player.py` 末尾：

```python
def _experience() -> "AgentExperience":
    from app.agent.experience import AgentExperience, GameReflection

    exp = AgentExperience(memory_id="me")
    exp.record_game(
        game_id="g0",
        role=RoleType.WEREWOLF,
        won=False,
        reflection=GameReflection(lessons=["(往局教训) 当被查杀时，应先对跳"], opponent_notes={5: ["爱跟票"]}),
        seat_to_memory_id={0: "me", 5: "bob"},
        my_seat=0,
        ts="t",
    )
    return exp


async def test_experience_in_system_prompt_only_and_mapped_opponent() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is WolfDeliberation:
            return WolfDeliberation(analysis="a", proposed_target=3)
        return SpeechDecision(reasoning="r", content="c")

    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=0,
        game_config=build_preset("std_9_kill_side"),
        agent_config=AgentConfig(model="scripted"),
        client=client,
        experience=_experience(),
        opponents={"bob": 7},
    )
    await port.act(_obs("NIGHT_WEREWOLF"), time.time() + 60)
    _m, system, user = client.calls[-1]
    assert "== 跨局经验 ==" in system and "(往局教训)" in system and "7号：爱跟票" in system
    assert "往局教训" not in user and "跨局经验" not in user
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    assert client.calls[-1][1] == system  # 缓存：同一系统 prompt


async def test_no_experience_means_no_block() -> None:
    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        return SpeechDecision(reasoning="r", content="c")

    port, client = _port(script)
    await port.act(_obs("DAY_SPEECH"), time.time() + 60)
    assert "跨局经验" not in client.calls[-1][1]


async def test_reflect_on_game_uses_own_memory_and_reveal() -> None:
    from app.agent.experience import GameReflection, build_reveal
    from app.cli.bot import run_game

    state, _ = run_game(build_preset("std_9_kill_side").model_copy(update={"seed": 3}), "g1")
    wolf_seat = next(p.seat for p in state.players if p.role == RoleType.WEREWOLF)

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        if rm is WolfDeliberation:
            return WolfDeliberation(analysis="私谋X", proposed_target=3)
        if rm is GameReflection:
            return GameReflection(lessons=["L"], opponent_notes={})
        return SpeechDecision(reasoning="r", content="c")

    client = ScriptedLLMClient(script)
    port = AgentPlayerPort(
        seat=wolf_seat,
        game_config=state.config,
        agent_config=AgentConfig(model="scripted", reflection_model="cheap"),
        client=client,
    )
    await port.act(_obs("NIGHT_WEREWOLF", seat=wolf_seat), time.time() + 60)
    reveal = build_reveal(state, wolf_seat, notable_seats=[3])
    out = await port.reflect_on_game(reveal)
    assert out is not None and out.lessons == ["L"]
    model, system, user = client.calls[-1]
    assert model == "cheap" and "整局复盘" in system
    assert "== 终局揭示 ==" in user and "== 狼队私谋 ==\n[第1夜私谋] 私谋X" in user
    with pytest.raises(ValueError, match="座位"):
        await port.reflect_on_game(build_reveal(state, (wolf_seat + 1) % 9, notable_seats=[]))


async def test_reflect_on_game_failure_returns_none() -> None:
    from app.agent.experience import build_reveal
    from app.cli.bot import run_game

    state, _ = run_game(build_preset("std_9_kill_side").model_copy(update={"seed": 3}), "g1")

    def boom(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise RuntimeError("LLM 故障")

    port, _client = _port(boom)
    assert await port.reflect_on_game(build_reveal(state, 0, notable_seats=[])) is None
```

（`_port` 的座位固定为 0，`build_reveal(state, 0, …)` 与之匹配。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py -q` → 新用例失败（`experience_text` 未知参数；`AgentPlayerPort` 无 `experience`；无 `reflect_on_game`）。

- [ ] **Step 3: 实现**

`backend/app/agent/prompts.py` `static_system_prompt`：

```python
def static_system_prompt(
    config: GameConfig,
    seat: int,
    role: RoleType,
    personality_text: str = "",
    experience_text: str = "",
) -> str:
    roles_desc = "、".join(f"{slot.role.value}x{slot.count}" for slot in config.roles)
    win = _WIN_TEXT.get(config.win_condition, str(config.win_condition))
    sheriff = "启用警长（1.5 票与发言顺序权）" if config.sheriff.enabled else "无警长"
    # 人设段（issue #57）与跨局经验段（issue #59）：只在静态段，位于角色行之后、通用约束句之前；
    # 为空时输出逐字不变
    personality_block = f"== 你的性格 ==\n{personality_text}\n" if personality_text else ""
    experience_block = f"== 跨局经验 ==\n{experience_text}\n" if experience_text else ""
    return (
        "你在玩狼人杀。服务器是唯一裁决者，你只提交意图。\n"
        f"本局配置：{config.num_players} 人（{roles_desc}）；胜利条件：{win}；{sheriff}。\n"
        f"你是 {seat} 号，角色：{role.value}。{ROLE_BRIEFS[role]}\n"
        f"{personality_block}"
        f"{experience_block}"
        "发言用中文，符合角色立场；狼人白天绝不能泄露夜间的私下谋划。"
    )
```

`backend/app/agent/agent_player.py`：
- import：`from collections.abc import Mapping, Sequence`；`from app.agent.experience import (DEFAULT_EXPERIENCE_BUDGET_CHARS, AgentExperience, GameReflection, GameReveal, build_reflection_prompt, render_experience)`；`from app.engine.config import GameConfig, RoleType`。
- `AgentConfig` 末尾加：
  ```python
      # 装配跨局经验的字符预算（issue #59）
      experience_budget_chars: int = DEFAULT_EXPERIENCE_BUDGET_CHARS
  ```
- `__init__` 签名在 `personality` 之后加 `experience: AgentExperience | None = None, opponents: Mapping[str, int] | None = None`；体内 `self._experience = experience`、`self._opponents: dict[str, int] = dict(opponents or {})`。
- `_system_for`：
  ```python
      def _system_for(self, obs: PlayerObservation) -> str:
          if self._system_prompt is None:
              personality_text = render_personality(self._personality) if self._personality else ""
              # 跨局经验按本局角色挑选，故只能在首个 observation 到达后渲染；随后缓存
              experience_text = (
                  render_experience(
                      self._experience,
                      role=obs.my_role,
                      opponents=self._opponents,
                      budget_chars=self._cfg.experience_budget_chars,
                  )
                  if self._experience is not None
                  else ""
              )
              static = static_system_prompt(
                  self._game_config,
                  self._seat,
                  obs.my_role,
                  personality_text=personality_text,
                  experience_text=experience_text,
              )
              if self._skills:
                  static += "\n== 你的技能 ==\n" + skills_index_text(self._skills)
              self._system_prompt = static
          return self._system_prompt
  ```
- 在 `act` 之后新增方法：
  ```python
      async def reflect_on_game(
          self, reveal: GameReveal, *, timeout_s: float = 120.0
      ) -> GameReflection | None:
          """局后复盘（issue #59）：只用本端口自己的记忆分区 + 终局揭示；任何失败 → None。

          不写回 AgentMemory；由 runtime 的 postgame 把结果记入经验存储。
          """
          if reveal.my_seat != self._seat:
              raise ValueError(f"揭示表座位 {reveal.my_seat} 与端口座位 {self._seat} 不符")
          night_private = (
              self.memory.night_private_context() if reveal.my_role == RoleType.WEREWOLF else ""
          )
          system, user = build_reflection_prompt(reveal, self.memory.build_context(), night_private)
          try:
              return await asyncio.wait_for(
                  self._client.complete_structured(
                      system_prompt=system,
                      user_prompt=user,
                      response_model=GameReflection,
                      model=self._cfg.reflection_model or self._cfg.model,
                      temperature=self._cfg.temperature,
                  ),
                  timeout=timeout_s,
              )
          except Exception as exc:  # 含超时与校验失败：降级为本局不写经验
              logger.warning("seat=%d 局后复盘失败：%s", self._seat, exc)
              return None
  ```
- `build_agent_port` 签名加 `experience: AgentExperience | None = None, opponents: Mapping[str, int] | None = None`；构造时传 `experience=experience, opponents=opponents`；docstring「issue #56/#58」→「issue #56/#58/#59」。

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_agent_prompts.py tests/test_agent_player.py -q` → PASS；四条命令全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts.py backend/app/agent/agent_player.py backend/tests/test_agent_prompts.py backend/tests/test_agent_player.py
git commit -m "feat(agent): 跨局经验注入系统 prompt 静态段；端口 reflect_on_game 局后复盘 (issue #59)"
```

---

### Task 4: 局后编排 + registry / API / CLI 触发 + 档案表

**Files:**
- Create: `backend/app/runtime/postgame.py`
- Modify: `backend/app/runtime/registry.py`、`backend/app/main.py`、`backend/app/cli/play.py`、`backend/app/cli/play_human.py`、`backend/app/cli/render.py`
- Test: `backend/tests/test_registry.py`、`backend/tests/test_api_lobby.py`、`backend/tests/test_cli_play_watch.py`、`backend/tests/test_cli_render.py`（追加）

**Interfaces:**
- Consumes: Task 1 `build_reveal`、`AgentExperience`；Task 2 `ExperienceStore`、`InMemoryExperienceStore`、`JsonFileExperienceStore`；Task 3 `reflect_on_game`、`build_agent_port(experience=, opponents=)`。
- Produces: `postgame.seat_memory_ids(profiles, num_players) -> dict[int, str]`、`postgame.opponents_for(seat, seat_ids) -> dict[str, int]`、`async postgame.run_postgame(*, game_id, final_state, profiles, ports, store, now=utc_now_iso) -> dict[str, AgentExperience]`；`GameHandle.seat_memory_ids / experiences / postgame_task`；`GameRegistry(..., experience_store=None)` + `.experience_store`；`create_app(..., memory_dir=None, experience_store=None)`；CLI `--memory-dir`、`load_experiences(agents, num_players, store)`、`_wire_game(..., experiences=None)`、`run_watch/run_play(..., experience_store=None)`；`render_agent_roster(..., experiences=None)`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registry.py` 末尾：

```python
async def test_memory_id_loads_experience_wires_opponents_and_runs_postgame() -> None:
    from pydantic import BaseModel

    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.experience import AgentExperience, GameReflection
    from app.agent.memory import ReflectionResult
    from app.agent.profile import AgentProfile
    from app.runtime.experience_store import InMemoryExperienceStore
    from app.runtime.postgame import opponents_for
    from tests.llm_helpers import ScriptedLLMClient, action_to_decision

    store = InMemoryExperienceStore()
    seeded = AgentExperience(memory_id="alice")
    seeded.record_game(
        game_id="g0", role=RoleType.VILLAGER, won=True,
        reflection=GameReflection(lessons=["(seeded) 慎投"], opponent_notes={1: ["跟票"]}),
        seat_to_memory_id={0: "alice", 1: "bob"}, my_seat=0, ts="t",
    )
    store.save(seeded)
    seen: dict[int, tuple[object, dict[str, int]]] = {}

    def factory(seat: int, handle: GameHandle) -> PlayerPort:
        seen[seat] = (handle.experiences.get(seat), opponents_for(seat, handle.seat_memory_ids))

        def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
            if rm is ReflectionResult:
                return ReflectionResult(summary="(r)", qa=[])
            if rm is GameReflection:
                return GameReflection(lessons=[f"(lesson of {seat})"], opponent_notes={})
            assert handle.runner is not None
            return action_to_decision(RandomBot.choose_action(handle.runner.state, seat), rm)

        return AgentPlayerPort(
            seat=seat, game_config=handle.config,
            agent_config=AgentConfig(model="scripted", agent_seed=1),
            client=ScriptedLLMClient(script),
            experience=handle.experiences.get(seat),
            opponents=opponents_for(seat, handle.seat_memory_ids),
        )

    reg = GameRegistry(
        InMemoryEventStore(), RunnerTimeouts(speech_sec=30.0, action_sec=30.0),
        agent_port_factory=factory, experience_store=store,
    )
    agents = {
        "0": AgentProfile(model="m", memory_id="alice"),
        "1": AgentProfile(model="m", memory_id="bob"),
        "*": AgentProfile(model="m"),
    }
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = reg.create(config, allow_spectators=False, agents=agents)
    reg.start(handle)
    assert handle.seat_memory_ids == {0: "alice", 1: "bob"}
    exp0, opp0 = seen[0]
    assert isinstance(exp0, AgentExperience) and exp0.games_played == 1 and opp0 == {"bob": 1}
    assert seen[1][1] == {"alice": 0} and seen[2] == (None, {"alice": 0, "bob": 1})
    assert store.saves == 1  # 只有测试自己的 seed；对局中不写
    assert handle.task is not None
    await asyncio.wait_for(handle.task, timeout=120)
    assert store.saves == 1  # 终局瞬间仍未写：写入只在 postgame 任务里
    updated = await asyncio.wait_for(await _postgame_of(handle), timeout=60)
    assert set(updated) == {"alice", "bob"} and store.saves == 3
    alice = store.load("alice")
    assert alice.games_played == 2 and alice.lessons[-1].text == "(lesson of 0)"
    assert store.load("bob").lessons[-1].text == "(lesson of 1)"


async def _postgame_of(handle: GameHandle) -> "asyncio.Task[object]":
    """done-callback 与 await 的唤醒同在下一轮事件循环；让出几步再取 postgame_task。"""
    for _ in range(10):
        if handle.postgame_task is not None:
            return handle.postgame_task  # type: ignore[return-value]
        await asyncio.sleep(0)
    raise AssertionError("postgame_task 未被调度")


async def test_no_memory_id_means_no_postgame_task() -> None:
    reg = _registry()  # 文件已有的辅助工厂；若无则用 GameRegistry(InMemoryEventStore(), TIMEOUTS)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    handle = reg.create(config, allow_spectators=False, ai_model=None)
    reg.start(handle)
    assert handle.task is not None
    await asyncio.wait_for(handle.task, timeout=60)
    await asyncio.sleep(0)
    assert handle.postgame_task is None and handle.seat_memory_ids == {}


def test_create_rejects_duplicate_and_star_memory_id() -> None:
    from app.agent.profile import AgentProfile

    reg = GameRegistry(InMemoryEventStore())
    config = build_preset("std_9_kill_side")
    with pytest.raises(ValueError, match="重复"):
        reg.create(
            config, allow_spectators=False,
            agents={"0": AgentProfile(model="m", memory_id="a"), "1": AgentProfile(model="m", memory_id="a")},
        )
    with pytest.raises(ValueError, match="'\\*'"):
        reg.create(config, allow_spectators=False, agents={"*": AgentProfile(model="m", memory_id="a")})
```

（`test_registry.py` 已 import `RandomBot`、`build_preset`、`RunnerTimeouts`、`PlayerPort`、`GameHandle`、`GameRegistry`、`InMemoryEventStore`、`pytest`、`asyncio`；需补 `from app.engine.config import RoleType`。`_registry()` 若文件没有同名辅助，用 `GameRegistry(InMemoryEventStore(), RunnerTimeouts(speech_sec=30.0, action_sec=30.0))`。）

追加到 `backend/tests/test_api_lobby.py` 末尾：

```python
def test_create_agents_memory_id_echo_and_conflicts_400(client: TestClient) -> None:
    body = {
        "preset": "std_9_kill_side",
        "agents": {"0": {"model": "m", "memory_id": "alice"}, "1": {"model": "m", "memory_id": "bob"}},
    }
    r = client.post("/api/v1/games", json=body)
    assert r.status_code == 200 and r.json()["agents"]["0"]["memory_id"] == "alice"
    dup = {"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "memory_id": "a"}, "1": {"model": "m", "memory_id": "a"}}}
    assert client.post("/api/v1/games", json=dup).status_code == 400
    star = {"preset": "std_9_kill_side", "agents": {"*": {"model": "m", "memory_id": "a"}}}
    assert client.post("/api/v1/games", json=star).status_code == 400
    bad = {"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "memory_id": "a/b"}}}
    assert client.post("/api/v1/games", json=bad).status_code == 422


def test_create_app_memory_dir_is_lazy_and_corrupt_file_is_500(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.store.event_store import InMemoryEventStore

    mem = tmp_path / "mem"
    c = TestClient(create_app(store=InMemoryEventStore(), memory_dir=mem))
    r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "ai_model": "m"})
    assert r.status_code == 200 and not mem.exists()  # 无 memory_id 永不建目录
    mem.mkdir()
    (mem / "alice.json").write_text("{bad", encoding="utf-8")
    r = c.post(
        "/api/v1/games",
        json={"preset": "std_9_kill_side", "agents": {"0": {"model": "m", "memory_id": "alice"}}},
    )
    assert r.status_code == 200  # 建局只登记；装配在 start
    game_id, host = r.json()["game_id"], r.json()["host_token"]
    r = c.post(f"/api/v1/games/{game_id}/start", json={}, headers=_auth(host))
    assert r.status_code == 500 and "alice.json" in r.json()["detail"]
```

（`_auth` 是文件已有的辅助，与 `test_create_join_start_all_ai` 同一写法。）

追加到 `backend/tests/test_cli_render.py::test_render_agent_roster` 末尾：

```python
    from app.agent.experience import AgentExperience

    with_mid = {"0": AgentProfile(model="m", memory_id="alice")}
    assert "记忆 alice" in render_agent_roster(with_mid, num_players=1, human_seat=None)
    exp = AgentExperience(memory_id="alice", games_played=4)
    out = render_agent_roster(with_mid, num_players=1, human_seat=None, experiences={"alice": exp})
    assert "记忆 alice（4 局）" in out
```

追加到 `backend/tests/test_cli_play_watch.py` 末尾：

```python
def test_load_agent_profiles_memory_id_and_wire_passes_experience(tmp_path) -> None:
    from app.agent.agent_player import AgentPlayerPort
    from app.agent.experience import AgentExperience
    from app.cli.play import load_agent_profiles, load_experiences
    from app.runtime.experience_store import InMemoryExperienceStore

    y = tmp_path / "p.yaml"
    y.write_text(
        'seats:\n  "0": {model: ollama/a, memory_id: alice}\n  "3": {model: ollama/b, memory_id: bob}\n',
        encoding="utf-8",
    )
    agents = load_agent_profiles(str(y))
    assert agents["0"].memory_id == "alice" and agents["3"].memory_id == "bob"
    store = InMemoryExperienceStore()
    store.save(AgentExperience(memory_id="alice", games_played=2))
    exps = load_experiences(agents, 9, store)
    assert exps["alice"].games_played == 2 and exps["bob"].games_played == 0
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    _r, _c, ports = _wire_game(config, agents=agents, experiences=exps)
    p0, p3 = ports[0], ports[3]
    assert isinstance(p0, AgentPlayerPort) and isinstance(p3, AgentPlayerPort)
    assert p0._experience is exps["alice"] and p0._opponents == {"bob": 3}
    assert p3._opponents == {"alice": 0}


def test_main_memory_dir_default_and_duplicate_memory_id(tmp_path, capsys) -> None:
    from app.cli.play import main

    y = tmp_path / "dup.yaml"
    y.write_text(
        'seats:\n  "0": {model: ollama/a, memory_id: a}\n  "1": {model: ollama/b, memory_id: a}\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main(["--agents", str(y)])
    assert "重复" in capsys.readouterr().err


def test_watch_game_with_memory_runs_postgame_and_persists(tmp_path, capsys, monkeypatch) -> None:
    """随机 bot 局 + 一个脚本化 Agent 座位配 memory_id：结束后复盘落盘并打印摘要。"""
    from pydantic import BaseModel

    import app.cli.play as play_mod
    from app.agent.agent_player import AgentConfig, AgentPlayerPort
    from app.agent.experience import GameReflection
    from app.agent.memory import ReflectionResult
    from app.agent.profile import AgentProfile
    from app.cli.bot import RandomBot
    from app.runtime.experience_store import JsonFileExperienceStore
    from tests.llm_helpers import ScriptedLLMClient, action_to_decision

    holder: dict[str, object] = {}

    def fake_build_agent_port(seat, game_config, profile, *, library=None, experience=None, opponents=None):
        def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
            if rm is ReflectionResult:
                return ReflectionResult(summary="(r)", qa=[])
            if rm is GameReflection:
                return GameReflection(lessons=["(cli lesson)"], opponent_notes={})
            runner = holder["runner"]
            return action_to_decision(RandomBot.choose_action(runner.state, seat), rm)  # type: ignore[attr-defined]

        return AgentPlayerPort(
            seat=seat, game_config=game_config, agent_config=AgentConfig(model="scripted"),
            client=ScriptedLLMClient(script), experience=experience, opponents=opponents,
        )

    import app.agent.agent_player as ap

    monkeypatch.setattr(ap, "build_agent_port", fake_build_agent_port)
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    mem = tmp_path / "mem"
    store = JsonFileExperienceStore(mem)
    agents = {"0": AgentProfile(model="m", memory_id="alice")}

    async def _no_read(prompt: str) -> str:
        raise AssertionError("看局非 step 模式不应读输入")

    orig_wire = play_mod._wire_game

    def wire(config, **kw):
        out = orig_wire(config, **kw)
        holder["runner"] = out[0]
        return out

    monkeypatch.setattr(play_mod, "_wire_game", wire)
    state = asyncio.run(
        run_watch(config, view="GM", delay=0.0, step=False, agents=agents, experience_store=store, read_line=_no_read)
    )
    from app.engine.phases import Phase

    assert state.phase == Phase.GAME_OVER
    out = capsys.readouterr().out
    assert "记忆 alice" in out.splitlines()[0]  # 档案表列
    assert "复盘中" in out and "记忆 alice：1 局，教训 1" in out
    assert store.load("alice").lessons[0].text == "(cli lesson)"
```

（`_wire_game` 里 `build_agent_port` 是函数内局部 import `from app.agent.agent_player import build_agent_port`，所以 monkeypatch 模块属性即可生效。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_registry.py tests/test_api_lobby.py tests/test_cli_render.py tests/test_cli_play_watch.py -q` → 新用例失败（`experience_store` 未知参数、无 `postgame` 模块、`load_experiences` 不存在、roster 无「记忆」列等）。

- [ ] **Step 3: 实现**

**`backend/app/runtime/postgame.py`**（新）：

```python
"""局后复盘编排（issue #59）：终局后对有 memory_id 的 Agent 端口做整局复盘并写入经验存储。

只在 GAME_OVER 后运行；单座位失败只记日志、不影响其他座位；对局中绝不写 store。
模块级不 import app.agent.agent_player（litellm 惰性加载）——端口能力用结构化协议判断。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.agent.experience import AgentExperience, GameReflection, GameReveal, build_reveal
from app.agent.profile import AgentProfiles, profile_for
from app.engine.phases import Phase
from app.engine.state import GameState
from app.runtime.experience_store import ExperienceStore
from app.runtime.player_port import PlayerPort

logger = logging.getLogger(__name__)


@runtime_checkable
class SupportsGameReflection(Protocol):
    """能做局后复盘的端口（AgentPlayerPort 实现）。"""

    async def reflect_on_game(self, reveal: GameReveal) -> GameReflection | None: ...


def seat_memory_ids(profiles: AgentProfiles, num_players: int) -> dict[int, str]:
    """座位 → memory_id（只含配置了 memory_id 的座位；"*" 档案已被 validate_profiles 拒绝）。"""
    out: dict[int, str] = {}
    for seat in range(num_players):
        p = profile_for(profiles, seat)
        if p is not None and p.memory_id is not None:
            out[seat] = p.memory_id
    return out


def opponents_for(seat: int, seat_ids: Mapping[int, str]) -> dict[str, int]:
    """装配用：其他有 memory_id 的座位，memory_id → 本局座位。"""
    return {mid: s for s, mid in seat_ids.items() if s != seat}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def run_postgame(
    *,
    game_id: str,
    final_state: GameState,
    profiles: AgentProfiles,
    ports: Mapping[int, PlayerPort],
    store: ExperienceStore,
    now: Callable[[], str] = utc_now_iso,
) -> dict[str, AgentExperience]:
    """对每个有 memory_id 的 Agent 座位：揭示 → 复盘 → load → record_game → save。返回本次更新。"""
    if final_state.phase != Phase.GAME_OVER:
        raise ValueError("局后复盘只能在 GAME_OVER 后运行")
    seat_ids = seat_memory_ids(profiles, len(final_state.players))
    updated: dict[str, AgentExperience] = {}
    for seat, mid in seat_ids.items():
        port = ports.get(seat)
        if not isinstance(port, SupportsGameReflection):
            continue  # 真人占座 / 随机 bot：档案未生效
        try:
            reveal = build_reveal(final_state, seat, notable_seats=[s for s in seat_ids if s != seat])
            reflection = await port.reflect_on_game(reveal)
            if reflection is None:
                continue
            exp = store.load(mid)
            exp.record_game(
                game_id=game_id,
                role=reveal.my_role,
                won=reveal.my_won,
                reflection=reflection,
                seat_to_memory_id=seat_ids,
                my_seat=seat,
                ts=now(),
            )
            store.save(exp)
            updated[mid] = exp
        except Exception as exc:  # 单座位失败不影响其他座位
            logger.warning("memory_id=%s seat=%d 局后写入经验失败：%s", mid, seat, exc)
    return updated
```

**`backend/app/runtime/registry.py`**：
- import：`from app.agent.experience import AgentExperience`；`from app.runtime.experience_store import ExperienceStore, InMemoryExperienceStore`；`from app.runtime.postgame import opponents_for, run_postgame, seat_memory_ids`。
- `GameHandle.__init__` 末尾加：
  ```python
          # 跨局记忆（issue #59）：start 时装配；task 正常结束后由 registry 调度 postgame
          self.seat_memory_ids: dict[int, str] = {}
          self.experiences: dict[int, AgentExperience] = {}
          self.postgame_task: asyncio.Task[dict[str, AgentExperience]] | None = None
  ```
- `GameRegistry.__init__` 加参数 `experience_store: ExperienceStore | None = None`，体内 `self._experience_store: ExperienceStore = experience_store if experience_store is not None else InMemoryExperienceStore()`；加 `@property experience_store`。
- `start()`：在 `handle.connections = ConnectionManager(...)` 之前加：
  ```python
          # 跨局记忆装配：只对没被真人占的、配了 memory_id 的座位 load（坏文件在此 fail-loud）
          handle.seat_memory_ids = seat_memory_ids(handle.agents, handle.config.num_players)
          for seat, mid in handle.seat_memory_ids.items():
              if seat not in handle.ports:
                  handle.experiences[seat] = self._experience_store.load(mid)
  ```
  `handle.task = asyncio.create_task(runner.run())` 之后加：
  ```python
          if handle.seat_memory_ids:
              handle.task.add_done_callback(lambda t: self._schedule_postgame(handle, t))
  ```
- 新方法：
  ```python
      def _schedule_postgame(self, handle: GameHandle, task: asyncio.Task[GameState]) -> None:
          """runner 正常终局后异步复盘；崩溃/取消不复盘。任务对象挂在 handle 上供测试 await。"""
          if task.cancelled() or task.exception() is not None:
              return
          handle.postgame_task = asyncio.create_task(
              run_postgame(
                  game_id=handle.game_id,
                  final_state=task.result(),
                  profiles=handle.agents,
                  ports=handle.ports,
                  store=self._experience_store,
              )
          )
  ```
- `_build_agent_port`：`build_agent_port(seat, handle.config, profile, library=self.skill_library, experience=handle.experiences.get(seat), opponents=opponents_for(seat, handle.seat_memory_ids))`。

**`backend/app/main.py`**：
- import：`from app.runtime.experience_store import ExperienceStore, JsonFileExperienceStore`。
- `create_app` 加参数 `memory_dir: Path | None = None, experience_store: ExperienceStore | None = None`；`GameRegistry(...)` 加 `experience_store=experience_store or JsonFileExperienceStore(memory_dir or Path("data/agent_memory"))`。docstring/注释一行：「跨局记忆目录（issue #59）：惰性建目录，无 memory_id 的运行永不落盘」。

**`backend/app/cli/render.py`**：
- import：`from collections.abc import Mapping`；`from app.agent.experience import AgentExperience`。
- 签名 `render_agent_roster(agents, num_players, human_seat, *, experiences: Mapping[str, AgentExperience] | None = None)`；在 `personality` 之后加：
  ```python
          if p.memory_id is not None:
              exp = (experiences or {}).get(p.memory_id)
              games = f"（{exp.games_played} 局）" if exp is not None else ""
              parts.append(f"记忆 {p.memory_id}{games}")
  ```

**`backend/app/cli/play.py`**：
- import：`from collections.abc import Awaitable, Callable, Mapping`；`from app.agent.experience import AgentExperience`；`from app.runtime.experience_store import ExperienceStore, InMemoryExperienceStore, JsonFileExperienceStore`；`from app.runtime.postgame import opponents_for, run_postgame, seat_memory_ids`；`from app.store.event_store import StoreError`。
- 新函数（放 `_wire_game` 之前）：
  ```python
  def load_experiences(
      agents: AgentProfiles, num_players: int, store: ExperienceStore
  ) -> dict[str, AgentExperience]:
      """建局前装载所有配了 memory_id 座位的经验（坏文件在此 fail-loud）。"""
      return {mid: store.load(mid) for mid in seat_memory_ids(agents, num_players).values()}


  async def _postgame_report(
      state: GameState,
      agents: AgentProfiles,
      ports: Mapping[int, PlayerPort],
      store: ExperienceStore,
      game_id: str,
  ) -> None:
      """终局后复盘并打印每个 memory_id 的累积摘要；无 memory_id 档案 → 静默。"""
      if not seat_memory_ids(agents, len(state.players)):
          return
      print("复盘中…")
      updated = await run_postgame(
          game_id=game_id, final_state=state, profiles=agents, ports=ports, store=store
      )
      for mid, exp in updated.items():
          notes = sum(len(v) for v in exp.opponent_notes.values())
          print(f"记忆 {mid}：{exp.games_played} 局，教训 {len(exp.lessons)}，对手笔记 {notes}")
  ```
- `_wire_game` 签名加 `experiences: Mapping[str, AgentExperience] | None = None`；体内循环前 `seat_ids = seat_memory_ids(agents, n)`，`build_agent_port(seat, config, profile, library=library, experience=(experiences or {}).get(profile.memory_id) if profile.memory_id else None, opponents=opponents_for(seat, seat_ids))`（拆行以过 ruff）。
- `run_watch` 签名加 `experience_store: ExperienceStore | None = None`；体内：
  ```python
      store = experience_store if experience_store is not None else InMemoryExperienceStore()
      experiences = load_experiences(agents or {}, config.num_players, store)
      runner, conns, ports = _wire_game(config, agents=agents, library=library, experiences=experiences)
      print(render_agent_roster(agents or {}, config.num_players, None, experiences=experiences))
      ...
      conns.subscribe(view, on_events)  # 必须先于 run
      state = await runner.run()
      await _postgame_report(state, agents or {}, ports, store, f"cli-{config.seed}")
      return state
  ```
- `main`：加 `parser.add_argument("--memory-dir", default="data/agent_memory", help="跨局记忆目录（每个 memory_id 一个 JSON；无 memory_id 档案时不落盘）")`；`store = JsonFileExperienceStore(Path(args.memory_dir))`；两个 `asyncio.run(...)` 调用各加 `experience_store=store`，并包一层：
  ```python
      try:
          asyncio.run(...)
      except StoreError as exc:  # 坏的经验文件：明确报错而非 traceback
          parser.error(str(exc))
  ```

**`backend/app/cli/play_human.py`**：`run_play` 签名加 `experience_store: ExperienceStore | None = None`（import `ExperienceStore, InMemoryExperienceStore` 与 `load_experiences, _postgame_report` 自 `app.cli.play`）；与 `run_watch` 同样：load → `_wire_game(..., experiences=experiences)` → roster 带 `experiences=` → `finally` 块之后、打印「游戏结束」之前 `await _postgame_report(state, agents or {}, ports, store, f"cli-{config.seed}")`。

- [ ] **Step 4: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_registry.py tests/test_api_lobby.py tests/test_cli_render.py tests/test_cli_play_watch.py -q` → PASS。
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 全绿；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 仍过（postgame/experience_store 不 import agent_player）。

- [ ] **Step 5: 真机看一眼**（`backend/`；**不要**用 `timeout` 包裹）

```bash
printf 'seats:\n  "0": {name: 老张, model: ollama/a, memory_id: laozhang}\n  "3": {model: ollama/b, memory_id: bot3}\n' > /tmp/agents-m.yaml
PYTHONUNBUFFERED=1 uv run python -m app.cli.play --preset std_9_kill_side --seed 3 --view gm --delay 0 --no-color --agents /tmp/agents-m.yaml --memory-dir /tmp/agenthowl-mem 2>/dev/null | head -4
```
Expected 第 1 行：`0号 老张 · ollama/a · T=0.3 · 记忆 laozhang（0 局）`；第 4 行 `3号 Bot3 · ollama/b · T=0.3 · 记忆 bot3（0 局）`；`/tmp/agenthowl-mem` 不存在（`head` 提前关管道，局未结束）。另跑坏文件：`mkdir -p /tmp/agenthowl-mem && echo '{bad' > /tmp/agenthowl-mem/laozhang.json` 后同命令 `2>&1 | grep -o "error:.*" | head -c 160` → `error: 经验文件不是合法 JSON：…laozhang.json…`。

- [ ] **Step 6: Commit**

```bash
git add backend/app/runtime/postgame.py backend/app/runtime/registry.py backend/app/main.py backend/app/cli/play.py backend/app/cli/play_human.py backend/app/cli/render.py backend/tests/test_registry.py backend/tests/test_api_lobby.py backend/tests/test_cli_render.py backend/tests/test_cli_play_watch.py
git commit -m "feat(runtime): 局后复盘编排 + registry/API/CLI 触发与装配；档案表记忆列 (issue #59)"
```

---

### Task 5: 两局集成测试 + README / PRD

**Files:**
- Modify: `backend/tests/test_agent_integration.py`（追加）、`README.md`（YAML 样例 + 新小节「跨局记忆 / Cross-game memory」）、`docs/specs/requirements.md`（§4.4.1 补段、§5.2 `agents` 说明补 `memory_id`）

**Interfaces:**
- Consumes: Task 4 全部。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_agent_integration.py` 末尾：

```python
async def test_two_games_accumulate_experience_and_second_game_prompt_has_it() -> None:
    """两座位配 memory_id：第 1 局终局后复盘落盘（局中零写入）；第 2 局系统 prompt 含往局教训与对手行。"""
    from app.agent.experience import GameReflection
    from app.agent.profile import AgentProfile
    from app.runtime.experience_store import InMemoryExperienceStore
    from app.runtime.postgame import opponents_for

    store = InMemoryExperienceStore()
    clients: dict[int, ScriptedLLMClient] = {}

    def make_registry() -> GameRegistry:
        def factory(seat: int, handle: GameHandle) -> PlayerPort:
            base = _omniscient_script(handle, seat)

            def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
                if rm is GameReflection:
                    return GameReflection(
                        lessons=[f"(lesson {seat}) 当被怀疑时，应先摆事实"],
                        opponent_notes={s: [f"(note by {seat})"] for s in range(9)},
                    )
                return base(rm, system, user)

            client = ScriptedLLMClient(script)
            clients[seat] = client
            return AgentPlayerPort(
                seat=seat,
                game_config=handle.config,
                agent_config=AgentConfig(model="scripted", agent_seed=7),
                client=client,
                experience=handle.experiences.get(seat),
                opponents=opponents_for(seat, handle.seat_memory_ids),
            )

        return GameRegistry(
            InMemoryEventStore(), TIMEOUTS, agent_port_factory=factory, experience_store=store
        )

    agents = {
        "0": AgentProfile(model="scripted", memory_id="alice"),
        "1": AgentProfile(model="scripted", memory_id="bob"),
        "*": AgentProfile(model="scripted"),
    }
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def postgame_of(handle: GameHandle):  # done-callback 在下一轮循环才挂上任务
        for _ in range(10):
            if handle.postgame_task is not None:
                return handle.postgame_task
            await asyncio.sleep(0)
        raise AssertionError("postgame_task 未被调度")

    reg1 = make_registry()
    h1 = reg1.create(config, allow_spectators=False, agents=agents)
    reg1.start(h1)
    assert store.saves == 0
    assert h1.task is not None
    await asyncio.wait_for(h1.task, timeout=120)
    assert store.saves == 0  # 对局中（含终局瞬间）不写；写入只在 postgame 任务里
    await asyncio.wait_for(await postgame_of(h1), timeout=60)
    assert store.saves == 2
    alice = store.load("alice")
    assert alice.games_played == 1 and alice.lessons[0].text.startswith("(lesson 0)")
    assert [n.text for n in alice.opponent_notes["bob"]] == ["(note by 0)"]
    assert set(alice.opponent_notes) == {"bob"}  # 无 memory_id 座位与自己被丢弃
    # 第 1 局的系统 prompt 不含经验（首局）
    assert all("跨局经验" not in c[1] for s in (0, 1) for c in clients[s].calls)

    reg2 = make_registry()
    h2 = reg2.create(config, allow_spectators=False, agents=agents)
    reg2.start(h2)
    assert h2.experiences[0].games_played == 1
    assert h2.task is not None
    await asyncio.wait_for(h2.task, timeout=120)
    # 0 号可能首夜被刀而一次未行动；取 0/1 中有决策调用的那位（两位同时首夜出局极罕见）
    s = next(s for s in (0, 1) if any("== 局势 ==" in c[2] for c in clients[s].calls))
    system = next(c[1] for c in clients[s].calls if "== 局势 ==" in c[2])
    assert "== 跨局经验 ==" in system and f"(lesson {s})" in system
    assert f"{1 - s}号：(note by {s})" in system  # 对手 memory_id 映射回本局座位
    assert all("跨局经验" not in c[1] for c in clients[2].calls)  # 无 memory_id 座位无经验
    await asyncio.wait_for(await postgame_of(h2), timeout=60)
    assert store.load("alice").games_played == 2 and store.saves == 4
```

（`clients[seat]` 在第 2 局 `make_registry` 时被覆盖，故第 2 局断言看到的是第 2 局的调用记录；第 1 局断言须放在 `reg2` 之前——如上。）

- [ ] **Step 2: 跑测试确认通过**

Run: `uv run pytest tests/test_agent_integration.py -q` → 全 PASS（Task 4 已实现；本用例是端到端验收，预期直接过；若失败即为缺陷，按报告处理）。

- [ ] **Step 3: 文档**

`README.md`：
- 「每座位 Agent 档案」YAML 样例：`"0"` 加 `memory_id: laozhang`，`"3"` 加 `memory_id: bot3`。
- 在「人格 / Personality」之后新增小节「跨局记忆 / Cross-game memory」（`###`，风格对齐相邻小节）：`memory_id` 是什么（文件名安全、同局唯一、`"*"` 不可配）；局后复盘做什么（自身视角 + 终局揭示 → 1–3 条教训 + 对有 `memory_id` 对手的笔记）；存哪（`data/agent_memory/<memory_id>.json`，`--memory-dir` / `create_app(memory_dir=)`；上限 50 条教训、每对手 10 条；坏文件建局即报错）；下一局怎么用（系统 prompt 静态段「== 跨局经验 ==」，当前角色优先，预算 1200 字）；隔离（只进自己的 prompt、局中不写、不进反思）；复盘失败只记日志；已知限制（两局同 `memory_id` 同时结束后写覆盖）；多局累积靠重复运行。附最小 YAML 样例与一段终端输出（档案表「记忆 laozhang（0 局）」、结束后「记忆 laozhang：1 局，教训 2，对手笔记 1」）。

`docs/specs/requirements.md`：
- §4.4.1 末尾补一段「**跨局经验（issue #59）**：`AgentProfile.memory_id` 标识的 Agent 在局后用 `reflection_model` 对『自身视角记忆 + 终局揭示』复盘，写入 `data/agent_memory/<memory_id>.json`（教训 ≤50、对手笔记按对手 `memory_id` 键 ≤10）；下一局装配为静态段『== 跨局经验 ==』（当前角色优先，字符预算）。对局中不写入；对手笔记只对有 `memory_id` 的对手记录。」
- §5.2 `agents` 字段说明补 `memory_id`（同局唯一、`"*"` 不可配 → 400；格式非法 → 422；指向 §4.4.1）。

- [ ] **Step 4: 全量验证**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_agent_integration.py README.md docs/specs/requirements.md
git commit -m "test(agent): 两局跨局记忆集成验收；README/PRD 跨局记忆说明 (issue #59)"
```

---

## Self-Review

- **Spec 覆盖**：§1 判据→T1（缺省零变化：`memory_id=None`）、T3（静态段/只渲染一次）、T4（局中不写、失败只记日志、触发点）、T5（端到端）；§2 schema/校验→T1；§3 复盘→T1（prompt）+T3（端口）；§4 装配→T3（prompt/端口）+T4（roster）；§5 存储/触发→T2+T4；§6 测试逐条→T1–T5；§7 不在范围无任务。
- **占位符扫描**：无 TBD/TODO；T5 Step 2 预期直接通过是明确预期。
- **类型一致性**：`build_reveal(state, seat, *, notable_seats)`、`GameReveal.my_seat/my_role/my_won/notable_seats`、`build_reflection_prompt(reveal, memory_context, night_private)`、`render_experience(exp, *, role, opponents, budget_chars)`、`AgentExperience.record_game(game_id, role, won, reflection, seat_to_memory_id, my_seat, ts)`、`ExperienceStore.load/save`、`run_postgame(game_id, final_state, profiles, ports, store, now)`、`seat_memory_ids(profiles, num_players)`、`opponents_for(seat, seat_ids)`、`AgentPlayerPort(experience=, opponents=)`、`build_agent_port(..., experience=, opponents=)`、`GameHandle.seat_memory_ids/experiences/postgame_task`、`GameRegistry(experience_store=)`、`create_app(memory_dir=, experience_store=)`、`render_agent_roster(..., experiences=)`、`load_experiences(agents, num_players, store)`、`_wire_game(..., experiences=)`、`run_watch/run_play(..., experience_store=)` 在各任务间一致。
- **import 方向**：`experience.py` 只依赖 pydantic + `app.engine`；`profile.py` import 它安全；`experience_store.py` / `postgame.py`（runtime）只 import `app.agent.experience` / `app.agent.profile`，不 import `agent_player`；`SupportsGameReflection` 用结构化协议避免 isinstance 依赖 agent_player。
- **契约连带**：`AgentProfile` 新增字段 → `test_api_lobby.py::test_create_legacy_ai_model_echoes_star` 精确相等 dict 补 `"memory_id": None`（T1 Step 4 已含）。
