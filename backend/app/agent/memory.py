"""agent 记忆（issue #31，PRD §4.4.2 初版"三件套"）。

Freshness（最近 K 条原文）+ Informativeness（规则打分 top-N 补充）+ 每轮反思
（惰性触发，Completeness L=5 预置 + M=2 自问并入同一次调用）。不引入向量检索。
night_private 分区单列：狼人夜间私有推理只能经 night_private_context() 读取，
build_context()（昼间上下文）在实现上不触碰该分区。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMClient
from app.engine.events import (
    Event,
    EventType,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
)

logger = logging.getLogger(__name__)

PREDEFINED_QUESTIONS: list[str] = [
    "你的角色和阵营是什么？",
    "当前是第几轮、什么阶段？",
    "本轮谁死亡或出局了？",
    "谁声称了什么身份？可信度如何？",
    "你当前的目标是什么？下一步计划？",
]


class MemoryEntry(BaseModel):
    seq: int
    round: int
    kind: str
    text: str
    score: int


class ReflectionQA(BaseModel):
    question: str
    answer: str


class ReflectionResult(BaseModel):
    summary: str
    qa: list[ReflectionQA] = Field(default_factory=list)


_SCORE_4 = {
    EventType.DEATH_ANNOUNCED,
    EventType.NIGHT_RESOLVED,
    EventType.PLAYER_EXILED,
    EventType.HUNTER_SHOT,
    EventType.WOLF_SELF_DESTRUCT,
}
_SCORE_3 = {
    EventType.SHERIFF_ELECTED,
    EventType.BADGE_PASSED,
    EventType.SHERIFF_BADGE_LOST,
    EventType.LAST_WORDS,
}
_SCORE_2 = {
    EventType.WITCH_SAVED,
    EventType.WITCH_POISONED,
    EventType.WITCH_POTION_CONSUMED,
    EventType.GUARD_PROTECTED,
    EventType.WOLF_KILL_PROPOSED,
    EventType.WOLF_KILL_DECIDED,
    EventType.VOTE_RESULT,
}


def _score(event: Event, seat: int) -> int:
    if event.type == EventType.SEER_CHECKED and event.actor_seat == seat:
        return 5  # 自身查验结果：最高信息量
    if event.type == EventType.ROLES_ASSIGNED:
        return 5
    if event.type in _SCORE_4:
        return 4
    if event.type in _SCORE_3:
        return 3
    if event.type == EventType.PLAYER_SPOKE:
        p = event.payload
        if isinstance(p, PlayerSpokePayload) and (p.claim_role is not None or p.badge_flow):
            return 3  # 跳身份/报警徽流的发言
        return 1
    if event.type in _SCORE_2:
        return 2
    return 1


def _render(event: Event) -> str:
    """事件 → 中文一行文本。特判高频类型，其余回退通用格式。"""
    p = event.payload
    t = event.type
    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        claim = f"（声称{p.claim_role.value}）" if p.claim_role is not None else ""
        bf = f"（警徽流{list(p.badge_flow)}）" if p.badge_flow else ""
        return f"{event.actor_seat}号发言{claim}{bf}：{p.content}"
    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        return f"你查验了{p.target}号：{p.result.value}"
    dumped = p.model_dump(mode="json")
    actor = f" actor={event.actor_seat}" if event.actor_seat is not None else ""
    return f"{t.value}{actor} {dumped}"


class AgentMemory:
    def __init__(self, seat: int, *, freshness_k: int = 15, informative_top_n: int = 10) -> None:
        self._seat = seat
        self._k = freshness_k
        self._top_n = informative_top_n
        self.entries: list[MemoryEntry] = []
        self._reflections: list[tuple[int, str]] = []  # (round, rendered_text)
        self._night_private: list[tuple[int, str]] = []  # (round, text)
        self._current_round = 0
        self._reflected_rounds: set[int] = set()  # 含"已尝试但失败"，避免重试烧预算

    def ingest(self, events: list[Event]) -> None:
        for e in events:
            if e.type == EventType.ROUND_STARTED and isinstance(e.payload, RoundStartedPayload):
                self._current_round = e.payload.round
            self.entries.append(
                MemoryEntry(
                    seq=e.seq,
                    round=self._current_round,
                    kind=e.type.value,
                    text=_render(e),
                    score=_score(e, self._seat),
                )
            )

    async def on_events(self, events: list[Event]) -> None:
        """ConnectionManager 订阅适配：只摄入。broadcast 在 runner 提交路径上，禁止阻塞。"""
        self.ingest(events)

    def note_night_private(self, text: str, round: int) -> None:
        self._night_private.append((round, text))

    def _context_lines(self) -> list[str]:
        recent = self.entries[-self._k :]
        older = self.entries[: -self._k] if len(self.entries) > self._k else []
        picked = sorted(
            sorted(older, key=lambda e: e.score, reverse=True)[: self._top_n],
            key=lambda e: e.seq,
        )
        lines = [f"[反思·第{r}轮] {t}" for r, t in self._reflections]
        lines += [f"[要点] {e.text}" for e in picked]
        lines += [e.text for e in recent]
        return lines

    def build_context(self) -> str:
        """昼间上下文。实现上不读 _night_private —— 公私分离的结构落点。"""
        return "\n".join(self._context_lines())

    def night_private_context(self) -> str:
        return "\n".join(f"[第{r}夜私谋] {t}" for r, t in self._night_private)

    def rounds_needing_reflection(self) -> list[int]:
        done = {e.round for e in self.entries if e.round > 0}
        return sorted(
            r for r in done if r < self._current_round and r not in self._reflected_rounds
        )

    async def reflect(self, client: LLMClient, model: str, temperature: float = 0.3) -> None:
        for r in self.rounds_needing_reflection():
            round_lines = "\n".join(e.text for e in self.entries if e.round == r)
            questions = "\n".join(f"- {q}" for q in PREDEFINED_QUESTIONS)
            user_prompt = (
                f"以下是狼人杀第{r}轮你观察到的全部事件：\n{round_lines}\n\n"
                f"请总结本轮局势（summary），并回答以下问题（qa），"
                f"另外自行提出并回答 2 个你认为对后续决策最重要的问题：\n{questions}"
            )
            self._reflected_rounds.add(r)  # 先标记：失败也不重试（降级保留原始条目）
            try:
                result = await client.complete_structured(
                    system_prompt="你是狼人杀玩家，正在复盘上一轮。",
                    user_prompt=user_prompt,
                    response_model=ReflectionResult,
                    model=model,
                    temperature=temperature,
                )
            except Exception:
                logger.warning(
                    "座位 %d 第 %d 轮反思失败，降级保留原始记忆", self._seat, r, exc_info=True
                )
                continue
            qa_text = "；".join(f"{x.question}→{x.answer}" for x in result.qa)
            self._reflections.append((r, f"{result.summary}｜{qa_text}"))
