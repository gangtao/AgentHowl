"""GameRunner 集成：12 bot 全自动经 runner + store 跑完整局（issue #29）。"""

import asyncio
from pathlib import Path

import pytest

from app.engine.actions import Action, Speak
from app.engine.config import build_preset
from app.engine.events import EventType
from app.engine.observation import PlayerObservation
from app.engine.phases import Phase
from app.runtime.connection import ConnectionManager
from app.runtime.game_runner import GameLobby, GameRunner, LobbyError, RunnerTimeouts
from app.runtime.player_port import BotPlayerPort, PlayerPort
from app.store.event_store import (
    EventStore,
    InMemoryEventStore,
    JsonFileEventStore,
    load_state,
)


def _make_runner(store: EventStore, seed: int = 42, preset: str = "std_12_yn_hunter_idiot"):  # type: ignore[no-untyped-def]
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        connections=ConnectionManager(state_provider=lambda: runner.state),
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    return runner


class HangingPort:
    """永不返回的端口：模拟断线/挂起玩家。"""

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class AlwaysInvalidPort:
    """永远提交非法 intent（夜里发言必 WRONG_PHASE；白天发言合法，故包一层计数狼刀自己）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self.calls += 1
        # 对任意阶段都非法：actor 座位冒用他人（NOT_YOUR_TURN）
        other = (observation.my_seat + 1) % 9
        return Speak(actor_seat=other, content="(evil)")


class RetryOncePort:
    """每个窗口先交一次非法 intent，被拒后交出合法 bot 行动：验证重试成功路径。"""

    def __init__(self, inner: PlayerPort) -> None:
        self._inner = inner
        self.calls = 0

    async def act(self, observation: PlayerObservation, deadline_ts: float) -> Action:
        self.calls += 1
        if self.calls % 2 == 1:
            other = (observation.my_seat + 1) % 9
            return Speak(actor_seat=other, content="(oops)")
        return await self._inner.act(observation, deadline_ts)


def _make_special_runner(
    store: EventStore, seed: int, timeouts: RunnerTimeouts
) -> tuple[GameRunner, dict[int, PlayerPort]]:
    """9 人局，全 bot；调用方把 seat 0 换成特殊端口后 run。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": seed})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        timeouts=timeouts,
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    return runner, ports


class TestLobby:
    def test_join_assigns_seats_and_rejects_overflow(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        assert lobby.join("Alice") == 0
        assert lobby.join("Bob", player_type="AGENT") == 1
        lobby.fill_with_bots()
        assert lobby.is_full
        with pytest.raises(LobbyError):
            lobby.join("Carol")
        roster = lobby.roster()
        assert roster[0].display_name == "Alice"
        assert roster[0].player_type == "HUMAN"
        assert roster[2].display_name == "Bot2"

    def test_roster_requires_full(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        lobby.join("Alice")
        with pytest.raises(LobbyError):
            lobby.roster()

    def test_game_meta_matches_roster(self) -> None:
        cfg = build_preset("std_9_kill_side")
        lobby = GameLobby(cfg, game_id="g1")
        lobby.fill_with_bots()
        meta = lobby.game_meta()
        assert meta.game_id == "g1"
        assert [s.display_name for s in meta.roster] == [f"Bot{i}" for i in range(9)]


class TestRunnerIntegration:
    async def test_full_game_memory_store(self) -> None:
        store = InMemoryEventStore()
        runner = _make_runner(store)
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        events = store.load_events("g1")
        # 生命周期头 + 落库回放终局口径一致（winner/alive；游标字段不保证，见 engine 游标注释）
        assert [e.type for e in events[:2]] == [EventType.GAME_CREATED, EventType.GAME_STARTED]
        replayed = load_state(store, "g1")
        assert replayed.winner == final.winner
        assert [p.alive for p in replayed.players] == [p.alive for p in final.players]
        # runtime meta 充实：每事件带墙钟
        assert all("wall_ts" in e.meta for e in events)

    async def test_full_game_jsonl_store_cold_reload(self, tmp_path: Path) -> None:
        store = JsonFileEventStore(tmp_path / "d")
        runner = _make_runner(store, seed=7)
        final = await runner.run()
        cold = JsonFileEventStore(tmp_path / "d")
        replayed = load_state(cold, "g1")
        assert replayed.phase == Phase.GAME_OVER
        assert replayed.winner == final.winner

    async def test_spectator_stream_is_public_only(self) -> None:
        store = InMemoryEventStore()
        runner = _make_runner(store, seed=9)
        got: list[EventType] = []

        async def spec_cb(events) -> None:  # type: ignore[no-untyped-def]
            got.extend(e.type for e in events)

        assert runner.connections is not None
        runner.connections.subscribe("SPECTATOR", spec_cb)
        await runner.run()
        assert EventType.GAME_CREATED in got
        assert EventType.ROLES_ASSIGNED not in got  # GM_ONLY 不得泄给观众


def test_runner_timeouts_from_config() -> None:
    cfg = build_preset("std_9_kill_side")
    t = RunnerTimeouts.from_config(cfg)
    assert t.speech_sec == float(cfg.speech_timeout_sec)
    assert t.action_sec == float(cfg.action_timeout_sec)


class TestTimeoutAndRetry:
    async def test_hanging_port_replaced_by_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=0.02, action_sec=0.02)
        )
        ports[0] = HangingPort()
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        events = store.load_events("g1")
        timed_out = [e for e in events if e.meta.get("timeout") == "true"]
        assert timed_out, "挂起座位必须留下超时代打事件"
        replayed = load_state(store, "g1")
        assert replayed.winner == final.winner

    async def test_rejections_exhausted_falls_to_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5)
        )
        evil = AlwaysInvalidPort()
        ports[0] = evil
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        assert evil.calls >= 3  # 至少被重试到上限一次
        events = store.load_events("g1")
        assert any(e.meta.get("timeout") == "true" for e in events)

    async def test_retry_then_valid_needs_no_default(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0)
        )
        retry = RetryOncePort(BotPlayerPort(state_provider=lambda: runner.state))
        ports[0] = retry
        final = await runner.run()
        assert final.phase == Phase.GAME_OVER
        assert retry.calls >= 2  # 至少发生过一次「拒绝 → 重试成功」
        events = store.load_events("g1")
        # 重试全部成功：全局不应出现任何超时代打事件（其余座位是即时 bot）
        assert not any(e.meta.get("timeout") == "true" for e in events)

    async def test_missing_port_raises_RuntimeError(self) -> None:
        store = InMemoryEventStore()
        runner, ports = _make_special_runner(
            store, seed=42, timeouts=RunnerTimeouts(speech_sec=0.5, action_sec=0.5)
        )
        del ports[0]
        with pytest.raises(RuntimeError, match="未接入"):
            await runner.run()
