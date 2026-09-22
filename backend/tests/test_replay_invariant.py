"""事件溯源不变量（issue #37）：每步 `step` 后 `reduce_all(step 前状态, 本步事件) == step 后状态`。

M1 曾对「游标字段」豁免（sheriff_confirmed / PK 收窄的 sheriff_candidates / pending_hunter /
resume_token / skip_day 直接 model_copy 写入，不经事件）。本测试把豁免收回：全字段相等，含
state_version。这是断线续局与前端 TS reducer 对齐的前提。
"""

import pytest

from app.cli.bot import RandomBot
from app.engine.config import build_preset
from app.engine.engine import create_game, step
from app.engine.events import reduce_all
from app.engine.phases import Phase, expected_actors
from tests.test_determinism import PRESETS, _blank


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", [1, 7, 42, 99])
def test_every_step_is_reproducible_from_its_events(preset: str, seed: int) -> None:
    cfg = build_preset(preset).model_copy(update={"seed": seed})
    res = create_game(cfg, "g")
    assert reduce_all(_blank(res.state), res.events) == res.state
    state, events = res.state, list(res.events)
    guard = 0
    while state.phase != Phase.GAME_OVER:
        actors = sorted(expected_actors(state))
        assert actors, f"无人可行动但未终局：phase={state.phase}"
        for seat in actors:
            if seat not in expected_actors(state):
                continue
            before = state
            res = step(state, RandomBot.choose_action(state, seat))
            assert res.rejection is None
            replayed = reduce_all(before, res.events)
            assert replayed == res.state, (
                f"step 不可复现 @ {before.phase}/{before.election_stage!r} seat={seat}: "
                f"{_diff(replayed, res.state)}"
            )
            state = res.state
            events.extend(res.events)
        guard += 1
        assert guard < 100_000
    # 终局：从空白状态全量回放也全等（不再排除任何字段）
    assert reduce_all(_blank(state), events) == state


def _diff(a: object, b: object) -> dict[str, tuple[object, object]]:
    da, db = a.model_dump(), b.model_dump()  # type: ignore[attr-defined]
    return {k: (da[k], db[k]) for k in da if da[k] != db[k]}
