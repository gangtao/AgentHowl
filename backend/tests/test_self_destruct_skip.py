"""竞选期自爆「立即天黑」（issue #8）：死讯绕行猎人/遗言后仍跳过当天。"""

from app.engine.actions import NightAction, NightActionType, SelfDestruct, Speak
from app.engine.config import Faction, RoleType, build_preset
from app.engine.engine import step
from app.engine.events import Event, EventType, PhaseChangedPayload
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, Player


def _mk_player(seat: int, role: RoleType, alive: bool = True) -> Player:
    return Player(
        seat=seat,
        display_name=f"P{seat}",
        role=role,
        faction=Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD,
        alive=alive,
    )


def _election_state(night_deaths: tuple[int, ...] = (), **kw: object) -> GameState:
    """竞选期（死讯未公布）：7 人，狼 0/1，猎人 5。"""
    roles = [
        RoleType.WEREWOLF,
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.WITCH,
    ]
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 7, "seed": 1})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": tuple(_mk_player(i, r) for i, r in enumerate(roles)),
        "election_stage": "candidacy",
        "night_deaths": night_deaths,
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _no_day_speech(events: list[Event]) -> bool:
    return not any(
        e.type == EventType.PHASE_CHANGED
        and isinstance(e.payload, PhaseChangedPayload)
        and e.payload.to == Phase.DAY_SPEECH
        for e in events
    )


def test_selfdestruct_with_hunter_detour_skips_day() -> None:
    # 首夜刀死猎人(5)，死讯被竞选推迟；狼 0 自爆
    st = _election_state(night_deaths=(5,))
    all_events: list[Event] = []

    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    all_events += res.events
    st = res.state
    # 死讯公布后猎人可开枪 -> 绕行 HUNTER_SHOOT
    assert st.phase == Phase.HUNTER_SHOOT
    assert expected_actors(st) == {5}

    res = step(st, NightAction(actor_seat=5, action_type=NightActionType.SHOOT, target_seat=3))
    assert res.rejection is None
    all_events += res.events
    st = res.state
    # 首夜死者遗言（FIRST_NIGHT_ONLY，round 1）
    assert st.phase == Phase.LAST_WORDS
    while st.phase == Phase.LAST_WORDS:
        speaker = next(iter(expected_actors(st)))
        res = step(st, Speak(actor_seat=speaker, content="遗言"))
        assert res.rejection is None
        all_events += res.events
        st = res.state

    # 核心断言：处理完枪与遗言后直接入夜（round 2），全程无 DAY_SPEECH
    assert st.round == 2
    assert st.phase in (
        Phase.NIGHT_WEREWOLF,
        Phase.NIGHT_GUARD,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
    )
    assert _no_day_speech(all_events)
    assert st.skip_day is False  # 游标已消费


def test_selfdestruct_peaceful_night_synchronous_skip() -> None:
    # 平安夜（空死讯）：无绕行，同步直接入夜（原 hack 语义保留）
    st = _election_state(night_deaths=())
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert res.state.round == 2
    assert res.state.phase in (
        Phase.NIGHT_WEREWOLF,
        Phase.NIGHT_GUARD,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
    )
    assert _no_day_speech(res.events)
    assert res.state.skip_day is False


def test_day_selfdestruct_unchanged_and_flag_untouched() -> None:
    # 白天自爆路径不使用 skip_day（恒 False），行为照旧直接入夜
    roles = [RoleType.WEREWOLF, RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER, RoleType.WITCH]
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=2,
        players=tuple(_mk_player(i, r) for i, r in enumerate(roles)),
        speech_order=(0, 1, 2, 3, 4),
        speech_idx=0,
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert res.state.round == 3
    assert res.state.skip_day is False
