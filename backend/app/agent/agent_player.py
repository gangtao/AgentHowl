"""AgentPlayerPort：LLM Agent 的 PlayerPort 实现（issue #31）。

诚实观察者：只凭 observation 与订阅到的可见事件决策，不触碰引擎 state。
活性兜底完全由 runner 持有（异常/超时 → 默认行动）；本端口零兜底逻辑，
LLM 任何失败一律上抛。狼夜私有推理是独立调用，产出只进 night_private 分区。
"""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from app.agent.decisions import (
    DecisionKind,
    WolfDeliberation,
    decision_kind_for,
    response_model_for,
    to_action,
)
from app.agent.llm_client import DEFAULT_MODEL, LLMClient
from app.agent.memory import AgentMemory
from app.agent.prompts import build_prompt, build_wolf_night_prompt, static_system_prompt
from app.engine.actions import Action
from app.engine.config import GameConfig
from app.engine.events import Event
from app.engine.observation import PlayerObservation


class AgentConfig(BaseModel):
    model: str = DEFAULT_MODEL
    model_speech: str | None = None  # §8.3 分层路由落点：发言用（可更强的）模型
    reflection_model: str | None = None
    temperature: float = 0.3
    agent_seed: int = 0
    deadline_margin_s: float = 2.0  # 剩余时间低于此不再发起 LLM 调用
    reflection_min_remaining_s: float = 10.0  # 剩余时间高于此才做惰性反思
    thinking: bool = False  # 开启推理模型思考（软 JSON 解析；更强推理但明显更慢）


class AgentPlayerPort:
    def __init__(
        self,
        seat: int,
        game_config: GameConfig,
        agent_config: AgentConfig,
        client: LLMClient,
        memory: AgentMemory | None = None,
    ) -> None:
        self._seat = seat
        self._game_config = game_config
        self._cfg = agent_config
        self._client = client
        self.memory = memory if memory is not None else AgentMemory(seat)
        self._system_prompt: str | None = None  # 静态段按首个 observation 的角色惰性生成

    async def on_events(self, events: list[Event]) -> None:
        await self.memory.on_events(events)

    def _system_for(self, obs: PlayerObservation) -> str:
        if self._system_prompt is None:
            self._system_prompt = static_system_prompt(self._game_config, self._seat, obs.my_role)
        return self._system_prompt

    def _model_for(self, kind: DecisionKind) -> str:
        if kind is DecisionKind.SPEECH and self._cfg.model_speech is not None:
            return self._cfg.model_speech
        return self._cfg.model

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        remaining = deadline_ts - time.time()
        if remaining <= self._cfg.deadline_margin_s:
            raise TimeoutError(f"座位 {self._seat} 行动窗口剩余不足（{remaining:.1f}s）")

        # 惰性反思：只在时间宽裕时补做，失败由 memory 内部降级
        if (
            remaining > self._cfg.reflection_min_remaining_s
            and self.memory.rounds_needing_reflection()
        ):
            await self.memory.reflect(
                self._client,
                self._cfg.reflection_model or self._cfg.model,
                self._cfg.temperature,
            )

        kind = decision_kind_for(observation)
        if kind is DecisionKind.WOLF_NIGHT:
            user_prompt = build_wolf_night_prompt(
                observation,
                self.memory.build_context(),
                self.memory.night_private_context(),
                agent_seed=self._cfg.agent_seed,
            )
        else:
            # 注意：这条路径拿不到 night_private —— 公私分离
            user_prompt = build_prompt(
                kind,
                observation,
                self.memory.build_context(),
                agent_seed=self._cfg.agent_seed,
            )

        budget = deadline_ts - time.time() - self._cfg.deadline_margin_s
        if budget <= 0:
            raise TimeoutError(f"座位 {self._seat} 装配后已无调用预算")
        decision = await asyncio.wait_for(
            self._client.complete_structured(
                system_prompt=self._system_for(observation),
                user_prompt=user_prompt,
                response_model=response_model_for(kind),
                model=self._model_for(kind),
                temperature=self._cfg.temperature,
                thinking=self._cfg.thinking,
            ),
            timeout=budget,
        )
        if isinstance(decision, WolfDeliberation):
            self.memory.note_night_private(decision.analysis, observation.round)
        return to_action(kind, decision, observation.my_seat)


def build_agent_port(
    seat: int,
    game_config: GameConfig,
    ai_model: str,
    ai_model_speech: str | None,
    thinking: bool = False,
    reflection_model: str | None = None,
) -> AgentPlayerPort:
    """registry 默认工厂：真实 LiteLLM 客户端 + 按 GameConfig.seed 派生 agent_seed。"""
    from app.agent.llm_client import LiteLLMInstructorClient

    return AgentPlayerPort(
        seat=seat,
        game_config=game_config,
        agent_config=AgentConfig(
            model=ai_model,
            model_speech=ai_model_speech,
            reflection_model=reflection_model,
            agent_seed=game_config.seed if game_config.seed is not None else 0,
            thinking=thinking,
        ),
        client=LiteLLMInstructorClient(),
    )
