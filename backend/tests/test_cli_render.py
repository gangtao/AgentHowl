"""CLI 叙述器（issue #44 Task 1）：事件/观察/工具渲染，纯函数无 IO。"""

import pytest

from app.cli.render import color, render_event, render_observation, render_tools
from app.engine.config import RoleType
from app.engine.events import (
    DeathAnnouncedPayload,
    Event,
    EventType,
    GameOverPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    Visibility,
    VoteCastPayload,
    VoteResultPayload,
    WolfSelfDestructPayload,
)
from app.engine.observation import PlayerObservation


def _ev(etype: EventType, payload, *, actor: int | None = None, vis=Visibility.PUBLIC) -> Event:
    return Event(
        seq=1, game_id="g", ts=1.0, type=etype, actor_seat=actor, payload=payload, visibility=vis
    )


@pytest.mark.parametrize(
    ("event"),
    [
        _ev(EventType.ROUND_STARTED, RoundStartedPayload(round=2)),
        _ev(EventType.PHASE_CHANGED, PhaseChangedPayload(to="VOTE")),
        _ev(EventType.PLAYER_SPOKE, PlayerSpokePayload(content="我是好人"), actor=3),
        _ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))),
        _ev(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=4)),
        _ev(EventType.VOTE_CAST, VoteCastPayload(voter=1, target=2)),
        _ev(EventType.VOTE_RESULT, VoteResultPayload(tally=((2, 3.0),), exiled=2, tie_seats=())),
        _ev(EventType.WOLF_SELF_DESTRUCT, WolfSelfDestructPayload(seat=6)),
        _ev(EventType.GAME_OVER, GameOverPayload(winner="GOOD")),
        # GM 视角事件也应可读
        _ev(
            EventType.SEER_CHECKED,
            SeerCheckedPayload(target=7, result="WOLF"),
            actor=8,
            vis=Visibility.ROLE_SELF,
        ),
    ],
)
def test_render_event_nonempty_readable(event: Event) -> None:
    out = render_event(event)
    assert isinstance(out, str) and out.strip()  # 非空
    assert "model_dump" not in out and "payload=" not in out  # 不是 raw dump


def test_render_event_speech_contains_content() -> None:
    ev = _ev(
        EventType.PLAYER_SPOKE,
        PlayerSpokePayload(content="我怀疑2号", claim_role=RoleType.SEER),
        actor=3,
    )
    out = render_event(ev)
    assert "我怀疑2号" in out and "3" in out


def test_render_death_and_gameover_wording() -> None:
    assert "5" in render_event(_ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(5,))))
    peaceful = render_event(_ev(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=())))
    assert peaceful.strip()  # 平安夜也有文案
    assert "GOOD" in render_event(_ev(EventType.GAME_OVER, GameOverPayload(winner="GOOD")))


def test_render_unknown_type_falls_back_readable() -> None:
    # ROLE_SKIPPED 未必特判 → 通用格式仍非空可读
    from app.engine.events import RoleSkippedPayload

    out = render_event(
        _ev(EventType.ROLE_SKIPPED, RoleSkippedPayload(role=RoleType.WITCH, reason="dead"))
    )
    assert out.strip()


def _obs(phase: str = "DAY_SPEECH") -> PlayerObservation:
    return PlayerObservation(
        game_id="g",
        state_version=1,
        my_seat=0,
        my_role=RoleType.SEER,
        my_status="ALIVE",
        phase=phase,
        round=1,
        seats=[{"seat": i, "alive": True, "is_sheriff": False} for i in range(9)],
        sheriff_seat=None,
        badge_flow_claims={},
        private={"check_results": [{"target": 3, "result": "WOLF"}]},
        available_actions=[0],
    )


def test_render_observation_and_tools() -> None:
    out = render_observation(_obs())
    assert "1" in out and ("预言家" in out or "SEER" in out)  # 角色出现
    assert "wolf_chat" not in out  # 内部键不外露
    tools = render_tools(("speak", "self_destruct", "get_game_state"))
    assert "speak" in tools


def test_color_disabled_is_plaintext() -> None:
    assert color("hi", "red", enabled=False) == "hi"
    assert "hi" in color("hi", "red", enabled=True)
