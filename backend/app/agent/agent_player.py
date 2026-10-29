"""AgentPlayerPort：LLM Agent 的 PlayerPort 实现（issue #31）。

诚实观察者：只凭 observation 与订阅到的可见事件决策，不触碰引擎 state。
活性兜底完全由 runner 持有（异常/超时 → 默认行动）；本端口零兜底逻辑，
LLM 任何失败一律上抛。狼夜私有推理是独立调用，产出只进 night_private 分区。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.agent.decisions import (
    DecisionKind,
    WolfDeliberation,
    decision_kind_for,
    response_model_for,
    to_action,
)
from app.agent.experience import (
    DEFAULT_EXPERIENCE_BUDGET_CHARS,
    AgentExperience,
    GameReflection,
    GameReveal,
    build_reflection_prompt,
    render_experience,
)
from app.agent.llm_client import DEFAULT_MODEL, LLMClient
from app.agent.memory import AgentMemory
from app.agent.personality import PersonalitySpec, render_personality
from app.agent.prompts import (
    badge_flow_allowed,
    build_prompt,
    build_wolf_night_prompt,
    static_system_prompt,
)
from app.agent.skills import (
    DEFAULT_SKILL_BUDGET_CHARS,
    Skill,
    assemble_skills,
    select_skills,
    skills_index_text,
)
from app.engine.actions import Action, RejectedReason, Speak
from app.engine.config import GameConfig, RoleType
from app.engine.events import Event
from app.engine.observation import PlayerObservation

if TYPE_CHECKING:
    from app.agent.profile import AgentProfile
    from app.agent.provider import Provider
    from app.agent.skills import SkillLibrary

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    model: str = DEFAULT_MODEL
    model_speech: str | None = None  # §8.3 分层路由落点：发言用（可更强的）模型
    reflection_model: str | None = None
    temperature: float = 0.3
    agent_seed: int = 0
    deadline_margin_s: float = 2.0  # 剩余时间低于此不再发起 LLM 调用
    # issue #177：装配（反思 / 技能 / prompt）之后剩余预算低于此也不发起调用——否则 wait_for 会在
    # 几十毫秒内取消协程，litellm 把取消记成「Connection timed out」，误导排查
    min_call_s: float = 1.0
    reflection_min_remaining_s: float = 10.0  # 剩余时间高于此才做惰性反思
    # 结构化输出校验失败的最大重试次数（issue #86）：实际次数还会按剩余预算收紧——
    # 一次生成慢模型要 20–60s，三连重试会吃满整个发言窗口、记成「超时」
    max_retries: int = 2
    assumed_call_s: float = 15.0  # 尚无实测耗时前，估算单次生成所需秒数
    thinking: bool = False  # 开启推理模型思考（软 JSON 解析；更强推理但明显更慢）
    # 每次决策装配技能正文的字符预算（issue #58）
    skill_budget_chars: int = DEFAULT_SKILL_BUDGET_CHARS
    # 装配跨局经验的字符预算（issue #59）
    experience_budget_chars: int = DEFAULT_EXPERIENCE_BUDGET_CHARS


class AgentPlayerPort:
    def __init__(
        self,
        seat: int,
        game_config: GameConfig,
        agent_config: AgentConfig,
        client: LLMClient,
        memory: AgentMemory | None = None,
        skills: Sequence[Skill] = (),
        personality: PersonalitySpec | None = None,
        experience: AgentExperience | None = None,
        opponents: Mapping[str, int] | None = None,
    ) -> None:
        self._seat = seat
        self._game_config = game_config
        self._cfg = agent_config
        self._client = client
        self.memory = memory if memory is not None else AgentMemory(seat)
        self._system_prompt: str | None = None  # 静态段按首个 observation 的角色惰性生成
        self._skills = tuple(skills)
        self._personality = personality
        self._experience = experience
        self._opponents: dict[str, int] = dict(opponents or {})
        self.last_skills_used: tuple[str, ...] = ()
        self._call_seconds: float | None = None  # 单次决策生成耗时的滑动均值（issue #86）
        self._last_rejection: str | None = None  # runner 回填的上次拒绝原因，下次 prompt 带上
        self._last_speak: Speak | None = (
            None  # 上次提交的发言：BADGE_FLOW_INVALID 时去掉警徽流直接重交
        )

    def notify_result(
        self, rejected_reason: str | None, state_version: int, event_id: str | None
    ) -> None:
        """runner 裁决回填（SupportsResultFeedback）：被拒原因喂给下一次决策，否则模型只能
        盲重试同一个非法行动直到落默认（issue #53）。"""
        self._last_rejection = rejected_reason

    def _retries_for_budget(self, budget: float) -> int:
        """按剩余预算决定还能重试几次：预算至少够跑 n 次生成才允许 n-1 次重试。"""
        est = self._call_seconds if self._call_seconds is not None else self._cfg.assumed_call_s
        est = max(est, 1e-3)
        attempts = int(budget // est)
        return max(0, min(self._cfg.max_retries, attempts - 1))

    def _note_call_seconds(self, seconds: float) -> None:
        prev = self._call_seconds
        self._call_seconds = seconds if prev is None else 0.5 * prev + 0.5 * seconds

    async def on_events(self, events: list[Event]) -> None:
        await self.memory.on_events(events)

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

    def _model_for(self, kind: DecisionKind) -> str:
        if kind is DecisionKind.SPEECH and self._cfg.model_speech is not None:
            return self._cfg.model_speech
        return self._cfg.model

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        remaining = deadline_ts - time.time()
        if remaining <= self._cfg.deadline_margin_s:
            raise TimeoutError(f"座位 {self._seat} 行动窗口剩余不足（{remaining:.1f}s）")

        # 警徽流被拒：发言正文本身没问题，去掉警徽流原样重交——不再花一次生成、也不会三连拒
        # 把整段发言丢掉（真机局 4 号上警发言因此"超时"）。
        if (
            self._last_rejection == str(RejectedReason.BADGE_FLOW_INVALID)
            and self._last_speak is not None
            and self._last_speak.badge_flow
            and self._last_speak.actor_seat == observation.my_seat
        ):
            logger.warning(
                "seat=%d phase=%s 警徽流 %s 被拒，去掉警徽流重交发言",
                self._seat,
                observation.phase,
                self._last_speak.badge_flow,
            )
            self._last_rejection = None
            action: Action = self._last_speak.model_copy(update={"badge_flow": ()})
            self._last_speak = None
            return action

        # 惰性反思：只在时间宽裕时补做，失败由 memory 内部降级。
        # issue #42：每次 act 至多反思一轮，且只给它「超出决策底线」的那段时间——
        # 之前一次循环全部待反思轮且无单次预算，慢反思会吃掉决策窗口，该回合落默认行动
        if (
            remaining > self._cfg.reflection_min_remaining_s
            and self.memory.rounds_needing_reflection()
        ):
            slice_s = remaining - self._cfg.reflection_min_remaining_s
            try:
                await asyncio.wait_for(
                    self.memory.reflect(
                        self._client,
                        self._cfg.reflection_model or self._cfg.model,
                        self._cfg.temperature,
                        max_rounds=1,
                    ),
                    timeout=slice_s,
                )
            except TimeoutError:
                logger.warning(
                    "seat=%d phase=%s 反思超过预算 %.1fs，本回合跳过（该轮不再重试）",
                    self._seat,
                    observation.phase,
                    slice_s,
                )

        selected = select_skills(self._skills, observation.my_role, observation.phase)
        skills_text, used = assemble_skills(selected, self._cfg.skill_budget_chars)
        self.last_skills_used = used
        if used:
            logger.info("seat=%d phase=%s skills=%s", self._seat, observation.phase, ",".join(used))

        kind = decision_kind_for(observation)
        if kind is DecisionKind.WOLF_NIGHT:
            user_prompt = build_wolf_night_prompt(
                observation,
                self.memory.build_context(),
                self.memory.night_private_context(),
                agent_seed=self._cfg.agent_seed,
                skills_text=skills_text,
            )
        else:
            # 注意：这条路径拿不到 night_private —— 公私分离
            user_prompt = build_prompt(
                kind,
                observation,
                self.memory.build_context(),
                agent_seed=self._cfg.agent_seed,
                skills_text=skills_text,
            )

        allow_bf = badge_flow_allowed(observation)
        if allow_bf:
            user_prompt += (
                f"\n\nbadge_flow（警徽流）最多 {self._badge_flow_max()} 个座位，"
                "须存活、不重复、不含自己；不是预言家或不想报就留空。"
            )
        if self._last_rejection:
            user_prompt += (
                f"\n\n== 上一次提交被引擎拒绝 ==\n原因：{self._last_rejection}。"
                "请按当前阶段的合法行动重新给出决策，不要重复同样的提交。"
            )
            self._last_rejection = None

        budget = deadline_ts - time.time() - self._cfg.deadline_margin_s
        if budget < self._cfg.min_call_s:
            raise TimeoutError(
                f"座位 {self._seat} 装配后调用预算不足（{budget:.2f}s < {self._cfg.min_call_s}s）"
            )
        started = time.monotonic()
        decision = await asyncio.wait_for(
            self._client.complete_structured(
                system_prompt=self._system_for(observation),
                user_prompt=user_prompt,
                response_model=response_model_for(kind),
                model=self._model_for(kind),
                temperature=self._cfg.temperature,
                thinking=self._cfg.thinking,
                max_retries=self._retries_for_budget(budget),
            ),
            timeout=budget,
        )
        self._note_call_seconds(time.monotonic() - started)
        if isinstance(decision, WolfDeliberation):
            self.memory.note_night_private(decision.analysis, observation.round)
        if not allow_bf and getattr(decision, "badge_flow", None):
            logger.info(
                "seat=%d phase=%s 非竞选发言携带 badge_flow=%s，已剥除",
                self._seat,
                observation.phase,
                decision.badge_flow,  # type: ignore[attr-defined]
            )
        elif allow_bf and getattr(decision, "badge_flow", None):
            raw = list(decision.badge_flow)  # type: ignore[attr-defined]
            cleaned = self._sanitize_badge_flow(raw, observation)
            if cleaned != raw:
                logger.warning(
                    "seat=%d phase=%s 警徽流 %s 不合规（上限 %d/存活/不重复/不含自己），修正为 %s",
                    self._seat,
                    observation.phase,
                    raw,
                    self._badge_flow_max(),
                    cleaned,
                )
                decision = decision.model_copy(update={"badge_flow": cleaned})
        action = to_action(kind, decision, observation.my_seat, allow_badge_flow=allow_bf)
        self._last_speak = action if isinstance(action, Speak) else None
        return action

    def _badge_flow_max(self) -> int:
        return self._game_config.sheriff.badge_flow_max_length

    def _sanitize_badge_flow(self, flow: list[int], obs: PlayerObservation) -> list[int]:
        """按引擎规则（engine._validate 的 BADGE_FLOW_INVALID 条件）在提交前修正：
        去重、剔除自己与非存活座位、截到上限。模型只知道"未来几夜的验人顺序"，不知道上限是 2。"""
        alive = {int(p["seat"]) for p in obs.seats if p.get("alive")}
        out: list[int] = []
        for seat in flow:
            if seat == obs.my_seat or seat not in alive or seat in out:
                continue
            out.append(seat)
        return out[: self._badge_flow_max()]

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


def build_agent_port(
    seat: int,
    game_config: GameConfig,
    profile: AgentProfile,
    *,
    library: SkillLibrary | None = None,
    experience: AgentExperience | None = None,
    opponents: Mapping[str, int] | None = None,
    provider: Provider | None = None,
) -> AgentPlayerPort:
    """registry / CLI 默认工厂：真实 LiteLLM 客户端 + 档案映射的 AgentConfig
    （issue #56/#58/#59）。provider 非空时凭据绑定到本端口新建的客户端实例（issue #26）。
    """
    from app.agent.llm_client import LiteLLMInstructorClient
    from app.agent.profile import to_agent_config

    skills: Sequence[Skill] = ()
    if profile.skills:
        if library is None:
            from app.agent.skills import default_library

            library = default_library()
        skills = library.resolve(profile.skills)

    return AgentPlayerPort(
        seat=seat,
        game_config=game_config,
        agent_config=to_agent_config(profile, game_config, provider=provider),
        client=LiteLLMInstructorClient(
            api_base=provider.api_base if provider else None,
            api_key=provider.api_key if provider else None,
        ),
        skills=skills,
        personality=profile.personality,
        experience=experience,
        opponents=opponents,
    )
