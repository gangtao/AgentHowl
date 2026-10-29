# backend/tests/test_narration.py
"""旁白模板（issue #110）：事件 → 口播句子；白名单外返回空；全 preset 整局覆盖。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.profile import VoiceSpec
from app.cli.bot import run_game
from app.engine.config import PRESET_NAMES, build_preset
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
    Event,
    EventType,
    GameCreatedPayload,
    GameOverPayload,
    GameStartedPayload,
    GuardProtectedPayload,
    HunterShotPayload,
    IdiotRevealedPayload,
    NightResolvedPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    SheriffBadgeLostPayload,
    SheriffCandidacyPayload,
    SheriffDirectionSetPayload,
    SheriffElectedPayload,
    SheriffVoteCastPayload,
    SheriffVoteStartedPayload,
    SheriffWithdrewPayload,
    Visibility,
    VoteCastPayload,
    VoteResultPayload,
    VoteStartedPayload,
    WitchActedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfKillRevotePayload,
    WolfSelfDestructPayload,
)
from app.engine.phases import ElectionStage, Phase
from app.runtime.narration import (
    DEFAULT_NARRATION_EVENTS,
    TEMPLATED_EVENTS,
    NarrationCache,
    NarrationConfig,
    narrate,
    seats,
)
from tests.test_speech_audio import _wav  # noqa: E402  合法 WAV 生成器（已存在）


def _evt(t: EventType, payload: object, actor: int | None = None) -> Event:
    return Event(
        seq=1,
        game_id="g",
        ts=1.0,
        type=t,
        actor_seat=actor,
        payload=payload,
        visibility=Visibility.PUBLIC,  # type: ignore[arg-type]
    )


def test_seats_joiner() -> None:
    assert seats([3, 7]) == "3号、7号"
    assert seats([]) == ""


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (_evt(EventType.ROUND_STARTED, RoundStartedPayload(round=2)), ["第2轮，天黑请闭眼。"]),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WEREWOLF)),
            ["狼人请睁眼。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_GUARD)),
            ["守卫请睁眼。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_WITCH)),
            ["女巫请睁眼。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_SEER)),
            ["预言家请睁眼。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.NIGHT_HUNTER_CONFIRM)),
            ["猎人请确认状态。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_ELECTION)),
            ["天亮了，进入警长竞选。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.SHERIFF_PK)),
            ["警长竞选进入PK。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DEATH_ANNOUNCE)), ["天亮了。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.LAST_WORDS)), ["请发表遗言。"]),
        (
            _evt(
                EventType.PHASE_CHANGED,
                PhaseChangedPayload(to=Phase.DAY_SPEECH, speech_order=(1, 3)),
            ),
            ["进入发言环节，顺序：1号、3号。"],
        ),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.DAY_SPEECH)),
            ["进入发言环节。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE)), ["进入放逐投票。"]),
        (
            _evt(
                EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK, speech_order=(2, 5))
            ),
            ["平票PK，发言顺序：2号、5号。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.VOTE_PK)), ["平票PK。"]),
        (
            _evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.HUNTER_SHOOT)),
            ["猎人请开枪。"],
        ),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.IDIOT_FLIP)), ["白痴翻牌。"]),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.EXILE)), []),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.WIN_CHECK)), []),
        (_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=Phase.GAME_OVER)), []),
        (
            _evt(EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=(3, 7))),
            ["本夜结算，出局：3号、7号。"],
        ),
        (_evt(EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=())), ["本夜结算，平安夜。"]),
        (
            _evt(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=(3, 7))),
            ["昨夜出局的是3号、7号。"],
        ),
        (
            _evt(EventType.DEATH_ANNOUNCED, DeathAnnouncedPayload(seats=())),
            ["昨夜是平安夜，无人出局。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.CANDIDACY),
            ),
            ["上警报名开始。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.SPEECH, speech_order=(1, 3, 6)),
            ),
            ["上警发言，顺序：1号、3号、6号。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.SPEECH),
            ),
            ["上警发言。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.WITHDRAW),
            ),
            ["退水确认。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.VOTE),
            ),
            ["警下投票开始。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.DIRECTION),
            ),
            ["请警长决定发言方向。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.ANNOUNCE),
            ),
            ["公布竞选结果。"],
        ),
        (
            _evt(
                EventType.ELECTION_STAGE_CHANGED,
                ElectionStageChangedPayload(stage=ElectionStage.NONE),
            ),
            ["竞选环节结束。"],
        ),
        (
            _evt(EventType.SHERIFF_VOTE_STARTED, SheriffVoteStartedPayload(candidates=(1, 4))),
            ["警长开票，候选人：1号、4号。"],
        ),
        (_evt(EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=4)), ["4号当选警长。"]),
        (
            _evt(EventType.BADGE_PASSED, BadgePassedPayload(from_seat=4, to_seat=2)),
            ["4号把警徽移交给2号。"],
        ),
        (
            _evt(EventType.BADGE_PASSED, BadgePassedPayload(from_seat=4, to_seat=None)),
            ["4号撕毁警徽。"],
        ),
        (
            _evt(EventType.VOTE_STARTED, VoteStartedPayload(candidates=(), tie_round=0)),
            ["投票开始。"],
        ),
        (
            _evt(EventType.VOTE_STARTED, VoteStartedPayload(candidates=(1, 2), tie_round=1)),
            ["PK投票开始。"],
        ),
        (
            _evt(
                EventType.VOTE_RESULT, VoteResultPayload(tally=((4, 3.0),), exiled=4, tie_seats=())
            ),
            ["4号得票最高。"],
        ),
        (
            _evt(EventType.VOTE_RESULT, VoteResultPayload(tally=(), exiled=None, tie_seats=(1, 2))),
            ["平票：1号、2号。"],
        ),
        (_evt(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=4)), ["4号被放逐出局。"]),
        (_evt(EventType.PLAYER_EXILED, PlayerExiledPayload(seat=None)), ["本轮无人出局。"]),
        (
            _evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=5, victim=2)),
            ["5号猎人开枪，带走2号。"],
        ),
        (
            _evt(EventType.HUNTER_SHOT, HunterShotPayload(shooter=5, victim=None)),
            ["5号猎人没有开枪。"],
        ),
        (_evt(EventType.WOLF_SELF_DESTRUCT, WolfSelfDestructPayload(seat=6)), ["6号狼人自爆。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner="GOOD")), ["游戏结束，好人阵营获胜。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner="WOLF")), ["游戏结束，狼人阵营获胜。"]),
        (_evt(EventType.GAME_OVER, GameOverPayload(winner=None)), ["游戏结束，平局。"]),
    ],
)
def test_templates(event: Event, expected: list[str]) -> None:
    assert narrate(event, DEFAULT_NARRATION_EVENTS) == expected


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (_evt(EventType.GAME_STARTED, GameStartedPayload()), ["游戏开始。"]),
        (
            _evt(EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=4, running=True)),
            ["4号上警。"],
        ),
        (_evt(EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=4, running=False)), []),
        (_evt(EventType.SHERIFF_WITHDREW, SheriffWithdrewPayload(seat=4)), ["4号退水。"]),
        (
            _evt(EventType.SHERIFF_VOTE_CAST, SheriffVoteCastPayload(voter=1, target=4)),
            ["1号投给4号。"],
        ),
        (
            _evt(EventType.SHERIFF_VOTE_CAST, SheriffVoteCastPayload(voter=1, target=None)),
            ["1号弃票。"],
        ),
        (_evt(EventType.VOTE_CAST, VoteCastPayload(voter=2, target=5)), ["2号投给5号。"]),
        (_evt(EventType.VOTE_CAST, VoteCastPayload(voter=2, target=None)), ["2号弃票。"]),
        (
            _evt(EventType.SHERIFF_DIRECTION_SET, SheriffDirectionSetPayload(direction="RIGHT")),
            ["警长决定顺时针发言。"],
        ),
        (
            _evt(EventType.SHERIFF_DIRECTION_SET, SheriffDirectionSetPayload(direction="LEFT")),
            ["警长决定逆时针发言。"],
        ),
        (
            _evt(EventType.SHERIFF_BADGE_LOST, SheriffBadgeLostPayload(reason="NO_CANDIDATES")),
            ["本局无警长。"],
        ),
        (_evt(EventType.IDIOT_REVEALED, IdiotRevealedPayload(seat=7)), ["7号翻牌白痴，免于放逐。"]),
        # 以下是夜间私有事件：帧按来源事件可见性过滤，只有上帝（或当事人 / 狼队）听得到
        (_evt(EventType.GUARD_PROTECTED, GuardProtectedPayload(target=3)), ["守卫守护3号。"]),
        (_evt(EventType.GUARD_PROTECTED, GuardProtectedPayload(target=None)), ["守卫空守。"]),
        (
            _evt(EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=5, target=2)),
            ["5号狼人提议刀2号。"],
        ),
        (
            _evt(EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=5, target=None)),
            ["5号狼人提议空刀。"],
        ),
        (_evt(EventType.WOLF_KILL_DECIDED, WolfKillDecidedPayload(target=2)), ["狼人今夜刀2号。"]),
        (
            _evt(EventType.WOLF_KILL_DECIDED, WolfKillDecidedPayload(target=None)),
            ["狼人今夜空刀。"],
        ),
        (
            _evt(
                EventType.WOLF_KILL_REVOTE,
                WolfKillRevotePayload(round_no=1, proposals=((5, 2), (6, 3))),
            ),
            ["狼队意见不一致，再商量一轮。"],
        ),
        (_evt(EventType.WITCH_SAVED, WitchActedPayload(save=True)), ["女巫使用解药。"]),
        (_evt(EventType.WITCH_POISONED, WitchActedPayload(poison_target=6)), ["女巫毒了6号。"]),
        (
            _evt(EventType.SEER_CHECKED, SeerCheckedPayload(target=3, result="GOOD")),
            ["预言家查验3号，是好人。"],
        ),
        (
            _evt(EventType.SEER_CHECKED, SeerCheckedPayload(target=3, result="WOLF")),
            ["预言家查验3号，是狼人。"],
        ),
    ],
)
def test_extra_templates(event: Event, expected: list[str]) -> None:
    """用户反馈：上帝视角应该听到所有事件——上警 / 退水 / 逐票 / 方向 / 夜间行动都有旁白。"""
    assert event.type in DEFAULT_NARRATION_EVENTS
    assert narrate(event, DEFAULT_NARRATION_EVENTS) == expected


def test_outside_whitelist_is_empty() -> None:
    e = _evt(EventType.GAME_CREATED, GameCreatedPayload(num_players=9))
    assert narrate(e, DEFAULT_NARRATION_EVENTS) == []
    # 白名单只含 VOTE_STARTED 时，VOTE_CAST 也不播
    assert (
        narrate(
            _evt(EventType.VOTE_CAST, VoteCastPayload(voter=1, target=2)),
            frozenset({EventType.VOTE_STARTED}),
        )
        == []
    )
    # 白名单只含 VOTE_STARTED 时，ROUND_STARTED 也不播
    r = _evt(EventType.ROUND_STARTED, RoundStartedPayload(round=1))
    assert narrate(r, frozenset({EventType.VOTE_STARTED})) == []


def test_speech_events_never_narrated() -> None:
    """Review Focus 1：名单里写了发言事件也不播（发言由发言配音负责，避免双播）。"""
    e = _evt(EventType.PLAYER_SPOKE, PlayerSpokePayload(content="大家好"), actor=1)
    assert narrate(e, frozenset({EventType.PLAYER_SPOKE})) == []


def test_every_phase_and_stage_has_a_branch() -> None:
    """新增 Phase / ElectionStage 枚举值而未加模板 → 这里 fail-loud。"""
    for ph in Phase:
        narrate(_evt(EventType.PHASE_CHANGED, PhaseChangedPayload(to=ph)), DEFAULT_NARRATION_EVENTS)
    for st in ElectionStage:
        narrate(
            _evt(EventType.ELECTION_STAGE_CHANGED, ElectionStageChangedPayload(stage=st)),
            DEFAULT_NARRATION_EVENTS,
        )


def test_default_whitelist_all_templated() -> None:
    assert DEFAULT_NARRATION_EVENTS <= TEMPLATED_EVENTS
    assert EventType.PLAYER_SPOKE not in DEFAULT_NARRATION_EVENTS


# 返回空属正常的 PHASE_CHANGED 分支（spec §3.2）
_SILENT_PHASES = {Phase.EXILE, Phase.WIN_CHECK, Phase.LOBBY, Phase.ROLE_ASSIGN, Phase.GAME_OVER}


@pytest.mark.parametrize("preset", PRESET_NAMES)
def test_full_game_coverage(preset: str) -> None:
    """4 个 preset × 固定 seed 跑完整局：白名单事件全部能渲染成以「。」结尾的句子。"""
    cfg = build_preset(preset).model_copy(update={"seed": 11})
    _final, events = run_game(cfg, "g_cov")
    narrated = 0
    for e in events:
        if e.type not in DEFAULT_NARRATION_EVENTS:
            assert narrate(e, DEFAULT_NARRATION_EVENTS) == []
            continue
        out = narrate(e, DEFAULT_NARRATION_EVENTS)
        if e.type == EventType.PHASE_CHANGED and e.payload.to in _SILENT_PHASES:  # type: ignore[attr-defined]
            assert out == []
            continue
        if e.type == EventType.SHERIFF_CANDIDACY and not e.payload.running:  # type: ignore[attr-defined]
            assert out == []  # 「不上警」不报
            continue
        assert out, f"{preset}: {e.type} 无旁白"
        assert all(s.endswith("。") for s in out)
        narrated += 1
    assert narrated > 10


def test_config_defaults(tmp_path: Path) -> None:
    cfg = NarrationConfig.from_env({}, data_dir=tmp_path)
    assert cfg.speaker == "uncle_fu"
    assert cfg.events == DEFAULT_NARRATION_EVENTS
    assert cfg.cache_dir == tmp_path / "narration"
    assert cfg.voice == VoiceSpec(mode="preset", speaker="uncle_fu")


def test_config_from_env_custom(tmp_path: Path) -> None:
    env = {
        "AGENTHOWL_NARRATOR_VOICE": "vivian",
        "AGENTHOWL_NARRATION_EVENTS": " VOTE_STARTED, GAME_OVER ,PLAYER_SPOKE",
        "AGENTHOWL_NARRATION_DIR": str(tmp_path / "x"),
    }
    cfg = NarrationConfig.from_env(env, data_dir=tmp_path)
    assert cfg.speaker == "vivian"
    # PLAYER_SPOKE 允许出现但会被 narrate() 忽略；名单本身保留它（不替用户改配置）
    assert cfg.events == frozenset(
        {EventType.VOTE_STARTED, EventType.GAME_OVER, EventType.PLAYER_SPOKE}
    )
    assert cfg.cache_dir == tmp_path / "x"
    # 空串 = 默认
    assert (
        NarrationConfig.from_env({"AGENTHOWL_NARRATION_EVENTS": ""}, data_dir=tmp_path).events
        == DEFAULT_NARRATION_EVENTS
    )


@pytest.mark.parametrize(
    "env",
    [
        {"AGENTHOWL_NARRATOR_VOICE": "nobody"},
        {"AGENTHOWL_NARRATION_EVENTS": "VOTE_STARTED,NOT_AN_EVENT"},
        {"AGENTHOWL_NARRATION_EVENTS": "GAME_CREATED"},  # 合法类型但没有模板
    ],
)
def test_config_fail_loud(tmp_path: Path, env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        NarrationConfig.from_env(env, data_dir=tmp_path)


def test_cache_roundtrip_and_key(tmp_path: Path) -> None:
    cache = NarrationCache(tmp_path / "narr")
    assert cache.get("uncle_fu", "投票开始。") is None
    wav = _wav(0.1)
    p = cache.put("uncle_fu", "投票开始。", wav)
    assert p.parent == tmp_path / "narr" and p.suffix == ".wav"
    assert not list((tmp_path / "narr").glob("*.tmp"))
    assert cache.get("uncle_fu", "投票开始。") == wav
    # 换声线换 key
    assert NarrationCache.key("vivian", "投票开始。") != NarrationCache.key(
        "uncle_fu", "投票开始。"
    )
    assert len(NarrationCache.key("vivian", "投票开始。")) == 16


def test_cache_corrupt_file_is_miss(tmp_path: Path) -> None:
    cache = NarrationCache(tmp_path / "narr")
    (tmp_path / "narr").mkdir()
    (tmp_path / "narr" / f"{NarrationCache.key('uncle_fu', '投票开始。')}.wav").write_bytes(b"junk")
    assert cache.get("uncle_fu", "投票开始。") is None
