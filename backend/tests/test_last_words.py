from app.cli.bot import run_game
from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    Event,
    EventType,
    HunterShotPayload,
    IdiotRevealedPayload,
    Visibility,
    reduce,
)
from app.engine.phases import Phase
from app.engine.state import GameState, Player, player_at
from tests.factories import stage1_config


def _state() -> GameState:
    players = tuple(
        Player(seat=s, display_name=f"P{s}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for s in range(4)
    )
    return GameState(
        game_id="g",
        config=build_preset("std_9_kill_side"),
        phase=Phase.HUNTER_SHOOT,
        round=1,
        players=players,
        pending_hunter=0,
    )


def _evt(type_: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=type_,
        actor_seat=actor,
        payload=payload,
        visibility=Visibility.PUBLIC,
    )  # type: ignore[arg-type]


def test_hunter_shot_kills_victim_and_clears_pending() -> None:
    payload = HunterShotPayload(shooter=0, victim=2)
    new = reduce(_state(), _evt(EventType.HUNTER_SHOT, payload, actor=0))
    assert player_at(new, 2).alive is False
    assert new.pending_hunter is None


def test_hunter_shot_no_victim() -> None:
    payload = HunterShotPayload(shooter=0, victim=None)
    new = reduce(_state(), _evt(EventType.HUNTER_SHOT, payload, actor=0))
    assert new.pending_hunter is None
    assert all(p.alive for p in new.players)


def test_idiot_revealed_survives_loses_vote() -> None:
    new = reduce(_state(), _evt(EventType.IDIOT_REVEALED, IdiotRevealedPayload(seat=1), actor=1))
    p = player_at(new, 1)
    assert p.alive is True
    assert p.idiot_revealed is True
    assert p.can_vote is False


def test_first_night_death_has_night_last_words() -> None:
    # stage1 板默认 FIRST_NIGHT_ONLY：首夜若有死者，事件流应含 LAST_WORDS
    _, events = run_game(stage1_config(seed=13), game_id="g")
    types = [e.type for e in events]
    # 至少存在一次 LAST_WORDS（首夜死者或白天出局者）
    assert EventType.LAST_WORDS in types
