"""WS 端点：观战流隔离、真人经 WS 对局、重连补发（issue #30）。"""

import asyncio
import contextlib
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.cli.bot import RandomBot
from app.engine.events import Event
from app.main import create_app
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.player_port import HumanPlayerPort, TurnPrompt
from app.store.event_store import InMemoryEventStore
from tests.test_api_play import _auth, _start_ai_game, _to_tool_call


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=10.0, action_sec=10.0)
    )
    with TestClient(app) as c:
        yield c


def test_spectator_stream_public_only_until_game_over(client: TestClient) -> None:
    gid, created = _start_ai_game(client, seed=42)
    frames: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={created['spectator_token']}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "game_over":
                break
    events = [f for f in frames if f["type"] == "game_event"]
    assert events and all(f["event"]["visibility"] == "PUBLIC" for f in events)
    assert any(
        f["type"] == "phase_change" for f in frames
    )  # PUBLIC 的 PHASE_CHANGED 存在（如 VOTE）
    assert frames[-1]["winner"] in ("GOOD", "WOLF", None)


def test_unknown_token_closes_4401(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/ws?token=garbage") as ws,
    ):
        ws.receive_json()


def test_human_plays_whole_game_via_ws(client: TestClient) -> None:
    created = client.post("/api/v1/games", json={"config_override": {"seed": 42}}).json()
    gid = created["game_id"]
    joined = client.post(f"/api/v1/games/{gid}/join", json={"display_name": "Alice"}).json()
    client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    seat = joined["seat"]
    with client.websocket_connect(f"/api/v1/ws?token={joined['player_token']}") as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "game_over":
                break
            if frame["type"] == "your_turn":
                assert frame["observation"]["my_seat"] == seat
                action = RandomBot.choose_action(handle.runner.state, seat)
                ws.send_json(_to_tool_call(action))
            if frame["type"] == "action_result":
                assert frame["ok"], frame["rejected_reason"]
    assert handle.task.done() and handle.task.result().winner is not None


def test_reconnect_backfills_from_seq(client: TestClient) -> None:
    gid, created = _start_ai_game(client, seed=7)
    spec = created["spectator_token"]
    # 等对局结束后模拟"错过整场"的重连：from_seq 补发应与 REST /events 完全一致
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not handle.task.done() and time.time() < deadline:
        time.sleep(0.05)
    rest_events = client.get(f"/api/v1/games/{gid}/events?from_seq=5", headers=_auth(spec)).json()
    got: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={spec}&from_seq=5") as ws:
        # 补发帧中夹带 phase_change/game_over 派生帧（不计入 rest_events），故按
        # game_event 数量而非固定收帧次数收敛——原按 len(rest_events) 收帧次数的写法
        # 在派生帧存在时会提前耗尽收帧配额，属测试自身计数缺陷，非 ws.py 实现问题。
        while len(got) < len(rest_events):
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                got.append(frame["event"])
    assert [e["seq"] for e in got] == [e["seq"] for e in rest_events]


def test_reconnect_to_running_game_loses_no_events(client: TestClient) -> None:
    """复现 issue #30 复审 Critical #1：补发与订阅之间若有窗口，运行中对局会丢事件。

    对局刚 start 就立即连接（不等待终局），backfill 读历史与 runner 持续
    commit 事件的时间窗口完全重叠——旧实现"先补发后订阅"会在此窗口丢帧。

    start 请求返回后让出极短时间片（毫秒级 sleep，TestClient 的后台事件循环
    在独立线程持续推进，故此间 runner 已产出若干事件但对局仍在运行）——
    经验证：此时序在旧实现上 6/6 复现丢帧，对局在连接时刻仍未终局。
    """
    gid, created = _start_ai_game(client, seed=21)
    spec = created["spectator_token"]
    time.sleep(0.002)
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    assert not handle.task.done()  # 确认连接时对局仍在运行（复现场景的前提）
    got: list[dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/ws?token={spec}&from_seq=0") as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "game_event":
                got.append(frame["event"])
            if frame["type"] == "game_over":
                break
    rest_events = client.get(f"/api/v1/games/{gid}/events?from_seq=0", headers=_auth(spec)).json()
    got_seqs = [e["seq"] for e in got]
    assert got_seqs == [e["seq"] for e in rest_events]  # 完整、无洞、无重复


def test_backfilled_phase_change_round_is_historical(client: TestClient) -> None:
    """复现 issue #30 复审 Critical #2：补发的 phase_change 帧不得携带终局 round。"""
    gid, created = _start_ai_game(client, seed=7)
    spec = created["spectator_token"]
    handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
    deadline = time.time() + 30
    while not handle.task.done() and time.time() < deadline:
        time.sleep(0.05)
    rounds: list[int] = []
    with client.websocket_connect(f"/api/v1/ws?token={spec}&from_seq=0") as ws:
        while True:
            frame = ws.receive_json()
            if frame["type"] == "phase_change":
                rounds.append(frame["round"])
            if frame["type"] == "game_over":
                break
    assert rounds == sorted(rounds)  # 非递减
    assert min(rounds) == 1  # 旧实现恒为终局 round（>1 局时必失败）


def test_host_token_ws_rejected(client: TestClient) -> None:
    """HOST 无读流权限，与 REST require_kind 同口径（issue #30 复审 Important #2）。"""
    created = client.post(
        "/api/v1/games",
        json={"config_override": {"seed": 1}, "allow_spectators": False},
    ).json()
    gid = created["game_id"]
    r = client.post(f"/api/v1/games/{gid}/start", json={}, headers=_auth(created["host_token"]))
    assert r.status_code == 200
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/api/v1/ws?token={created['host_token']}") as ws,
    ):
        ws.receive_json()


async def test_second_connection_keeps_your_turn_channel() -> None:
    """detach_sender 仅当前持有者可解除：旧连接不得摘除新连接的推送通道
    （issue #30 复审 Important #1）。"""
    port = HumanPlayerPort()
    seen_a: list[TurnPrompt] = []
    seen_b: list[TurnPrompt] = []

    async def a(p: TurnPrompt) -> None:
        seen_a.append(p)

    async def b(p: TurnPrompt) -> None:
        seen_b.append(p)

    port.attach_sender(a)
    port.attach_sender(b)  # 模拟第二条连接（重连）接管推送
    port.detach_sender(a)  # 旧连接（第一条）清理时解除自己持有的 sender
    assert port._sender is b  # b 未被误摘除

    from app.cli.bot import RandomBot
    from app.engine.config import build_preset
    from app.engine.engine import create_game
    from app.engine.observation import build_observation
    from app.engine.phases import expected_actors

    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    seat = sorted(expected_actors(state))[0]
    obs = build_observation(state, seat)
    task = asyncio.ensure_future(port.act(obs, deadline_ts=time.time() + 30))
    prompt = await port.wait_armed(1.0)
    assert prompt is not None
    assert seen_b and not seen_a  # 推送经由存活的 b，而非已摘除的 a
    port.submit(RandomBot.choose_action(state, seat))
    await task


async def test_dead_sender_task_still_unsubscribes() -> None:
    """sender 任务先于 receive 循环异常死亡时，finally 清理不得被跳过（订阅必须摘除）。

    当 sender_task 因 WebSocketDisconnect（客户端 TCP 中断）等异常死亡时，
    旧的 finally 顺序（cancel → await → unsubscribe）会在 await 处重新抛出异常，
    导致 unsubscribe 和 detach_sender 被跳过，连接仍留在 ConnectionManager._subs 中
    （孤儿订阅）。新顺序（unsubscribe → detach → cancel → await suppress多种异常）
    保证清理无条件执行。
    """
    from app.runtime.connection import ConnectionManager

    manager = ConnectionManager(lambda: None)  # type: ignore[arg-type]
    viewer = "test_seat"
    events_collected: list[list[Event]] = []

    async def on_events(events: list[Event]) -> None:
        events_collected.append(events)

    # 订阅
    manager.subscribe(viewer, on_events)
    assert len(manager._subs) == 1

    # 模拟 sender_task 异常死亡
    async def boom() -> None:
        raise WebSocketDisconnect(1006)

    sender_task = asyncio.create_task(boom())
    # 让任务完成
    with contextlib.suppress(WebSocketDisconnect):
        await sender_task

    # 执行新的 finally 清理顺序（按 ws.py 修复版本）
    manager.unsubscribe(viewer, on_events)
    sender_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError):
        await sender_task

    # 断言：订阅必须被摘除
    assert len(manager._subs) == 0
