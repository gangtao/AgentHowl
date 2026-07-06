import pytest

from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.events import EventType
from app.engine.phases import Phase

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


@pytest.mark.parametrize("preset", PRESETS)
def test_sweep_125_seeds_each_terminates(preset: str) -> None:
    # 4 preset × 125 seed = 500 局
    for seed in range(125):
        cfg = build_preset(preset).model_copy(update={"seed": seed})
        final, events = run_game(cfg, game_id=f"{preset}-{seed}")
        assert final.phase == Phase.GAME_OVER, f"{preset} seed={seed} 未终局"
        go = [e for e in events if e.type == EventType.GAME_OVER]
        assert len(go) == 1, f"{preset} seed={seed} GAME_OVER 事件数={len(go)}"
        # 有胜负或达 max_rounds 平局
        assert final.winner in ("GOOD", "WOLF", None)
