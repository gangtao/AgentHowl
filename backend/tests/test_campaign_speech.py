"""上警发言子阶段（issue #47）：配置、事件契约、发言流、拒绝矩阵、回放保真。"""

from app.engine.config import (
    CampaignSpeechOrder,
    Faction,
    RoleType,
    SheriffRule,
    build_preset,
)
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    Visibility,
    reduce,
)
from app.engine.phases import ElectionStage, Phase, campaign_speaking, expected_actors
from app.engine.state import GameState, Player


def _players(n: int, wolves: tuple[int, ...] = (0,)) -> tuple[Player, ...]:
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
    n: int = 6,
    sheriff: SheriffRule | None = None,
    seed: int = 1,
    wolves: tuple[int, ...] = (0,),
    **kw: object,
) -> GameState:
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": n, "seed": seed})
    if sheriff is not None:
        cfg = cfg.model_copy(update={"sheriff": sheriff})
    base: dict[str, object] = {
        "game_id": "g",
        "config": cfg,
        "phase": Phase.SHERIFF_ELECTION,
        "round": 1,
        "players": _players(n, wolves=wolves),
        "night_deaths": (),
        "resolved_first_night": True,
    }
    base.update(kw)
    return GameState(**base)  # type: ignore[arg-type]


def _stage_evt(stage: ElectionStage, order: tuple[int, ...] | None = None) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=EventType.ELECTION_STAGE_CHANGED,
        actor_seat=None,
        payload=ElectionStageChangedPayload(stage=stage, speech_order=order),
        visibility=Visibility.PUBLIC,
    )


# ---------- Task 1：契约 ----------


def test_config_defaults() -> None:
    sr = SheriffRule()
    assert sr.campaign_speech_enabled is True
    assert sr.campaign_speech_order == CampaignSpeechOrder.JUDGE_ODD_EVEN
    assert {o.value for o in CampaignSpeechOrder} == {"JUDGE_ODD_EVEN", "SEAT_ASC"}


def test_stage_enum_has_speech() -> None:
    assert ElectionStage.SPEECH.value == "speech"


def test_reduce_speech_stage_sets_queue_and_resets_cursor() -> None:
    st = _state(election_stage="candidacy", speech_order=(9, 9, 9), speech_idx=3)
    new = reduce(st, _stage_evt(ElectionStage.SPEECH, (3, 1)))
    assert new.election_stage == "speech"
    assert new.speech_order == (3, 1)
    assert new.speech_idx == 0
    assert st.speech_idx == 3  # 原状态不变（纯函数）


def test_reduce_stage_without_order_keeps_queue() -> None:
    st = _state(election_stage="speech", speech_order=(3, 1), speech_idx=2)
    new = reduce(st, _stage_evt(ElectionStage.WITHDRAW))
    assert new.election_stage == "withdraw"
    assert new.speech_order == (3, 1) and new.speech_idx == 2


def test_payload_backward_compatible_with_old_logs() -> None:
    # 旧持久化日志无 speech_order 键
    p = ElectionStageChangedPayload.model_validate({"stage": "vote"})
    assert p.speech_order is None


def test_expected_actors_in_speech_stage() -> None:
    st = _state(
        election_stage="speech", sheriff_candidates=(1, 3), speech_order=(3, 1), speech_idx=0
    )
    assert campaign_speaking(st)
    assert expected_actors(st) == {3}
    st2 = st.model_copy(update={"speech_idx": 1})
    assert expected_actors(st2) == {1}
    done = st.model_copy(update={"speech_idx": 2})
    assert not campaign_speaking(done)
    assert expected_actors(done) == set()


def test_campaign_speaking_false_outside_speech_stage() -> None:
    # PK 发言期与其他子阶段不算上警发言
    assert not campaign_speaking(
        _state(election_stage="withdraw", speech_order=(1, 2), speech_idx=0)
    )
    assert not campaign_speaking(_state(phase=Phase.SHERIFF_PK, speech_order=(1, 2), speech_idx=0))
