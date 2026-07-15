"""REST 端点（PRD §5.2）。零裁决：鉴权/序列化/转发（issue #30）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
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
from app.runtime.registry import GameRegistry
from app.schemas.actions import ToolCallError
from app.schemas.games import (
    CreateGameRequest,
    CreateGameResponse,
    JoinRequest,
    JoinResponse,
    StartRequest,
    StartResponse,
)

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
