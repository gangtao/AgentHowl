"""局后复盘任务的生命周期（issue #68 / #70）：可观测、开局前等待、关停前等待。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi.testclient import TestClient

from app.agent.experience import AgentExperience
from app.engine.config import build_preset
from app.runtime.game_runner import RunnerTimeouts
from app.runtime.history import list_history
from app.runtime.registry import GameHandle, GameRegistry
from app.store.event_store import InMemoryEventStore
from tests.conftest import bearer, login_as, make_app


def _registry() -> GameRegistry:
    return GameRegistry(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
    )


def _create(reg: GameRegistry, cfg: Any) -> GameHandle:
    return reg.create(cfg, allow_spectators=True)


async def _slow_postgame(delay: float, flag: dict[str, bool]) -> dict[str, AgentExperience]:
    await asyncio.sleep(delay)
    flag["done"] = True
    return {}


async def test_pending_tasks_and_wait_by_memory_id() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 1})
    h1, h2 = _create(reg, cfg), _create(reg, cfg)
    h1.seat_memory_ids = {0: "alice", 3: "bob"}
    h2.seat_memory_ids = {0: "carol"}
    f1: dict[str, bool] = {}
    f2: dict[str, bool] = {}
    h1.postgame_task = asyncio.create_task(_slow_postgame(0.2, f1))
    h2.postgame_task = asyncio.create_task(_slow_postgame(5.0, f2))
    assert len(reg.pending_postgame_tasks()) == 2
    assert reg.pending_postgame_tasks(memory_ids={"bob"}) == [h1.postgame_task]
    assert reg.pending_postgame_tasks(memory_ids={"zoe"}) == []
    # 只等与本局 memory_id 有交集的：h2 还在跑也不挡
    assert await reg.wait_postgame(memory_ids={"alice"}, timeout=3.0) is True
    assert f1.get("done") is True
    # 有界等待：超时返回 False，任务不被取消
    assert await reg.wait_postgame(memory_ids={"carol"}, timeout=0.05) is False
    assert not h2.postgame_task.done()
    h2.postgame_task.cancel()


async def test_postgame_status_transitions() -> None:
    reg = _registry()
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 1})
    h = _create(reg, cfg)
    assert h.postgame_status() == "none"  # 无 memory_id 座位
    h.seat_memory_ids = {0: "alice"}
    assert h.postgame_status() == "none"  # 还没开局
    h.postgame_task = asyncio.create_task(_slow_postgame(0.05, {}))
    assert h.postgame_status() == "pending"
    await h.postgame_task
    assert h.postgame_status() == "done"

    async def boom() -> dict[str, AgentExperience]:
        raise RuntimeError("x")

    h.postgame_task = asyncio.create_task(boom())
    await asyncio.sleep(0)
    assert h.postgame_status() == "failed"


def test_history_rows_carry_postgame_status() -> None:
    """issue #70：GET /games 行带 postgame 进度；重启后只剩事件文件 → none。"""
    store = InMemoryEventStore()
    app = make_app(store=store, timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0))
    with TestClient(app) as client:
        login_as(client, "host")
        created = client.post(
            "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 3}}
        ).json()
        gid = created["game_id"]
        client.post(f"/api/v1/games/{gid}/start", json={}, headers=bearer(created["host_token"]))
        handle = client.app.state.games.get(gid)  # type: ignore[attr-defined]
        deadline = time.time() + 30
        while not (handle.task is not None and handle.task.done()) and time.time() < deadline:
            time.sleep(0.05)
        rows = {r["game_id"]: r for r in client.get("/api/v1/games").json()}
        assert rows[gid]["postgame"] == "none"  # 随机 bot 局：没有 memory_id
        # 伪造一个复盘中的终局
        handle.seat_memory_ids = {0: "alice"}
        flag: dict[str, bool] = {}
        client.portal.call(
            lambda: setattr(handle, "postgame_task", asyncio.create_task(_slow_postgame(3.0, flag)))
        )
        rows = {r["game_id"]: r for r in client.get("/api/v1/games").json()}
        assert rows[gid]["postgame"] == "pending"
        handle.postgame_task.cancel()
    # 注册表层：没有 handle 的历史局 → none
    reg = _registry()
    assert all(r.postgame == "none" for r in list_history(store, reg))


def test_start_waits_for_overlapping_memory_id_postgame() -> None:
    """issue #70：上一局同 memory_id 的复盘未落盘时，开局先（有界）等它完成。"""
    app = make_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
    )
    with TestClient(app) as client:
        login_as(client, "host")
        games = client.app.state.games  # type: ignore[attr-defined]
        g1 = client.post(
            "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 3}}
        ).json()
        h1 = games.get(g1["game_id"])
        h1.seat_memory_ids = {0: "alice"}
        flag: dict[str, bool] = {}
        client.portal.call(
            lambda: setattr(h1, "postgame_task", asyncio.create_task(_slow_postgame(0.5, flag)))
        )
        g2 = client.post(
            "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 4}}
        ).json()
        h2 = games.get(g2["game_id"])
        # 第二局的 memory_id 与上一局重叠（随机 bot 局本无档案，直接给注册表打桩）
        games.memory_ids_for_start = lambda handle: {"alice"} if handle is h2 else set()
        t0 = time.time()
        r = client.post(
            f"/api/v1/games/{g2['game_id']}/start", json={}, headers=bearer(g2["host_token"])
        )
        assert r.status_code == 200
        assert flag.get("done") is True  # 开局返回前上一局复盘已落盘
        assert time.time() - t0 >= 0.4
        # 不重叠的对局不等待
        g3 = client.post(
            "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 5}}
        ).json()
        t1 = time.time()
        client.post(
            f"/api/v1/games/{g3['game_id']}/start", json={}, headers=bearer(g3["host_token"])
        )
        assert time.time() - t1 < 0.4


def test_shutdown_waits_for_pending_postgame() -> None:
    """issue #68：lifespan 关停前有界等待未完成的复盘任务，经验得以落盘。"""
    app = make_app(
        store=InMemoryEventStore(), timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
    )
    flag: dict[str, bool] = {}
    with TestClient(app) as client:
        login_as(client, "host")
        created = client.post(
            "/api/v1/games", json={"preset": "std_9_kill_side", "config_override": {"seed": 3}}
        ).json()
        handle = client.app.state.games.get(created["game_id"])  # type: ignore[attr-defined]
        handle.seat_memory_ids = {0: "alice"}
        client.portal.call(
            lambda: setattr(handle, "postgame_task", asyncio.create_task(_slow_postgame(0.5, flag)))
        )
        assert flag.get("done") is None
    # with 退出触发 lifespan shutdown：任务应已被等到完成，而不是随事件循环关闭被取消
    assert flag.get("done") is True
    assert handle.postgame_task.done() and not handle.postgame_task.cancelled()
