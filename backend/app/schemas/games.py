"""建局/加入/开局/视图等请求响应模型（PRD §5.2，issue #30）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.profile import AgentProfile


class CreateGameRequest(BaseModel):
    preset: str = "std_9_kill_side"
    config_override: dict[str, Any] = Field(default_factory=dict)
    num_ai_players: int | None = None  # 提供时 start 校验空位数一致
    allow_spectators: bool = True
    ai_model: str | None = None  # 设置后空位由 LLM Agent 填充（None=沿用 RandomBot）
    ai_model_speech: str | None = None  # 发言层模型（None=同 ai_model；PRD §8.3 分层路由）
    agents: dict[str, AgentProfile] = Field(default_factory=dict)  # 档案：座位号或 "*"（issue #56）


class CreateGameResponse(BaseModel):
    game_id: str
    host_token: str
    spectator_token: str | None
    gm_token: str  # 上帝视角只读 token（issue #26）；只发给建局者
    config: dict[str, Any]
    agents: dict[str, AgentProfile]  # 解析后的档案映射（含旧 ai_model 折叠为 "*"）


class JoinRequest(BaseModel):
    display_name: str
    player_type: Literal["HUMAN", "AGENT"] = "HUMAN"


class JoinResponse(BaseModel):
    player_token: str
    seat: int
    ws_url: str


class StartRequest(BaseModel):
    fill_with_bots: bool = True


class StartResponse(BaseModel):
    ok: bool
    num_players: int


class SpectatorView(BaseModel):
    game_id: str
    phase: str
    round: int
    seats: list[dict[str, Any]]
    sheriff_seat: int | None
    winner: str | None


class SpeechItem(BaseModel):
    seq: int
    round: int
    phase: str
    seat: int
    content: str
    claim_role: str | None = None
    badge_flow: tuple[int, ...] = ()
    kind: Literal["speech", "last_words"]
