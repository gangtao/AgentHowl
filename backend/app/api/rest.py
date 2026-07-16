"""REST 端点（PRD §5.2）。零裁决：鉴权/序列化/转发（issue #30）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import (
    TokenInfo,
    TokenRegistry,
    get_games,
    get_tokens,
    require_kind,
    require_token,
)
from app.engine.config import build_preset
from app.engine.events import Event, EventType, Visibility
from app.engine.observation import build_observation, visible_events
from app.engine.phases import Phase
from app.runtime.player_port import NotYourTurnError, TurnPrompt
from app.runtime.registry import GameHandle, GameRegistry
from app.schemas.actions import (
    ActionResponse,
    ToolCall,
    ToolCallError,
    available_tools_for,
    parse_tool_call,
)
from app.schemas.games import (
    CreateGameRequest,
    CreateGameResponse,
    JoinRequest,
    JoinResponse,
    SpectatorView,
    SpeechItem,
    StartRequest,
    StartResponse,
)
from app.store.event_store import event_to_json

router = APIRouter(prefix="/games", tags=["games"])


@router.post("")
def create_game_endpoint(
    req: CreateGameRequest,
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> CreateGameResponse:
    try:
        config = build_preset(req.preset).model_copy(update=req.config_override)
        config = type(config).model_validate(config.model_dump())  # override 后全量校验
    except (KeyError, ValueError, ValidationError) as exc:
        raise ToolCallError(f"preset/config_override 非法：{exc}") from exc
    handle = games.create(
        config, allow_spectators=req.allow_spectators, num_ai_players=req.num_ai_players
    )
    host_token = tokens.issue(TokenInfo(game_id=handle.game_id, seat=None, kind="HOST"))
    spectator_token = (
        tokens.issue(TokenInfo(game_id=handle.game_id, seat=None, kind="SPECTATOR"))
        if req.allow_spectators
        else None
    )
    return CreateGameResponse(
        game_id=handle.game_id,
        host_token=host_token,
        spectator_token=spectator_token,
        config=config.model_dump(mode="json"),
    )


@router.post("/{game_id}/join")
def join_endpoint(
    game_id: str,
    req: JoinRequest,
    games: GameRegistry = Depends(get_games),
    tokens: TokenRegistry = Depends(get_tokens),
) -> JoinResponse:
    handle = games.get(game_id)
    seat = games.join(handle, req.display_name, req.player_type)
    token = tokens.issue(TokenInfo(game_id=game_id, seat=seat, kind="PLAYER"))
    return JoinResponse(player_token=token, seat=seat, ws_url=f"/api/v1/ws?token={token}")


@router.post("/{game_id}/start")
async def start_endpoint(
    game_id: str,
    req: StartRequest,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> StartResponse:
    handle = games.get(game_id)
    require_kind(info, game_id, "HOST")
    games.start(handle, fill_with_bots=req.fill_with_bots)
    return StartResponse(ok=True, num_players=handle.config.num_players)


def _handle_for(games: GameRegistry, game_id: str) -> GameHandle:
    handle = games.get(game_id)
    handle.ensure_healthy()
    return handle


def games_store_events(games: GameRegistry, game_id: str) -> list[Event]:
    return games.store.load_events(game_id)


@router.get("/{game_id}/state")
def state_endpoint(
    game_id: str,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> dict[str, Any]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR")
    live = handle.live_state()  # 未开局 → LobbyError(409)
    if info.kind == "PLAYER":
        assert info.seat is not None
        return build_observation(live, info.seat).model_dump(mode="json")
    return SpectatorView(
        game_id=game_id,
        phase=str(live.phase),
        round=live.round,
        seats=[
            {
                "seat": p.seat,
                "display_name": p.display_name,
                "alive": p.alive,
                "is_sheriff": p.is_sheriff,
                "idiot_revealed": p.idiot_revealed,
            }
            for p in live.players
        ],
        sheriff_seat=live.sheriff_seat,
        winner=live.winner,
    ).model_dump(mode="json")


@router.get("/{game_id}/speeches")
def speeches_endpoint(
    game_id: str,
    round: int | None = Query(default=None),
    phase: str | None = Query(default=None),
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> list[SpeechItem]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR")
    if not handle.started:
        return []
    # 服务端以 GM 视角扫描以计算 round/phase（返回的两类事件本身是 PUBLIC）
    out: list[SpeechItem] = []
    cur_round, cur_phase = 0, ""
    for e in games_store_events(games, game_id):
        if e.type == EventType.ROUND_STARTED:
            cur_round = int(e.payload.round)  # type: ignore[attr-defined]
        elif e.type == EventType.PHASE_CHANGED:
            cur_phase = str(e.payload.to)  # type: ignore[attr-defined]
        elif (
            e.type == EventType.PLAYER_SPOKE
            and e.actor_seat is not None
            and e.visibility == Visibility.PUBLIC
        ):
            # 护栏：即使未来出现非 PUBLIC 的发言类事件（如狼频道），也不得进入公开 speeches
            out.append(
                SpeechItem(
                    seq=e.seq,
                    round=cur_round,
                    phase=cur_phase,
                    seat=e.actor_seat,
                    content=e.payload.content,  # type: ignore[attr-defined]
                    claim_role=None
                    if e.payload.claim_role is None  # type: ignore[attr-defined]
                    else str(e.payload.claim_role),  # type: ignore[attr-defined]
                    badge_flow=e.payload.badge_flow,  # type: ignore[attr-defined]
                    kind="speech",
                )
            )
        elif e.type == EventType.LAST_WORDS and e.visibility == Visibility.PUBLIC:
            # 护栏：即使未来出现非 PUBLIC 的发言类事件（如狼频道），也不得进入公开 speeches
            out.append(
                SpeechItem(
                    seq=e.seq,
                    round=cur_round,
                    phase=cur_phase,
                    seat=e.payload.seat,  # type: ignore[attr-defined]
                    content=e.payload.content,  # type: ignore[attr-defined]
                    kind="last_words",
                )
            )
    if round is not None:
        out = [s for s in out if s.round == round]
    if phase is not None:
        out = [s for s in out if s.phase == phase]
    return out


@router.get("/{game_id}/events")
def events_endpoint(
    game_id: str,
    from_seq: int = Query(default=0),
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR")
    if not handle.started:
        return []
    viewer: Any = info.seat if info.kind == "PLAYER" else "SPECTATOR"
    events = games.store.load_events(game_id, from_seq=from_seq)
    return [event_to_json(e) for e in visible_events(handle.live_state(), events, viewer)]


@router.get("/{game_id}/replay")
def replay_endpoint(
    game_id: str,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> list[dict[str, Any]]:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER", "SPECTATOR", "HOST")
    if not handle.started or handle.live_state().phase != Phase.GAME_OVER:
        raise HTTPException(status_code=403, detail="对局未结束，上帝视角回放未开放")
    return [event_to_json(e) for e in games.store.load_events(game_id)]


@router.post("/{game_id}/actions")
async def actions_endpoint(
    game_id: str,
    call: ToolCall,
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> ActionResponse:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER")
    assert info.seat is not None
    port = handle.human_ports.get(info.seat)
    if port is None:
        raise HTTPException(status_code=403, detail="该座位非外接玩家")
    action = parse_tool_call(call, actor_seat=info.seat)
    try:
        outcome = await port.submit_and_wait(action, timeout=10.0)
    except TimeoutError:
        raise NotYourTurnError("行动窗口已关闭（可能已超时代打）") from None
    return ActionResponse(
        ok=outcome.ok,
        event_id=outcome.event_id,
        state_version=outcome.state_version,
        rejected_reason=outcome.rejected_reason,
    )


@router.get("/{game_id}/my-turn")
async def my_turn_endpoint(
    game_id: str,
    wait: float = Query(default=25.0, le=30.0),
    info: TokenInfo = Depends(require_token),
    games: GameRegistry = Depends(get_games),
) -> Response:
    handle = _handle_for(games, game_id)
    require_kind(info, game_id, "PLAYER")
    assert info.seat is not None
    port = handle.human_ports.get(info.seat)
    if port is None:
        raise HTTPException(status_code=403, detail="该座位非外接玩家")
    deadline = time.time() + wait
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return Response(status_code=204)
        if handle.task is not None and handle.task.done():
            return Response(status_code=204)  # 对局已终局：立即结束长轮询
        prompt = await port.wait_armed(min(remaining, 0.25))
        if prompt is not None:
            return JSONResponse(_your_turn_payload(prompt))


def _your_turn_payload(prompt: TurnPrompt) -> dict[str, Any]:
    return {
        "observation": prompt.observation.model_dump(mode="json"),
        "available_tools": list(available_tools_for(prompt.observation)),
        "deadline_ts": prompt.deadline_ts,
    }
