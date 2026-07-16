"""WebSocket 端点（PRD §5.3）：按视角推送 + 行动帧 + 重连补发（issue #30）。

单写者队列设计（issue #30 复审加固，对应 Critical #1/#2、Important #1/#2、Minor #2）：
- ``ws.send_json`` 只由唯一的 sender 任务调用；receive 循环、订阅回调、your_turn
  推送都只把帧塞进 ``out_q``，避免运行中的 runner 回调任务与 receive 循环任务
  并发无锁调用 ``send_json`` 而互相插队/损坏帧。
- 订阅先于补发历史读取，且二者之间不 ``await``：单线程事件循环上，这保证
  ``subscribe`` 之后提交的事件只经 ``on_events`` 到达 ``out_q``，之前提交的
  只存在于 ``history`` 里——不丢事件，也不重复。
- 补发的 ``phase_change`` 帧携带的是事件发生当时的历史 round（服务端扫描
  全量 GM 事件流得到 seq→round 映射，与 ``rest.py`` 的 speeches 端点同一套路），
  而不是连接时刻的 live round；实时投递的帧则维持 live round（投递时即为当时值）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import TokenInfo
from app.api.rest import _your_turn_payload
from app.engine.events import Event, EventType
from app.engine.observation import visible_events
from app.runtime.player_port import HumanPlayerPort, NotYourTurnError, TurnPrompt
from app.runtime.registry import GameRegistry
from app.schemas.actions import ToolCall, ToolCallError, parse_tool_call
from app.store.event_store import event_to_json

router = APIRouter()


def _build_event_frames(
    events: list[Event], round_for: Callable[[Event], int]
) -> list[dict[str, Any]]:
    """game_event + 由可见 PHASE_CHANGED/GAME_OVER 派生的附加帧（纯构建，不做 IO）。

    round_for 由调用方决定语义：补发路径传历史 seq→round 映射的查表函数，
    实时路径传返回当前 live round 的函数。
    """
    frames: list[dict[str, Any]] = []
    for e in events:
        frames.append({"type": "game_event", "seq": e.seq, "event": event_to_json(e)})
        if e.type == EventType.PHASE_CHANGED:
            frames.append(
                {
                    "type": "phase_change",
                    "to": str(e.payload.to),  # type: ignore[attr-defined]
                    "round": round_for(e),
                }
            )
        if e.type == EventType.GAME_OVER:
            frames.append(
                {"type": "game_over", "winner": e.payload.winner}  # type: ignore[attr-defined]
            )
    return frames


def _seq_round_map(gm_events: list[Event]) -> dict[int, int]:
    """seq→round：以 GM 视角扫描全量事件流跟踪 ROUND_STARTED（同 rest.py speeches 套路）。"""
    out: dict[int, int] = {}
    cur_round = 0
    for e in gm_events:
        if e.type == EventType.ROUND_STARTED:
            cur_round = int(e.payload.round)  # type: ignore[attr-defined]
        out[e.seq] = cur_round
    return out


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
    if info.kind not in ("PLAYER", "SPECTATOR"):
        # HOST 无读流权限，与 REST require_kind 同口径（issue #30 复审 Important #2）
        await ws.close(code=4403)
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
    out_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_events(events: list[Event]) -> None:
        """实时订阅回调：只入队，不直接 send（issue #30 复审 Critical #1）。"""
        for frame in _build_event_frames(events, lambda _e: handle.live_state().round):
            out_q.put_nowait(frame)

    # ---- 关键同步块：先订阅、后读历史、再把历史帧入队，中间不 await ----
    # 单线程事件循环上，此顺序保证 subscribe 之后提交的事件只经 on_events 到达，
    # 之前的只存在于 history 里；不丢不重（issue #30 复审 Critical #1）。
    handle.connections.subscribe(viewer, on_events)
    history = games.store.load_events(info.game_id, from_seq=from_seq)
    round_map = _seq_round_map(games.store.load_events(info.game_id))
    backfill = visible_events(handle.live_state(), history, viewer)
    for frame in _build_event_frames(backfill, lambda e: round_map.get(e.seq, 0)):
        out_q.put_nowait(frame)
    # ---- 同步块结束 ----

    async def sender_loop() -> None:
        """唯一的 ws.send_json 调用点：串行消费队列，杜绝并发无锁 send。"""
        while True:
            frame = await out_q.get()
            await ws.send_json(frame)

    sender_task = asyncio.create_task(sender_loop())

    # 玩家：attach your_turn 推送（同样只入队）
    port: HumanPlayerPort | None = None
    sender_cb: Callable[[TurnPrompt], Awaitable[None]] | None = None
    if info.kind == "PLAYER" and info.seat is not None:
        port = handle.human_ports.get(info.seat)
        if port is not None:

            async def send_prompt(prompt: TurnPrompt) -> None:
                out_q.put_nowait({"type": "your_turn", **_your_turn_payload(prompt)})

            sender_cb = send_prompt
            port.attach_sender(send_prompt)
            # 若连接时恰在窗口内，立即补推当前 prompt
            if port.current_prompt is not None:
                await send_prompt(port.current_prompt)

    try:
        while True:
            raw = await ws.receive_json()
            try:
                call = ToolCall.model_validate(raw)
                if not (info.kind == "PLAYER" and info.seat is not None and port is not None):
                    out_q.put_nowait({"type": "error", "detail": "该连接无行动权限或座位无端口"})
                    continue
                action = parse_tool_call(call, actor_seat=info.seat)
                outcome = await port.submit_and_wait(action, timeout=10.0)
                out_q.put_nowait(
                    {
                        "type": "action_result",
                        "ok": outcome.ok,
                        "event_id": outcome.event_id,
                        "state_version": outcome.state_version,
                        "rejected_reason": outcome.rejected_reason,
                    }
                )
            except (ToolCallError, NotYourTurnError, TimeoutError) as exc:
                out_q.put_nowait({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        # 先做不可跳过的清理，再回收 sender 任务（其死因与 teardown 无关，一律吞掉）
        handle.connections.unsubscribe(viewer, on_events)
        if port is not None and sender_cb is not None:
            port.detach_sender(sender_cb)
        sender_task.cancel()
        with contextlib.suppress(
            asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError
        ):
            await sender_task
