"""agent 记忆（issue #31 Task 4）：K=15 新鲜窗口、打分 top-N、私有分区隔离、惰性反思。"""

from pydantic import BaseModel

from app.agent.memory import (
    PREDEFINED_QUESTIONS,
    AgentMemory,
    ReflectionQA,
    ReflectionResult,
)
from app.engine.config import Faction
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    Visibility,
)
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
