from app.engine.actions import NightAction, NightActionType
from app.engine.config import Faction, RoleType
from app.engine.engine import create_game, step
from app.engine.events import Event, EventType, PlayerSpokePayload, Visibility
from app.engine.observation import build_observation, make_visibility_filter
from app.engine.state import GameState, living_of_role, living_wolves
from tests.factories import stage1_config


def _start() -> GameState:
    return create_game(stage1_config(seed=3), game_id="g").state


def test_non_wolf_has_no_teammates_or_chat() -> None:
    state = _start()
    for p in state.players:
        obs = build_observation(state, p.seat)
        if p.faction != Faction.WOLF:
            assert obs.private.get("teammates") in (None, [])
            assert obs.private.get("wolf_chat") in (None, [])


def test_wolf_sees_teammates() -> None:
    state = _start()
    wolf = living_wolves(state)[0]
    obs = build_observation(state, wolf.seat)
    teammates = obs.private["teammates"]
    assert set(teammates) == {w.seat for w in living_wolves(state)} - {wolf.seat}


def test_seer_private_has_check_results_after_check() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    state = step(
        state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer)
    ).state
    for w in wolves:
        state = step(
            state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=seer)
        ).state
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    state = step(state, NightAction(actor_seat=witch, action_type=NightActionType.SKIP)).state
    check = NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=wolves[0])
    state = step(state, check).state
    obs = build_observation(state, seer)
    results = obs.private["check_results"]
    assert any(r["seat"] == wolves[0] and r["result"] == Faction.WOLF.value for r in results)


def test_witch_sees_kill_only_with_antidote() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    victim = next(p.seat for p in state.players if p.role == RoleType.VILLAGER)
    state = step(state, NightAction(actor_seat=guard, action_type=NightActionType.SKIP)).state
    for w in wolves:
        state = step(
            state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=victim)
        ).state
    # 现在轮到女巫，且解药未用 -> 应看到刀口
    obs = build_observation(state, witch)
    assert obs.private["tonight_killed_seat"] == victim
    assert obs.private["antidote_available"] is True


def test_dead_player_gets_no_private_night_info() -> None:
    state = _start()
    # 手动把预言家标记死亡
    seer = living_of_role(state, RoleType.SEER)[0].seat
    players = tuple(
        p.model_copy(update={"alive": False}) if p.seat == seer else p for p in state.players
    )
    state = state.model_copy(update={"players": players})
    obs = build_observation(state, seer)
    assert obs.my_status == "DEAD"
    assert obs.private.get("check_results") in (None, [])


def _mk_event(vis: Visibility, actor: int | None = None) -> Event:
    return Event(
        seq=1, game_id="g", ts=1.0, type=EventType.PLAYER_SPOKE,
        actor_seat=actor, payload=PlayerSpokePayload(content="x"), visibility=vis,
    )


def test_visible_events_filtering() -> None:
    state = _start()
    wolf = living_wolves(state)[0].seat
    non_wolf = next(p.seat for p in state.players if p.faction == Faction.GOOD)
    evs = [
        _mk_event(Visibility.PUBLIC),
        _mk_event(Visibility.WOLVES),
        _mk_event(Visibility.ROLE_SELF, actor=wolf),
        _mk_event(Visibility.GM_ONLY),
    ]
    vis_for = make_visibility_filter(state)
    gm = vis_for(evs, "GM")
    assert len(gm) == 4
    spec = vis_for(evs, "SPECTATOR")
    assert [e.visibility for e in spec] == [Visibility.PUBLIC]
    wolf_view = vis_for(evs, wolf)
    assert Visibility.WOLVES in {e.visibility for e in wolf_view}
    assert Visibility.GM_ONLY not in {e.visibility for e in wolf_view}
    non_wolf_view = vis_for(evs, non_wolf)
    assert Visibility.WOLVES not in {e.visibility for e in non_wolf_view}
