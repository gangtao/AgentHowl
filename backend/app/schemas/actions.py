"""工具调用（PRD §4.1）↔ 引擎 Action 映射与行动响应信封（issue #30）。

actor_seat 一律由调用方从 token 注入，body 内同名字段被忽略（防冒充）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.actions import (
    Action,
    DayVote,
    Direction,
    NightAction,
    NightActionType,
    SelfDestruct,
    SheriffAction,
    SheriffActionType,
    Speak,
)
from app.engine.config import RoleType
from app.engine.observation import PlayerObservation


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallError(ValueError):
    """工具名未知或参数非法（api 映射 400）。"""


class ActionResponse(BaseModel):
    """PRD §4.1 统一信封。"""

    ok: bool
    event_id: str | None = None
    state_version: int
    rejected_reason: str | None = None


def _opt_int(v: object) -> int | None:
    return None if v is None else int(v)  # type: ignore[call-overload]


def parse_tool_call(call: ToolCall, actor_seat: int) -> Action:
    a = call.arguments
    try:
        if call.tool == "speak":
            claim = a.get("claim_role")
            claim_role = None if claim in (None, "NONE") else RoleType(str(claim))
            return Speak(
                actor_seat=actor_seat,
                content=str(a["content"]),
                claim_role=claim_role,
                badge_flow=tuple(int(s) for s in a.get("badge_flow", ())),
            )
        if call.tool == "vote":
            return DayVote(
                actor_seat=actor_seat,
                target_seat=_opt_int(a.get("target_seat")),
                abstain=bool(a.get("abstain", False)),
            )
        if call.tool == "night_action":
            return NightAction(
                actor_seat=actor_seat,
                action_type=NightActionType(str(a["action_type"])),
                target_seat=_opt_int(a.get("target_seat")),
            )
        if call.tool == "sheriff_action":
            d = a.get("direction")
            return SheriffAction(
                actor_seat=actor_seat,
                action_type=SheriffActionType(str(a["action_type"])),
                target_seat=_opt_int(a.get("target_seat")),
                direction=None if d is None else Direction(str(d)),
            )
        if call.tool == "self_destruct":
            return SelfDestruct(actor_seat=actor_seat)
        if call.tool == "bid_to_speak":
            # 引擎 Action 联合暂无 Bid 类型（speech_order_rule=BIDDING 未实现），解析期即拒
            raise ToolCallError("bid_to_speak 未启用（BIDDING 模式未实现）")
    except ToolCallError:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise ToolCallError(f"工具 {call.tool} 参数非法：{exc}") from exc
    raise ToolCallError(f"未知工具：{call.tool}")


_READONLY = ("get_game_state", "get_speeches")


def available_tools_for(obs: PlayerObservation) -> tuple[str, ...]:
    """按阶段给出可用行动工具（粗粒度 UI/Agent 提示；合法性裁决仍在引擎）。"""
    ph = obs.phase
    if ph.startswith("NIGHT_") or ph == "HUNTER_SHOOT":
        return ("night_action", *_READONLY)
    if ph == "DAY_SPEECH":
        return ("speak", "self_destruct", *_READONLY)
    if ph in ("VOTE", "VOTE_PK"):
        return ("vote", "speak", *_READONLY)
    if ph in ("SHERIFF_ELECTION", "SHERIFF_PK"):
        return ("sheriff_action", "speak", "self_destruct", *_READONLY)
    if ph == "LAST_WORDS":
        return ("speak", "sheriff_action", *_READONLY)
    return _READONLY
