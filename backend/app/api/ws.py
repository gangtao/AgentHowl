"""WebSocket 端点（PRD §5.3）：按视角推送 + 行动帧 + 重连补发（issue #30）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import TokenInfo
from app.api.rest import _your_turn_payload
from app.engine.events import Event, EventType
from app.engine.observation import visible_events
from app.runtime.player_port import HumanPlayerPort, NotYourTurnError, TurnPrompt
from app.runtime.registry import GameHandle, GameRegistry
from app.schemas.actions import ToolCall, ToolCallError, parse_tool_call
from app.store.event_store import event_to_json

router = APIRouter()


def _frame(e: Event) -> dict[str, Any]:
    return {"type": "game_event", "seq": e.seq, "event": event_to_json(e)}


async def _send_event_frames(ws: WebSocket, handle: GameHandle, events: list[Event]) -> None:
    """game_event + 由可见 PHASE_CHANGED/GAME_OVER 派生的附加帧。"""
    for e in events:
        await ws.send_json(_frame(e))
        if e.type == EventType.PHASE_CHANGED:
            await ws.send_json(
                {
                    "type": "phase_change",
                    "to": str(e.payload.to),  # type: ignore[attr-defined]
                    "round": handle.live_state().round,
                }
            )
        if e.type == EventType.GAME_OVER:
            await ws.send_json(
                {"type": "game_over", "winner": e.payload.winner}  # type: ignore[attr-defined]
            )


@router.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket, token: str = Query(...), from_seq: int = Query(default=0)
) -> None:
    tokens = ws.app.state.tokens
    games: GameRegistry = ws.app.state.games
    info: TokenInfo | None = tokens.resolve(token)
    if info is None:
        await ws.close(code=4401)
        return
    try:
        handle = games.get(info.game_id)
    except LookupError:
        await ws.close(code=4404)
        return
    if not handle.started or handle.connections is None:
        await ws.close(code=4409)
        return
    await ws.accept()

    viewer: Any = info.seat if info.kind == "PLAYER" else "SPECTATOR"

    # 1) 重连补发：from_seq 起该视角可见历史
    history = games.store.load_events(info.game_id, from_seq=from_seq)
    await _send_event_frames(ws, handle, visible_events(handle.live_state(), history, viewer))

    # 2) 订阅实时流
    async def on_events(events: list[Event]) -> None:
        await _send_event_frames(ws, handle, events)

    handle.connections.subscribe(viewer, on_events)

    # 3) 玩家：attach your_turn 推送
    port: HumanPlayerPort | None = None
    if info.kind == "PLAYER" and info.seat is not None:
        port = handle.human_ports.get(info.seat)
        if port is not None:

            async def send_prompt(prompt: TurnPrompt) -> None:
                await ws.send_json({"type": "your_turn", **_your_turn_payload(prompt)})

            port.attach_sender(send_prompt)
            # 若连接时恰在窗口内，立即补推当前 prompt
            if port.current_prompt is not None:
                await send_prompt(port.current_prompt)

    try:
        while True:
            raw = await ws.receive_json()
            try:
                call = ToolCall.model_validate(raw)
                assert info.kind == "PLAYER" and info.seat is not None and port is not None
                action = parse_tool_call(call, actor_seat=info.seat)
                outcome = await port.submit_and_wait(action, timeout=10.0)
                await ws.send_json(
                    {
                        "type": "action_result",
                        "ok": outcome.ok,
                        "event_id": outcome.event_id,
                        "state_version": outcome.state_version,
                        "rejected_reason": outcome.rejected_reason,
                    }
                )
            except (ToolCallError, NotYourTurnError, AssertionError, TimeoutError) as exc:
                await ws.send_json({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        handle.connections.unsubscribe(viewer, on_events)
        if port is not None:
            port.detach_sender()
