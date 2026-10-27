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

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.api.auth import user_from_cookie
from app.api.deps import TokenInfo
from app.api.rest import (
    _owner_locked,
    _session_viewer,
    _share_viewer,
    _your_turn_payload,
    viewer_of,
)
from app.api.views import event_json_for_viewer
from app.engine.events import Event, EventType
from app.engine.observation import visible_events
from app.runtime.connection import public_phase
from app.runtime.player_port import (
    ACCEPT_WAIT_SEC,
    HumanPlayerPort,
    NotYourTurnError,
    StalePromptError,
    SubmitOutcome,
    TurnPrompt,
)
from app.runtime.registry import GameRegistry
from app.schemas.actions import ToolCall, ToolCallError, parse_tool_call

router = APIRouter()


# ACCEPT_WAIT_SEC 定义在 app.runtime.player_port（REST / WS 共用）；这里保留模块级名字
# 以便测试 monkeypatch。
__all__ = ["ACCEPT_WAIT_SEC", "router"]


def _build_event_frames(
    events: list[Event],
    round_for: Callable[[Event], int],
    viewer: Any,
    *,
    visible_seqs: set[int] | None = None,
) -> list[dict[str, Any]]:
    """game_event + 由 PHASE_CHANGED/GAME_OVER 派生的附加帧（纯构建，不做 IO）。

    round_for 由调用方决定语义：补发路径传历史 seq→round 映射的查表函数，
    实时路径传返回当前 live round 的函数。
    viewer 用于 meta 字段过滤（issue #60）：非 GM 视角只保留公开 meta。

    phase_change 帧（issue #128）：GM 从可见事件派生、阶段名原样；非 GM 视角的夜间 PHASE_CHANGED
    是 GM_ONLY，故非 GM 的补发路径传**全量**历史加 `visible_seqs`——事件只对可见的发 game_event，
    phase_change 则对每条 PHASE_CHANGED 都发、阶段名经 public_phase 折叠。非 GM 实时路径
    （visible_seqs=None）这里不派生 phase_change，由 ConnectionManager 的阶段订阅统一供给，
    避免重复。
    """
    gm = viewer == "GM"
    frames: list[dict[str, Any]] = []
    for e in events:
        shown = visible_seqs is None or e.seq in visible_seqs
        if shown:
            event_json = event_json_for_viewer(e, viewer)
            frames.append({"type": "game_event", "seq": e.seq, "event": event_json})
        if e.type == EventType.PHASE_CHANGED and (gm or visible_seqs is not None):
            to = e.payload.to  # type: ignore[attr-defined]
            frames.append(
                {
                    "type": "phase_change",
                    "to": str(to) if gm else public_phase(to),
                    "round": round_for(e),
                }
            )
        if shown and e.type == EventType.GAME_OVER:
            frames.append(
                {"type": "game_over", "winner": e.payload.winner}  # type: ignore[attr-defined]
            )
    return frames


def _action_result_frame(outcome: SubmitOutcome) -> dict[str, Any]:
    return {
        "type": "action_result",
        "ok": outcome.ok,
        "event_id": outcome.event_id,
        "state_version": outcome.state_version,
        "rejected_reason": outcome.rejected_reason,
    }


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
    ws: WebSocket,
    token: str | None = Query(default=None),
    game_id: str | None = Query(default=None),
    share: str | None = Query(default=None),
    from_seq: int = Query(default=0),
) -> None:
    """三种入口：?token=（对局 token）| ?game_id=&share=（分享链接）| ?game_id=（会话 cookie）。"""
    # accept 必须在任何 close 之前：uvicorn 会把 accept 前的 close 折叠成 HTTP 403
    # 握手失败，浏览器端 WebSocket 只能看到 CloseEvent.code === 1006，拿不到下面
    # 这些 4xxx 关闭码（Starlette TestClient 在 accept 前也能送达 code，故测试未发现）。
    await ws.accept()

    tokens = ws.app.state.tokens
    games: GameRegistry = ws.app.state.games
    info: TokenInfo | None = None
    if token:
        info = tokens.resolve(token)
        if info is not None and info.kind == "GM" and _owner_locked(games, info.game_id):
            await ws.close(code=4403)  # 建局者已入座：上帝视角封锁（issue #115）
            return
    elif game_id:
        try:
            if share:
                info = _share_viewer(games, ws.app.state.secret, game_id, share)
            else:
                user = user_from_cookie(ws.app.state.users, ws.cookies)
                info = _session_viewer(games, user, game_id)
        except HTTPException as exc:
            await ws.close(code={403: 4403, 404: 4404}.get(exc.status_code, 4401))
            return
    if info is None:
        await ws.close(code=4401)
        return
    if info.kind not in ("PLAYER", "SPECTATOR", "GM"):
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

    viewer: Any = viewer_of(info)
    out_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_events(events: list[Event]) -> None:
        """实时订阅回调：只入队，不直接 send（issue #30 复审 Critical #1）。"""
        for frame in _build_event_frames(events, lambda _e: handle.live_state().round, viewer):
            out_q.put_nowait(frame)

    async def on_frame(frame: dict[str, Any]) -> None:
        out_q.put_nowait(frame)  # speech_audio / speech_audio_end：已按本连接视角过滤（issue #110）

    # 非 GM 视角的阶段帧去重（issue #135）：每个夜间子阶段的 PHASE_CHANGED 折叠后都是
    # ("NIGHT", round)，补发与实时两条路径共用同一个「上一条」记录，相邻重复只发一次。
    last_phase: tuple[str, int] | None = None

    def put_phase(to: str, rnd: int) -> None:
        nonlocal last_phase
        if viewer != "GM" and last_phase == (to, rnd):
            return
        last_phase = (to, rnd)
        out_q.put_nowait({"type": "phase_change", "to": to, "round": rnd})

    async def on_phases(phases: list[tuple[str, int]]) -> None:
        """非 GM 视角的阶段帧（issue #128）：夜间阶段对它们不可见，由此通道补上。"""
        for to, rnd in phases:
            put_phase(to, rnd)

    # ---- 关键同步块：先订阅、后读历史、再把历史帧入队，中间不 await ----
    # 单线程事件循环上，此顺序保证 subscribe 之后提交的事件只经 on_events 到达，
    # 之前的只存在于 history 里；不丢不重（issue #30 复审 Critical #1）。
    handle.connections.subscribe(viewer, on_events)
    handle.connections.subscribe_frames(viewer, on_frame)
    if viewer != "GM":
        handle.connections.subscribe_phases(on_phases)
    history = games.store.load_events(info.game_id, from_seq=from_seq)
    round_map = _seq_round_map(games.store.load_events(info.game_id))
    backfill = visible_events(handle.live_state(), history, viewer)
    if viewer == "GM":
        frames = _build_event_frames(backfill, lambda e: round_map.get(e.seq, 0), viewer)
    else:
        frames = _build_event_frames(
            history,
            lambda e: round_map.get(e.seq, 0),
            viewer,
            visible_seqs={e.seq for e in backfill},
        )
    for frame in frames:
        if frame["type"] == "phase_change":
            put_phase(frame["to"], frame["round"])
        else:
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
    closer_cb: Callable[[int], None] | None = None
    if info.kind == "PLAYER" and info.seat is not None:
        port = handle.human_ports.get(info.seat)
        if port is not None:

            async def send_prompt(prompt: TurnPrompt) -> None:
                out_q.put_nowait({"type": "your_turn", **_your_turn_payload(prompt)})

            sender_cb = send_prompt
            port.attach_sender(send_prompt)

            def window_closed(state_version: int) -> None:
                # issue #125：窗口被其它连接提交或超时关闭 → 本连接清掉残留 prompt
                out_q.put_nowait({"type": "window_closed", "state_version": state_version})

            closer_cb = window_closed
            port.attach_closer(window_closed)
            # 若连接时恰在窗口内，立即补推当前 prompt
            if port.current_prompt is not None:
                await send_prompt(port.current_prompt)

    # 迟到的裁决结果投递任务（同步窗口）：连接关闭时一并取消
    late_results: set[asyncio.Task[None]] = set()

    async def deliver_late(fut: asyncio.Future[SubmitOutcome]) -> None:
        out_q.put_nowait(_action_result_frame(await fut))

    try:
        while True:
            raw = await ws.receive_json()
            try:
                call = ToolCall.model_validate(raw)
                if not (info.kind == "PLAYER" and info.seat is not None and port is not None):
                    out_q.put_nowait({"type": "error", "detail": "该连接无行动权限或座位无端口"})
                    continue
                action = parse_tool_call(call, actor_seat=info.seat)
                fut = port.submit(action, state_version=call.state_version)
                try:
                    outcome = await asyncio.wait_for(asyncio.shield(fut), timeout=ACCEPT_WAIT_SEC)
                except TimeoutError:
                    # 同步窗口（上警 / 投票 / 狼刀提案）要等全体行动者到齐才裁决，结果可能迟到
                    # 整个时限（真机局里其他座位是 LLM）。提交已被端口接收（否则 submit 抛
                    # NotYourTurn），
                    # 先告知已受理，结果到了再补 action_result；连接期间 act() 必然以裁决或
                    # WINDOW_CLOSED 结束该 future，不会悬空。
                    out_q.put_nowait(
                        {"type": "action_accepted", "detail": "已提交，等待其他玩家行动后裁决"}
                    )
                    task = asyncio.create_task(deliver_late(fut))
                    late_results.add(task)
                    task.add_done_callback(late_results.discard)
                    continue
                out_q.put_nowait(_action_result_frame(outcome))
            except (ToolCallError, NotYourTurnError) as exc:
                # code（issue #125）：NOT_YOUR_TURN / STALE_PROMPT 表示该窗口对本连接已结束，
                # 前端据此清掉残留 prompt；TOOL_CALL 是参数错，窗口仍开着可重试
                code = (
                    "STALE_PROMPT"
                    if isinstance(exc, StalePromptError)
                    else "NOT_YOUR_TURN"
                    if isinstance(exc, NotYourTurnError)
                    else "TOOL_CALL"
                )
                out_q.put_nowait(
                    {"type": "error", "code": code, "detail": str(exc) or exc.__class__.__name__}
                )
    except WebSocketDisconnect:
        pass
    finally:
        # 先做不可跳过的清理，再回收 sender 任务（其死因与 teardown 无关，一律吞掉）
        handle.connections.unsubscribe(viewer, on_events)
        handle.connections.unsubscribe_frames(viewer, on_frame)
        handle.connections.unsubscribe_phases(on_phases)
        for task in late_results:
            task.cancel()
        if port is not None and sender_cb is not None:
            port.detach_sender(sender_cb)
        if port is not None and closer_cb is not None:
            port.detach_closer(closer_cb)
        sender_task.cancel()
        with contextlib.suppress(
            asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError
        ):
            await sender_task
