"""HumanPlayerPort：开窗/提交/裁决回填/长轮询（issue #30）。"""

import asyncio
import time

import pytest

from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.engine import create_game
from app.engine.observation import build_observation
from app.engine.phases import Phase, expected_actors
from app.runtime.game_runner import GameLobby, GameRunner, RunnerTimeouts
from app.runtime.player_port import (
    BotPlayerPort,
    HumanPlayerPort,
    NotYourTurnError,
    PlayerPort,
    TurnPrompt,
)
from app.store.event_store import InMemoryEventStore


def _obs():  # type: ignore[no-untyped-def]
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    seat = sorted(expected_actors(state))[0]
    return state, seat, build_observation(state, seat)


async def test_act_arms_and_submit_resolves() -> None:
    state, seat, obs = _obs()
    port = HumanPlayerPort()
    task = asyncio.ensure_future(port.act(obs, deadline_ts=time.time() + 30))
    prompt = await port.wait_armed(1.0)
    assert isinstance(prompt, TurnPrompt) and prompt.observation.my_seat == seat
    action = RandomBot.choose_action(state, seat)
    outcome_fut = port.submit(action)
    assert await task == action
    # 模拟 runner 裁决回填
    port.notify_result(None, 5, "evt_00005")
    outcome = await outcome_fut
    assert outcome.ok and outcome.event_id == "evt_00005" and outcome.state_version == 5


async def test_submit_when_not_armed_raises() -> None:
    state, seat, _ = _obs()
    port = HumanPlayerPort()
    with pytest.raises(NotYourTurnError):
        port.submit(RandomBot.choose_action(state, seat))


async def test_sender_receives_prompt_and_bad_sender_detached() -> None:
    state, seat, obs = _obs()
    port = HumanPlayerPort()
    seen: list[TurnPrompt] = []

    async def sender(p: TurnPrompt) -> None:
        seen.append(p)
        raise RuntimeError("断线")

    port.attach_sender(sender)
    task = asyncio.ensure_future(port.act(obs, deadline_ts=time.time() + 30))
    await port.wait_armed(1.0)
    assert len(seen) == 1  # 推送已发生；抛错后 sender 被自摘除，窗口不受影响
    port.submit(RandomBot.choose_action(state, seat))
    await task


async def test_cancelled_window_backfills_window_closed() -> None:
    """提交与超时同 tick 竞争：act 被取消时，提交方必须收到 WINDOW_CLOSED 而非挂死。"""
    state, seat, obs = _obs()
    port = HumanPlayerPort()
    task = asyncio.ensure_future(port.act(obs, deadline_ts=time.time() + 30))
    await port.wait_armed(1.0)
    outcome_fut = port.submit(RandomBot.choose_action(state, seat))
    task.cancel()  # 模拟 runner wait_for 超时在同 tick 取消
    with pytest.raises(asyncio.CancelledError):
        await task
    outcome = await asyncio.wait_for(outcome_fut, 1.0)  # 不得挂死
    assert outcome.ok is False and outcome.rejected_reason == "WINDOW_CLOSED"
    with pytest.raises(NotYourTurnError):
        port.submit(RandomBot.choose_action(state, seat))  # 窗口已关


async def test_full_game_with_human_seat_via_port() -> None:
    """整局：seat 0 经 HumanPlayerPort 由测试驱动，裁决回填 ok；其余为 bot。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    lobby = GameLobby(cfg, game_id="g1")
    lobby.fill_with_bots()
    store = InMemoryEventStore()
    ports: dict[int, PlayerPort] = {}
    runner = GameRunner(
        store=store,
        config=cfg,
        game_id="g1",
        roster=lobby.roster(),
        ports=ports,
        timeouts=RunnerTimeouts(speech_sec=5.0, action_sec=5.0),
    )
    for seat in range(cfg.num_players):
        ports[seat] = BotPlayerPort(state_provider=lambda: runner.state)
    human = HumanPlayerPort()
    ports[0] = human

    prompt_count = [0]

    async def drive_human() -> None:
        while True:
            prompt = await human.wait_armed(5.0)
            if prompt is None:
                return  # 终局后不再开窗
            prompt_count[0] += 1
            action = RandomBot.choose_action(runner.state, 0)
            outcome = await human.submit_and_wait(action, timeout=5.0)
            assert outcome.ok, outcome.rejected_reason

    driver = asyncio.ensure_future(drive_human())
    final = await runner.run()
    driver.cancel()
    results = await asyncio.gather(driver, return_exceptions=True)
    for r in results:
        # 正常退出(None)或被取消是预期；驱动协程内的断言失败必须让测试失败
        assert r is None or isinstance(r, asyncio.CancelledError), r
    assert final.phase == Phase.GAME_OVER
    # 全程零超时代打：真人每窗都及时提交
    assert not any(e.meta.get("timeout") == "true" for e in store.load_events("g1"))
    # 真人座位至少被提示过一次
    assert prompt_count[0] > 0
