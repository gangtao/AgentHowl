# GM 旁白 / 游戏进程统一配音 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GM / 系统播报（阶段切换、结算、竞选投票结果、终局等）用一条固定旁白声线配音，整句缓存跨局复用，帧与音频端点按视角过滤，节奏与发言配音同一套门控。

**Architecture:** 新模块 `app/runtime/narration.py` 把事件渲染成口播句子并提供 `NarrationCache`；`SpeechAudioSink` 抽出「落盘 + 推帧 + 等待」内核 `_emit`，新增 `narrate()` 复用它；`ConnectionManager` 帧订阅带 viewer、`broadcast_frame` 带来源事件并经 `visible_events` 过滤；runner 用 `_voice(events)` 按 seq 顺序统一调度发言与旁白；REST 音频端点直播期间按 token 视角过滤。前端只多认一个 `kind` 字段并在聚光牌显示 GM 占位。

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / pytest-asyncio（后端，`uv run`）；React 18 + TypeScript + Zustand + Vitest（前端，`npm run check`）。

**Spec:** `docs/superpowers/specs/2026-10-15-gm-narration-design.md`

## Global Constraints

- 引擎 `backend/app/engine/` 零改动（本计划不改任何引擎文件、不改事件形状，fixtures 不需重生成）。
- `app/runtime`、`app/api` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 必须保持通过。`app/runtime/narration.py` 只 import `app.engine.*`、`app.agent.profile`、标准库。
- 信息隔离只经 `app.engine.observation.visible_events`，任何新代码不得自造可见性判断。
- 旁白文本只含座位号与固定文案；`AGENTHOWL_TTS_API_KEY` 不进任何响应 / 日志 / 异常。
- 口播文案以 §3.2 表为准，逐字使用（句尾「。」，座位「N号」，多座位用「、」连接）。
- 默认白名单（逐字）：`ROUND_STARTED,PHASE_CHANGED,NIGHT_RESOLVED,DEATH_ANNOUNCED,ELECTION_STAGE_CHANGED,SHERIFF_VOTE_STARTED,SHERIFF_ELECTED,BADGE_PASSED,VOTE_STARTED,VOTE_RESULT,PLAYER_EXILED,HUNTER_SHOT,WOLF_SELF_DESTRUCT,GAME_OVER`。
- 环境变量：`AGENTHOWL_NARRATOR_VOICE`（默认 `uncle_fu`，必须 ∈ `PRESET_SPEAKERS`）、`AGENTHOWL_NARRATION_EVENTS`（逗号分隔；未设或空串 = 默认名单）、`AGENTHOWL_NARRATION_DIR`（默认 `data/narration`）。
- 缓存键 `sha256(f"{speaker}\n{text}").hexdigest()[:16]`，文件 `<cache_dir>/<key>.wav`，写入先 `<key>.wav.tmp` 再 `os.replace`。
- 帧新增字段 `"kind": "speech" | "narration"`；`speech_audio_end` 帧同样带 `kind`。
- 建局 `narration=true` 且 `voice=false` → HTTP 400，detail `旁白需要先开启语音播报`。
- 旁白任何失败不得让对局中断（WARNING + 跳过）。
- 代码注释 / 文档中文，标识符英文；ruff 100 列、mypy strict；提交信息尾部 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。
- 后端测试统一 `cd backend && uv run pytest --ignore=tests/test_api_e2e.py -q`（#74 已知 flaky 用例在该文件）。

## Review Focus

1. 白名单里写了 `PLAYER_SPOKE` / `LAST_WORDS`：`narrate()` 必须返回 `[]`，否则同一句既播发言又播旁白 → Task 1 测试 `test_speech_events_never_narrated`。
2. 缓存目录不可写（只读挂载 / 权限）：旁白仍要能播，只是不缓存 → Task 5 测试 `test_narrate_plays_even_if_cache_put_fails`。
3. 狼人座位视角收到 `WOLVES` 事件的帧、村民座位收不到；`GM_ONLY` 只 GM 收 → Task 4 测试 `test_frame_filtered_by_viewer`。
4. 直播中某个 seq 的事件对观众不可见：清单不列、文件 404（不能泄漏「存在但不可见」）→ Task 7 测试 `test_live_audio_filtered_by_viewer`。
5. 前端收到旧版无 `kind` 的帧或 `voicingSeq` 在本视角事件列表里找不到：聚光牌退回「轮到谁」，不崩 → Task 8 测试 `GamePage voicingActor` 用例。

---

### Task 1: 旁白模板 `narrate()`

**Files:**
- Create: `backend/app/runtime/narration.py`
- Test: `backend/tests/test_narration.py`

**Interfaces:**
- Consumes: `app.engine.events.Event/EventType/*Payload`、`app.engine.phases.Phase/ElectionStage`。
- Produces: `DEFAULT_NARRATION_EVENTS: frozenset[EventType]`、`SPEECH_EVENTS: frozenset[EventType]`、`narrate(event: Event, events: frozenset[EventType]) -> list[str]`、`seats(xs: Iterable[int]) -> str`、`TEMPLATED_EVENTS: frozenset[EventType]`（有模板的类型集合，Task 2 校验白名单用）。

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_narration.py
"""旁白模板（issue #110）：事件 → 口播句子；白名单外返回空；全 preset 整局覆盖。"""

from __future__ import annotations

import pytest

from app.cli.bot import run_game
from app.engine.config import PRESET_NAMES, build_preset
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
    Event,
    EventType,
    GameOverPayload,
    HunterShotPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SheriffElectedPayload,
    SheriffVoteStartedPayload,
    Visibility,
    VoteCastPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WolfSelfDestructPayload,
)
from app.engine.phases import ElectionStage, Phase
from app.runtime.narration import (
    DEFAULT_NARRATION_EVENTS,
    TEMPLATED_EVENTS,
    narrate,
    seats,
)


def _evt(t: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(
        seq=1, game_id="g", ts=1.0, type=t, actor_seat=actor,
        payload=payload, visibility=Visibility.PUBLIC,  # type: ignore[arg-type]
    )


def test_seats_joiner() -> None:
    assert seats([3, 7]) == "3号、7号"
    assert seats([]) == ""


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (_evt(EventType.ROUND_STARTED, RoundStartedPayload(round=2)), ["第2轮，天黑请闭眼。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WEREWOLF)), ["狼人请睁眼。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_GUARD)), ["守卫请睁眼。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WITCH)), ["女巫请睁眼。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_SEER)), ["预言家请睁眼。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_HUNTER_CONFIRM)), ["猎人请确认状态。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_ELECTION)), ["天亮了，进入警长竞选。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_PK)), ["警长竞选进入PK。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DEATH_ANNOUNCE)), ["天亮了。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.LAST_WORDS)), ["请发表遗言。"]),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH, speech_order=(1, 3))),
            ["进入发言环节，顺序：1号、3号。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH)), ["进入发言环节。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE)), ["进入放逐投票。"]),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK, speech_order=(2, 5))),
            ["平票PK，发言顺序：2号、5号。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK)), ["平票PK。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.HUNTER_SHOOT)), ["猎人请开枪。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.IDIOT_FLIP)), ["白痴翻牌。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE)), []),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.WIN_CHECK)), []),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.GAME_OVER)), []),
        (_evt(EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=(3, 7))), ["本夜结算，出局：3号、7号。"]),
        (_evt(EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=())), ["本夜结算，平安夜。"]),
        (_evt(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(3, 7))), ["昨夜出局的是3号、7号。"]),
        (_evt(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=())), ["昨夜是平安夜，无人出局。"]),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.CANDIDACY)),
            ["上警报名开始。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.SPEECH, speech_order=(1, 3, 6)),
            ),
            ["上警发言，顺序：1号、3号、6号。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.SPEECH)),
            ["上警发言。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.WITHDRAW)),
            ["退水确认。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.VOTE)),
            ["警下投票开始。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.DIRECTION)),
            ["请警长决定发言方向。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.ANNOUNCE)),
            ["公布竞选结果。"],
        ),
        (
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.NONE)),
            ["竞选环节结束。"],
        ),
        (
            _evt(EventType.SHERIFF_VOTE_STARTED, SheriffVoteStartedPayload(candidates=(1, 4))),
            ["警长开票，候选人：1号、4号。"],
        ),
        (_evt(EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=4)), ["4号当选警长。"]),
        (_evt(EventType.BADGE_PASSED, BadgePassedPayload(from_seat=4, to_seat=2)), ["4号把警徽移交给2号。"]),
        (_evt(EventType.BADGE_PASSED, BadgePassedPayload(from_seat=4, to_seat=None)), ["4号撕毁警徽。"]),
        (_evt(EventType.VOTE_STARTED, VoteStartedPayload(candidates=(), tie_round=0)), ["投票开始。"]),
        (_evt(EventType.VOTE_STARTED, VoteStartedPayload(candidates=(1, 2), tie_round=1)), ["PK投票开始。"]),
        (
            _evt(EventType.VOTE_RESULT, VoteResultPayload(tally=((4, 3.0),), exiled=4, tie_seats=())),
            ["4号得票最高。"],
        ),
        (
            _evt(EventType.VOTE_RESULT, VoteResultPayload(tally=(), exiled=None, tie_seats=(1, 2))),
            ["平票：1号、2号。"],
        ),
        (_evt(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=4)), ["4号被放逐出局。"]),
        (_evt(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=None)), ["本轮无人出局。"]),
        (_evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=5, victim=2)), ["5号猎人开枪，带走2号。"]),
        (_evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=5, victim=None)), ["5号猎人没有开枪。"]),
        (_evt(EventType.WOLF_SELF_DESTRUCT, WolfSelfDestructPayload(seat=6)), ["6号狼人自爆。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner="GOOD")), ["游戏结束，好人阵营获胜。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner="WOLF")), ["游戏结束，狼人阵营获胜。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner=None)), ["游戏结束，平局。"]),
    ],
)
def test_templates(event: Event, expected: list[str]) -> None:
    assert narrate(event, DEFAULT_NARRATION_EVENTS) == expected


def test_outside_whitelist_is_empty() -> None:
    e = _evt(EventType.VOTE_CAST, VoteCastPayload(voter=1, target=2))
    assert narrate(e, DEFAULT_NARRATION_EVENTS) == []
    # 白名单只含 VOTE_STARTED 时，ROUND_STARTED 也不播
    r = _evt(EventType.ROUND_STARTED, RoundStartedPayload(round=1))
    assert narrate(r, frozenset({EventType.VOTE_STARTED})) == []


def test_speech_events_never_narrated() -> None:
    """Review Focus 1：名单里写了发言事件也不播（发言由发言配音负责，避免双播）。"""
    e = _evt(EventType.PLAYER_SPOKE, PlayerSpokePayload(content="大家好"), actor=1)
    assert narrate(e, frozenset({EventType.PLAYER_SPOKE})) == []


def test_every_phase_and_stage_has_a_branch() -> None:
    """新增 Phase / ElectionStage 枚举值而未加模板 → 这里 fail-loud。"""
    for ph in Phase:
        narrate(_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=ph)), DEFAULT_NARRATION_EVENTS)
    for st in ElectionStage:
        narrate(
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=st)),
            DEFAULT_NARRATION_EVENTS,
        )


def test_default_whitelist_all_templated() -> None:
    assert DEFAULT_NARRATION_EVENTS <= TEMPLATED_EVENTS
    assert EventType.PLAYER_SPOKE not in DEFAULT_NARRATION_EVENTS


# 返回空属正常的 PHASE_CHANGED 分支（spec §3.2）
_SILENT_PHASES = {Phase.EXILE, Phase.WIN_CHECK, Phase.LOBBY, Phase.ROLE_ASSIGN, Phase.GAME_OVER}


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_full_game_coverage(preset: str) -> None:
    """4 个 preset × 固定 seed 跑完整局：白名单事件全部能渲染成以「。」结尾的句子。"""
    cfg = build_preset(preset).model_copy(update={"seed": 11})
    _final, events = run_game(cfg, "g_cov")
    narrated = 0
    for e in events:
        if e.type not in DEFAULT_NARRATION_EVENTS:
            assert narrate(e, DEFAULT_NARRATION_EVENTS) == []
            continue
        out = narrate(e, DEFAULT_NARRATION_EVENTS)
        if e.type == EventType.PHASE_CHANGED and e.payload.to in _SILENT_PHASES:  # type: ignore[attr-defined]
            assert out == []
            continue
        assert out, f"{preset}: {e.type} 无旁白"
        assert all(s.endswith("。") for s in out)
        narrated += 1
    assert narrated > 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_narration.py -q`
Expected: FAIL（`ModuleNotFoundError: app.runtime.narration`）

- [ ] **Step 3: Implement `narration.py`（模板部分）**

```python
# backend/app/runtime/narration.py
"""GM 旁白（issue #110）：事件 → 口播句子模板；句子级 WAV 缓存；旁白配置。

纯函数 + 本地文件缓存；不 import 任何 LLM / 网络代码。口播文案与 app/cli/render.py 的终端
渲染互不复用（后者带 【】[GM] 装饰）。模板一律一句一个「。」结尾；座位读作「N号」。
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.agent.profile import PRESET_SPEAKERS, VoiceSpec
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
    Event,
    EventType,
    GameOverPayload,
    HunterShotPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    RoundStartedPayload,
    SheriffElectedPayload,
    SheriffVoteStartedPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WolfSelfDestructPayload,
)
from app.engine.phases import ElectionStage, Phase

logger = logging.getLogger(__name__)

DEFAULT_NARRATOR_SPEAKER = "uncle_fu"
NARRATOR_WARM_TEXT = "大家好。"

# 发言事件永远不走旁白（由发言配音负责），即使用户把它们写进白名单
SPEECH_EVENTS: frozenset[EventType] = frozenset({EventType.PLAYER_SPOKE, EventType.LAST_WORDS})

DEFAULT_NARRATION_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.ROUND_STARTED,
        EventType.PHASE_CHANGED,
        EventType.NIGHT_RESOLVED,
        EventType.DEATH_ANNOUNCED,
        EventType.ELECTION_STAGE_CHANGED,
        EventType.SHERIFF_VOTE_STARTED,
        EventType.SHERIFF_ELECTED,
        EventType.BADGE_PASSED,
        EventType.VOTE_STARTED,
        EventType.VOTE_RESULT,
        EventType.PLAYER_EXILED,
        EventType.HUNTER_SHOT,
        EventType.WOLF_SELF_DESTRUCT,
        EventType.GAME_OVER,
    }
)


def seats(xs: Iterable[int]) -> str:
    return "、".join(f"{s}号" for s in xs)


_PHASE_LINE: dict[Phase, str] = {
    Phase.NIGHT_GUARD: "守卫请睁眼。",
    Phase.NIGHT_WEREWOLF: "狼人请睁眼。",
    Phase.NIGHT_WITCH: "女巫请睁眼。",
    Phase.NIGHT_SEER: "预言家请睁眼。",
    Phase.NIGHT_HUNTER_CONFIRM: "猎人请确认状态。",
    Phase.SHERIFF_ELECTION: "天亮了，进入警长竞选。",
    Phase.SHERIFF_PK: "警长竞选进入PK。",
    Phase.DEATH_ANNOUNCE: "天亮了。",
    Phase.LAST_WORDS: "请发表遗言。",
    Phase.VOTE: "进入放逐投票。",
    Phase.HUNTER_SHOOT: "猎人请开枪。",
    Phase.IDIOT_FLIP: "白痴翻牌。",
}
# 过渡阶段不播（终局由 GAME_OVER 播）
_SILENT_PHASES: frozenset[Phase] = frozenset(
    {Phase.EXILE, Phase.WIN_CHECK, Phase.LOBBY, Phase.ROLE_ASSIGN, Phase.GAME_OVER}
)

_STAGE_LINE: dict[ElectionStage, str] = {
    ElectionStage.CANDIDACY: "上警报名开始。",
    ElectionStage.SPEECH: "上警发言。",
    ElectionStage.WITHDRAW: "退水确认。",
    ElectionStage.VOTE: "警下投票开始。",
    ElectionStage.DIRECTION: "请警长决定发言方向。",
    ElectionStage.ANNOUNCE: "公布竞选结果。",
    ElectionStage.NONE: "竞选环节结束。",
}


def _phase_changed(p: PhaseChangedPayload) -> list[str]:
    if p.to == Phase.DAY_SPEECH:
        return [f"进入发言环节，顺序：{seats(p.speech_order)}。" if p.speech_order else "进入发言环节。"]
    if p.to == Phase.VOTE_PK:
        return [f"平票PK，发言顺序：{seats(p.speech_order)}。" if p.speech_order else "平票PK。"]
    if p.to in _SILENT_PHASES:
        return []
    if p.to in _PHASE_LINE:
        return [_PHASE_LINE[p.to]]
    raise KeyError(f"Phase 缺少旁白模板：{p.to}")


def _election_stage(p: ElectionStageChangedPayload) -> list[str]:
    if p.stage == ElectionStage.SPEECH and p.speech_order:
        return [f"上警发言，顺序：{seats(p.speech_order)}。"]
    if p.stage in _STAGE_LINE:
        return [_STAGE_LINE[p.stage]]
    raise KeyError(f"ElectionStage 缺少旁白模板：{p.stage}")


def _render(event: Event) -> list[str]:  # noqa: PLR0911
    p = event.payload
    t = event.type
    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        return [f"第{p.round}轮，天黑请闭眼。"]
    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        return _phase_changed(p)
    if t == EventType.NIGHT_RESOLVED and isinstance(p, NightResolvedPayload):
        return [f"本夜结算，出局：{seats(p.deaths)}。" if p.deaths else "本夜结算，平安夜。"]
    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        return [f"昨夜出局的是{seats(p.seats)}。" if p.seats else "昨夜是平安夜，无人出局。"]
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        return _election_stage(p)
    if t == EventType.SHERIFF_VOTE_STARTED and isinstance(p, SheriffVoteStartedPayload):
        return [f"警长开票，候选人：{seats(p.candidates)}。"]
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        return [f"{p.seat}号当选警长。"]
    if t == EventType.BADGE_PASSED and isinstance(p, BadgePassedPayload):
        if p.to_seat is not None:
            return [f"{p.from_seat}号把警徽移交给{p.to_seat}号。"]
        return [f"{p.from_seat}号撕毁警徽。"]
    if t == EventType.VOTE_STARTED and isinstance(p, VoteStartedPayload):
        return ["PK投票开始。" if p.tie_round > 0 else "投票开始。"]
    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        return [f"{p.exiled}号得票最高。" if p.exiled is not None else f"平票：{seats(p.tie_seats)}。"]
    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        return [f"{p.seat}号被放逐出局。" if p.seat is not None else "本轮无人出局。"]
    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        if p.victim is not None:
            return [f"{p.shooter}号猎人开枪，带走{p.victim}号。"]
        return [f"{p.shooter}号猎人没有开枪。"]
    if t == EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
        return [f"{p.seat}号狼人自爆。"]
    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        who = {"GOOD": "好人阵营获胜", "WOLF": "狼人阵营获胜"}.get(p.winner or "", "平局")
        return [f"游戏结束，{who}。"]
    raise KeyError(f"事件缺少旁白模板：{t}")


# 有模板的事件类型；白名单校验只认这个集合（Task 2 的 NarrationConfig 用）
TEMPLATED_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.ROUND_STARTED,
        EventType.PHASE_CHANGED,
        EventType.NIGHT_RESOLVED,
        EventType.DEATH_ANNOUNCED,
        EventType.ELECTION_STAGE_CHANGED,
        EventType.SHERIFF_VOTE_STARTED,
        EventType.SHERIFF_ELECTED,
        EventType.BADGE_PASSED,
        EventType.VOTE_STARTED,
        EventType.VOTE_RESULT,
        EventType.PLAYER_EXILED,
        EventType.HUNTER_SHOT,
        EventType.WOLF_SELF_DESTRUCT,
        EventType.GAME_OVER,
    }
)


def narrate(event: Event, events: frozenset[EventType]) -> list[str]:
    """白名单内 → 按模板渲染（可能为空，如过渡阶段）；白名单外 / 发言事件 → []。"""
    if event.type in SPEECH_EVENTS or event.type not in events:
        return []
    return _render(event)
```

（`NarrationConfig` / `NarrationCache` 留到 Task 2 追加到同一文件；此步只放模板部分，但文件头 import 已包含 Task 2 需要的 `hashlib/os/dataclass/Mapping/Path/PRESET_SPEAKERS/VoiceSpec`——若 ruff 报未使用 import，先删掉，Task 2 再加回。）

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_narration.py -q && uv run ruff check app/runtime/narration.py tests/test_narration.py && uv run mypy app`
Expected: 全部 PASS，ruff / mypy 无报错。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/narration.py backend/tests/test_narration.py
git commit -m "feat(narration): 事件→口播句子模板与默认白名单 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `NarrationConfig` 与 `NarrationCache`

**Files:**
- Modify: `backend/app/runtime/narration.py`（追加）
- Test: `backend/tests/test_narration.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `DEFAULT_NARRATION_EVENTS`、`TEMPLATED_EVENTS`、`SPEECH_EVENTS`；`app.runtime.tts.wav_duration`（合法性校验）。
- Produces:
  - `NarrationConfig(speaker: str, events: frozenset[EventType], cache_dir: Path)`（frozen dataclass，`__post_init__` 校验）、`NarrationConfig.from_env(env: Mapping[str, str] | None = None, *, data_dir: Path) -> NarrationConfig`、`NarrationConfig.voice -> VoiceSpec`。
  - `NarrationCache(cache_dir: Path)`：`key(speaker, text) -> str`（staticmethod）、`get(speaker, text) -> bytes | None`、`put(speaker, text, wav) -> Path`。

- [ ] **Step 1: Write the failing tests（追加到 `tests/test_narration.py`）**

```python
from pathlib import Path

from app.runtime.narration import NarrationCache, NarrationConfig
from tests.test_speech_audio import _wav  # 合法 WAV 生成器（已存在）


def test_config_defaults(tmp_path: Path) -> None:
    cfg = NarrationConfig.from_env({}, data_dir=tmp_path)
    assert cfg.speaker == "uncle_fu"
    assert cfg.events == DEFAULT_NARRATION_EVENTS
    assert cfg.cache_dir == tmp_path / "narration"
    assert cfg.voice == VoiceSpec(mode="preset", speaker="uncle_fu")


def test_config_from_env_custom(tmp_path: Path) -> None:
    env = {
        "AGENTHOWL_NARRATOR_VOICE": "vivian",
        "AGENTHOWL_NARRATION_EVENTS": " VOTE_STARTED, GAME_OVER ,PLAYER_SPOKE",
        "AGENTHOWL_NARRATION_DIR": str(tmp_path / "x"),
    }
    cfg = NarrationConfig.from_env(env, data_dir=tmp_path)
    assert cfg.speaker == "vivian"
    # PLAYER_SPOKE 允许出现但会被 narrate() 忽略；名单本身保留它（不替用户改配置）
    assert cfg.events == frozenset({EventType.VOTE_STARTED, EventType.GAME_OVER, EventType.PLAYER_SPOKE})
    assert cfg.cache_dir == tmp_path / "x"
    # 空串 = 默认
    assert NarrationConfig.from_env({"AGENTHOWL_NARRATION_EVENTS": ""}, data_dir=tmp_path).events == DEFAULT_NARRATION_EVENTS


@pytest.mark.parametrize(
    "env",
    [
        {"AGENTHOWL_NARRATOR_VOICE": "nobody"},
        {"AGENTHOWL_NARRATION_EVENTS": "VOTE_STARTED,NOT_AN_EVENT"},
        {"AGENTHOWL_NARRATION_EVENTS": "VOTE_CAST"},  # 合法类型但没有模板
    ],
)
def test_config_fail_loud(tmp_path: Path, env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        NarrationConfig.from_env(env, data_dir=tmp_path)


def test_cache_roundtrip_and_key(tmp_path: Path) -> None:
    cache = NarrationCache(tmp_path / "narr")
    assert cache.get("uncle_fu", "投票开始。") is None
    wav = _wav(0.1)
    p = cache.put("uncle_fu", "投票开始。", wav)
    assert p.parent == tmp_path / "narr" and p.suffix == ".wav"
    assert not list((tmp_path / "narr").glob("*.tmp"))
    assert cache.get("uncle_fu", "投票开始。") == wav
    # 换声线换 key
    assert NarrationCache.key("vivian", "投票开始。") != NarrationCache.key("uncle_fu", "投票开始。")
    assert len(NarrationCache.key("vivian", "投票开始。")) == 16


def test_cache_corrupt_file_is_miss(tmp_path: Path) -> None:
    cache = NarrationCache(tmp_path / "narr")
    (tmp_path / "narr").mkdir()
    (tmp_path / "narr" / f"{NarrationCache.key('uncle_fu', '投票开始。')}.wav").write_bytes(b"junk")
    assert cache.get("uncle_fu", "投票开始。") is None
```

需要在测试文件顶部加 `from app.agent.profile import VoiceSpec`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_narration.py -q`
Expected: FAIL（`ImportError: NarrationCache`）

- [ ] **Step 3: Implement（追加到 `narration.py` 末尾）**

```python
@dataclass(frozen=True)
class NarrationConfig:
    """旁白配置：声线 + 事件白名单 + 缓存目录。构造即校验（fail-loud）。"""

    speaker: str
    events: frozenset[EventType]
    cache_dir: Path

    def __post_init__(self) -> None:
        if self.speaker not in PRESET_SPEAKERS:
            raise ValueError(f"旁白声线必须是预置 speaker {PRESET_SPEAKERS}：{self.speaker!r}")
        missing = sorted(t.value for t in self.events - TEMPLATED_EVENTS - SPEECH_EVENTS)
        if missing:
            raise ValueError(f"旁白白名单里的事件没有模板：{missing}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, data_dir: Path) -> NarrationConfig:
        e = os.environ if env is None else env
        speaker = (e.get("AGENTHOWL_NARRATOR_VOICE") or DEFAULT_NARRATOR_SPEAKER).strip()
        raw = (e.get("AGENTHOWL_NARRATION_EVENTS") or "").strip()
        if raw:
            names = [x.strip() for x in raw.split(",") if x.strip()]
            try:
                events = frozenset(EventType(n) for n in names)
            except ValueError as exc:
                raise ValueError(f"AGENTHOWL_NARRATION_EVENTS 含未知事件：{exc}") from exc
        else:
            events = DEFAULT_NARRATION_EVENTS
        cache_dir = Path(e.get("AGENTHOWL_NARRATION_DIR") or (data_dir / "narration"))
        return cls(speaker=speaker, events=events, cache_dir=cache_dir)

    @property
    def voice(self) -> VoiceSpec:
        return VoiceSpec(mode="preset", speaker=self.speaker)


class NarrationCache:
    """句子级 WAV 缓存：key = sha256(speaker + 句子)[:16]；所有对局共用。"""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    @staticmethod
    def key(speaker: str, text: str) -> str:
        return hashlib.sha256(f"{speaker}\n{text}".encode()).hexdigest()[:16]

    def _path(self, speaker: str, text: str) -> Path:
        return self._dir / f"{self.key(speaker, text)}.wav"

    def get(self, speaker: str, text: str) -> bytes | None:
        """未命中 / 文件不是合法 WAV → None（坏文件视为未命中，由 put 覆盖）。"""
        from app.runtime.tts import TtsError, wav_duration  # 惰性：避免 narration ↔ tts 循环

        p = self._path(speaker, text)
        try:
            data = p.read_bytes()
            wav_duration(data)
        except (OSError, TtsError):
            return None
        return data

    def put(self, speaker: str, text: str, wav: bytes) -> Path:
        p = self._path(speaker, text)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".wav.tmp")
        tmp.write_bytes(wav)
        os.replace(tmp, p)
        return p
```

注意：`app/runtime/tts.py` 不 import narration，所以其实可以顶层 import `wav_duration`；若顶层 import 不产生循环（`tts.py` 只 import `app.agent.profile`），改为顶层 import 并删掉惰性 import 注释。

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_narration.py -q && uv run ruff check . && uv run mypy app`
Expected: PASS，无 lint / type 报错。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/narration.py backend/tests/test_narration.py
git commit -m "feat(narration): NarrationConfig.from_env 与句子级 WAV 缓存 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `concat_wav`

**Files:**
- Modify: `backend/app/runtime/tts.py`（在 `wav_duration` 之后追加）
- Test: `backend/tests/test_tts.py`（追加）

**Interfaces:**
- Produces: `concat_wav(parts: list[bytes]) -> bytes`：把多个同格式 WAV 的 PCM data 拼成一个；单元素原样返回；空列表 / 格式不一致 / 非 WAV → `TtsError`。

- [ ] **Step 1: Write the failing tests（追加到 `tests/test_tts.py`）**

```python
import io
import wave

from app.runtime.tts import TtsError, concat_wav, wav_duration


def _pcm_wav(seconds: float, rate: int = 8000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)
    return buf.getvalue()


def test_concat_wav_joins_data_chunks() -> None:
    out = concat_wav([_pcm_wav(0.2), _pcm_wav(0.3)])
    assert out[:4] == b"RIFF" and wav_duration(out) == pytest.approx(0.5, abs=0.001)
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 8000 and w.getnframes() == 4000


def test_concat_wav_single_and_errors() -> None:
    one = _pcm_wav(0.1)
    assert concat_wav([one]) is one
    with pytest.raises(TtsError):
        concat_wav([])
    with pytest.raises(TtsError):
        concat_wav([_pcm_wav(0.1, rate=8000), _pcm_wav(0.1, rate=16000)])
    with pytest.raises(TtsError):
        concat_wav([one, b"not a wav"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_tts.py -k concat -q`
Expected: FAIL（`ImportError: concat_wav`）

- [ ] **Step 3: Implement（`tts.py`，放在 `wav_duration` 后面）**

```python
def _wav_chunks(wav: bytes) -> tuple[bytes, bytes]:
    """→ (fmt 块内容, PCM data)；不是 WAV / 缺块 → TtsError。"""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise TtsError("不是 WAV")
    pos = 12
    fmt: bytes | None = None
    while pos + 8 <= len(wav):
        cid = wav[pos : pos + 4]
        size = int.from_bytes(wav[pos + 4 : pos + 8], "little")
        body = wav[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            if fmt is None:
                raise TtsError("WAV data 块先于 fmt 块")
            return fmt, body
        pos += 8 + size + (size & 1)
    raise TtsError("WAV 头缺少 fmt/data 块")


def concat_wav(parts: list[bytes]) -> bytes:
    """同采样率 / 声道 / 位宽的多段 WAV → 一段（直接拼 data 块）。单段原样返回。"""
    if not parts:
        raise TtsError("concat_wav: 没有可拼接的音频")
    if len(parts) == 1:
        _wav_chunks(parts[0])  # 仍校验合法性
        return parts[0]
    fmt0, datas = None, []
    for p in parts:
        fmt, data = _wav_chunks(p)
        if fmt0 is None:
            fmt0 = fmt
        elif fmt != fmt0:
            raise TtsError("concat_wav: 各段 WAV 格式不一致")
        datas.append(data)
    assert fmt0 is not None
    data = b"".join(datas)
    fmt_chunk = b"fmt " + len(fmt0).to_bytes(4, "little") + fmt0 + (b"\x00" if len(fmt0) & 1 else b"")
    data_chunk = b"data" + len(data).to_bytes(4, "little") + data + (b"\x00" if len(data) & 1 else b"")
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tts.py -q && uv run ruff check . && uv run mypy app`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/tts.py backend/tests/test_tts.py
git commit -m "feat(tts): concat_wav 拼接同格式 WAV 的 data 块 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `ConnectionManager` 帧按视角过滤 + WS 接入

**Files:**
- Modify: `backend/app/runtime/connection.py:16-64`
- Modify: `backend/app/api/ws.py:113-120,178`
- Modify: `backend/app/runtime/speech_audio.py:80-130`（`speak()` 加 `event` 形参并透传给 `broadcast_frame`）
- Modify: `backend/app/runtime/game_runner.py:298-316`（`_maybe_speak` 把事件 `e` 传给 `speak`）
- Modify: `backend/tests/test_connection.py:126-146`
- Modify: `backend/tests/test_speech_audio.py`（`subscribe_frames` 加 viewer；`speak()` 调用加 `event`）
- Modify: `backend/tests/test_game_runner.py:404-416`（`_RecordingSink.speak` 签名加 `event`）
- Test: `backend/tests/test_connection.py`

**Interfaces:**
- Produces: `ConnectionManager.subscribe_frames(viewer: Viewer, callback: FrameSubscriber)`、`unsubscribe_frames(viewer, callback)`、`async broadcast_frame(frame: dict[str, Any], event: Event) -> None`；`SpeechAudioSink.speak(game_id, seq, text, voice, connections, event: Event)`。
- Task 5 在此基础上抽内核；ws 在本任务传 viewer。

- [ ] **Step 1: Write the failing tests（替换 `test_connection.py` 里 `test_broadcast_frame_reaches_all_and_drops_bad_subscriber`，并新增一个）**

```python
@pytest.mark.asyncio
async def test_broadcast_frame_reaches_visible_and_drops_bad_subscriber() -> None:
    """issue #110：帧随来源事件按视角过滤；坏订阅者摘除。"""
    cm = ConnectionManager(state_provider=_state)
    got: list[dict] = []

    async def good(frame: dict) -> None:
        got.append(frame)

    async def bad(frame: dict) -> None:
        raise RuntimeError("boom")

    cm.subscribe_frames("SPECTATOR", good)
    cm.subscribe_frames("SPECTATOR", bad)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 1}, _evt(1, Visibility.PUBLIC))
    await cm.broadcast_frame({"type": "speech_audio_end", "seq": 1, "parts": 1}, _evt(1, Visibility.PUBLIC))
    assert [f["type"] for f in got] == ["speech_audio", "speech_audio_end"]
    cm.unsubscribe_frames("SPECTATOR", good)
    await cm.broadcast_frame({"type": "speech_audio", "seq": 2}, _evt(2, Visibility.PUBLIC))
    assert len(got) == 2


@pytest.mark.asyncio
async def test_frame_filtered_by_viewer() -> None:
    """Review Focus 3：GM_ONLY 只 GM 收；WOLVES 只狼座位（seat 0）与 GM 收；观众 / 村民不收。"""
    cm = ConnectionManager(state_provider=_state)
    got: dict[str, list[int]] = {"GM": [], "SPECTATOR": [], "wolf": [], "villager": []}

    def sub(name: str):  # type: ignore[no-untyped-def]
        async def cb(frame: dict) -> None:
            got[name].append(frame["seq"])

        return cb

    cm.subscribe_frames("GM", sub("GM"))
    cm.subscribe_frames("SPECTATOR", sub("SPECTATOR"))
    cm.subscribe_frames(0, sub("wolf"))
    cm.subscribe_frames(1, sub("villager"))
    await cm.broadcast_frame({"seq": 1}, _evt(1, Visibility.GM_ONLY))
    await cm.broadcast_frame({"seq": 2}, _evt(2, Visibility.WOLVES))
    await cm.broadcast_frame({"seq": 3}, _evt(3, Visibility.PUBLIC))
    assert got == {"GM": [1, 2, 3], "SPECTATOR": [3], "wolf": [2, 3], "villager": [3]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_connection.py -q`
Expected: FAIL（`subscribe_frames() takes 2 positional arguments but 3 were given`）

- [ ] **Step 3: Implement `connection.py`**

把帧订阅部分替换为：

```python
# 原始帧订阅者（issue #103 / #110）：帧不是事件，但必须声明来源事件，按视角过滤后投递
FrameSubscriber = Callable[[dict[str, Any]], Awaitable[None]]
```

```python
    def __init__(self, state_provider: Callable[[], GameState]) -> None:
        self._state_provider = state_provider
        self._subs: list[tuple[Viewer, Subscriber]] = []
        self._frame_subs: list[tuple[Viewer, FrameSubscriber]] = []
```

```python
    def subscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None:
        """原始帧订阅（speech_audio 等）：帧随来源事件经 visible_events 过滤（issue #110）。"""
        self._frame_subs.append((viewer, callback))

    def unsubscribe_frames(self, viewer: Viewer, callback: FrameSubscriber) -> None:
        self._frame_subs = [
            (v, cb) for v, cb in self._frame_subs if not (v == viewer and cb is callback)
        ]

    async def broadcast_frame(self, frame: dict[str, Any], event: Event) -> None:
        """只投给能看到 event 的视角——与事件广播同一过滤点，不自造判断。"""
        state = self._state_provider()
        for viewer, cb in list(self._frame_subs):
            if not visible_events(state, [event], viewer):
                continue
            try:
                await cb(frame)
            except Exception:
                logger.warning("帧订阅者回调异常，已摘除 viewer=%r type=%s", viewer, frame.get("type"), exc_info=True)
                self.unsubscribe_frames(viewer, cb)
```

更新模块 docstring 第二段：「帧订阅也按视角过滤（issue #110）」。

- [ ] **Step 4: 更新 `ws.py`**

`app/api/ws.py:120` → `handle.connections.subscribe_frames(viewer, on_frame)`；`:178` → `handle.connections.unsubscribe_frames(viewer, on_frame)`；`on_frame` 的注释改为 `# speech_audio / speech_audio_end：已按本连接视角过滤（issue #110）`。

- [ ] **Step 5: `speak()` 带上来源事件**

`app/runtime/speech_audio.py`：`speak` 签名末尾加 `event: Event`（`from app.engine.events import Event`），两处 `broadcast_frame({...})` 改为 `broadcast_frame({...}, event)`。
`app/runtime/game_runner.py` `_maybe_speak`：`speak(self._game_id, e.seq, text, profile.voice, self.connections, e)`。

测试同步：
- `tests/test_speech_audio.py` 顶部加辅助

```python
from app.engine.events import Event, EventType, Visibility, VoteStartedPayload, RoundStartedPayload


def _public(seq: int, t: EventType = EventType.VOTE_STARTED) -> Event:
    payload = (
        VoteStartedPayload(candidates=(), tie_round=0)
        if t == EventType.VOTE_STARTED
        else RoundStartedPayload(round=seq)
    )
    vis = Visibility.PUBLIC if t == EventType.VOTE_STARTED else Visibility.GM_ONLY
    return Event(seq=seq, game_id="g1", ts=float(seq), type=t, payload=payload, visibility=vis)
```

  两处 `cm.subscribe_frames(sub)` → `cm.subscribe_frames("GM", sub)`；所有 `sink.speak(...)` 调用末尾加 `_public(<该调用的 seq>)`。
- `tests/test_game_runner.py` `_RecordingSink.speak` 签名改为 `(self, game_id, seq, text, voice, connections, event)`。

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/test_connection.py tests/test_api_ws.py tests/test_speech_audio.py tests/test_game_runner.py tests/test_api_voice.py -q && uv run ruff check . && uv run mypy app`
Expected: 全部 PASS，mypy 干净。

- [ ] **Step 7: Commit**

```bash
git add backend/app/runtime/connection.py backend/app/runtime/speech_audio.py backend/app/runtime/game_runner.py backend/app/api/ws.py backend/tests/test_connection.py backend/tests/test_speech_audio.py backend/tests/test_game_runner.py
git commit -m "feat(connection): 帧订阅带 viewer，broadcast_frame 随来源事件经 visible_events 过滤 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `SpeechAudioSink` 内核抽取 + `narrate()` + 预热旁白声线

**Files:**
- Modify: `backend/app/runtime/speech_audio.py`
- Modify: `backend/tests/test_speech_audio.py`

**Interfaces:**
- Consumes: Task 1/2 `narrate`、`NarrationConfig`、`NarrationCache`、`NARRATOR_WARM_TEXT`；Task 3 `concat_wav`；Task 4 `broadcast_frame(frame, event)`、`speak(..., event)`、测试辅助 `_public(seq, t)`。
- Produces:
  - `SpeechAudioSink(audio_dir, tts, anchors=None, *, narration: NarrationConfig | None = None, narration_cache: NarrationCache | None = None)`
  - `async speak(game_id, seq, text, voice, connections, event: Event) -> None`
  - `async narrate(game_id, event: Event, connections) -> None`
  - `async warm(voices: list[VoiceSpec]) -> None`（配置了旁白时自动把旁白声线加进去）
  - 帧：`{"type":"speech_audio", seq, part, url, duration, "kind"}`、`{"type":"speech_audio_end", seq, parts, "kind"}`。

- [ ] **Step 1: Write the failing tests（追加到 `tests/test_speech_audio.py`）**

```python
from app.runtime.narration import DEFAULT_NARRATION_EVENTS, NarrationCache, NarrationConfig


class CountingTts:
    """每次 synthesize 产一段 0.05s；记录文本。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: object = None
    ) -> AsyncIterator[AudioPart]:
        self.calls.append(text)
        yield AudioPart(index=0, wav=_wav(0.05), duration_sec=0.05)

    async def probe(self) -> TtsStatus:
        return TtsStatus(enabled=True, ok=True, url="fake")


def _narr(tmp_path: Path) -> NarrationConfig:
    return NarrationConfig(
        speaker="uncle_fu", events=DEFAULT_NARRATION_EVENTS, cache_dir=tmp_path / "narr"
    )


@pytest.mark.asyncio
async def test_narrate_pushes_frames_with_kind_and_caches(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    tts = CountingTts()
    cache = NarrationCache(tmp_path / "narr")
    sink = SpeechAudioSink(tmp_path / "audio", tts, narration=_narr(tmp_path), narration_cache=cache)
    await sink.narrate("g1", _public(5), cm)
    assert tts.calls == ["投票开始。"]
    assert frames[0]["kind"] == "narration" and frames[0]["seq"] == 5 and frames[0]["part"] == 0
    assert frames[-1] == {"type": "speech_audio_end", "seq": 5, "parts": 1, "kind": "narration"}
    assert sink.manifest("g1") == {"5": [{"part": 0, "duration": pytest.approx(0.05, abs=0.01)}]}
    assert cache.get("uncle_fu", "投票开始。") is not None
    # 第二次：零 TTS 调用，仍推帧、仍落到对局目录
    await sink.narrate("g1", _public(9), cm)
    assert tts.calls == ["投票开始。"]
    assert sink.path_for("g1", 9, 0) is not None


@pytest.mark.asyncio
async def test_narrate_outside_whitelist_is_noop(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    cfg = NarrationConfig(speaker="uncle_fu", events=frozenset({EventType.GAME_OVER}), cache_dir=tmp_path / "n")
    tts = CountingTts()
    sink = SpeechAudioSink(tmp_path / "audio", tts, narration=cfg, narration_cache=NarrationCache(cfg.cache_dir))
    t0 = time.monotonic()
    await sink.narrate("g1", _public(5), cm)
    assert tts.calls == [] and frames == [] and time.monotonic() - t0 < 0.1


@pytest.mark.asyncio
async def test_narrate_filtered_frames_follow_event_visibility(tmp_path: Path) -> None:
    cm = ConnectionManager(state_provider=_state)
    got: dict[str, list[str]] = {"GM": [], "SPECTATOR": []}

    def sub(name: str):  # type: ignore[no-untyped-def]
        async def cb(f: dict) -> None:
            got[name].append(f["type"])

        return cb

    cm.subscribe_frames("GM", sub("GM"))
    cm.subscribe_frames("SPECTATOR", sub("SPECTATOR"))
    sink = SpeechAudioSink(tmp_path / "audio", CountingTts(), narration=_narr(tmp_path), narration_cache=NarrationCache(tmp_path / "narr"))
    await sink.narrate("g1", _public(2, EventType.ROUND_STARTED), cm)  # GM_ONLY
    assert got["GM"] == ["speech_audio", "speech_audio_end"] and got["SPECTATOR"] == []


@pytest.mark.asyncio
async def test_narrate_tts_failure_skips_and_no_frames(tmp_path: Path) -> None:
    class Boom:
        async def synthesize_sentences(self, text: str, voice: VoiceSpec, ref_audio: object = None) -> AsyncIterator[AudioPart]:
            raise TtsError("down")
            yield  # pragma: no cover

        async def probe(self) -> TtsStatus:
            return TtsStatus(enabled=True, ok=False, url="fake")

    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(tmp_path / "audio", Boom(), narration=_narr(tmp_path), narration_cache=NarrationCache(tmp_path / "narr"))
    await sink.narrate("g1", _public(5), cm)  # 不抛
    assert frames == [] and sink.manifest("g1") == {}


@pytest.mark.asyncio
async def test_narrate_plays_even_if_cache_put_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review Focus 2：缓存目录不可写只告警，本句仍播。"""
    cache = NarrationCache(tmp_path / "narr")

    def boom(*a: object, **k: object) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(cache, "put", boom)
    cm = ConnectionManager(state_provider=_state)
    frames: list[dict] = []

    async def sub(f: dict) -> None:
        frames.append(f)

    cm.subscribe_frames("GM", sub)
    sink = SpeechAudioSink(tmp_path / "audio", CountingTts(), narration=_narr(tmp_path), narration_cache=cache)
    await sink.narrate("g1", _public(5), cm)
    assert [f["type"] for f in frames] == ["speech_audio", "speech_audio_end"]


@pytest.mark.asyncio
async def test_narrate_without_config_is_noop(tmp_path: Path) -> None:
    sink = SpeechAudioSink(tmp_path / "audio", CountingTts())
    await sink.narrate("g1", _public(5), None)  # 未配置旁白：不抛、不做事


@pytest.mark.asyncio
async def test_warm_includes_narrator_voice(tmp_path: Path) -> None:
    tts = CountingTts()
    sink = SpeechAudioSink(tmp_path / "audio", tts, narration=_narr(tmp_path), narration_cache=NarrationCache(tmp_path / "narr"))
    await sink.warm([VoiceSpec(mode="preset", speaker="dylan")])
    assert len(tts.calls) == 2  # dylan + uncle_fu 各一句
```

现有 `test_speak_writes_parts_pushes_frames_and_waits` 里 `frames[0]` / `frames[2]` 的期望字典加上 `"kind": "speech"`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_speech_audio.py -q`
Expected: FAIL（`TypeError: unexpected keyword argument 'narration'` / `speak() takes 6 positional arguments`）

- [ ] **Step 3: Implement `speech_audio.py`**

替换 import 与类主体（保留 `_check_game_id`、`manifest`、`path_for`、`delete_game` 不变）：

```python
from collections.abc import AsyncIterator
from typing import Any, Literal

from app.agent.profile import VoiceSpec
from app.engine.events import Event
from app.runtime.connection import ConnectionManager
from app.runtime.narration import NARRATOR_WARM_TEXT, NarrationCache, NarrationConfig, narrate
from app.runtime.tts import AudioPart, TtsClient, TtsError, concat_wav, wav_duration
from app.runtime.voice_anchors import VoiceAnchorStore

AudioKind = Literal["speech", "narration"]
```

```python
class SpeechAudioSink:
    def __init__(
        self,
        audio_dir: Path,
        tts: TtsClient,
        anchors: VoiceAnchorStore | None = None,
        *,
        narration: NarrationConfig | None = None,
        narration_cache: NarrationCache | None = None,
    ) -> None:
        self._dir = audio_dir
        self._tts = tts
        self._anchors = anchors
        self._narration = narration
        self._cache = narration_cache
        if narration is not None and narration_cache is None:
            raise ValueError("配置了旁白必须同时给 narration_cache")

    # ---------- 预热 ----------

    async def warm(self, voices: list[VoiceSpec]) -> None:
        """…原 docstring…；配置了旁白时把旁白声线一起预热（issue #110）。"""
        if self._narration is not None:
            voices = [*voices, self._narration.voice]
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for voice in voices:
            key = (
                (voice.mode, voice.speaker, None)
                if voice.mode == "preset"
                else (voice.mode, None, voice.anchor or voice.style)
            )
            if key in seen:
                continue
            seen.add(key)
            try:
                ref = await self._anchors.ensure_for(voice, self._tts) if self._anchors else None
                async for _ in self._tts.synthesize_sentences(NARRATOR_WARM_TEXT, voice, ref):
                    pass
            except TtsError as exc:
                logger.warning("声线预热失败（%s）：%s", key, exc)
```

（`WARM_TEXT` 常量改为 `WARM_TEXT = NARRATOR_WARM_TEXT` 以保留旧名给已有测试 import。）

```python
    # ---------- 发言 ----------

    async def speak(
        self,
        game_id: str,
        seq: int,
        text: str,
        voice: VoiceSpec,
        connections: ConnectionManager | None,
        event: Event,
    ) -> None:
        """失败不抛：WARNING 后对已推句子照常等待，对局继续。"""
        ref_audio: Path | None = None
        if voice.mode == "design" and self._anchors is not None:
            try:
                ref_audio = await self._anchors.ensure_for(voice, self._tts)
            except TtsError as exc:
                logger.warning("game=%s seq=%d 锚点生成失败，退回逐句设计：%s", game_id, seq, exc)
        await self._emit(
            game_id, seq, self._tts.synthesize_sentences(text, voice, ref_audio), connections, event, "speech"
        )

    # ---------- 旁白 ----------

    async def narrate(self, game_id: str, event: Event, connections: ConnectionManager | None) -> None:
        """白名单事件 → 逐句（缓存优先）→ 同一内核推帧等待；未配置旁白 / 无句子 → 直接返回。"""
        if self._narration is None or self._cache is None:
            return
        sentences = narrate(event, self._narration.events)
        if not sentences:
            return
        await self._emit(game_id, event.seq, self._narration_parts(sentences), connections, event, "narration")

    async def _narration_parts(self, sentences: list[str]) -> AsyncIterator[AudioPart]:
        assert self._narration is not None and self._cache is not None
        speaker, voice = self._narration.speaker, self._narration.voice
        k = 0
        for sentence in sentences:
            wav = self._cache.get(speaker, sentence)
            if wav is None:
                try:
                    pieces = [p.wav async for p in self._tts.synthesize_sentences(sentence, voice)]
                    wav = concat_wav(pieces)
                except TtsError as exc:
                    logger.warning("旁白合成失败，跳过：%r %s", sentence, exc)
                    continue
                try:
                    self._cache.put(speaker, sentence, wav)
                except OSError as exc:
                    logger.warning("旁白缓存写入失败（本句仍播）：%s", exc)
            yield AudioPart(index=k, wav=wav, duration_sec=wav_duration(wav))
            k += 1

    # ---------- 内核：落盘 + 推帧 + 等待 ----------

    async def _emit(
        self,
        game_id: str,
        seq: int,
        parts: AsyncIterator[AudioPart],
        connections: ConnectionManager | None,
        event: Event,
        kind: AudioKind,
    ) -> None:
        _check_game_id(game_id)
        expected_finish: float | None = None
        count = 0
        try:
            async for part in parts:
                path = self._dir / game_id / f"{seq}-{part.index}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(part.wav)
                now = time.monotonic()
                expected_finish = max(expected_finish if expected_finish is not None else now, now)
                expected_finish += part.duration_sec
                count += 1
                if connections is not None:
                    await connections.broadcast_frame(
                        {
                            "type": "speech_audio",
                            "seq": seq,
                            "part": part.index,
                            "url": f"/api/v1/games/{game_id}/audio/{seq}/{part.index}",
                            "duration": round(part.duration_sec, 3),
                            "kind": kind,
                        },
                        event,
                    )
        except TtsError as exc:
            logger.warning("game=%s seq=%d %s 配音失败（已推 %d 句）：%s", game_id, seq, kind, count, exc)
        if count and connections is not None:
            await connections.broadcast_frame(
                {"type": "speech_audio_end", "seq": seq, "parts": count, "kind": kind}, event
            )
        if expected_finish is not None:
            await asyncio.sleep(max(0.0, expected_finish + AUDIO_TAIL_SEC - time.monotonic()))
```

模块 docstring 追加一段：「issue #110：旁白走同一内核 `_emit`，帧带 `kind`，并随来源事件按视角过滤。」

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_speech_audio.py tests/test_game_runner.py tests/test_connection.py -q && uv run ruff check . && uv run mypy app`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/speech_audio.py backend/tests/test_speech_audio.py
git commit -m "feat(speech_audio): 抽出 _emit 内核，新增 narrate()（句子缓存 + kind 帧），预热含旁白声线 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Runner `_voice(events)` 统一调度

**Files:**
- Modify: `backend/app/runtime/game_runner.py:119-146,152-164,285-316,317-325`
- Test: `backend/tests/test_game_runner.py`

**Interfaces:**
- Consumes: Task 5 `speak(..., event)`、`narrate(game_id, event, connections)`。
- Produces: `GameRunner(..., speech_audio=None, narration_enabled: bool = False)`；私有 `_voice(events)`。

- [ ] **Step 1: Write the failing tests（追加到 `tests/test_game_runner.py`）**

```python
class _KindSink:
    """记录 (kind, seq) 顺序；narrate 只记录不等待。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def speak(self, game_id: str, seq: int, text: str, voice: object, connections: object, event: object) -> None:
        self.calls.append(("speech", seq))

    async def narrate(self, game_id: str, event: object, connections: object) -> None:
        self.calls.append(("narration", event.seq))  # type: ignore[attr-defined]


async def test_runner_voices_events_in_seq_order_with_narration() -> None:
    """issue #110：发言与旁白按 seq 顺序交给 sink（同一提交里发言先于阶段切换）；
    narration_enabled=True 时每条事件都经 narrate（白名单判断在 sink 内）。"""
    from app.agent.profile import AgentProfile, VoiceSpec

    store = InMemoryEventStore()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    sink = _KindSink()
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        agents={"*": AgentProfile(model="x", voice=VoiceSpec(mode="preset", speaker="eric"))},
        speech_audio=sink,  # type: ignore[arg-type]
        narration_enabled=True,
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    assert (await runner.run()).phase == Phase.GAME_OVER
    seqs = [s for _k, s in sink.calls]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    events = store.load_events("g1")
    speech_seqs = {e.seq for e in events if e.type in (EventType.PLAYER_SPOKE, EventType.LAST_WORDS)}
    assert {s for k, s in sink.calls if k == "speech"} == speech_seqs
    assert {s for k, s in sink.calls if k == "narration"} == {e.seq for e in events} - speech_seqs


async def test_runner_narration_disabled_never_calls_narrate() -> None:
    from app.agent.profile import AgentProfile

    store = InMemoryEventStore()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 7})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    sink = _KindSink()
    runner = GameRunner(
        store=store, config=cfg, game_id="g1", roster=lobby.roster(), ports=ports,
        agents={"*": AgentProfile(model="x")}, speech_audio=sink,  # type: ignore[arg-type]
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    await runner.run()
    assert sink.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_game_runner.py -k "voices_events or narration_disabled" -q`
Expected: FAIL（`unexpected keyword argument 'narration_enabled'`）

- [ ] **Step 3: Implement**

构造函数增 `narration_enabled: bool = False` → `self._narration_enabled = narration_enabled`。

`run()` 里 `await self._commit(res.events)` 之后加 `await self._voice(res.events)`。

`_drive_seat` 里 `await self._maybe_speak(seat, res.events)` → `await self._voice(res.events)`。

`_apply_default` 里 `_commit` 之后加 `await self._voice(res.events)`。

（`_commit` 全文件只有这三处调用：`run()`、`_drive_seat`、`_apply_default`；`_drive_window` 的非法回退走 `_drive_seat`。）

把 `_maybe_speak` 整体替换为：

```python
    async def _voice(self, events: list[Event]) -> None:
        """配音统一调度（issue #103 / #110）：按 seq 顺序，发言事件走该座位档案的声线，
        其余事件交给旁白（白名单判断在 sink 内）。同一提交常是 [PLAYER_SPOKE, PHASE_CHANGED]，
        必须先放发言再放「进入投票」。sink 自身吞 TtsError；这里再兜一层任何异常，
        配音永远不能让对局陪葬。"""
        if self._speech_audio is None:
            return
        for e in events:
            try:
                if e.type in (EventType.PLAYER_SPOKE, EventType.LAST_WORDS):
                    # 两类发言事件引擎都写了 actor_seat（engine.py LAST_WORDS 处 actor=action.actor_seat）
                    if e.actor_seat is None:
                        continue
                    profile = profile_for(self._agents, e.actor_seat)
                    if profile is None or profile.voice is None:
                        continue
                    await self._speech_audio.speak(
                        self._game_id, e.seq, str(e.payload.content), profile.voice, self.connections, e  # type: ignore[attr-defined]
                    )
                elif self._narration_enabled:
                    await self._speech_audio.narrate(self._game_id, e, self.connections)
            except Exception:
                logger.warning("seq=%d 配音异常，跳过等待", e.seq, exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_game_runner.py tests/test_registry.py -q && uv run ruff check . && uv run mypy app`
Expected: PASS（含既有 `test_runner_waits_for_speech_audio_only_for_voiced_seats`、`test_runner_sink_exception_does_not_kill_game`）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/game_runner.py backend/tests/test_game_runner.py
git commit -m "feat(runner): _voice 按 seq 顺序统一调度发言配音与旁白 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 建局 `narration` 开关、装配、音频端点视角过滤、文档

**Files:**
- Modify: `backend/app/schemas/games.py:20,30`
- Modify: `backend/app/runtime/registry.py:50-75,136-165,240-262`
- Modify: `backend/app/api/rest.py:70-120,503-567`
- Modify: `backend/app/main.py:60-125`
- Modify: `.env.example`（发言配音块末尾）、`README.md:218-224`
- Test: `backend/tests/test_api_voice.py`

**Interfaces:**
- Consumes: Task 2 `NarrationConfig`、`NarrationCache`；Task 5 sink 构造参数；Task 6 `narration_enabled`。
- Produces: `CreateGameRequest.narration: bool = False`、`CreateGameResponse.narration: bool`；`GameRegistry.create(..., narration: bool = False)`；`GameHandle.narration_enabled`；`create_app(..., narration_config: NarrationConfig | None = None)`；`rest.py` 的 `_audio_visible_seqs(games, game_id, info) -> set[int] | None`。

- [ ] **Step 1: Write the failing tests（追加到 `tests/test_api_voice.py`）**

```python
from app.engine.events import EventType
from app.runtime.narration import NarrationConfig


class SlowNarrationTts(FakeTts):
    """旁白句子给 0.6s 时长，让对局在直播期间停留足够久以便测试过滤。"""

    async def synthesize_sentences(
        self, text: str, voice: VoiceSpec, ref_audio: object = None
    ) -> AsyncIterator[AudioPart]:
        self.texts.append(text)
        dur = 0.6 if voice.speaker == "uncle_fu" else 0.02
        yield AudioPart(index=0, wav=_wav(dur), duration_sec=dur)


def _narr_app(tmp_path: Path, tts: Any, events: frozenset[EventType], public_history: bool | None = None) -> TestClient:
    cfg = NarrationConfig(speaker="uncle_fu", events=events, cache_dir=tmp_path / "narration")
    app = create_app(
        store=InMemoryEventStore(),
        agent_library=InMemoryAgentLibrary(),
        timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5),
        agent_port_factory=lambda seat, h: BotPlayerPort(state_provider=h.live_state),
        tts_client=tts,
        audio_dir=tmp_path / "audio",
        voices_dir=tmp_path / "voices",
        public_history=public_history,
        narration_config=cfg,
    )
    return TestClient(app)


def test_create_game_narration_requires_voice(client: TestClient) -> None:
    r = client.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": False, "narration": True})
    assert r.status_code == 400 and "旁白" in r.json()["detail"]
    r = client.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True, "narration": True})
    assert r.status_code == 200 and r.json()["narration"] is True
    r = client.post("/api/v1/games", json={"preset": "std_9_kill_side", "voice": True})
    assert r.json()["narration"] is False


def test_narrated_game_streams_narration_frames_and_reuses_cache(tmp_path: Path) -> None:
    tts = FakeTts()
    with _narr_app(tmp_path, tts, frozenset({EventType.VOTE_STARTED, EventType.GAME_OVER})) as c:
        for _ in range(2):
            r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 3}, "voice": True, "narration": True})
            created = r.json()
            gid = created["game_id"]
            frames: list[dict[str, Any]] = []
            c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
            with c.websocket_connect(f"/api/v1/ws?token={created['gm_token']}") as ws:
                while True:
                    f = ws.receive_json()
                    frames.append(f)
                    if f["type"] == "game_over":
                        break
            narr = [f for f in frames if f["type"] == "speech_audio" and f.get("kind") == "narration"]
            assert narr, "没有旁白帧"
            narrated_seqs = {f["seq"] for f in narr}
            by_seq = {f["event"]["seq"]: f["event"]["type"] for f in frames if f["type"] == "game_event"}
            assert {by_seq[s] for s in narrated_seqs} <= {"VOTE_STARTED", "GAME_OVER"}
            # 清单里旁白与发言同列
            m = c.get(f"/api/v1/games/{gid}/audio", headers=_auth(created["gm_token"])).json()
            assert all(str(s) in m for s in narrated_seqs)
        # 两局下来，旁白句子只各合成一次（投票开始。/ PK投票开始。/ 游戏结束…）
        narr_texts = [t for t in tts.texts if t.endswith("。") and t != "大家好。"]
        assert len(narr_texts) == len(set(narr_texts))
        assert (tmp_path / "narration").is_dir() and list((tmp_path / "narration").glob("*.wav"))


def test_live_audio_filtered_by_viewer(tmp_path: Path) -> None:
    """Review Focus 4：直播中 GM_ONLY 事件的旁白——观众清单不列、文件 404；GM 能取。"""
    with _narr_app(tmp_path, SlowNarrationTts(), frozenset({EventType.ROUND_STARTED, EventType.GAME_OVER})) as c:
        r = c.post("/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 3}, "voice": True, "narration": True})
        created = r.json()
        gid = created["game_id"]
        c.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
        url: str | None = None
        with c.websocket_connect(f"/api/v1/ws?token={created['gm_token']}") as ws:
            while url is None:
                f = ws.receive_json()
                if f["type"] == "speech_audio" and f.get("kind") == "narration":
                    url = f["url"]
                    seq = f["seq"]
            # 此刻 runner 正在等这句（0.6s）播完：对局仍在直播
            gm = _auth(created["gm_token"])
            sp = _auth(created["spectator_token"])
            assert str(seq) in c.get(f"/api/v1/games/{gid}/audio", headers=gm).json()
            assert str(seq) not in c.get(f"/api/v1/games/{gid}/audio", headers=sp).json()
            assert c.get(url, headers=gm).status_code == 200
            assert c.get(url, headers=sp).status_code == 404
            assert c.get(url, params={"token": created["spectator_token"]}).status_code == 404
        _finish(c, created)
        # 终局公开：匿名全量
        assert c.get(url).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_api_voice.py -q`
Expected: FAIL（`narration_config` 未知参数 / 响应无 `narration` 字段）

- [ ] **Step 3: Schemas**

`app/schemas/games.py`：`CreateGameRequest` 加 `narration: bool = False  # GM 旁白配音（issue #110）：需 voice=True`；`CreateGameResponse` 加 `narration: bool  # 实际生效的旁白开关（issue #110）`。

- [ ] **Step 4: Registry**

`GameHandle.__init__` 增 `narration_enabled: bool = False` → `self.narration_enabled = narration_enabled`。`create()` 增 `narration: bool = False`，构造 handle 时传 `narration_enabled=narration`。`start()` 里 `GameRunner(...)` 增 `narration_enabled=handle.voice_enabled and handle.narration_enabled`。

- [ ] **Step 5: REST 建局**

`rest.py` 建局处，在 TTS 探测之前：

```python
    if req.narration and not req.voice:
        raise HTTPException(status_code=400, detail="旁白需要先开启语音播报")
```

`games.create(..., narration=req.narration)`；响应 `narration=handle.narration_enabled`。

- [ ] **Step 6: REST 音频端点过滤**

在 `audio_manifest_endpoint` 前加辅助函数：

```python
def _audio_visible_seqs(games: GameRegistry, game_id: str, info: TokenInfo | None) -> set[int] | None:
    """直播期间按 token 视角可见的事件 seq 集合；None = 不过滤（终局 / GM / 未开局）。
    与 /replay 口径一致：终局后全量；HOST 按观众处理。"""
    if info is None or info.kind == "GM":
        return None
    try:
        handle = games.get(game_id)
    except LookupError:
        return None
    if not handle.started or handle.live_state().phase == Phase.GAME_OVER:
        return None
    viewer: Any = info.seat if info.kind == "PLAYER" else "SPECTATOR"
    events = games.store.load_events(game_id)
    return {e.seq for e in visible_events(handle.live_state(), events, viewer)}
```

`audio_manifest_endpoint`：`_finished_or_handle(...)` 之后：

```python
    manifest = sink.manifest(game_id)
    allowed = _audio_visible_seqs(games, game_id, info)
    if allowed is None:
        return manifest
    return {k: v for k, v in manifest.items() if int(k) in allowed}
```

`audio_part_endpoint`：`sink.path_for` 之前：

```python
    allowed = _audio_visible_seqs(games, game_id, info)
    if allowed is not None and seq not in allowed:
        raise HTTPException(status_code=404, detail="音频不存在")
```

确认 `rest.py` 顶部已 import `visible_events`（`from app.engine.observation import build_observation, visible_events` 类似行已存在；没有就加）。两端点 docstring 加一句「直播期间按视角过滤（issue #110）」。

- [ ] **Step 7: main.py 装配**

`create_app` 签名增 `narration_config: NarrationConfig | None = None`；在构造 sink 前：

```python
    # GM 旁白（issue #110）：配置校验 fail-loud；句子缓存全局共用
    narration = narration_config or NarrationConfig.from_env(data_dir=Path("data"))
    app.state.speech_audio = SpeechAudioSink(
        audio_dir or Path("data/audio"),
        tts,
        app.state.voice_anchors,
        narration=narration,
        narration_cache=NarrationCache(narration.cache_dir),
    )
```

import：`from app.runtime.narration import NarrationCache, NarrationConfig`。

- [ ] **Step 8: 文档**

`.env.example` 发言配音块末尾追加：

```
# GM 旁白（issue #110）：建局勾「旁白」后，阶段切换 / 结算 / 竞选投票结果等用固定声线播报
#AGENTHOWL_NARRATOR_VOICE=uncle_fu     # 预置 speaker：vivian | serena | uncle_fu | dylan | eric
#AGENTHOWL_NARRATION_EVENTS=           # 逗号分隔的事件类型白名单；空=默认（阶段切换、结算、竞选/投票结果、死亡、终局）
#AGENTHOWL_NARRATION_DIR=data/narration # 旁白句子缓存（跨对局共用）
```

`README.md` 的「后端环境变量」条目后追加一条：「**GM 旁白**（issue #110）：建局页「语音播报」下勾「旁白」；`AGENTHOWL_NARRATOR_VOICE` 换声线、`AGENTHOWL_NARRATION_EVENTS` 调白名单；句子按哈希缓存在 `data/narration/`，第二局起几乎零 TTS 调用。」

- [ ] **Step 9: Run tests**

Run: `cd backend && uv run pytest --ignore=tests/test_api_e2e.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全部 PASS（含 litellm 守卫）。

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/games.py backend/app/runtime/registry.py backend/app/api/rest.py backend/app/main.py backend/tests/test_api_voice.py .env.example README.md
git commit -m "feat(api): 建局 narration 开关、旁白装配、音频端点直播期间按视角过滤 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: 前端——`kind` 透传、GM 聚光牌、建局「旁白」子开关

**Files:**
- Modify: `frontend/src/api/ws.ts:33-45,148-158`
- Modify: `frontend/src/store/voice.ts:20-26`（`AudioQueueItem.kind?`）
- Modify: `frontend/src/api/rest.ts:70-85`
- Modify: `frontend/src/pages/GamePage.tsx:360-367,465`
- Modify: `frontend/src/components/SpeakerSpotlight/SpeakerSpotlight.tsx`、`SpeakerSpotlight.module.css`
- Modify: `frontend/src/pages/Lobby.tsx:56,117,185-195`
- Test: `frontend/src/components/SpeakerSpotlight/SpeakerSpotlight.test.tsx`、`frontend/src/pages/GamePage.test.tsx`

**Interfaces:**
- Consumes: 帧字段 `kind`（可缺省）；`CreateGameRequest.narration`、`CreateGameResponse.narration`。
- Produces: `SpeakerSpotlightProps.seat: number | "GM" | null`；GamePage 内 `voicingActor: number | "GM" | null`。

- [ ] **Step 1: Write the failing tests**

`SpeakerSpotlight.test.tsx` 追加：

```tsx
  it("seat 为 GM 时显示旁白占位（issue #110）", () => {
    useVoice.setState({ playing: { seq: 1, part: 0 } });
    render(<SpeakerSpotlight state={state} seat="GM" avatars={{}} />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "GM 旁白中");
    expect(screen.getByText("GM")).toBeInTheDocument();
    expect(screen.getByText("旁白中 🔊")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });
```

`GamePage.test.tsx` 追加一个 describe（需 import `useVoice`）：

```tsx
describe("GamePage 聚光牌跟随配音（issue #110）", () => {
  it("voicingSeq 指向无 actor 的事件时显示 GM；找不到事件时退回轮到谁", async () => {
    stubFetch(() => jsonResponse(200, meta));
    vi.stubGlobal("WebSocket", vi.fn());
    render(<GamePage gameId="g_x" replay />);
    await screen.findByText(new RegExp(`已结束 · ${events.length} 条事件`));
    const narrated = events.find((e) => e.actor_seat === null && e.type === "VOTE_STARTED");
    expect(narrated).toBeDefined();
    act(() => useVoice.setState({ voicingSeq: narrated!.seq, playing: { seq: narrated!.seq, part: 0 } }));
    expect(await screen.findByText("旁白中 🔊")).toBeInTheDocument();
    act(() => useVoice.setState({ voicingSeq: 999999, playing: null }));
    expect(screen.queryByText("旁白中 🔊")).toBeNull();
    useVoice.getState().clear();
  });
});
```

（`act` 从 `@testing-library/react` import，`useVoice` 从 `../store/voice`。）

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/SpeakerSpotlight src/pages/GamePage.test.tsx`
Expected: FAIL（类型 / 文案不存在）

- [ ] **Step 3: `ws.ts` / `voice.ts` / `rest.ts`**

`WsFrame` 增 `kind?: "speech" | "narration"`；`enqueue({... duration: frame.duration ?? 0, kind: frame.kind ?? "speech" })`。头注释第 5 行加「`kind` 为 `speech|narration`（issue #110，缺省按 speech）」。

`voice.ts` `AudioQueueItem` 增 `kind?: "speech" | "narration";`（仅透传，不参与逻辑）。

`rest.ts` `CreateGameRequest` 增 `/** GM 旁白（issue #110）；需 voice=true，否则后端 400。 */ narration?: boolean;`，`CreateGameResponse` 增 `narration: boolean;`。

- [ ] **Step 4: `SpeakerSpotlight.tsx`**

```tsx
export interface SpeakerSpotlightProps {
  state: GameState;
  /** 当前发言座位；"GM" 表示旁白正在播（issue #110）；null 时不渲染。 */
  seat: number | "GM" | null;
  avatars: Record<number, string>;
}

export default function SpeakerSpotlight({ state, seat, avatars }: SpeakerSpotlightProps): JSX.Element | null {
  const voicePlaying = useVoice((s) => s.playing);
  if (seat === null) return null;
  if (seat === "GM") {
    return (
      <div className={styles.root} role="status" aria-label="GM 旁白中">
        <div className={`${styles.ring} ${styles.gmRing}`}>
          <span className={styles.gmAvatar} aria-hidden="true">🎙️</span>
        </div>
        <div className={styles.text}>
          <span className={styles.name}>GM</span>
          <span className={styles.tag}>{voicePlaying !== null ? "旁白中 🔊" : "旁白中"}</span>
        </div>
      </div>
    );
  }
  // …原座位分支不变…
}
```

CSS 追加：

```css
.gmRing {
  border-color: var(--color-divider);
}

.gmAvatar {
  width: 128px;
  height: 128px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 56px;
  background: color-mix(in srgb, var(--color-divider) 60%, var(--color-surface));
}
```

（项目里没有 `--color-text-muted`：上面两处都改用 `var(--color-divider)`。）

- [ ] **Step 5: `GamePage.tsx`**

```tsx
  const voicingSeq = useVoice((s) => s.voicingSeq);
  // 座位 / "GM"（事件无 actor_seat，如阶段切换的旁白，issue #110）/ null（找不到事件 → 退回轮到谁）
  const voicingActor = useMemo<number | "GM" | null>(() => {
    if (voicingSeq === null) return null;
    const e = events.find((x) => x.seq === voicingSeq);
    if (e === undefined) return null;
    return e.actor_seat ?? "GM";
  }, [events, voicingSeq]);
  const speaking = typeof voicingActor === "number" ? voicingActor : voicingActor === null ? turnSpeaker : null;
  const spotlight: number | "GM" | null = voicingActor === "GM" ? "GM" : speaking;
```

`<SpeakerSpotlight state={view} seat={spotlight} avatars={avatars} />`；`SeatCircle` 的 `speaking={speaking}` 不变（旁白时为 null → 无座位高亮）。

- [ ] **Step 6: `Lobby.tsx`**

`const [narration, setNarration] = useState(false);`；body 增 `narration: voice && narration`；语音开关下方加：

```tsx
          {tts.enabled && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, marginLeft: 20 }}>
              <input
                type="checkbox"
                checked={voice && narration}
                disabled={!tts.ok || !voice}
                onChange={(e) => setNarration(e.target.checked)}
              />
              旁白（GM 播报阶段 / 结算 / 投票结果）
            </label>
          )}
```

- [ ] **Step 7: Run checks**

Run: `cd frontend && npm run check`
Expected: lint + tsc + vitest 全绿（含新用例）。

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): 旁白帧 kind 透传、聚光牌 GM 占位、建局「旁白」子开关 (issue #110)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: 全量门禁 + 真机冒烟

**Files:** 无新改动（除非门禁发现问题）。

- [ ] **Step 1: 后端全量**

Run: `cd backend && uv run pytest --ignore=tests/test_api_e2e.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: 全绿。

- [ ] **Step 2: 前端全量**

Run: `cd frontend && npm run check && npm run build`
Expected: 全绿。

- [ ] **Step 3: 真机冒烟（宿主机 TTS 已起：`make tts`）**

```bash
cd /Users/gangtao/Code/gang/AgentHowl && docker compose up -d --build
export no_proxy=127.0.0.1,localhost
curl -s http://localhost:8000/api/v1/tts/status
# 建一局 voice+narration，用 gm_token 连 WS 看到 kind=narration 的帧；
# 对局结束后 ls backend/data/narration/*.wav 非空；再建一局，后端日志里旁白句子不再新合成
```

把冒烟结果（旁白帧数、缓存文件数、第二局新增合成数）记进 ledger；发现的非本期问题按惯例开 issue。

- [ ] **Step 4: 推 PR**

```bash
git push -u origin feat/gm-narration
gh pr create --title "feat: GM 旁白 / 游戏进程统一配音 (issue #110)" --body "$(cat <<'EOF'
## 概要
- 新增 `app/runtime/narration.py`：事件→口播句子模板（默认白名单：阶段切换、结算、竞选/投票结果、死亡、终局）、句子级 WAV 缓存 `data/narration/`（跨局复用）、`NarrationConfig.from_env`
- `SpeechAudioSink` 抽出 `_emit` 内核，新增 `narrate()`；帧带 `kind`
- `ConnectionManager.broadcast_frame(frame, event)` 随来源事件经 `visible_events` 按视角过滤；音频清单 / 文件端点直播期间同样过滤
- runner `_voice(events)` 按 seq 顺序统一调度发言与旁白
- 建局 `narration` 开关（需 `voice`）；前端聚光牌 GM 占位、「旁白」子开关
- 环境变量：`AGENTHOWL_NARRATOR_VOICE` / `AGENTHOWL_NARRATION_EVENTS` / `AGENTHOWL_NARRATION_DIR`

Spec：`docs/superpowers/specs/2026-10-15-gm-narration-design.md`

## 验证
- 后端 pytest / ruff / mypy / litellm 守卫；前端 `npm run check` + build
- 真机：见 PR 评论

Closes #110

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
