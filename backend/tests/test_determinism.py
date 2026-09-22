import pytest

from app.cli.bot import run_game
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import reduce_all
from app.engine.phases import Phase
from app.engine.state import GameState, Player

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


def _blank(final: GameState) -> GameState:
    players = tuple(
        Player(
            seat=p.seat,
            display_name=p.display_name,
            role=RoleType.VILLAGER,
            faction=Faction.GOOD,
        )
        for p in final.players
    )
    return GameState(
        game_id=final.game_id,
        config=final.config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [1, 17, 100])
def test_same_seed_byte_identical_event_log(preset: str, seed: int) -> None:
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    _, ev1 = run_game(cfg, game_id="g")
    _, ev2 = run_game(cfg, game_id="g")
    dump1 = [e.model_dump(mode="json") for e in ev1]
    dump2 = [e.model_dump(mode="json") for e in ev2]
    assert dump1 == dump2
    # issue #34：payload 须按运行时具体类序列化——否则上面的比较对负载恒为 {}、形同虚设
    roles = next(d for d in dump1 if d["type"] == "ROLES_ASSIGNED")
    assert roles["payload"].get("assignments"), "payload 序列化为空：比较未覆盖事件负载"
    assert all(d["payload"] != {} for d in dump1 if d["type"] not in ("GAME_STARTED",))


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [3, 42, 256])
def test_reduce_events_equals_live_state(preset: str, seed: int) -> None:
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    final, events = run_game(cfg, game_id="g")
    replayed = reduce_all(_blank(final), events)
    assert replayed.phase == final.phase == Phase.GAME_OVER
    assert replayed == final  # issue #37：全字段相等（逐步不变量见 test_replay_invariant.py）
