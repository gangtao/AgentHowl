"""agent 记忆（issue #31 Task 4）：K=15 新鲜窗口、打分 top-N、私有分区隔离、惰性反思。"""

from pydantic import BaseModel

from app.agent.memory import (
    PREDEFINED_QUESTIONS,
    AgentMemory,
    ReflectionQA,
    ReflectionResult,
    _render,
)
from app.engine.config import Faction
from app.engine.events import (
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
    Event,
    EventType,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    Visibility,
)
from app.engine.phases import ElectionStage
from tests.llm_helpers import ScriptedLLMClient


def _ev(seq: int, etype: EventType, payload, *, actor: int | None = None) -> Event:
    return Event(
        seq=seq,
        game_id="g_m",
        ts=float(seq),
        type=etype,
        actor_seat=actor,
        payload=payload,
        visibility=Visibility.PUBLIC,
    )


def _spoke(seq: int, seat: int, content: str) -> Event:
    return _ev(seq, EventType.PLAYER_SPOKE, PlayerSpokePayload(content=content), actor=seat)


def test_round_tracking_and_scoring() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest(
        [
            _ev(
                2,
                EventType.SEER_CHECKED,
                SeerCheckedPayload(target=3, result=Faction.WOLF),
                actor=0,
            ),
            _ev(3, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))),
            _spoke(4, 2, "平安夜"),
        ]
    )
    by_kind = {e.kind: e for e in mem.entries}
    assert by_kind[EventType.SEER_CHECKED.value].score == 5  # 自身查验最高分
    assert by_kind[EventType.DEATH_ANNOUNCED.value].score == 4
    assert by_kind[EventType.PLAYER_SPOKE.value].score == 1  # 无声称的普通发言
    assert all(e.round == 1 for e in mem.entries)


def test_claim_speech_scores_3() -> None:
    mem = AgentMemory(seat=0)
    from app.engine.config import RoleType

    mem.ingest(
        [
            _ev(
                1,
                EventType.PLAYER_SPOKE,
                PlayerSpokePayload(content="我是预言家", claim_role=RoleType.SEER),
                actor=4,
            )
        ]
    )
    assert mem.entries[0].score == 3


def test_freshness_window_plus_topn() -> None:
    mem = AgentMemory(seat=0, freshness_k=3, informative_top_n=2)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    # 一条高分旧事件 + 一串低分发言把它挤出新鲜窗口
    mem.ingest([_ev(2, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(7,)))])
    mem.ingest([_spoke(10 + i, 1, f"话{i}") for i in range(6)])
    ctx = mem.build_context()
    assert "话5" in ctx and "话4" in ctx and "话3" in ctx  # 最近 K=3
    assert "7" in ctx  # 高分死亡事件经 top-N 补充保留
    assert "话0" not in ctx  # 低分旧发言被裁剪


def test_render_election_stage_changed_special_cases_speech_order() -> None:
    # F4（终审修复）：ELECTION_STAGE_CHANGED 不该落回通用回退，把 speech_order=None 渲染成噪音
    with_order = _ev(
        1,
        EventType.ELECTION_STAGE_CHANGED,
        ElectionStageChangedPayload(stage=ElectionStage.SPEECH, speech_order=(3, 1)),
    )
    text = _render(with_order)
    assert "[3, 1]" in text
    assert "None" not in text

    without_order = _ev(
        2,
        EventType.ELECTION_STAGE_CHANGED,
        ElectionStageChangedPayload(stage=ElectionStage.WITHDRAW),
    )
    text2 = _render(without_order)
    assert "speech_order" not in text2
    assert "None" not in text2

    ended = _ev(
        3, EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=ElectionStage.NONE)
    )
    assert "结束" in _render(ended)


def test_night_private_partition_never_in_context() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.note_night_private("私谋：今晚刀 3 号，明天悍跳预言家", round=1)
    assert "私谋" not in mem.build_context()
    assert "私谋" in mem.night_private_context()


async def test_reflection_folds_summary_and_questions() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest([_spoke(2, 1, "第一轮发言")])
    mem.ingest([_ev(3, EventType.ROUND_STARTED, RoundStartedPayload(round=2))])
    assert mem.rounds_needing_reflection() == [1]

    seen_prompts: list[str] = []

    def script(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        seen_prompts.append(user)
        assert rm is ReflectionResult
        return ReflectionResult(
            summary="首轮平稳",
            qa=[ReflectionQA(question=q, answer="a") for q in PREDEFINED_QUESTIONS],
        )

    await mem.reflect(ScriptedLLMClient(script), model="scripted")
    assert mem.rounds_needing_reflection() == []
    assert "首轮平稳" in mem.build_context()
    # L=5 预置问句进了反思 prompt
    assert all(q in seen_prompts[0] for q in PREDEFINED_QUESTIONS)


async def test_reflection_failure_degrades() -> None:
    mem = AgentMemory(seat=0)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    mem.ingest([_spoke(2, 1, "x")])
    mem.ingest([_ev(3, EventType.ROUND_STARTED, RoundStartedPayload(round=2))])

    def boom(rm: type[BaseModel], system: str, user: str) -> BaseModel:
        raise RuntimeError("llm down")

    await mem.reflect(ScriptedLLMClient(boom), model="scripted")
    # 失败：标记已尝试（不重试烧预算），原始条目保留
    assert mem.rounds_needing_reflection() == []
    assert "x" in mem.build_context()


async def test_on_events_is_pure_ingest() -> None:
    mem = AgentMemory(seat=0)
    await mem.on_events([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    assert len(mem.entries) == 1


def test_render_and_score_wolf_kill_revote() -> None:
    from app.agent.memory import _render, _score
    from app.engine.events import WolfKillRevotePayload

    ev = Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.WOLF_KILL_REVOTE,
        actor_seat=None,
        payload=WolfKillRevotePayload(round_no=1, proposals=((0, 8), (1, None), (2, 8))),
        visibility=Visibility.WOLVES,
    )
    out = _render(ev)
    assert "第 1 轮" in out and "0 号→8 号" in out and "1 号→空刀" in out
    assert "None" not in out and "proposals" not in out
    assert _score(ev, seat=0) == 2


def test_campaign_speeches_score_2_and_outrank_candidacy_noise() -> None:
    """issue #52：上警发言 / 警上 PK 发言得 2 分，「不上警」声明得 0 分；
    竞选发言不会被一串上警声明挤出后置投票人的上下文。"""
    from app.engine.events import (
        ElectionStageChangedPayload,
        PhaseChangedPayload,
        SheriffCandidacyPayload,
    )
    from app.engine.phases import Phase

    mem = AgentMemory(seat=0, freshness_k=3, informative_top_n=2)
    mem.ingest([_ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1))])
    # 竞选声明：上警 1 分、不上警 0 分
    mem.ingest(
        [
            _ev(2, EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=2, running=True)),
            _ev(3, EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=3, running=False)),
        ]
    )
    assert [e.score for e in mem.entries[1:]] == [1, 0]
    # 上警发言子阶段：普通发言 2 分
    mem.ingest(
        [
            _ev(
                4,
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.SPEECH, speech_order=(2, 5)),
            ),
            _spoke(5, 2, "我是警上发言"),
        ]
    )
    assert mem.entries[-1].score == 2
    # 退水子阶段 / 白天发言：回到 1 分
    mem.ingest(
        [
            _ev(
                6,
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.WITHDRAW),
            ),
            _ev(7, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH)),
            _spoke(8, 4, "白天发言"),
        ]
    )
    assert mem.entries[-1].score == 1
    # 警上 PK：PK 发言 2 分
    mem.ingest(
        [
            _ev(9, EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_PK)),
            _spoke(10, 5, "PK发言"),
        ]
    )
    assert mem.entries[-1].score == 2
    # 窗口：一串「不上警」把竞选发言推出新鲜窗口后，top-N 仍把竞选发言捞回来
    mem.ingest(
        [
            _ev(
                20 + i,
                EventType.SHERIFF_CANDIDACY,
                SheriffCandidacyPayload(seat=6 + i, running=False),
            )
            for i in range(5)
        ]
    )
    ctx = mem.build_context()
    assert "我是警上发言" in ctx and "PK发言" in ctx
    assert "白天发言" not in ctx  # 1 分普通发言被 2 分竞选发言挤掉


def test_ingest_degrades_on_render_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """issue #42：单条事件渲染抛错不能让 on_events 抛出（否则 ConnectionManager 摘除订阅、
    该座位记忆自此断流），降级成占位条目。"""
    import app.agent.memory as memory_mod

    real_render = memory_mod._render

    def flaky(e):  # type: ignore[no-untyped-def]
        if e.type == EventType.DEATH_ANNOUNCED:
            raise RuntimeError("boom")
        return real_render(e)

    monkeypatch.setattr(memory_mod, "_render", flaky)
    mem = AgentMemory(seat=0)
    mem.ingest(
        [
            _ev(1, EventType.ROUND_STARTED, RoundStartedPayload(round=1)),
            _ev(2, EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))),
            _spoke(3, 2, "照常"),
        ]
    )
    assert [e.seq for e in mem.entries] == [1, 2, 3]
    assert "记录失败" in mem.entries[1].text
    assert "照常" in mem.build_context()


async def test_reflect_max_rounds_limits_work() -> None:
    mem = AgentMemory(seat=0)
    for r in (1, 2, 3):
        mem.ingest([_ev(r, EventType.ROUND_STARTED, RoundStartedPayload(round=r))])
    calls: list[str] = []

    def script(rm, system, user):  # type: ignore[no-untyped-def]
        calls.append(user)
        return ReflectionResult(summary="s", qa=[])

    await mem.reflect(ScriptedLLMClient(script), "m", max_rounds=1)
    assert len(calls) == 1 and mem.rounds_needing_reflection() == [2]
    await mem.reflect(ScriptedLLMClient(script), "m")
    assert len(calls) == 2 and mem.rounds_needing_reflection() == []
