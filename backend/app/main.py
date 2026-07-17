"""FastAPI 装配（issue #30）。uvicorn 入口：`uvicorn app.main:app`。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import rest, ws
from app.api.deps import TokenRegistry
from app.runtime.game_runner import LobbyError, RunnerTimeouts
from app.runtime.player_port import NotYourTurnError, PlayerPort
from app.runtime.registry import GameRegistry
from app.schemas.actions import ToolCallError
from app.store.event_store import EventStore, JsonFileEventStore, StoreError

if TYPE_CHECKING:
    from app.runtime.registry import GameHandle


def create_app(
    *,
    store: EventStore | None = None,
    timeouts: RunnerTimeouts | None = None,
    data_dir: Path | None = None,
    agent_port_factory: Callable[[int, GameHandle], PlayerPort] | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentHowl API", version="0.1.0")
    app.state.games = GameRegistry(
        store=store or JsonFileEventStore(data_dir or Path("data/games")),
        timeouts=timeouts,
        agent_port_factory=agent_port_factory,
    )
    app.state.tokens = TokenRegistry()
    app.include_router(rest.router, prefix="/api/v1")
    app.include_router(ws.router, prefix="/api/v1")

    def _handler(status: int):  # type: ignore[no-untyped-def]
        async def h(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return h

    app.add_exception_handler(LobbyError, _handler(409))
    app.add_exception_handler(NotYourTurnError, _handler(409))
    app.add_exception_handler(ToolCallError, _handler(400))
    app.add_exception_handler(LookupError, _handler(404))
    app.add_exception_handler(StoreError, _handler(500))
    # runner task 崩溃后 handle.ensure_healthy() 抛出裸 RuntimeError，需兜底为 500（否则落到
    # Starlette 默认异常页，客户端拿不到 JSON detail）——issue #30 Task 5 复审发现。
    app.add_exception_handler(RuntimeError, _handler(500))
    return app


app = create_app()
