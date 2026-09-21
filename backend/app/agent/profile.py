"""AgentProfile（issue #56）：每座位独立的内置 Agent 配置。

registry / api / cli 三个入口都只经本模块解析档案：查找（座位优先于 "*"）、
键校验、旧字段（ai_model 等）折叠、到 AgentConfig 的映射。字段随各 issue 增量添加
（#56 模型路由、#58 skills、#57 personality、#59 memory_id）；
extra="forbid" 保证未实现的键被拒绝而非静默忽略。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.experience import MEMORY_ID_PATTERN
from app.agent.personality import PersonalitySpec
from app.agent.skills import SkillError
from app.engine.config import GameConfig

if TYPE_CHECKING:
    # 仅类型标注用；运行期改在 to_agent_config 内局部 import，
    # 避免 registry 等模块导入本档案模块时连带加载 agent_player → litellm（惰性加载设计）。
    from app.agent.agent_player import AgentConfig
    from app.agent.skills import SkillLibrary

STAR = "*"  # 默认档案键：未单独配置的空位


class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None  # 展示名（roster display_name）；缺省 Bot{seat}
    model: str
    model_speech: str | None = None  # 发言层模型（None=同 model；PRD §8.3 分层路由）
    reflection_model: str | None = None
    thinking: bool = False
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    skills: tuple[str, ...] = ()  # 技能名或 "*"（issue #58）；元组（有序、不可变）
    # 注意：配置了 personality 的档案不可哈希，勿以档案对象为键（见 #57 规格 §2）
    personality: PersonalitySpec | None = None  # 任意性格特点（issue #57）
    # 跨局记忆标识（issue #59）：None=不持久化；同一局内须唯一，"*" 档案不得配置
    memory_id: str | None = Field(default=None, pattern=MEMORY_ID_PATTERN)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v: object) -> object:
        """去首尾空白；去空后为空串归一为 None（非 str 交给 pydantic 原校验报错）。"""
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


AgentProfiles = dict[str, AgentProfile]


def profile_for(agents: AgentProfiles, seat: int) -> AgentProfile | None:
    """座位专属档案优先，其次 "*"；都没有 → None（该座位用 RandomBot）。

    用 is not None 而非 `or`：座位档案本身是 truthy 的 BaseModel 实例，
    但显式写成 is not None 避免未来模型加 __bool__/__len__ 语义时静默改变优先级。
    """
    p = agents.get(str(seat))
    return p if p is not None else agents.get(STAR)


def validate_profiles(
    agents: AgentProfiles, num_players: int, library: SkillLibrary | None = None
) -> None:
    """键只能是 "*" 或 0..num_players-1 的十进制座位号；给了 library 时连带校验技能名；
    memory_id 须座位唯一且不得配在 "*"。
    """
    for key in agents:
        if key == STAR:
            continue
        if not key.isdecimal() or str(int(key)) != key or not 0 <= int(key) < num_players:
            raise ValueError(f"agents 键 {key!r} 非法：须为 '*' 或 0..{num_players - 1} 的座位号")
    seen: dict[str, str] = {}
    for key, profile in agents.items():
        mid = profile.memory_id
        if mid is None:
            continue
        if key == STAR:
            raise ValueError("agents['*'] 不能配置 memory_id：通配档案会展开成多个座位共用一份记忆")
        if mid in seen:
            raise ValueError(
                f"memory_id {mid!r} 被座位 {seen[mid]} 与 {key} 重复使用：同一局内须唯一"
            )
        seen[mid] = key
    if library is not None:
        for profile in agents.values():
            try:
                library.resolve(profile.skills)
            except SkillError as exc:
                raise ValueError(str(exc)) from exc


def legacy_to_profiles(
    ai_model: str | None,
    ai_model_speech: str | None = None,
    *,
    reflection_model: str | None = None,
    thinking: bool = False,
) -> AgentProfiles:
    """旧入口（ai_model 等）等价于 "*" 默认档案；ai_model 为空 → 空映射（全 RandomBot）。"""
    if ai_model is None:
        return {}
    return {
        STAR: AgentProfile(
            model=ai_model,
            model_speech=ai_model_speech,
            reflection_model=reflection_model,
            thinking=thinking,
        )
    }


def merge_profiles(agents: AgentProfiles | None, legacy: AgentProfiles) -> AgentProfiles:
    """合并显式档案与旧字段折叠结果；两边都给了 "*" 视为冲突。

    legacy 只可能是 legacy_to_profiles 的输出：空映射或单键 "*"；下面的覆盖逻辑
    （update）依赖这个隐式契约，若 legacy 携带其他键会静默覆盖对应座位档案。
    """
    assert set(legacy) <= {STAR}, f"legacy 只应含 '*' 键，实为 {set(legacy)!r}"
    agents = dict(agents or {})
    if STAR in agents and STAR in legacy:
        raise ValueError("ai_model 与 agents['*'] 不能同时指定")
    agents.update(legacy)
    return agents


def to_agent_config(profile: AgentProfile, game_config: GameConfig) -> AgentConfig:
    """agent_seed 仍取 GameConfig.seed（候选洗牌本已按座位区分），其余字段逐项映射。"""
    from app.agent.agent_player import AgentConfig  # 局部 import：见文件头 TYPE_CHECKING 注释

    return AgentConfig(
        model=profile.model,
        model_speech=profile.model_speech,
        reflection_model=profile.reflection_model,
        thinking=profile.thinking,
        temperature=profile.temperature,
        agent_seed=game_config.seed if game_config.seed is not None else 0,
    )
