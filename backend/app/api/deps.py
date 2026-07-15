"""认证：不透明 token 登记表（PRD §5.4，MVP 内存 dict）与 FastAPI 依赖注入（issue #30）。"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.runtime.registry import GameRegistry


class TokenInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_id: str
    seat: int | None  # HOST/SPECTATOR 无座位
    kind: Literal["HOST", "PLAYER", "SPECTATOR"]


class TokenRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, TokenInfo] = {}

    def issue(self, info: TokenInfo) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = info
        return token

    def resolve(self, token: str) -> TokenInfo | None:
        return self._tokens.get(token)


_bearer = HTTPBearer(auto_error=False)


def get_games(request: Request) -> GameRegistry:  # 运行时取自 app.state
    from app.runtime.registry import GameRegistry  # 局部导入防环

    games = request.app.state.games
    assert isinstance(games, GameRegistry)
    return games


def get_tokens(request: Request) -> TokenRegistry:
    tokens = request.app.state.tokens
    assert isinstance(tokens, TokenRegistry)
    return tokens


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    tokens: TokenRegistry = Depends(get_tokens),
) -> TokenInfo:
    if creds is None:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    info = tokens.resolve(creds.credentials)
    if info is None:
        raise HTTPException(status_code=401, detail="token 无效")
    return info


def require_kind(info: TokenInfo, game_id: str, *kinds: str) -> TokenInfo:
    """token 必须属于该对局且 kind 在允许集合内，否则 403。"""
    if info.game_id != game_id or info.kind not in kinds:
        raise HTTPException(status_code=403, detail="token 与对局或操作不匹配")
    return info
