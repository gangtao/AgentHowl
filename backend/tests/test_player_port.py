"""PlayerPort 协议与 BotPlayerPort（issue #29）。asyncio_mode=auto，无需逐个标记。"""

import time

from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.observation import build_observation
from app.engine.phases import expected_actors
from app.runtime.player_port import BotPlayerPort, PlayerPort


async def test_bot_port_action_accepted_by_engine() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 42})
    state = create_game(cfg, game_id="g").state
    port = BotPlayerPort(state_provider=lambda: state)
    seat = sorted(expected_actors(state))[0]
    obs = build_observation(state, seat)
    action = await port.act(obs, deadline_ts=time.time() + 30)
    assert step(state, action).rejection is None


def test_bot_port_satisfies_protocol() -> None:
    port: PlayerPort = BotPlayerPort(state_provider=lambda: None)  # type: ignore[arg-type, return-value]
    assert hasattr(port, "act")
