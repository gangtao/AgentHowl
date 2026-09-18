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
