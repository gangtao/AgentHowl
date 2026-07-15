"""认证：不透明 token 登记表（PRD §5.4，MVP 内存 dict）。issue #30。

FastAPI 依赖注入函数在 Task 4 追加于本文件。
"""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
