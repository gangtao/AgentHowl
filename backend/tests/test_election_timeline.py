"""竞选子阶段事件化（issue #17）：ELECTION_STAGE_CHANGED 契约与时间线重建。"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    SheriffCandidacyPayload,
    Visibility,
    reduce,
    reduce_all,
)
from app.engine.phases import ElectionStage, Phase
from app.engine.state import GameState, Player

PRESETS = ["std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side", "std_9_kill_all"]


def _base_state() -> GameState:
    players = tuple(
        Player(seat=s, display_name=f"P{s}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for s in range(4)
    )
    return GameState(
        game_id="g1",
        config=build_preset("std_9_kill_side"),
        phase=Phase.SHERIFF_ELECTION,
        players=players,
    )


def _stage_evt(stage: ElectionStage) -> Event:
    return Event(
        seq=1,
        game_id="g1",
        ts=1.0,
        type=EventType.ELECTION_STAGE_CHANGED,
        payload=ElectionStageChangedPayload(stage=stage),
        visibility=Visibility.PUBLIC,
    )


def test_election_stage_enum_values() -> None:
    assert ElectionStage.NONE.value == ""
    assert ElectionStage.CANDIDACY.value == "candidacy"
    assert ElectionStage.WITHDRAW.value == "withdraw"
    assert ElectionStage.VOTE.value == "vote"
    assert ElectionStage.DIRECTION.value == "direction"
    assert ElectionStage.ANNOUNCE.value == "announce"


def test_reduce_writes_election_stage() -> None:
    state = _base_state()
    new = reduce(state, _stage_evt(ElectionStage.WITHDRAW))
    assert new.election_stage == "withdraw"
    assert new.state_version == state.state_version + 1
    assert state.election_stage == ""  # 原状态不变（纯函数）
    back = reduce(new, _stage_evt(ElectionStage.NONE))
    assert back.election_stage == ""


# 合法子阶段转移（时间线语法）：任何阶段都可经流失/自爆直接收尾到 ""
_VALID_NEXT: dict[str, set[str]] = {
    "candidacy": {"withdraw", ""},
    "withdraw": {"vote", ""},
    "vote": {"direction", ""},
    "direction": {"announce", ""},
    "announce": {""},
}


def _blank(like: GameState) -> GameState:
    players = tuple(
        Player(
            seat=p.seat, display_name=p.display_name, role=RoleType.VILLAGER, faction=Faction.GOOD
        )
        for p in like.players
    )
    return GameState(
        game_id=like.game_id,
        config=like.config,
        phase=Phase.LOBBY,
        round=0,
        players=players,
    )


def _stage_sequence(events: list[Event]) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.type == EventType.ELECTION_STAGE_CHANGED:
            assert isinstance(e.payload, ElectionStageChangedPayload)
            out.append(e.payload.stage.value)
    return out


def test_stage_timeline_reconstructible_and_wellformed() -> None:
    from app.cli.bot import run_game

    for preset in PRESETS:
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            _, events = run_game(cfg, "g")
            seq = _stage_sequence(events)
            if not (cfg.sheriff.enabled and cfg.sheriff.election_before_first_death_announce):
                assert seq == []
                continue
            assert seq, f"{preset}/{seed}: 竞选开启但无子阶段标记"
            assert seq[0] == "candidacy" and seq[-1] == ""
            assert seq.count("candidacy") == 1  # 竞选只在首日发生一次
            for a, b in zip(seq, seq[1:], strict=False):
                assert b in _VALID_NEXT[a], f"{preset}/{seed}: {a}→{b} 非法（seq={seq}）"


def test_stepwise_replay_equals_live_election_stage() -> None:
    from app.cli.bot import RandomBot
    from app.engine.engine import create_game, step
    from app.engine.phases import expected_actors

    cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": 7})
    res = create_game(cfg, "g")
    state, events = res.state, list(res.events)
    blank = _blank(state)
    guard = 0
    while state.phase != Phase.GAME_OVER:
        for seat in sorted(expected_actors(state)):
            if seat not in expected_actors(state):
                continue
            r = step(state, RandomBot.choose_action(state, seat))
            assert r.rejection is None
            state, events = r.state, [*events, *r.events]
            # 中局强等价：任意前缀重放的 election_stage 与 live 一致
            assert reduce_all(blank, events).election_stage == state.election_stage
        guard += 1
        assert guard < 100_000


def test_reaffirm_disambiguated_by_stage_markers() -> None:
    from app.cli.bot import run_game

    # 标记把每个 SHERIFF_CANDIDACY(running=True) 分类到 candidacy/withdraw 窗口；
    # 断言分类恒可判定，且样本里确有退水期再确认（issue #17 的歧义场景）。
    found_reaffirm = False
    for seed in range(1, 30):
        cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": seed})
        _, events = run_game(cfg, "g")
        stage = ""
        for e in events:
            if e.type == EventType.ELECTION_STAGE_CHANGED:
                assert isinstance(e.payload, ElectionStageChangedPayload)
                stage = e.payload.stage.value
            elif e.type == EventType.SHERIFF_CANDIDACY:
                assert isinstance(e.payload, SheriffCandidacyPayload)
                if e.payload.running:
                    assert stage in ("candidacy", "withdraw")
                    if stage == "withdraw":
                        found_reaffirm = True
    assert found_reaffirm


def test_badge_lost_closes_stage_marker() -> None:
    from app.engine.engine import _advance_election

    # 退水后候选清空 -> ALL_WITHDREW 流失；断言 SHERIFF_BADGE_LOST 之后紧跟收尾标记 ""
    st = _base_state().model_copy(
        update={
            "round": 1,
            "election_stage": "withdraw",
            "sheriff_candidates": (),
            "sheriff_withdrawn": frozenset({1}),
        }
    )
    _, events = _advance_election(st)
    types = [e.type for e in events]
    i = types.index(EventType.SHERIFF_BADGE_LOST)
    assert types[i + 1] == EventType.ELECTION_STAGE_CHANGED
    p = events[i + 1].payload
    assert isinstance(p, ElectionStageChangedPayload)
    assert p.stage == ElectionStage.NONE
