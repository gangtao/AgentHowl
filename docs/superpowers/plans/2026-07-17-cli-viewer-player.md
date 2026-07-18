# CLI 观战/对局器（issue #44）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 终端里看局与玩局——`app/cli/render.py`（事件/观察/工具叙述器）+ `app/cli/play.py`（`python -m app.cli.play`：无 `--seat` 看局、`--seat N` 交互玩局），进程内 async 跑 runtime，纯客户端零裁决零信息隔离旁路。

**Architecture:** 手工装配 `InMemoryEventStore` + `GameRunner` + `ConnectionManager`，打印型订阅者**先于** `run()` 挂上，`asyncio.run` 驱动。看局=打印订阅者按 `--view`（GM 默认）叙述并限速；玩局=座 N 配 `HumanPlayerPort`、并发 turn-loop 经注入式 async reader 读行、mini-syntax→`parse_tool_call`→`submit_and_wait`。

**Tech Stack:** Python 3.11+ 标准库（argparse/asyncio）；无新依赖；复用 engine/runtime/schemas，不 import api。

**规格:** `docs/superpowers/specs/2026-07-17-cli-viewer-player-design.md`（本计划唯一裁决依据）

## Global Constraints

- 分支 `feat/cli-viewer-player`（已建，规格已提交 e317509）；工作目录 `backend/`
- 质量门（每任务收尾）：`uv run pytest -q`（全量约 140s，Bash timeout 360000）、`uv run mypy app`（strict）、`uv run ruff check .`、`uv run ruff format --check .`
- 注释/docstring 中文；标识符/CLI 英文；ruff line-length 100
- **不改引擎**；CLI 纯客户端：只经 `visible_events`/`build_observation` 取视角
- 不 import `app.api`（避免拖入 FastAPI）；`render.py` 复用 `app/engine/events.py` payload 模型
- 订阅须先于 `runner.run()`；`state_provider` lambda 须容忍 run 前不被调用（`GameRunner.state` run 前抛 RuntimeError）
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## 关键既有签名（复用，勿改）

- `app/engine/events.py`：`Event{seq, game_id, ts, type: EventType, actor_seat: int|None, payload: EventPayload, visibility: Visibility, meta: dict[str,str]}`；payload 模型 `PlayerSpokePayload{content, claim_role, badge_flow}`、`LastWordsPayload{seat, content}`、`DeathAnnouncedPayload{seats}`、`PlayerExiledPayload{seat|None}`、`HunterShotPayload{shooter, victim}`、`WolfSelfDestructPayload{seat}`、`VoteStartedPayload{candidates, tie_round}`、`VoteCastPayload{voter, target}`、`VoteResultPayload{tally, exiled, tie_seats}`、`RoundStartedPayload{round}`、`PhaseChangedPayload{to, speech_order}`、`SheriffElectedPayload{seat}`、`SheriffCandidacyPayload{seat, running}`、`BadgePassedPayload{from_seat, to_seat}`、`GameOverPayload{winner}`、`SeerCheckedPayload{target, result}`、`GuardProtectedPayload{target}`、`WolfKillProposedPayload{wolf_seat, target}`、`WolfKillDecidedPayload{target}`
- `app/engine/observation.py`：`build_observation(state, seat) -> PlayerObservation`；`visible_events(state, events, viewer) -> list[Event]`；`Viewer = int | Literal["SPECTATOR","GM"]`；`PlayerObservation{game_id, state_version, my_seat, my_role, my_status, phase:str, round, seats:list[dict], sheriff_seat, badge_flow_claims, private:dict, election_stage, sheriff_candidates, vote_candidates, pk_speech_pending, available_actions}`
- `app/engine/engine.py`：`RosterEntry{display_name: str, player_type: Literal["HUMAN","AGENT"]="AGENT"}`
- `app/runtime/game_runner.py`：`GameRunner(*, store, config, game_id, roster, ports, connections=None, timeouts=None)`；`async run() -> GameState`；`.state`（run 前抛）；`RunnerTimeouts{speech_sec, action_sec}`
- `app/runtime/connection.py`：`ConnectionManager(state_provider)`；`subscribe(viewer, cb)`；`Subscriber = Callable[[list[Event]], Awaitable[None]]`
- `app/runtime/player_port.py`：`BotPlayerPort(state_provider)`；`HumanPlayerPort()`：`async wait_armed(timeout) -> TurnPrompt|None`、`submit(action) -> Future[SubmitOutcome]`、`async submit_and_wait(action, timeout=10.0) -> SubmitOutcome`；`NotYourTurnError`；`TurnPrompt{observation, deadline_ts}`；`SubmitOutcome{ok, event_id, state_version, rejected_reason}`
- `app/schemas/actions.py`：`ToolCall{tool, arguments}`；`parse_tool_call(call, actor_seat) -> Action`；`available_tools_for(obs) -> tuple[str,...]`；`ToolCallError`
- `app/agent/agent_player.py`：`build_agent_port(seat, game_config, ai_model, ai_model_speech) -> AgentPlayerPort`
- `app/store/event_store.py`：`InMemoryEventStore()`（`GameRunner.run` 自建 GameMeta 并 create_game，CLI 无需自建）
- `app/engine/config.py`：`build_preset(name) -> GameConfig`；`GameConfig.num_players`

---

### Task 1: render.py —— 事件/观察/工具叙述器 + 颜色工具

**Files:**
- Create: `backend/app/cli/render.py`
- Test: `backend/tests/test_cli_render.py`

**Interfaces:**
- Produces（Task 2/3 依赖）:
  - `render_event(event: Event) -> str`（叙述相关类型可读中文行；未特判→简洁通用格式，非 raw dict）
  - `render_observation(obs: PlayerObservation) -> str`
  - `render_tools(tools: tuple[str, ...]) -> str`
  - `color(text: str, style: str, *, enabled: bool | None = None) -> str`（`enabled=None` 时按 `sys.stdout.isatty()` 且无 `NO_COLOR` 决定）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli_render.py`：

```python
"""CLI 叙述器（issue #44 Task 1）：事件/观察/工具渲染，纯函数无 IO。"""

import pytest

from app.cli.render import color, render_event, render_observation, render_tools
from app.engine.config import RoleType
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    GameOverPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    VoteCastPayload,
    VoteResultPayload,
    Visibility,
    WolfSelfDestructPayload,
)
from app.engine.observation import PlayerObservation


def _ev(etype: EventType, payload, *, actor: int | None = None, vis=Visibility.PUBLIC) -> Event:
    return Event(
        seq=1, game_id="g", ts=1.0, type=etype, actor_seat=actor, payload=payload, visibility=vis
    )


@pytest.mark.parametrize(
    ("event"),
    [
        _ev(EventType.ROUND_STARTED, RoundStartedPayload(round=2)),
        _ev(EventType.PHASE_CHANGED, PhaseChangedPayload(to="VOTE")),
        _ev(EventType.PLAYER_SPOKE, PlayerSpokePayload(content="我是好人"), actor=3),
        _ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))),
        _ev(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=4)),
        _ev(EventType.VOTE_CAST, VoteCastPayload(voter=1, target=2)),
        _ev(EventType.VOTE_RESULT, VoteResultPayload(tally=((2, 3.0),), exiled=2, tie_seats=())),
        _ev(EventType.WOLF_SELF_DESTRUCT, WolfSelfDestructPayload(seat=6)),
        _ev(EventType.GAME_OVER, GameOverPayload(winner="GOOD")),
        # GM 视角事件也应可读
        _ev(EventType.SEER_CHECKED, SeerCheckedPayload(target=7, result="WOLF"), actor=8,
            vis=Visibility.ROLE_SELF),
    ],
)
def test_render_event_nonempty_readable(event: Event) -> None:
    out = render_event(event)
    assert isinstance(out, str) and out.strip()  # 非空
    assert "model_dump" not in out and "payload=" not in out  # 不是 raw dump


def test_render_event_speech_contains_content() -> None:
    ev = _ev(
        EventType.PLAYER_SPOKE,
        PlayerSpokePayload(content="我怀疑2号", claim_role=RoleType.SEER),
        actor=3,
    )
    out = render_event(ev)
    assert "我怀疑2号" in out and "3" in out


def test_render_death_and_gameover_wording() -> None:
    assert "5" in render_event(_ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))))
    peaceful = render_event(_ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=())))
    assert peaceful.strip()  # 平安夜也有文案
    assert "GOOD" in render_event(_ev(EventType.GAME_OVER, GameOverPayload(winner="GOOD")))


def test_render_unknown_type_falls_back_readable() -> None:
    # ROLE_SKIPPED 未必特判 → 通用格式仍非空可读
    from app.engine.events import RoleSkippedPayload

    out = render_event(
        _ev(EventType.ROLE_SKIPPED, RoleSkippedPayload(role=RoleType.WITCH, reason="dead"))
    )
    assert out.strip()


def _obs(phase: str = "DAY_SPEECH") -> PlayerObservation:
    return PlayerObservation(
        game_id="g",
        state_version=1,
        my_seat=0,
        my_role=RoleType.SEER,
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private={"check_results": [{"target": 3, "result": "WOLF"}]},
        available_actions=[0],
    )


def test_render_observation_and_tools() -> None:
    out = render_observation(_obs())
    assert "1" in out and ("预言家" in out or "SEER" in out)  # 角色出现
    assert "wolf_chat" not in out  # 内部键不外露
    tools = render_tools(("speak", "self_destruct", "get_game_state"))
    assert "speak" in tools


def test_color_disabled_is_plaintext() -> None:
    assert color("hi", "red", enabled=False) == "hi"
    assert "hi" in color("hi", "red", enabled=True)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_render.py -q`
Expected: FAIL —— `app.cli.render` 不存在

- [ ] **Step 3: 实现**

`backend/app/cli/render.py`：

```python
"""CLI 叙述器（issue #44）：事件/观察/工具渲染成可读中文。纯函数、无 IO、不 import api。

专用于终端展示；不复用 agent 层私有 _render（其通用回退是 raw dict）。
"""

from __future__ import annotations

import sys

from app.engine.config import RoleType
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    Event,
    EventType,
    GameOverPayload,
    GuardProtectedPayload,
    HunterShotPayload,
    LastWordsPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    SheriffCandidacyPayload,
    SheriffElectedPayload,
    VoteCastPayload,
    VoteResultPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfSelfDestructPayload,
)
from app.engine.observation import PlayerObservation

_ANSI = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
    "bold": "1",
}

_ROLE_ZH = {
    RoleType.WEREWOLF: "狼人",
    RoleType.VILLAGER: "村民",
    RoleType.SEER: "预言家",
    RoleType.WITCH: "女巫",
    RoleType.HUNTER: "猎人",
    RoleType.GUARD: "守卫",
    RoleType.IDIOT: "白痴",
}


def color(text: str, style: str, *, enabled: bool | None = None) -> str:
    """ANSI 上色；enabled=None 时按 stdout 是否 TTY 且无 NO_COLOR 决定。"""
    import os

    if enabled is None:
        enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if not enabled or style not in _ANSI:
        return text
    return f"\033[{_ANSI[style]}m{text}\033[0m"


def _seats(xs: object) -> str:
    return "、".join(f"{s}号" for s in xs) if xs else "无"  # type: ignore[union-attr]


def render_event(event: Event) -> str:
    """单事件 → 一行可读中文。未特判类型回退简洁通用格式（非 raw dict）。"""
    p = event.payload
    t = event.type

    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        return f"———— 第 {p.round} 轮 ————"
    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        return f"【阶段】{p.to.value if hasattr(p.to, 'value') else p.to}"
    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        claim = f"（自称{_ROLE_ZH.get(p.claim_role, p.claim_role)}）" if p.claim_role else ""
        badge = f"（警徽流{list(p.badge_flow)}）" if p.badge_flow else ""
        return f"{event.actor_seat}号发言{claim}{badge}：{p.content}"
    if t == EventType.LAST_WORDS and isinstance(p, LastWordsPayload):
        return f"{p.seat}号遗言：{p.content}"
    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        return f"【天亮】昨夜出局：{_seats(p.seats)}" if p.seats else "【天亮】平安夜，无人出局"
    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        return f"【放逐】{p.seat}号被票出" if p.seat is not None else "【放逐】无人出局"
    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        return (
            f"{p.shooter}号猎人开枪带走 {p.victim}号"
            if p.victim is not None
            else f"{p.shooter}号猎人未开枪"
        )
    if t == EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
        return f"💥 {p.seat}号狼人自爆！"
    if t == EventType.VOTE_STARTED:
        return "【投票开始】"
    if t == EventType.VOTE_CAST and isinstance(p, VoteCastPayload):
        return f"  {p.voter}号 → {p.target}号" if p.target is not None else f"  {p.voter}号 弃票"
    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        if p.exiled is not None:
            return f"【计票】{p.exiled}号得票最高，出局"
        return f"【计票】平票：{_seats(p.tie_seats)}"
    if t == EventType.SHERIFF_CANDIDACY and isinstance(p, SheriffCandidacyPayload):
        return f"{p.seat}号{'上警竞选' if p.running else '不上警'}"
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        return f"【警长】{p.seat}号当选警长"
    if t == EventType.BADGE_PASSED and isinstance(p, BadgePassedPayload):
        return (
            f"{p.from_seat}号移交警徽给 {p.to_seat}号"
            if p.to_seat is not None
            else f"{p.from_seat}号撕毁警徽"
        )
    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        who = {"GOOD": "好人阵营", "WOLF": "狼人阵营"}.get(p.winner or "", "平局")
        return f"═══════ 游戏结束：{who}胜 ═══════"
    # GM 视角夜间事件
    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        res = "狼人" if str(p.result) == "WOLF" or getattr(p.result, "value", None) == "WOLF" else "好人"
        return f"[GM] 预言家查验 {p.target}号：{res}"
    if t == EventType.GUARD_PROTECTED and isinstance(p, GuardProtectedPayload):
        return f"[GM] 守卫守护 {p.target}号" if p.target is not None else "[GM] 守卫空守"
    if t == EventType.WOLF_KILL_PROPOSED and isinstance(p, WolfKillProposedPayload):
        return f"[GM] {p.wolf_seat}号狼提议刀 {p.target}号"
    if t == EventType.WOLF_KILL_DECIDED and isinstance(p, WolfKillDecidedPayload):
        return f"[GM] 狼队决定刀 {p.target}号" if p.target is not None else "[GM] 狼队空刀"

    # 通用回退：可读、非 raw dict
    fields = event.payload.model_dump(mode="json")
    actor = f"{event.actor_seat}号 " if event.actor_seat is not None else ""
    body = "，".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
    return f"[{t.value}] {actor}{body}".rstrip()


def render_observation(obs: PlayerObservation) -> str:
    """本座局势摘要（多行）。排除内部键 wolf_chat。"""
    alive = [s["seat"] for s in obs.seats if s.get("alive")]
    role = _ROLE_ZH.get(obs.my_role, obs.my_role)
    lines = [
        f"你是 {obs.my_seat}号 · {role} · {'存活' if obs.my_status == 'ALIVE' else '出局'}",
        f"第 {obs.round} 轮 · 阶段 {obs.phase} · 存活 {alive}",
        f"警长：{obs.sheriff_seat if obs.sheriff_seat is not None else '无'}",
    ]
    if obs.election_stage:
        lines.append(f"竞选子阶段：{obs.election_stage} · 候选 {obs.sheriff_candidates}")
    if obs.badge_flow_claims:
        lines.append(f"公开警徽流：{obs.badge_flow_claims}")
    priv = {k: v for k, v in obs.private.items() if k != "wolf_chat"}
    if priv:
        lines.append(f"你的私有信息：{priv}")
    return "\n".join(lines)


def render_tools(tools: tuple[str, ...]) -> str:
    return "可用工具：" + "、".join(tools)
```

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_cli_render.py -q` → PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/cli/render.py tests/test_cli_render.py
git commit -m "feat(cli): 事件/观察/工具叙述器 render.py (issue #44)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: play.py 看局模式 —— 装配 + 打印订阅者 + 节奏 + argparse

**Files:**
- Create: `backend/app/cli/play.py`
- Test: `backend/tests/test_cli_play_watch.py`

**Interfaces:**
- Consumes: Task 1 `render_event`；runtime/engine 签名（见上）
- Produces（Task 3 依赖）:
  - `_wire_game(config, *, human_seat=None, ai_model=None) -> tuple[GameRunner, ConnectionManager, dict[int, PlayerPort]]`（装配 store/roster/ports/conns/runner；ports 未含订阅）
  - `_parse_view(view: str) -> Viewer`（`"gm"`→"GM"、`"spectator"`→"SPECTATOR"、`"seat:N"`→int(N)）
  - `async run_watch(config, *, view, delay, step, read_line) -> GameState`
  - `main(argv: list[str] | None = None) -> None`（argparse 入口）
  - `ReadLine = Callable[[str], Awaitable[str]]`；`default_read_line(prompt) -> str`（`asyncio.to_thread(input, prompt)`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli_play_watch.py`：

```python
"""CLI 看局（issue #44 Task 2）：全 bot 局经进程内 runner 叙述到终局。"""

import asyncio

from app.cli.play import _parse_view, _wire_game, run_watch
from app.engine.config import build_preset


def test_parse_view() -> None:
    assert _parse_view("gm") == "GM"
    assert _parse_view("spectator") == "SPECTATOR"
    assert _parse_view("seat:3") == 3


def test_wire_game_ports_and_no_start() -> None:
    from app.runtime.player_port import BotPlayerPort

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    runner, conns, ports = _wire_game(config)
    assert len(ports) == 9 and all(isinstance(p, BotPlayerPort) for p in ports.values())
    assert runner is not None and conns is not None  # 未 run


def test_watch_game_narrates_to_gameover(capsys) -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def _no_read(prompt: str) -> str:  # step=False 时不会被调用
        raise AssertionError("看局非 step 模式不应读输入")

    state = asyncio.run(
        run_watch(config, view="GM", delay=0.0, step=False, read_line=_no_read)
    )
    from app.engine.phases import Phase

    assert state.phase == Phase.GAME_OVER
    out = capsys.readouterr().out
    assert "游戏结束" in out  # GAME_OVER 叙述
    assert "第 1 轮" in out or "阶段" in out  # 有阶段/轮次叙述
    assert "[GM]" in out  # GM 视角含夜间内幕行


def test_watch_spectator_hides_gm_lines(capsys) -> None:
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})

    async def _no_read(prompt: str) -> str:
        raise AssertionError("不应读输入")

    asyncio.run(run_watch(config, view="SPECTATOR", delay=0.0, step=False, read_line=_no_read))
    out = capsys.readouterr().out
    assert "游戏结束" in out
    assert "[GM]" not in out  # 观战视角无夜间内幕
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_play_watch.py -q`
Expected: FAIL —— `app.cli.play` 不存在

- [ ] **Step 3: 实现**

`backend/app/cli/play.py`：

```python
"""CLI 观战/对局器（issue #44）：python -m app.cli.play。

无 --seat=看局；--seat N=交互玩局。进程内 async 跑 runtime，纯客户端。
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable

from app.cli.render import render_event
from app.engine.config import GameConfig, build_preset
from app.engine.engine import RosterEntry
from app.engine.events import Event
from app.engine.observation import Viewer
from app.engine.state import GameState
from app.runtime.connection import ConnectionManager
from app.runtime.game_runner import GameRunner, RunnerTimeouts
from app.runtime.player_port import BotPlayerPort, HumanPlayerPort, PlayerPort

ReadLine = Callable[[str], Awaitable[str]]

# 宽松默认超时，便于人类从容操作
_CLI_TIMEOUTS = RunnerTimeouts(speech_sec=120.0, action_sec=120.0)


async def default_read_line(prompt: str) -> str:
    """默认行读取器：线程内阻塞 input，不卡事件循环。"""
    return await asyncio.to_thread(input, prompt)


def _parse_view(view: str) -> Viewer:
    if view == "gm":
        return "GM"
    if view == "spectator":
        return "SPECTATOR"
    if view.startswith("seat:"):
        return int(view.split(":", 1)[1])
    raise ValueError(f"未知视角：{view}（用 gm|spectator|seat:N）")


def _wire_game(
    config: GameConfig, *, human_seat: int | None = None, ai_model: str | None = None
) -> tuple[GameRunner, ConnectionManager, dict[int, PlayerPort]]:
    """装配 store/roster/ports/conns/runner（不订阅、不 run）。"""
    from app.store.event_store import InMemoryEventStore

    n = config.num_players
    holder: dict[str, GameRunner] = {}

    def state_of() -> GameState:
        return holder["r"].state  # run 前不会被调用（订阅先于 run，bot.act 在 run 内）

    ports: dict[int, PlayerPort] = {}
    for seat in range(n):
        if seat == human_seat:
            ports[seat] = HumanPlayerPort()
        elif ai_model is not None:
            from app.agent.agent_player import build_agent_port

            ports[seat] = build_agent_port(seat, config, ai_model, None)
        else:
            ports[seat] = BotPlayerPort(state_provider=state_of)

    roster = [
        RosterEntry(
            display_name=f"P{i}", player_type=("HUMAN" if i == human_seat else "AGENT")
        )
        for i in range(n)
    ]
    conns = ConnectionManager(state_provider=state_of)
    runner = GameRunner(
        store=InMemoryEventStore(),
        config=config,
        game_id="cli",
        roster=roster,
        ports=ports,
        connections=conns,
        timeouts=_CLI_TIMEOUTS,
    )
    holder["r"] = runner
    return runner, conns, ports


async def run_watch(
    config: GameConfig,
    *,
    view: Viewer,
    delay: float,
    step: bool,
    ai_model: str | None = None,
    read_line: ReadLine = default_read_line,
) -> GameState:
    """看局：打印型订阅者按 view 叙述，delay/step 限速，跑到 GAME_OVER。

    ai_model 设置时全座由 LLM Agent 扮演（自对局）；否则内置随机 bot。
    """
    runner, conns, _ = _wire_game(config, ai_model=ai_model)

    async def on_events(events: list[Event]) -> None:
        for e in events:  # 已按 view 过滤
            line = render_event(e)
            if line:
                print(line)
            if step:
                await read_line("")  # 回车推进
            elif delay > 0:
                await asyncio.sleep(delay)

    conns.subscribe(view, on_events)  # 必须先于 run
    return await runner.run()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="app.cli.play", description="AgentHowl 终端观战/对局器"
    )
    parser.add_argument("--seat", type=int, default=None, help="设=真人玩该座；缺=看局")
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--view", default="gm", help="看局视角 gm|spectator|seat:N")
    parser.add_argument("--delay", type=float, default=0.6, help="看局逐事件延时（秒）")
    parser.add_argument("--step", action="store_true", help="看局逐步（回车推进）")
    parser.add_argument("--ai-model", default=None, help="LLM 自对局模型（如 ollama/llama3.1）")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    config = build_preset(args.preset).model_copy(update={"seed": args.seed})
    if args.no_color:
        import os

        os.environ["NO_COLOR"] = "1"

    if args.seat is None:
        asyncio.run(
            run_watch(
                config,
                view=_parse_view(args.view),
                delay=args.delay,
                step=args.step,
                ai_model=args.ai_model,
            )
        )
    else:
        from app.cli.play_human import run_play  # Task 3

        asyncio.run(run_play(config, seat=args.seat, ai_model=args.ai_model))


if __name__ == "__main__":
    main()
```

**说明**：`_parse_view` 对 `seat:N` 的 `int()` 若非法会抛 `ValueError`——可接受（argparse 层错误信息）。`main` 里 `--seat` 分支 import `app.cli.play_human`（Task 3 创建）；Task 2 单独执行时该分支不被测试触达（看局测试只调 `run_watch`），故 Task 2 提交时 `play_human` 尚不存在也不影响 Task 2 的门禁（import 在函数内，惰性）。

- [ ] **Step 4: 跑测试 + 质量门**

Run: `uv run pytest tests/test_cli_play_watch.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/cli/play.py tests/test_cli_play_watch.py
git commit -m "feat(cli): 看局模式——进程内 runner 叙述 + 视角/节奏 (issue #44)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: play_human.py 玩局模式 —— mini-syntax + turn-loop + 注入式 reader

**Files:**
- Create: `backend/app/cli/play_human.py`
- Test: `backend/tests/test_cli_play_human.py`

**Interfaces:**
- Consumes: Task 1 render；Task 2 `_wire_game`、`ReadLine`、`default_read_line`；`parse_tool_call`/`available_tools_for`/`ToolCall`/`ToolCallError`；`HumanPlayerPort`/`NotYourTurnError`
- Produces:
  - `class CliInputError(ValueError)`
  - `parse_line(line: str, obs: PlayerObservation) -> ToolCall`（mini-syntax；不裁决合法性）
  - `async run_play(config, *, seat, ai_model=None, read_line=default_read_line, on_wired=None) -> GameState`
    （`on_wired: Callable[[GameRunner], None] | None` —— 装配后 run 前回调，供测试捕获 runner）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_cli_play_human.py`：

```python
"""CLI 玩局（issue #44 Task 3）：mini-syntax 解析 + 真人座经脚本 reader 跑完整局。"""

import asyncio

import pytest

from app.cli.play_human import CliInputError, parse_line, run_play
from app.cli.render import RoleType  # re-export 便利；若无则从 config import
from app.engine.actions import (
    DayVote,
    NightAction,
    NightActionType,
    SelfDestruct,
    Speak,
)
from app.engine.config import build_preset
from app.engine.observation import PlayerObservation
from app.engine.phases import Phase
from app.schemas.actions import parse_tool_call


def _obs(phase: str = "DAY_SPEECH") -> PlayerObservation:
    from app.engine.config import RoleType as RT

    return PlayerObservation(
        game_id="g", state_version=1, my_seat=2, my_role=RT.VILLAGER, my_status="ALIVE",
        phase=phase, round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None, badge_flow_claims={}, private={}, available_actions=[2],
    )


def test_parse_line_speak_vote_night_selfdestruct() -> None:
    assert parse_tool_call(parse_line("speak 我怀疑3号", _obs()), actor_seat=2) == Speak(
        actor_seat=2, content="我怀疑3号"
    )
    assert parse_tool_call(parse_line("vote 3", _obs("VOTE")), actor_seat=2) == DayVote(
        actor_seat=2, target_seat=3
    )
    assert parse_tool_call(parse_line("vote abstain", _obs("VOTE")), actor_seat=2) == DayVote(
        actor_seat=2, abstain=True
    )
    assert parse_tool_call(
        parse_line("night check 5", _obs("NIGHT_SEER")), actor_seat=2
    ) == NightAction(actor_seat=2, action_type=NightActionType.CHECK, target_seat=5)
    assert parse_tool_call(
        parse_line("night skip", _obs("NIGHT_WITCH")), actor_seat=2
    ) == NightAction(actor_seat=2, action_type=NightActionType.SKIP)
    assert parse_tool_call(
        parse_line("self_destruct", _obs()), actor_seat=2
    ) == SelfDestruct(actor_seat=2)


def test_parse_line_rejects_bad_input() -> None:
    with pytest.raises(CliInputError):
        parse_line("", _obs())
    with pytest.raises(CliInputError):
        parse_line("frobnicate 3", _obs())
    with pytest.raises(CliInputError):
        parse_line("vote", _obs("VOTE"))  # 缺目标且非 abstain


def _action_to_line(action: object) -> str:
    """测试用逆映射：RandomBot 合法行动 → mini-syntax 行。"""
    if isinstance(action, Speak):
        return f"speak {action.content or '过'}"
    if isinstance(action, DayVote):
        return "vote abstain" if action.abstain else f"vote {action.target_seat}"
    if isinstance(action, NightAction):
        if action.target_seat is None:
            return f"night {action.action_type.value}"
        return f"night {action.action_type.value} {action.target_seat}"
    if isinstance(action, SelfDestruct):
        return "self_destruct"
    from app.engine.actions import SheriffAction

    assert isinstance(action, SheriffAction)
    tail = ""
    if action.target_seat is not None:
        tail = f" {action.target_seat}"
    elif action.direction is not None:
        tail = f" {action.direction.value.lower()}"
    return f"sheriff {action.action_type.value}{tail}"


async def test_human_seat_plays_full_game_via_scripted_reader() -> None:
    from app.cli.bot import RandomBot

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    captured: dict[str, object] = {}

    async def reader(prompt: str) -> str:
        runner = captured["r"]
        return _action_to_line(RandomBot.choose_action(runner.state, 2))  # type: ignore[attr-defined]

    state = await asyncio.wait_for(
        run_play(
            config, seat=2, read_line=reader, on_wired=lambda r: captured.__setitem__("r", r)
        ),
        timeout=120,
    )
    assert state.phase == Phase.GAME_OVER  # 真人座（脚本合法落子）整局跑通


async def test_human_bad_line_then_recovers(capsys) -> None:
    from app.cli.bot import RandomBot

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    captured: dict[str, object] = {}
    calls = {"n": 0}

    async def reader(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "garbage nonsense"  # 首次非法 → 应提示并重读，不卡死
        runner = captured["r"]
        return _action_to_line(RandomBot.choose_action(runner.state, 2))  # type: ignore[attr-defined]

    state = await asyncio.wait_for(
        run_play(
            config, seat=2, read_line=reader, on_wired=lambda r: captured.__setitem__("r", r)
        ),
        timeout=120,
    )
    assert state.phase == Phase.GAME_OVER
    assert "⚠" in capsys.readouterr().out  # 非法输入被提示
```

注：测试首行 `from app.cli.render import RoleType` 若 render 未 re-export 会失败——实现时**不要**为此在 render 加 re-export；改为测试直接 `from app.engine.config import RoleType`。实现者据实修正该 import（这是测试便利的小瑕疵，非产品接口）。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_play_human.py -q`
Expected: FAIL —— `app.cli.play_human` 不存在

- [ ] **Step 3: 实现**

`backend/app/cli/play_human.py`：

```python
"""CLI 玩局（issue #44）：真人座交互——mini-syntax 解析 + turn-loop。

纯客户端：只经 observation 与端口提交，合法性裁决全在引擎。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from app.cli.play import ReadLine, _wire_game, default_read_line
from app.cli.render import color, render_event, render_observation, render_tools
from app.engine.config import GameConfig
from app.engine.observation import PlayerObservation
from app.engine.phases import Phase
from app.engine.state import GameState
from app.runtime.game_runner import GameRunner
from app.runtime.player_port import HumanPlayerPort, NotYourTurnError
from app.schemas.actions import ToolCall, ToolCallError, available_tools_for, parse_tool_call

_HELP = (
    "命令：speak <话>｜vote <座>｜vote abstain｜night <类型> [座]"
    "（kill/check/save/poison/guard/shoot/skip）｜"
    "sheriff <类型> [座|left/right]｜self_destruct｜help｜state｜speeches"
)


class CliInputError(ValueError):
    """无法解析的输入行（提示后重读，不裁决合法性）。"""


def parse_line(line: str, obs: PlayerObservation) -> ToolCall:
    """mini-syntax → ToolCall。合法性（阶段/目标存活等）交引擎裁决。"""
    parts = line.strip().split()
    if not parts:
        raise CliInputError("空输入")
    cmd, args = parts[0], parts[1:]

    if cmd == "speak":
        return ToolCall(tool="speak", arguments={"content": " ".join(args)})
    if cmd == "self_destruct":
        return ToolCall(tool="self_destruct", arguments={})
    if cmd == "vote":
        if args and args[0] == "abstain":
            return ToolCall(tool="vote", arguments={"abstain": True})
        if not args:
            raise CliInputError("vote 需要座位号或 abstain")
        return ToolCall(tool="vote", arguments={"target_seat": _int(args[0])})
    if cmd == "night":
        if not args:
            raise CliInputError("night 需要行动类型")
        payload: dict[str, object] = {"action_type": args[0]}
        if len(args) > 1:
            payload["target_seat"] = _int(args[1])
        return ToolCall(tool="night_action", arguments=payload)
    if cmd == "sheriff":
        if not args:
            raise CliInputError("sheriff 需要行动类型")
        payload = {"action_type": args[0]}
        if len(args) > 1:
            if args[1] in ("left", "right"):
                payload["direction"] = args[1].upper()
            else:
                payload["target_seat"] = _int(args[1])
        return ToolCall(tool="sheriff_action", arguments=payload)
    raise CliInputError(f"未知命令：{cmd}（help 查看用法）")


def _int(s: str) -> int:
    try:
        return int(s)
    except ValueError as exc:
        raise CliInputError(f"需要座位号，收到：{s}") from exc


async def run_play(
    config: GameConfig,
    *,
    seat: int,
    ai_model: str | None = None,
    read_line: ReadLine = default_read_line,
    on_wired: Callable[[GameRunner], None] | None = None,
) -> GameState:
    """真人座玩局：并发 runner + turn-loop，跑到 GAME_OVER。"""
    runner, conns, ports = _wire_game(config, human_seat=seat, ai_model=ai_model)
    port = ports[seat]
    assert isinstance(port, HumanPlayerPort)
    if on_wired is not None:
        on_wired(runner)

    async def narrate(events: list[object]) -> None:
        for e in events:
            line = render_event(e)  # type: ignore[arg-type]
            if line:
                print(line)

    conns.subscribe(seat, narrate)  # 先于 run

    done = asyncio.Event()

    async def turn_loop() -> None:
        while not done.is_set():
            prompt = await port.wait_armed(0.25)
            if prompt is None:
                continue
            obs = prompt.observation
            print(color(f"\n—— 轮到你（{obs.my_seat}号）——", "cyan"))
            print(render_observation(obs))
            print(render_tools(available_tools_for(obs)))
            while True:  # 本窗口内重读，直到提交（成功→下一轮；被拒→回外层重开窗）
                line = await read_line("> ")
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] == "help":
                    print(_HELP)
                    continue
                if parts[0] == "state":
                    print(render_observation(obs))
                    continue
                if parts[0] == "speeches":
                    print("（发言见上方叙述）")
                    continue
                try:
                    call = parse_line(line, obs)
                    action = parse_tool_call(call, actor_seat=seat)
                except (CliInputError, ToolCallError) as exc:
                    print(color(f"⚠ {exc}", "yellow"))
                    continue
                try:
                    outcome = await port.submit_and_wait(action)
                except NotYourTurnError:
                    print(color("窗口已关闭（可能超时代打）", "grey"))
                    break
                if outcome.ok:
                    print(color("✓ 已提交", "green"))
                    break
                print(color(f"✗ 被拒：{outcome.rejected_reason}，请重试", "yellow"))
                break  # 重开窗（race-safe：回外层 wait_armed 捕获重开的窗口）

    loop_task = asyncio.create_task(turn_loop())
    try:
        state = await runner.run()
    finally:
        done.set()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    winner = {"GOOD": "好人胜", "WOLF": "狼人胜"}.get(state.winner or "", "平局")
    print(color(f"\n═══════ 游戏结束：{winner} ═══════", "bold"))
    return state
```

注：`Phase` import 若未直接用可删（ruff）；`narrate`/`turn_loop` 的 `list[object]` + `type: ignore` 与 Task 2 一致口径，实现者可改为 `list[Event]` 并 import `Event` 去掉 ignore（更佳）。

- [ ] **Step 4: 跑测试 + 全量回归 + 质量门**

Run: `uv run pytest tests/test_cli_play_human.py -q` → PASS
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 5: Commit**

```bash
git add app/cli/play_human.py tests/test_cli_play_human.py
git commit -m "feat(cli): 玩局模式——mini-syntax + 真人 turn-loop + 注入式 reader (issue #44)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: LLM 自对局 env 门控 smoke + README CLI 玩法

**Files:**
- Create: `backend/tests/test_cli_smoke.py`
- Modify: `README.md`（仓库根）

**Interfaces:**
- Consumes: Task 2 `run_watch`（`ai_model` 已接线）
- Produces: 无（收尾）

- [ ] **Step 1: 写 env 门控 smoke（默认自跳过）**

`backend/tests/test_cli_smoke.py`：

```python
"""CLI LLM 自对局冒烟（issue #44 Task 4）。默认跳过。

本地跑法：
    ollama pull llama3.1 && ollama serve &
    AGENTHOWL_SMOKE_MODEL=ollama/llama3.1 uv run pytest -m smoke tests/test_cli_smoke.py -q -s
"""

import asyncio
import os

import httpx
import pytest

from app.cli.play import run_watch
from app.engine.config import build_preset
from app.engine.phases import Phase

SMOKE_MODEL = os.environ.get("AGENTHOWL_SMOKE_MODEL")


def _ollama_reachable() -> bool:
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(SMOKE_MODEL is None, reason="AGENTHOWL_SMOKE_MODEL 未设置"),
    pytest.mark.skipif(
        SMOKE_MODEL is not None and SMOKE_MODEL.startswith("ollama/") and not _ollama_reachable(),
        reason="Ollama 端点不可达",
    ),
]


async def _no_read(prompt: str) -> str:
    raise AssertionError("看局不应读输入")


def test_cli_llm_self_play_watch(capsys: pytest.CaptureFixture[str]) -> None:
    assert SMOKE_MODEL is not None
    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    state = asyncio.run(
        run_watch(config, view="GM", delay=0.0, step=False, ai_model=SMOKE_MODEL, read_line=_no_read)
    )
    assert state.phase == Phase.GAME_OVER
    assert "游戏结束" in capsys.readouterr().out
```

- [ ] **Step 2: 验证默认跳过 + 质量门**

Run: `uv run pytest tests/test_cli_smoke.py -q`
Expected: 1 skipped（env 未设）
Run: `uv run pytest -q`（timeout 360000）→ 全量 PASS +（含既有 smoke）skipped
Run: `uv run mypy app && uv run ruff check . && uv run ruff format --check .` → 干净

- [ ] **Step 3: README 追加"终端对局 / CLI Play"一节**

在 `README.md` 末尾追加（用标准三反引号围栏）：

```markdown
## 终端对局 / CLI Play

无需前端，直接在终端看局或玩局（进程内跑，无需起 server）：

​```bash
cd backend

# 看局：全 bot 自对局，GM 视角逐事件叙述（--delay 控制节奏、--step 回车逐步）
uv run python -m app.cli.play --seed 3 --delay 0.6
uv run python -m app.cli.play --view spectator      # 只看公开信息（拟真观战）
uv run python -m app.cli.play --step                 # 回车逐步推进

# 玩局：你扮演 2 号座位，其余内置 bot 填充
uv run python -m app.cli.play --seat 2
#   轮到你时输入：speak 我怀疑3号 / vote 3 / vote abstain /
#   night check 5 / sheriff vote_sheriff 4 / self_destruct / help

# LLM 自对局（需本地 Ollama）：全座 LLM Agent，GM 视角围观
uv run python -m app.cli.play --ai-model ollama/llama3.1 --delay 0.3
​```

纯引擎胜负统计（无叙述、极快）另见 `python -m app.cli.simulate --games 100`。
```

- [ ] **Step 4: 质量门 + Commit**

Run: `uv run pytest -q`（timeout 360000）→ 不受影响
```bash
git add tests/test_cli_smoke.py README.md
git commit -m "test(cli): LLM 自对局 env 门控 smoke + README 终端对局 (issue #44)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **规格覆盖**：render.py→Task 1；看局（GM 默认 + view/delay/step）→Task 2；玩局（mini-syntax + turn-loop + 注入 reader）→Task 3；LLM 自对局（--ai-model，看局与玩局两路均接线）+ README→Task 4。硬约束（进程内 async、纯客户端经 visible_events、不 import api、订阅先于 run、state_provider lambda 容忍 run 前）→ Global Constraints + 各任务装配代码。
- **占位符扫描**：无 TBD/TODO；已删除 Task 2 早期误引入的 `_make_printer` 死函数。Task 3 测试首行 `from app.cli.render import RoleType` 是**故意的测试瑕疵**并已注明实现者改为从 config import（非产品接口留白）。
- **类型一致性**：`_wire_game(config, *, human_seat, ai_model)` 在 Task 2 定义、Task 3 `run_play` 复用；`run_watch(..., ai_model=None)` 与 `main` 看局分支一致传参；`ReadLine`/`default_read_line` Task 2 定义、Task 3 import；`parse_line`→`ToolCall`→`parse_tool_call` 契约在 Task 3 测试与实现一致；`on_wired(runner)` 测试与实现签名一致。
- **异步竞态**：玩局 turn-loop 恒以 `wait_armed` 重取窗口再提交（被拒后回外层重开窗），race-safe；`runner.run()` 结束在 finally 里 `done.set()` + cancel + suppress(CancelledError)，无悬挂。
