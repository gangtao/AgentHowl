import pytest
from pydantic import ValidationError

from app.engine.actions import (
    DayVote,
    NightAction,
    NightActionType,
    SelfDestruct,
    Speak,
)


def test_night_action_construct() -> None:
    a = NightAction(actor_seat=3, action_type=NightActionType.CHECK, target_seat=5)
    assert a.actor_seat == 3
    assert a.action_type == NightActionType.CHECK
    assert a.target_seat == 5


def test_night_action_skip_allows_no_target() -> None:
    a = NightAction(actor_seat=2, action_type=NightActionType.SKIP)
    assert a.target_seat is None


def test_day_vote_abstain() -> None:
    v = DayVote(actor_seat=1, abstain=True)
    assert v.abstain is True
    assert v.target_seat is None


def test_speak_defaults() -> None:
    s = Speak(actor_seat=0, content="hello")
    assert s.claim_role is None
    assert s.badge_flow == ()


def test_self_destruct_only_actor() -> None:
    sd = SelfDestruct(actor_seat=7)
    assert sd.actor_seat == 7


def test_action_is_frozen() -> None:
    a = NightAction(actor_seat=1, action_type=NightActionType.SKIP)
    with pytest.raises(ValidationError):
        a.actor_seat = 2  # type: ignore[misc]
