# Agent 档案评估（issue #60）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从已落盘的事件日志离线统计每个 Agent 档案（按内容指纹聚合）的多局胜率与行为指标；提供 A/B bench 驱动器把两份档案交错放进同一批对局并输出差异列。

**Architecture:** 新包 `app/eval/`（`fingerprint.py` / `metrics.py` / `report.py`，纯函数零 IO：输入 `GameMeta` + `list[Event]`，用引擎 `reduce` 维护回放状态做归因）；runtime 在 `GameRunner._commit` 的既有「meta 充实」点把端口 `last_skills_used` 写进首条事件 `meta["skills"]`；`app/cli/bench.py` 驱动 N 局（交错 + 逐局轮转分配 A/B 座位）落 `JsonFileEventStore` 并调用分析器，`--report-only` 只分析。引擎零改动。

**Tech Stack:** Python 3.11、Pydantic v2、asyncio、pytest（零 IO 零 mock；文件用 `tmp_path`）、uv、ruff（行宽 100，中文宽 2）、mypy strict。

**Spec:** `docs/superpowers/specs/2026-09-21-agent-eval-design.md`

## Global Constraints

- 引擎（`app/engine/`）零改动；引擎不读 `Event.meta`。
- `app/eval/` 纯函数零 IO；只依赖 pydantic、`app.engine`、`app.agent.profile/personality`、`app.store.event_store`（模型与 `initial_state`）。
- `app/runtime`、`app/api`、`app/cli`、`app/eval` 不得在模块级 import `app.agent.agent_player` / `app.agent.llm_client`（litellm 惰性加载；`tests/test_agent_profile.py::test_importing_registry_does_not_load_litellm` 守卫）。
- 档案身份 = 内容指纹（`model_dump(mode="json", exclude={"name","memory_id"})` 规范化 JSON 的 sha1 前 10 位）；标签只是显示。
- 比率 = 分子和 / 分母和；分母 0 → `None`（报告 `N/A`）。`meta.agents` 无该座位 → 指纹 `None` → 「随机 bot」组。
- `meta["skills"]` 只写在一次提交的首条事件；超时代打不写。
- `_wire_game` 新参数 `store` / `game_id` 默认值保持现状行为（`InMemoryEventStore()`、`"cli"`）。
- 中文注释、英文标识符；ruff 行宽 100（中文宽 2；超宽行按 ruff 折行）；测试零 IO 零 mock。
- 每任务结束前全绿（`backend/`）：`uv run pytest -q -x --ignore=tests/test_api_e2e.py`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`。

---

### Task 1: 指纹 + 指标分析器（`app/eval/fingerprint.py`、`app/eval/metrics.py`）

**Files:**
- Create: `backend/app/eval/__init__.py`（空 docstring 一行）、`backend/app/eval/fingerprint.py`、`backend/app/eval/metrics.py`
- Test: `backend/tests/test_eval_fingerprint.py`、`backend/tests/test_eval_metrics.py`（新）

**Interfaces:**
- Produces: `profile_fingerprint(profile) -> str`、`profile_summary(profile) -> str`；`SeatStats`、`GameAnalysis`、`RoleStats`、`ProfileStats`（含 `RATE_FIELDS`、`rates()`）、`analyze_game(meta, events) -> GameAnalysis`、`collect_profiles(metas) -> dict[str, AgentProfile]`、`aggregate(analyses, profiles=None) -> dict[str | None, ProfileStats]`、`diff(a, b) -> dict[str, float | None]`、`RANDOM_BOT_LABEL = "随机 bot"`。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_eval_fingerprint.py`：

```python
"""档案指纹与摘要（issue #60）。"""

from app.agent.personality import PersonalityPreset, PersonalitySpec
from app.agent.profile import AgentProfile
from app.eval.fingerprint import profile_fingerprint, profile_summary


def test_fingerprint_ignores_name_and_memory_id_but_not_content() -> None:
    base = AgentProfile(model="ollama/a", skills=("logic-chain", "side-taking"))
    same = AgentProfile(model="ollama/a", skills=("logic-chain", "side-taking"), name="老张", memory_id="x")
    assert profile_fingerprint(base) == profile_fingerprint(same)
    assert len(profile_fingerprint(base)) == 10
    assert profile_fingerprint(base) != profile_fingerprint(base.model_copy(update={"temperature": 0.7}))
    assert profile_fingerprint(base) != profile_fingerprint(
        AgentProfile(model="ollama/a", skills=("side-taking", "logic-chain"))
    )
    with_p = base.model_copy(update={"personality": PersonalitySpec(traits={"多疑": 0.9})})
    assert profile_fingerprint(base) != profile_fingerprint(with_p)


def test_profile_summary_format() -> None:
    assert profile_summary(AgentProfile(model="ollama/a")) == "ollama/a"
    rich = AgentProfile(
        model="ollama/b",
        skills=("logic-chain",),
        personality=PersonalitySpec(preset=PersonalityPreset(system="MBTI", value="enfp")),
        temperature=0.7,
        thinking=True,
    )
    assert profile_summary(rich) == "ollama/b · 技能 logic-chain · 性格 ENFP · T=0.7 · thinking"
```

`backend/tests/test_eval_metrics.py`：

```python
"""离线指标分析器（issue #60）：随机 bot 局的一致性 + 手工事件序列的口径——零 IO。"""

from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.engine.config import Faction, RoleType, build_preset, faction_of
from app.engine.engine import create_game
from app.engine.events import (
    Event,
    EventType,
    GameOverPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SheriffCandidacyPayload,
    SheriffElectedPayload,
    SheriffWithdrewPayload,
    Visibility,
    VoteCastPayload,
    VoteStartedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfKillRevotePayload,
)
from app.eval.fingerprint import profile_fingerprint
from app.eval.metrics import (
    RANDOM_BOT_LABEL,
    ProfileStats,
    aggregate,
    analyze_game,
    collect_profiles,
    diff,
)
from app.store.event_store import GameMeta, SeatName


def _meta(final, game_id: str = "g1", agents: dict[str, AgentProfile] | None = None) -> GameMeta:
    roster = tuple(SeatName(seat=p.seat, display_name=p.display_name) for p in final.players)
    return GameMeta(game_id=game_id, config=final.config, roster=roster, agents=agents or {})


def test_random_bot_game_consistency() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, "g1")
    a = analyze_game(_meta(final), events)
    assert a.winner == final.winner and a.rounds == final.round and a.sheriff_enabled
    assert set(a.roles) == set(range(9)) and all(fp is None for fp in a.fingerprints.values())
    for p in final.players:
        st = a.seats[p.seat]
        assert st.wins == (1 if final.winner is not None and p.faction == final.winner else 0)
        assert st.alive_at_end == (1 if p.alive else 0)
        assert 0 <= st.rounds_alive <= final.round
        assert st.exiled + st.night_killed <= 1  # 一人至多死一次于这两种原因
        if p.alive:
            assert st.exiled == st.night_killed == 0 and st.rounds_alive == final.round
    assert sum(st.speeches for st in a.seats.values()) == sum(
        1 for e in events if e.type is EventType.PLAYER_SPOKE
    )
    wolves = [s for s, r in a.roles.items() if r == RoleType.WEREWOLF]
    assert all(a.seats[w].wolf_nights >= 1 for w in wolves)
    assert all(a.seats[s].wolf_nights == 0 for s in a.seats if s not in wolves)


def test_manual_sequence_votes_wolves_speech_sheriff_skills() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, _ = run_game(cfg, "g1")
    roles = {s: (RoleType.WEREWOLF if s in (0, 1, 2) else RoleType.VILLAGER) for s in range(9)}
    head = create_game(cfg, "g1")
    # 用 ROLES_ASSIGNED 之后的真实 head 无法改角色，这里直接把角色事件替换掉
    events = [e for e in head.events if e.type is not EventType.ROLES_ASSIGNED]
    from app.engine.events import RolesAssignedPayload

    events.append(
        Event(
            seq=len(events) + 1, game_id="g1", ts=0.0, type=EventType.ROLES_ASSIGNED, actor_seat=None,
            payload=RolesAssignedPayload(assignments=tuple(roles.items())),
            visibility=Visibility.GM_ONLY,
        )
    )
    tail: list[tuple[EventType, object, int | None, dict[str, str]]] = [
        (EventType.ROUND_STARTED, RoundStartedPayload(round=1), None, {}),
        (EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=0, target=5), 0, {"skills": "wolf-team-kill"}),
        (EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=1, target=None), 1, {}),
        (EventType.WOLF_KILL_REVOTE, WolfKillRevotePayload(round_no=1, proposals=((0, 5), (1, None), (2, 5))), None, {}),
        (EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=0, target=5), 0, {}),
        (EventType.WOLF_KILL_DECIDED, WolfKillDecidedPayload(target=None), None, {}),
        (EventType.PLAYER_SPOKE, PlayerSpokePayload(content="我是预言家", claim_role=RoleType.SEER, badge_flow=(3, 4)), 4, {"skills": "seer-badge-flow,logic-chain"}),
        (EventType.PLAYER_SPOKE, PlayerSpokePayload(content="过"), 4, {}),
        (EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=4, running=True), 4, {}),
        (EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=5, running=False), 5, {}),
        (EventType.SHERIFF_WITHDREW, SheriffWithdrewPayload(seat=4), 4, {}),
        (EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=6), None, {}),
        (EventType.VOTE_STARTED, VoteStartedPayload(candidates=tuple(range(9)), tie_round=0), None, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=3, target=7), 3, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=4, target=8), 4, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=5, target=None), 5, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=6, target=2), 6, {}),
        (EventType.VOTE_STARTED, VoteStartedPayload(candidates=(7, 8), tie_round=1), None, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=3, target=8), 3, {}),  # 首轮 7∈PK 候选，改投 8 → 改票
        (EventType.VOTE_CAST, VoteCastPayload(voter=4, target=8), 4, {}),  # 首轮 8，坚持 → 不改
        (EventType.VOTE_CAST, VoteCastPayload(voter=6, target=7), 6, {}),  # 首轮 2∉PK 候选 → 不计入分母
        (EventType.PLAYER_EXILED, PlayerExiledPayload(seat=7), None, {}),
        (EventType.GAME_OVER, GameOverPayload(winner="WOLF"), None, {}),
    ]
    base = len(events)
    for i, (etype, payload, actor, meta) in enumerate(tail, start=base + 1):
        events.append(
            Event(seq=i, game_id="g1", ts=0.0, type=etype, actor_seat=actor, payload=payload,
                  visibility=Visibility.PUBLIC, meta=meta)
        )
    a = analyze_game(_meta(final, agents={"0": AgentProfile(model="m")}), events)

    s0, s1, s2, s3, s4, s5, s6, s7 = (a.seats[i] for i in range(8))
    # 狼队：三狼各 1 狼夜；0 号提案 2 次、无空刀；1 号 1 次空刀提案；重提与决定空刀记到三狼
    assert (s0.wolf_nights, s1.wolf_nights, s2.wolf_nights) == (1, 1, 1)
    assert (s0.proposals, s0.no_kill_proposals, s1.proposals, s1.no_kill_proposals) == (2, 0, 1, 1)
    assert all(st.revote_nights == 1 and st.decided_no_kill == 1 for st in (s0, s1, s2))
    assert s3.wolf_nights == 0 and s3.proposals == 0
    # 发言 / 警长
    assert (s4.speeches, s4.speech_chars, s4.claims, s4.badge_flows) == (2, 6, 1, 1)
    assert (s4.candidacies, s4.withdrew, s5.candidacies, s6.elected) == (1, 1, 0, 1)
    # 投票
    assert (s3.votes, s3.pk_votes_eligible, s3.vote_changes) == (2, 1, 1)
    assert (s4.votes, s4.pk_votes_eligible, s4.vote_changes) == (2, 1, 0)
    assert (s5.votes, s5.abstains) == (1, 1)
    assert (s6.votes, s6.pk_votes_eligible, s6.vote_changes) == (2, 0, 0)
    # 放逐与胜负
    assert s7.exiled == 1 and s7.rounds_alive == 1 and s7.alive_at_end == 0
    assert s0.wins == 1 and s3.wins == 0
    # 技能：按事件计次、逐名计数
    assert s0.skills_assembled == 1 and s0.skill_counts == {"wolf-team-kill": 1}
    assert s4.skills_assembled == 1 and s4.skill_counts == {"seer-badge-flow": 1, "logic-chain": 1}
    # 指纹：只有 0 号有档案
    assert a.fingerprints[0] == profile_fingerprint(AgentProfile(model="m")) and a.fingerprints[1] is None


def test_aggregate_by_fingerprint_role_and_diff() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, "g1")
    pa, pb = AgentProfile(model="a"), AgentProfile(model="b", temperature=0.9)
    agents1 = {str(s): (pa if s % 2 == 0 else pb) for s in range(9)}
    agents2 = {str(s): (pb if s % 2 == 0 else pa) for s in range(9)}
    m1, m2 = _meta(final, "g1", agents1), _meta(final, "g2", agents2)
    profiles = collect_profiles([m1, m2])
    assert set(profiles) == {profile_fingerprint(pa), profile_fingerprint(pb)}
    stats = aggregate([analyze_game(m1, events), analyze_game(m2, events)], profiles)
    sa, sb = stats[profile_fingerprint(pa)], stats[profile_fingerprint(pb)]
    assert sa.games == 9 and sb.games == 9 and sa.summary == "a"
    assert sa.games == sa.wolf_games + sa.good_games
    assert sum(r.games for r in sa.by_role.values()) == 9
    assert sa.sheriff_games == 9 and sa.win_rate is not None
    assert None not in stats  # 全部座位都有档案 → 无随机 bot 组
    d = diff(sa, sb)
    assert set(d) == set(ProfileStats.RATE_FIELDS)
    assert d["win_rate"] is not None
    # 分母为 0 → None 传播
    empty = ProfileStats(summary="x")
    assert empty.win_rate is None and diff(empty, sa)["win_rate"] is None
    # 随机 bot 组
    bare = aggregate([analyze_game(_meta(final), events)])
    assert set(bare) == {None} and bare[None].summary == RANDOM_BOT_LABEL and bare[None].games == 9
```

- [ ] **Step 2: 跑测试确认失败**

Run（`backend/`）：`uv run pytest tests/test_eval_fingerprint.py tests/test_eval_metrics.py -q`
Expected: `ModuleNotFoundError: app.eval`。

- [ ] **Step 3: 实现**

`backend/app/eval/__init__.py`：
```python
"""离线档案评估（issue #60）：纯函数，输入事件日志与 GameMeta，输出按档案指纹聚合的指标。"""
```

`backend/app/eval/fingerprint.py`：
```python
"""档案指纹与摘要（issue #60）：按内容聚合多局统计；name / memory_id 不参与。"""

from __future__ import annotations

import hashlib
import json

from app.agent.personality import personality_summary
from app.agent.profile import AgentProfile

_DEFAULT_TEMPERATURE = 0.3


def profile_fingerprint(profile: AgentProfile) -> str:
    """去 name / memory_id 后规范化 JSON 的 sha1 前 10 位：内容相同即同一配置。"""
    body = profile.model_dump(mode="json", exclude={"name", "memory_id"})
    canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:10]


def profile_summary(profile: AgentProfile) -> str:
    """报告显示名：模型 + 技能 + 性格 + 非默认温度 + thinking。"""
    parts = [profile.model]
    if profile.skills:
        parts.append("技能 " + ",".join(profile.skills))
    if profile.personality is not None:
        parts.append(f"性格 {personality_summary(profile.personality)}")
    if profile.temperature != _DEFAULT_TEMPERATURE:
        parts.append(f"T={profile.temperature}")
    if profile.thinking:
        parts.append("thinking")
    return " · ".join(parts)
```

`backend/app/eval/metrics.py`：
```python
"""离线指标分析器（issue #60）：逐事件回放归因，按档案指纹汇总。

analyze_game 用引擎 reduce 维护回放状态，只为知道「当前轮次 / 在世狼 / 投票轮」——引擎零改动。
比率 = 分子和 / 分母和；分母 0 → None（报告显示 N/A）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel

from app.agent.profile import AgentProfile
from app.engine.config import Faction, RoleType, faction_of
from app.engine.events import Event, EventType, reduce
from app.eval.fingerprint import profile_fingerprint, profile_summary
from app.store.event_store import GameMeta, initial_state

RANDOM_BOT_LABEL = "随机 bot"


class SeatStats(BaseModel):
    """一个座位一局的计数（全部为可加计数，汇总时逐字段求和）。"""

    wins: int = 0
    alive_at_end: int = 0
    rounds_alive: int = 0
    exiled: int = 0
    night_killed: int = 0
    speeches: int = 0
    speech_chars: int = 0
    claims: int = 0
    badge_flows: int = 0
    candidacies: int = 0
    elected: int = 0
    withdrew: int = 0
    votes: int = 0
    abstains: int = 0
    pk_votes_eligible: int = 0
    vote_changes: int = 0
    wolf_nights: int = 0
    proposals: int = 0
    no_kill_proposals: int = 0
    revote_nights: int = 0
    decided_no_kill: int = 0
    skills_assembled: int = 0
    skill_counts: dict[str, int] = {}

    def add(self, other: SeatStats) -> None:
        for name in self.model_fields:
            if name == "skill_counts":
                for k, v in other.skill_counts.items():
                    self.skill_counts[k] = self.skill_counts.get(k, 0) + v
            else:
                setattr(self, name, getattr(self, name) + getattr(other, name))


class GameAnalysis(BaseModel):
    game_id: str
    winner: str | None
    rounds: int
    sheriff_enabled: bool
    roles: dict[int, RoleType]
    fingerprints: dict[int, str | None]
    seats: dict[int, SeatStats]


def _die(seats: dict[int, SeatStats], dead: set[int], seat: int, round_no: int) -> None:
    if seat not in dead:
        dead.add(seat)
        seats[seat].rounds_alive = round_no


def analyze_game(meta: GameMeta, events: Sequence[Event]) -> GameAnalysis:  # noqa: PLR0912, PLR0915
    state = initial_state(meta)
    n = len(meta.roster)
    seats = {s: SeatStats() for s in range(n)}
    roles: dict[int, RoleType] = {}
    dead: set[int] = set()
    first_targets: dict[int, int | None] = {}  # 本轮首轮投票目标（VOTE_STARTED tie_round=0 重置）
    pk_candidates: tuple[int, ...] | None = None  # 非 None = 正处于 PK 轮
    night_counted = revote_counted = decided_counted = False
    winner: str | None = None
    for e in events:
        p = e.payload
        t = e.type
        # 归因用「应用前」的状态：当前轮次、在世狼
        alive_wolves = [pl.seat for pl in state.players if pl.alive and pl.faction == Faction.WOLF]
        if t is EventType.ROLES_ASSIGNED:
            roles = dict(p.assignments)  # type: ignore[attr-defined]
        elif t is EventType.ROUND_STARTED:
            night_counted = revote_counted = decided_counted = False
        elif t is EventType.WOLF_KILL_PROPOSED:
            if not night_counted:
                for w in alive_wolves:
                    seats[w].wolf_nights += 1
                night_counted = True
            st = seats[p.wolf_seat]  # type: ignore[attr-defined]
            st.proposals += 1
            if p.target is None:  # type: ignore[attr-defined]
                st.no_kill_proposals += 1
        elif t is EventType.WOLF_KILL_REVOTE:
            if not revote_counted:
                for w in alive_wolves:
                    seats[w].revote_nights += 1
                revote_counted = True
        elif t is EventType.WOLF_KILL_DECIDED:
            if p.target is None and not decided_counted:  # type: ignore[attr-defined]
                for w in alive_wolves:
                    seats[w].decided_no_kill += 1
                decided_counted = True
        elif t is EventType.NIGHT_RESOLVED:
            for s in p.deaths:  # type: ignore[attr-defined]
                _die(seats, dead, s, state.round)
                seats[s].night_killed += 1
        elif t is EventType.PLAYER_EXILED:
            if p.seat is not None:  # type: ignore[attr-defined]
                _die(seats, dead, p.seat, state.round)  # type: ignore[attr-defined]
                seats[p.seat].exiled += 1  # type: ignore[attr-defined]
        elif t is EventType.HUNTER_SHOT:
            if p.victim is not None:  # type: ignore[attr-defined]
                _die(seats, dead, p.victim, state.round)  # type: ignore[attr-defined]
        elif t is EventType.WOLF_SELF_DESTRUCT:
            _die(seats, dead, p.seat, state.round)  # type: ignore[attr-defined]
        elif t is EventType.PLAYER_SPOKE and e.actor_seat is not None:
            st = seats[e.actor_seat]
            st.speeches += 1
            st.speech_chars += len(p.content)  # type: ignore[attr-defined]
            if p.claim_role is not None:  # type: ignore[attr-defined]
                st.claims += 1
            if p.badge_flow:  # type: ignore[attr-defined]
                st.badge_flows += 1
        elif t is EventType.SHERIFF_CANDIDACY:
            if p.running:  # type: ignore[attr-defined]
                seats[p.seat].candidacies += 1  # type: ignore[attr-defined]
        elif t is EventType.SHERIFF_ELECTED:
            seats[p.seat].elected += 1  # type: ignore[attr-defined]
        elif t is EventType.SHERIFF_WITHDREW:
            seats[p.seat].withdrew += 1  # type: ignore[attr-defined]
        elif t is EventType.VOTE_STARTED:
            if p.tie_round == 0:  # type: ignore[attr-defined]
                first_targets = {}
                pk_candidates = None
            else:
                pk_candidates = tuple(p.candidates)  # type: ignore[attr-defined]
        elif t is EventType.VOTE_CAST:
            voter, target = p.voter, p.target  # type: ignore[attr-defined]
            st = seats[voter]
            st.votes += 1
            if target is None:
                st.abstains += 1
            if pk_candidates is None:
                first_targets[voter] = target
            else:
                first = first_targets.get(voter)
                if first is not None and first in pk_candidates:
                    st.pk_votes_eligible += 1
                    if target != first:
                        st.vote_changes += 1
        elif t is EventType.GAME_OVER:
            winner = p.winner  # type: ignore[attr-defined]
        skills = e.meta.get("skills")
        if skills and e.actor_seat is not None:
            st = seats[e.actor_seat]
            st.skills_assembled += 1
            for name in skills.split(","):
                if name:
                    st.skill_counts[name] = st.skill_counts.get(name, 0) + 1
        state = reduce(state, e)
    for s, st in seats.items():
        if s not in dead:
            st.alive_at_end = 1
            st.rounds_alive = state.round
        role = roles.get(s)
        if role is not None and winner is not None and faction_of(role) == winner:
            st.wins = 1
    fps = {
        s: (profile_fingerprint(meta.agents[str(s)]) if str(s) in meta.agents else None)
        for s in range(n)
    }
    return GameAnalysis(
        game_id=meta.game_id,
        winner=winner,
        rounds=state.round,
        sheriff_enabled=meta.config.sheriff.enabled,
        roles=roles,
        fingerprints=fps,
        seats=seats,
    )


class RoleStats(BaseModel):
    games: int = 0
    wins: int = 0


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


class ProfileStats(BaseModel):
    """一个档案（指纹）跨局汇总；比率为属性，分母 0 → None。"""

    RATE_FIELDS: tuple[str, ...] = (
        "win_rate", "wolf_win_rate", "good_win_rate", "survive_rate", "avg_rounds_alive",
        "exiled_rate", "night_killed_rate", "avg_speech_chars", "claim_rate", "badge_flow_rate",
        "candidacy_rate", "abstain_rate", "vote_change_rate", "no_kill_proposal_rate",
        "revote_night_rate", "decided_no_kill_rate",
    )

    summary: str = ""
    games: int = 0
    wins: int = 0
    wolf_games: int = 0
    wolf_wins: int = 0
    good_games: int = 0
    good_wins: int = 0
    sheriff_games: int = 0
    by_role: dict[RoleType, RoleStats] = {}
    totals: SeatStats = SeatStats()

    @property
    def win_rate(self) -> float | None:
        return _rate(self.wins, self.games)

    @property
    def wolf_win_rate(self) -> float | None:
        return _rate(self.wolf_wins, self.wolf_games)

    @property
    def good_win_rate(self) -> float | None:
        return _rate(self.good_wins, self.good_games)

    @property
    def survive_rate(self) -> float | None:
        return _rate(self.totals.alive_at_end, self.games)

    @property
    def avg_rounds_alive(self) -> float | None:
        return _rate(self.totals.rounds_alive, self.games)

    @property
    def exiled_rate(self) -> float | None:
        return _rate(self.totals.exiled, self.games)

    @property
    def night_killed_rate(self) -> float | None:
        return _rate(self.totals.night_killed, self.games)

    @property
    def avg_speech_chars(self) -> float | None:
        return _rate(self.totals.speech_chars, self.totals.speeches)

    @property
    def claim_rate(self) -> float | None:
        return _rate(self.totals.claims, self.totals.speeches)

    @property
    def badge_flow_rate(self) -> float | None:
        return _rate(self.totals.badge_flows, self.totals.speeches)

    @property
    def candidacy_rate(self) -> float | None:
        return _rate(self.totals.candidacies, self.sheriff_games)

    @property
    def abstain_rate(self) -> float | None:
        return _rate(self.totals.abstains, self.totals.votes)

    @property
    def vote_change_rate(self) -> float | None:
        return _rate(self.totals.vote_changes, self.totals.pk_votes_eligible)

    @property
    def no_kill_proposal_rate(self) -> float | None:
        return _rate(self.totals.no_kill_proposals, self.totals.proposals)

    @property
    def revote_night_rate(self) -> float | None:
        return _rate(self.totals.revote_nights, self.totals.wolf_nights)

    @property
    def decided_no_kill_rate(self) -> float | None:
        return _rate(self.totals.decided_no_kill, self.totals.wolf_nights)

    def rates(self) -> dict[str, float | None]:
        return {name: getattr(self, name) for name in self.RATE_FIELDS}


def collect_profiles(metas: Iterable[GameMeta]) -> dict[str, AgentProfile]:
    """各局 meta.agents 里出现过的档案，按指纹去重（供 aggregate 填 summary）。"""
    out: dict[str, AgentProfile] = {}
    for m in metas:
        for p in m.agents.values():
            out.setdefault(profile_fingerprint(p), p)
    return out


def aggregate(
    analyses: Iterable[GameAnalysis], profiles: Mapping[str, AgentProfile] | None = None
) -> dict[str | None, ProfileStats]:
    profiles = profiles or {}
    out: dict[str | None, ProfileStats] = {}
    for a in analyses:
        for seat, st in a.seats.items():
            fp = a.fingerprints.get(seat)
            if fp not in out:
                if fp is None:
                    summary = RANDOM_BOT_LABEL
                else:
                    prof = profiles.get(fp)
                    summary = profile_summary(prof) if prof is not None else fp
                out[fp] = ProfileStats(summary=summary)
            ps = out[fp]
            ps.games += 1
            ps.wins += st.wins
            role = a.roles.get(seat)
            if role is not None:
                if faction_of(role) == Faction.WOLF:
                    ps.wolf_games += 1
                    ps.wolf_wins += st.wins
                else:
                    ps.good_games += 1
                    ps.good_wins += st.wins
                rs = ps.by_role.setdefault(role, RoleStats())
                rs.games += 1
                rs.wins += st.wins
            if a.sheriff_enabled:
                ps.sheriff_games += 1
            ps.totals.add(st)
    return out


def diff(a: ProfileStats, b: ProfileStats) -> dict[str, float | None]:
    """a − b 的全部比率；任一为 None → None。"""
    ra, rb = a.rates(), b.rates()
    return {
        k: (ra[k] - rb[k] if ra[k] is not None and rb[k] is not None else None)  # type: ignore[operator]
        for k in ProfileStats.RATE_FIELDS
    }
```

mypy 说明：payload 按 `e.type` 分支访问字段，用 `# type: ignore[attr-defined]` 与仓库里 `render_event` 的做法一致；若仓库 `render_event` 用的是 `isinstance(p, XxxPayload)` 分支，改成同样写法（更干净，也去掉 ignore）——实现者以 `app/cli/render.py::render_event` 的现有风格为准。`ProfileStats.RATE_FIELDS` 若被 pydantic 当作字段报错，改为 `ClassVar[tuple[str, ...]]`（`from typing import ClassVar`）。`totals: SeatStats = SeatStats()` 若 pydantic 共享默认实例，改为 `Field(default_factory=SeatStats)`；`by_role`、`skill_counts` 同理用 `default_factory`。

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_eval_fingerprint.py tests/test_eval_metrics.py -q` → PASS；四条命令全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval backend/tests/test_eval_fingerprint.py backend/tests/test_eval_metrics.py
git commit -m "feat(eval): 档案指纹与离线指标分析器——逐事件回放归因、按指纹×角色汇总、A/B 差值 (issue #60)"
```

---

### Task 2: runtime 写入事件 `meta["skills"]`

**Files:**
- Modify: `backend/app/runtime/game_runner.py`（`_drive_seat`、`_commit`）
- Test: `backend/tests/test_game_runner.py`、`backend/tests/test_event_store.py`（追加）

**Interfaces:**
- Produces: `GameRunner._commit(events, timed_out=False, skills: Sequence[str] = ())`；成功行动的首条事件 `meta["skills"] = "a,b"`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_game_runner.py` 末尾：

```python
class _SkilledBot(BotPlayerPort):
    """带 last_skills_used 的随机 bot：模拟 AgentPlayerPort 的技能装配属性。"""

    last_skills_used: tuple[str, ...] = ("logic-chain", "side-taking")


async def test_commit_writes_skills_meta_on_first_event_only() -> None:
    """issue #60：一次提交的首条事件带 meta['skills']，同批后续事件不带；不传则不写。"""
    store = InMemoryEventStore()
    runner = _make_runner(store)
    res = create_game(runner._config, "g1")
    store.create_game(
        GameMeta(
            game_id="g1",
            config=runner._config,
            roster=tuple(SeatName(seat=p.seat, display_name=p.display_name) for p in res.state.players),
        )
    )
    runner._state = res.state
    await runner._commit(list(res.events), skills=("logic-chain", "side-taking"))
    events = store.load_events("g1")
    assert len(events) >= 2
    assert events[0].meta["skills"] == "logic-chain,side-taking"
    assert all("skills" not in e.meta for e in events[1:])
    assert all("wall_ts" in e.meta for e in events)


async def test_full_game_skilled_ports_tag_first_event_per_action_and_not_timeouts() -> None:
    store = InMemoryEventStore()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 5})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(store=store, config=cfg, game_id="g1", roster=lobby.roster(), ports=ports)
    for seat in range(cfg.num_players):
        ports[seat] = _SkilledBot(state_provider=lambda: runner.state)
    await runner.run()
    events = store.load_events("g1")
    tagged = [e for e in events if "skills" in e.meta]
    assert tagged and all(e.meta["skills"] == "logic-chain,side-taking" for e in tagged)
    assert all("timeout" not in e.meta for e in tagged)
    # 同一次提交（同 wall_ts 的连续事件）只有首条带标记
    for prev, cur in zip(events, events[1:], strict=False):
        if cur.meta.get("wall_ts") == prev.meta.get("wall_ts"):
            assert "skills" not in cur.meta
    # 生命周期头（非行动产生）不带标记
    assert all("skills" not in e.meta for e in events[:2])
```

（`GameMeta`、`SeatName`、`GameLobby`、`GameRunner` 已在该测试文件 import 列表中；若缺 `GameMeta`/`SeatName` 则补进 `from app.store.event_store import (...)`。）

追加到 `backend/tests/test_event_store.py` 末尾：

```python
def test_event_meta_skills_roundtrips_jsonl(tmp_path: Path) -> None:
    meta, _final, events = _run_fixture_game()
    tagged = events[5].model_copy(update={"meta": {**events[5].meta, "skills": "a,b"}})
    store = JsonFileEventStore(tmp_path)
    store.create_game(meta)
    for e in events[:5]:
        store.append("g1", e)
    store.append("g1", tagged)
    assert JsonFileEventStore(tmp_path).load_events("g1")[5].meta["skills"] == "a,b"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_game_runner.py -q -k skills` → `TypeError: _commit() got an unexpected keyword argument 'skills'` 与超时标记断言失败。

- [ ] **Step 3: 实现**

`backend/app/runtime/game_runner.py`：
- `_drive_seat` 成功路径：
  ```python
            self._state = res.state
            # 技能装配记录（issue #60）：端口若暴露 last_skills_used，写进本次提交的首条事件 meta
            skills = tuple(getattr(self._ports[seat], "last_skills_used", ()))
            await self._commit(res.events, skills=skills)
  ```
- `_commit`：
  ```python
    async def _commit(
        self, events: list[Event], timed_out: bool = False, skills: Sequence[str] = ()
    ) -> None:
        """meta 充实 → 落库 → 广播，同序。runtime 对事件的唯一合法改写点。"""
        wall_ts = datetime.now(UTC).isoformat()
        enriched: list[Event] = []
        for i, e in enumerate(events):
            meta = {**e.meta, "wall_ts": wall_ts}
            if timed_out:
                meta["timeout"] = "true"
            if skills and i == 0:  # 只标首条：一次行动记一次装配（issue #60）
                meta["skills"] = ",".join(skills)
            enriched.append(e.model_copy(update={"meta": meta}))
  ```
  其余（落库、广播）不变。`Sequence` 已在该文件 import（`from collections.abc import Mapping, Sequence`；若无则补）。

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_game_runner.py tests/test_event_store.py -q` → PASS；四条命令全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/app/runtime/game_runner.py backend/tests/test_game_runner.py backend/tests/test_event_store.py
git commit -m "feat(runtime): 行动首条事件 meta['skills'] 记录技能装配，供离线评估统计 (issue #60)"
```

---

### Task 3: 报告（`app/eval/report.py`）

**Files:**
- Create: `backend/app/eval/report.py`
- Test: `backend/tests/test_eval_report.py`（新）

**Interfaces:**
- Consumes: Task 1 `ProfileStats`、`diff`、`RANDOM_BOT_LABEL`。
- Produces: `COLUMNS`、`render_table(stats, labels) -> str`、`to_json(stats, labels) -> dict[str, object]`、`ordered(stats, labels) -> list[tuple[str | None, ProfileStats]]`。

- [ ] **Step 1: 写失败测试**

```python
"""评估报告（issue #60）：表格对齐、N/A、Δ 行、JSON 结构。"""

import json

from app.engine.config import RoleType
from app.eval.metrics import RANDOM_BOT_LABEL, ProfileStats, RoleStats, SeatStats
from app.eval.report import ordered, render_table, to_json


def _stats(games: int, wins: int, **totals: int) -> ProfileStats:
    ps = ProfileStats(summary="m", games=games, wins=wins, sheriff_games=games)
    ps.totals = SeatStats(**totals)
    ps.by_role[RoleType.SEER] = RoleStats(games=1, wins=1)
    return ps


def test_render_table_columns_na_and_delta_row() -> None:
    a = _stats(4, 3, alive_at_end=2, rounds_alive=10, speeches=8, speech_chars=80, claims=2, votes=6, pk_votes_eligible=2, vote_changes=1)
    b = _stats(4, 1, alive_at_end=1, rounds_alive=6, speeches=4, speech_chars=20, votes=4)
    bots = ProfileStats(summary=RANDOM_BOT_LABEL, games=8, wins=4)
    text = render_table({"fa": a, "fb": b, None: bots}, {"fa": "A", "fb": "B"})
    lines = text.splitlines()
    assert lines[0].startswith("档案") and "胜率" in lines[0] and "改票率" in lines[0]
    assert lines[1].startswith("A ") and "75.0%" in lines[1] and "10.0" in lines[1]  # 胜率、发言均长
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
    assert profiles[0]["rates"]["win_rate"] == 0.5 and profiles[0]["by_role"]["SEER"] == {"games": 1, "wins": 1}
    assert profiles[2]["fingerprint"] is None and profiles[2]["rates"]["win_rate"] == 0.0
    assert doc["diff"]["win_rate"] == -0.5 and doc["diff_labels"] == ["A", "B"]
    assert to_json({"fa": a}, {})["diff"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_eval_report.py -q` → `ModuleNotFoundError: app.eval.report`。

- [ ] **Step 3: 实现 `backend/app/eval/report.py`**

```python
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


def _display(fp: str | None, ps: ProfileStats, labels: Mapping[str | None, str]) -> str:
    if fp is None:
        return RANDOM_BOT_LABEL
    return labels.get(fp, ps.summary)


def render_table(stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]) -> str:
    rows = ordered(stats, labels)
    header = ["档案", *(h for h, _ in COLUMNS)]
    body = [
        [_display(fp, ps), *(_fmt(name, _value(ps, name)) for _, name in COLUMNS)]
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
    return "\n".join("  ".join(_pad(c, widths[i]) for i, c in enumerate(r)).rstrip() for r in table)


def to_json(stats: Mapping[str | None, ProfileStats], labels: Mapping[str | None, str]) -> dict[str, object]:
    rows = ordered(stats, labels)
    profiles: list[dict[str, object]] = []
    for fp, ps in rows:
        profiles.append(
            {
                "label": _display(fp, ps, labels),
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
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `uv run pytest tests/test_eval_report.py -q` → PASS；四条命令全绿。

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/report.py backend/tests/test_eval_report.py
git commit -m "feat(eval): 评估报告——东亚宽度对齐表格、N/A、Δ(A−B) 行与 JSON (issue #60)"
```

---

### Task 4: bench 驱动（`app/cli/bench.py`）+ `_wire_game(store=, game_id=)` + Makefile

**Files:**
- Create: `backend/app/cli/bench.py`
- Modify: `backend/app/cli/play.py`（`_wire_game`）、`Makefile`
- Test: `backend/tests/test_cli_bench.py`（新）、`backend/tests/test_cli_play_watch.py`（追加）

**Interfaces:**
- Consumes: Task 1/3 全部；`_wire_game`、`load_agent_profiles`、`validate_profiles`、`SkillLibrary`。
- Produces: `assign_seats(num_players, game_index, a, b) -> AgentProfiles`、`label_map(a, b, label_a, label_b) -> dict[str | None, str]`、`async run_bench(*, preset, seed, games, a, b, library, store, out=print) -> None`、`report(store, labels) -> tuple[str, dict[str, object]]`、`main(argv=None)`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_cli_play_watch.py` 末尾：

```python
def test_wire_game_accepts_store_and_game_id(tmp_path) -> None:
    from app.store.event_store import JsonFileEventStore

    config = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    store = JsonFileEventStore(tmp_path)
    runner, _c, _p = _wire_game(config, store=store, game_id="bench-3")
    asyncio.run(runner.run())
    assert store.list_games() == ["bench-3"]
    default_runner, _c2, _p2 = _wire_game(config)
    assert default_runner._game_id == "cli"
```

新建 `backend/tests/test_cli_bench.py`：

```python
"""A/B bench 驱动（issue #60）：座位分配、标签、零 LLM 端到端、--report-only、--json、参数错误。"""

import json

import pytest

from app.agent.profile import AgentProfile
from app.cli.bench import assign_seats, label_map, main
from app.eval.fingerprint import profile_fingerprint
from app.store.event_store import JsonFileEventStore


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
    assert labels[profile_fingerprint(b["0"])] == "乙/0" and labels[profile_fingerprint(b["*"])] == "乙/*"
    assert label_map(a, None, "A", "B") == {None: "随机 bot", profile_fingerprint(a["*"]): "A"}


def _table(out: str) -> str:
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("档案"))
    return "\n".join(lines[start:])


def test_main_zero_llm_writes_logs_reports_and_report_only_matches(tmp_path, capsys) -> None:
    out_dir = tmp_path / "run"
    js = tmp_path / "r.json"
    main(["--games", "2", "--seed", "3", "--preset", "std_9_kill_side", "--out", str(out_dir), "--json", str(js)])
    out = capsys.readouterr().out
    assert sorted(p.name for p in out_dir.iterdir()) == ["bench-3.jsonl", "bench-4.jsonl"]
    assert "seed=3 winner=" in out and "seed=4 winner=" in out
    table = _table(out)
    assert "随机 bot" in table and "Δ(" not in table
    row = next(line for line in table.splitlines() if line.startswith("随机 bot"))
    assert row.split()[1] == "18"  # 2 局 × 9 座位
    doc = json.loads(js.read_text(encoding="utf-8"))
    assert doc["profiles"][0]["label"] == "随机 bot" and doc["profiles"][0]["games"] == 18
    assert doc["diff"] is None
    main(["--report-only", str(out_dir)])
    assert _table(capsys.readouterr().out) == table


def test_main_ab_with_bot_ports_records_profiles_and_delta(tmp_path, capsys, monkeypatch) -> None:
    """A/B 端到端（零 LLM）：用随机 bot 端口顶替 Agent 端口，验证 meta.agents → 指纹 → 标签 → Δ 行。"""
    import app.agent.agent_player as ap
    from app.runtime.player_port import BotPlayerPort

    holder: dict[str, object] = {}

    def fake_build_agent_port(seat, game_config, profile, *, library=None, experience=None, opponents=None):
        return BotPlayerPort(state_provider=lambda: holder["runner"].state)  # type: ignore[attr-defined]

    monkeypatch.setattr(ap, "build_agent_port", fake_build_agent_port)
    import app.cli.play as play_mod

    orig = play_mod._wire_game

    def wire(config, **kw):
        out = orig(config, **kw)
        holder["runner"] = out[0]
        return out

    monkeypatch.setattr(play_mod, "_wire_game", wire)
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text('seats:\n  "*": {model: ollama/a, skills: [logic-chain]}\n', encoding="utf-8")
    b.write_text('seats:\n  "*": {model: ollama/b, personality: {traits: {从众: 0.9}}}\n', encoding="utf-8")
    out_dir = tmp_path / "ab"
    main(["--games", "2", "--seed", "3", "--out", str(out_dir), "--agents", str(a), "--agents-b", str(b)])
    table = _table(capsys.readouterr().out)
    lines = table.splitlines()
    assert lines[1].startswith("A ") and lines[2].startswith("B ") and lines[3].startswith("Δ(A−B)")
    assert lines[1].split()[1] == "9" and lines[2].split()[1] == "9"  # 2 局各 9 座位交错 → 各 9
    store = JsonFileEventStore(out_dir)
    m3, m4 = store.load_meta("bench-3"), store.load_meta("bench-4")
    assert m3.agents["0"].model == "ollama/a" and m3.agents["1"].model == "ollama/b"
    assert m4.agents["0"].model == "ollama/b" and m4.agents["1"].model == "ollama/a"


def test_main_argument_errors(tmp_path, capsys) -> None:
    b = tmp_path / "b.yaml"
    b.write_text('seats:\n  "*": {model: m}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--games", "1", "--agents-b", str(b), "--out", str(tmp_path / "x")])
    assert "--agents-b" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--report-only", str(tmp_path), "--games", "2"])
    assert "--report-only" in capsys.readouterr().err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli_bench.py tests/test_cli_play_watch.py -q -k "bench or store_and_game_id"` → `ModuleNotFoundError: app.cli.bench`；`_wire_game` 未知参数。

- [ ] **Step 3: 实现**

`backend/app/cli/play.py` `_wire_game`：签名加 `store: EventStore | None = None, game_id: str = "cli"`（`from app.store.event_store import EventStore` 放模块级 import；`InMemoryEventStore` 仍在函数内 import）；`GameRunner(store=store if store is not None else InMemoryEventStore(), ..., game_id=game_id, ...)`。docstring 补「store/game_id 供 bench 落盘（issue #60）」。

`backend/app/cli/bench.py`：

```python
"""A/B bench 驱动（issue #60）：N 局交错分配两份档案、落盘事件日志、离线汇总指标。

零 LLM 路径：不给 --agents 即全随机 bot（验收与测试用）。不做跨局记忆、不跑 postgame。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.agent.profile import AgentProfile, AgentProfiles, profile_for, validate_profiles
from app.agent.skills import BUILTIN_SKILLS_DIR, SkillError, SkillLibrary, default_library
from app.cli.play import _wire_game, load_agent_profiles
from app.engine.config import build_preset
from app.eval.fingerprint import profile_fingerprint
from app.eval.metrics import RANDOM_BOT_LABEL, aggregate, analyze_game, collect_profiles
from app.eval.report import render_table, to_json
from app.store.event_store import EventStore, JsonFileEventStore

Printer = Callable[[str], None]


def assign_seats(
    num_players: int, game_index: int, a: AgentProfiles, b: AgentProfiles | None
) -> AgentProfiles:
    """第 game_index 局的座位档案：交错 + 逐局轮转；解析为 None 的座位留给随机 bot。"""
    out: AgentProfiles = {}
    for seat in range(num_players):
        chosen = a if b is None or (seat + game_index) % 2 == 0 else b
        p = profile_for(chosen, seat)
        if p is not None:
            out[str(seat)] = p
    return out


def label_map(
    a: AgentProfiles, b: AgentProfiles | None, label_a: str, label_b: str
) -> dict[str | None, str]:
    """指纹 → 显示标签；一份档案集含多个不同档案时用「标签/座位键」区分。"""
    labels: dict[str | None, str] = {None: RANDOM_BOT_LABEL}
    for agents, label in ((a, label_a), (b, label_b)):
        if not agents:
            continue
        keyed: dict[str, str] = {}
        for key, p in agents.items():
            keyed.setdefault(profile_fingerprint(p), key)
        for fp, key in keyed.items():
            labels[fp] = label if len(keyed) == 1 else f"{label}/{key}"
    return labels


async def run_bench(
    *,
    preset: str,
    seed: int,
    games: int,
    a: AgentProfiles,
    b: AgentProfiles | None,
    library: SkillLibrary,
    store: EventStore,
    out: Printer = print,
) -> None:
    base = build_preset(preset)
    for i in range(games):
        s = seed + i
        config = base.model_copy(update={"seed": s})
        agents = assign_seats(config.num_players, i, a, b)
        runner, _conns, _ports = _wire_game(
            config, agents=agents, library=library, store=store, game_id=f"bench-{s}"
        )
        state = await runner.run()
        out(f"seed={s} winner={state.winner or 'DRAW'} rounds={state.round}")


def report(store: EventStore, labels: dict[str | None, str]) -> tuple[str, dict[str, object]]:
    """对 store 里全部对局做分析；返回 (表格文本, JSON 文档)。"""
    ids = store.list_games()
    metas = [store.load_meta(g) for g in ids]
    analyses = [analyze_game(m, store.load_events(m.game_id)) for m in metas]
    stats = aggregate(analyses, collect_profiles(metas))
    return render_table(stats, labels), to_json(stats, labels)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli.bench", description="AgentHowl 档案 A/B bench")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--preset", default="std_9_kill_side")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", type=load_agent_profiles, default=None, help="档案 A（YAML）")
    parser.add_argument("--agents-b", type=load_agent_profiles, default=None, help="档案 B（YAML）")
    parser.add_argument("--label-a", default="A")
    parser.add_argument("--label-b", default="B")
    parser.add_argument("--skills-dir", default=None)
    parser.add_argument("--out", default=None, help="事件日志目录（默认 data/bench/<时间戳>）")
    parser.add_argument("--json", default=None, help="把报告 JSON 写到该路径")
    parser.add_argument("--report-only", default=None, metavar="DIR", help="只分析已有日志目录")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if args.report_only is not None:
        if any(x in (argv or []) for x in ("--games", "--agents", "--agents-b", "--out")):
            parser.error("--report-only 不能与 --games/--agents/--agents-b/--out 同时给出")
        store: EventStore = JsonFileEventStore(Path(args.report_only))
        labels: dict[str | None, str] = {None: RANDOM_BOT_LABEL}
        table, doc = report(store, labels)
        print(table)
        if args.json:
            Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    if args.agents_b is not None and args.agents is None:
        parser.error("--agents-b 须与 --agents 同时给出")
    a: AgentProfiles = args.agents or {}
    b: AgentProfiles | None = args.agents_b
    try:
        library = (
            SkillLibrary.load([BUILTIN_SKILLS_DIR, Path(args.skills_dir)])
            if args.skills_dir
            else default_library()
        )
        n = build_preset(args.preset).num_players
        validate_profiles(a, n, library)
        if b is not None:
            validate_profiles(b, n, library)
    except (ValueError, SkillError) as exc:
        parser.error(str(exc))
    out_dir = Path(args.out) if args.out else Path("data/bench") / datetime.now().strftime("%Y%m%d-%H%M%S")
    store = JsonFileEventStore(out_dir)
    asyncio.run(
        run_bench(
            preset=args.preset, seed=args.seed, games=args.games, a=a, b=b, library=library, store=store
        )
    )
    labels = label_map(a, b, args.label_a, args.label_b)
    table, doc = report(store, labels)
    print(f"日志目录：{out_dir}")
    print(table)
    if args.json:
        Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
```

说明：`--report-only` 的互斥检查用 `argv` 里是否出现这些 flag 判断（`argv is None` 时用 `sys.argv[1:]`——实现时把 `argv = sys.argv[1:] if argv is None else argv` 放在 `parse_args` 前）。`_wire_game` 会在函数内 `from app.agent.agent_player import build_agent_port`——bench 模块级不 import 它，litellm 守卫不受影响。`JsonFileExperienceStore`/postgame 均不涉及。

`Makefile`：在 `sim` 目标之后加

```make
.PHONY: bench
bench: ## 档案 A/B bench（例：make bench GAMES=20 AGENTS=a.yaml AGENTS_B=b.yaml；不给 AGENTS 为随机 bot）
	cd $(BACKEND) && $(UV) python -m app.cli.bench --games $(GAMES) $(if $(AGENTS),--agents $(AGENTS),) $(if $(AGENTS_B),--agents-b $(AGENTS_B),) $(ARGS)
```

并在变量区加 `AGENTS_B ?=`（与 `AGENTS` 同一处）。

- [ ] **Step 4: 跑测试确认通过 + 全量（含 E2E）**

Run: `uv run pytest tests/test_cli_bench.py tests/test_cli_play_watch.py -q` → PASS。
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 全绿。

- [ ] **Step 5: 真机看一眼**（`backend/`）

```bash
uv run python -m app.cli.bench --games 3 --seed 3 --out /tmp/agenthowl-bench 2>&1 | tail -6
uv run python -m app.cli.bench --report-only /tmp/agenthowl-bench | head -3
```
Expected：3 行 `seed=… winner=… rounds=…`，`日志目录：…`，表头 `档案  局数  胜率 …`，一行 `随机 bot  27  …`；`--report-only` 同表。

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli/bench.py backend/app/cli/play.py Makefile backend/tests/test_cli_bench.py backend/tests/test_cli_play_watch.py
git commit -m "feat(cli): 档案 A/B bench 驱动——交错分配、落盘、离线报告；_wire_game 支持 store/game_id (issue #60)"
```

---

### Task 5: env 门控冒烟 + README / PRD

**Files:**
- Modify: `backend/tests/test_agent_bench.py`（追加）、`README.md`（新小节「档案评估 / Bench」+ Makefile 目标说明）、`docs/specs/requirements.md`（§4.4 之后补「档案评估」一段；§5.2 提一句 `/meta` 与事件 `meta.skills`）

- [ ] **Step 1: 冒烟测试**

追加到 `backend/tests/test_agent_bench.py` 末尾（沿用文件 `pytestmark` env 门控）：

```python
async def test_ab_bench_smoke(tmp_path) -> None:
    """A（多疑 0.9）vs B（从众 0.9）各跑 1 局，打印指标表；不断言方向。"""
    from app.agent.personality import PersonalitySpec
    from app.agent.profile import AgentProfile
    from app.agent.skills import default_library
    from app.cli.bench import label_map, report, run_bench
    from app.store.event_store import JsonFileEventStore

    assert SMOKE_MODEL is not None
    a = {"*": AgentProfile(model=SMOKE_MODEL, personality=PersonalitySpec(traits={"多疑": 0.9}))}
    b = {"*": AgentProfile(model=SMOKE_MODEL, personality=PersonalitySpec(traits={"从众": 0.9}))}
    store = JsonFileEventStore(tmp_path / "bench")
    await run_bench(
        preset="std_9_kill_side", seed=3, games=2, a=a, b=b, library=default_library(), store=store
    )
    table, _doc = report(store, label_map(a, b, "多疑", "从众"))
    print("\n[ab-bench]\n" + table)
    assert "Δ(多疑−从众)" in table
```

- [ ] **Step 2: 文档**

`README.md`：在「跨局记忆」小节之后新增「档案评估 / Bench」（`###`，风格对齐相邻小节）：用途（回答「配置有没有用」）；命令（`make bench GAMES=20 AGENTS=a.yaml AGENTS_B=b.yaml`、`python -m app.cli.bench --report-only data/bench/<run>`、`--json`）；座位分配规则（交错 + 逐局轮转）；聚合身份 = 内容指纹（`name` / `memory_id` 不参与）；指标列表（逐列一句口径，与规格 §2 一致）；随机 bot 组；技能次数来自事件 `meta.skills`（任何来源的日志都能统计）；不做跨局记忆；一段示例表格输出（用 Step 5 真机输出）。Makefile 目标表加 `bench`。

`docs/specs/requirements.md`：§4.4.2 之后（或 §4.4 末尾）补「**档案评估（issue #60）**：离线分析器（`app/eval/`）从事件日志按档案内容指纹汇总胜率与行为指标（存活 / 放逐、发言长度与声称、上警、改票、狼队空刀与重提、技能装配次数）；`app/cli/bench.py` 交错分配两份档案跑 N 局并给出 Δ 列。行动首条事件 `meta.skills` 由 runtime 写入，引擎不感知。」§5.2 事件日志说明处补一句 `meta.skills`。

- [ ] **Step 3: 全量验证**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app` → 全绿（冒烟用例 skip）。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_agent_bench.py README.md docs/specs/requirements.md
git commit -m "test(bench): A/B 冒烟；README/PRD 档案评估说明 (issue #60)"
```

---

## Self-Review

- **Spec 覆盖**：§1 判据→T4（零 LLM、A/B、`--report-only`）、T1（指纹）、T2（`meta.skills`）；§2 指标→T1；§3 分析器→T1；§4 runtime→T2；§5 bench→T4；§6 报告→T3；§7 测试→T1–T5；§8 不在范围无任务。
- **占位符扫描**：无 TBD/TODO；每个代码步都给了完整代码。
- **类型一致性**：`analyze_game(meta, events)`、`aggregate(analyses, profiles)`、`collect_profiles(metas)`、`diff(a, b)`、`ProfileStats.RATE_FIELDS/rates()`、`render_table(stats, labels)`、`to_json(stats, labels)`、`ordered(stats, labels)`、`assign_seats(n, i, a, b)`、`label_map(a, b, la, lb)`、`run_bench(...)`、`report(store, labels)`、`_wire_game(store=, game_id=)`、`_commit(events, timed_out, skills)` 在各任务间一致。
- **import 方向**：`app/eval` 依赖 pydantic、engine、agent.profile/personality、store（模型）；`app/cli/bench.py` 依赖 eval、cli.play、store；均不在模块级 import `agent_player`。
