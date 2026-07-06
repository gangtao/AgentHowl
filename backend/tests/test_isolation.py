from app.engine.actions import NightAction, NightActionType
from app.engine.config import Faction, RoleType
from app.engine.engine import create_game, step
from app.engine.events import (
    Event,
    EventType,
    PhaseChangedPayload,
    PlayerSpokePayload,
    SeerCheckedPayload,
    Visibility,
    WolfKillProposedPayload,
)
from app.engine.observation import build_observation, make_visibility_filter, visible_events
from app.engine.phases import Phase
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
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.PLAYER_SPOKE,
        actor_seat=actor,
        payload=PlayerSpokePayload(content="x"),
        visibility=vis,
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


def test_witch_no_kill_leak_after_antidote_used() -> None:
    # 解药用完且 knows_kill_after_antidote_used=False -> 不再注入刀口
    state = _start()
    witch_seat = living_of_role(state, RoleType.WITCH)[0].seat
    # 构造：女巫无解药，本夜有刀口
    players = tuple(
        p.model_copy(update={"witch_antidote": False}) if p.seat == witch_seat else p
        for p in state.players
    )
    victim = next(p.seat for p in state.players if p.role == RoleType.VILLAGER)
    st = state.model_copy(
        update={
            "players": players,
            "pending_night": state.pending_night.model_copy(update={"wolf_target": victim}),
        }
    )
    obs = build_observation(st, witch_seat)
    assert "tonight_killed_seat" not in obs.private
    assert obs.private["antidote_available"] is False


def test_every_visibility_class_filtered_correctly() -> None:
    state = _start()
    wolf = living_wolves(state)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat

    def ev(seq, type_, payload, vis, actor=None):
        return Event(
            seq=seq,
            game_id="g",
            ts=float(seq),
            type=type_,
            actor_seat=actor,
            payload=payload,
            visibility=vis,
        )

    events = [
        ev(
            1,
            EventType.PHASE_CHANGED,
            PhaseChangedPayload(to=Phase.NIGHT_WITCH),
            Visibility.GM_ONLY,
        ),
        ev(
            2,
            EventType.WOLF_KILL_PROPOSED,
            WolfKillProposedPayload(wolf_seat=wolf, target=0),
            Visibility.WOLVES,
            actor=wolf,
        ),
        ev(
            3,
            EventType.SEER_CHECKED,
            SeerCheckedPayload(target=0, result=Faction.WOLF),
            Visibility.ROLE_SELF,
            actor=seer,
        ),
    ]
    # 狼能看 WOLVES，看不到别人的 ROLE_SELF，看不到 GM_ONLY
    wolf_view = {e.seq for e in visible_events(state, events, wolf)}
    assert wolf_view == {2}
    seer_view = {e.seq for e in visible_events(state, events, seer)}
    assert seer_view == {3}
    spec_view = {e.seq for e in visible_events(state, events, "SPECTATOR")}
    assert spec_view == set()
    gm_view = {e.seq for e in visible_events(state, events, "GM")}
    assert gm_view == {1, 2, 3}
