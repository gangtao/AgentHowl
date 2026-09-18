"""狼队刀口收敛（issue #46）：可见提案、收敛轮、末轮兜底、回放保真。"""

import pytest

from app.engine.config import (
    ConfigError,
    Faction,
    GameConfig,
    RoleType,
    WolfKillRule,
    build_preset,
    validate_config,
)
from app.engine.events import (
    Event,
    EventType,
    RoundStartedPayload,
    Visibility,
    WolfKillRevotePayload,
    reduce,
)
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player

WOLVES = (0, 1, 2)


def _players(n: int = 9, wolves: tuple[int, ...] = WOLVES) -> tuple[Player, ...]:
    return tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=RoleType.WEREWOLF if i in wolves else RoleType.VILLAGER,
            faction=Faction.WOLF if i in wolves else Faction.GOOD,
        )
        for i in range(n)
    )


def _state(
    proposals: dict[int, int | None] | None = None,
    rule: WolfKillRule = WolfKillRule.UNANIMOUS_OR_NO_KILL,
    rounds: int = 2,
    seed: int = 1,
    **kw: object,
) -> GameState:
    """夜间狼阶段状态：3 狼 6 民；proposals 为本轮已提交的提案。"""
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"seed": seed, "wolf_kill_rule": rule, "wolf_consensus_rounds": rounds}
    )
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.NIGHT_WEREWOLF,
        "round": 1,
        "players": _players(),
        "wolf_proposals": dict(proposals or {}),
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _evt(etype: EventType, payload: object, vis: Visibility = Visibility.WOLVES) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=etype,
        actor_seat=None,
        payload=payload,  # type: ignore[arg-type]
        visibility=vis,
    )


# ---------- Task 1：契约 ----------


def test_config_default_and_validation() -> None:
    assert GameConfig(config_id="x").wolf_consensus_rounds == 2
    for name in ("std_12_yn_hunter_idiot", "std_9_kill_side"):
        assert build_preset(name).wolf_consensus_rounds == 2
    with pytest.raises(ConfigError, match="wolf_consensus_rounds"):
        validate_config(
            build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 0})
        )
    validate_config(build_preset("std_9_kill_side").model_copy(update={"wolf_consensus_rounds": 1}))


def test_state_defaults() -> None:
    st = _state()
    assert st.wolf_kill_round == 1
    assert st.wolf_proposal_history == ()


def test_reduce_revote_clears_proposals_and_records_history() -> None:
    st = _state({0: 8, 1: 3, 2: 8})
    snapshot = ((0, 8), (1, 3), (2, 8))
    new = reduce(
        st,
        _evt(
            EventType.WOLF_KILL_REVOTE,
            WolfKillRevotePayload(round_no=1, proposals=snapshot),
        ),
    )
    assert new.wolf_proposals == {}
    assert new.wolf_kill_round == 2
    assert new.wolf_proposal_history == (snapshot,)
    assert new.acted_seats == st.acted_seats  # 其他角色的已行动记录不受影响
    assert st.wolf_proposals == {0: 8, 1: 3, 2: 8}  # 纯函数：原状态不变
    # 狼重新成为行动者
    assert expected_actors(new) == set(WOLVES)


def test_reduce_round_started_resets_round_and_history() -> None:
    st = _state(wolf_kill_round=3, wolf_proposal_history=(((0, 8), (1, 3), (2, 8)),))
    new = reduce(st, _evt(EventType.ROUND_STARTED, RoundStartedPayload(round=2), Visibility.PUBLIC))
    assert new.wolf_kill_round == 1
    assert new.wolf_proposal_history == ()
    assert new.wolf_proposals == {}


def test_revote_payload_is_mapped_for_fail_loud_reduce() -> None:
    from app.engine.events import EVENT_PAYLOAD_TYPES

    assert EVENT_PAYLOAD_TYPES[EventType.WOLF_KILL_REVOTE] is WolfKillRevotePayload
