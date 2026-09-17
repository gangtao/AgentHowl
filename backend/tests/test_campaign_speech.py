"""上警发言子阶段（issue #47）：配置、事件契约、发言流、拒绝矩阵、回放保真。"""

from app.engine.config import (
    CampaignSpeechOrder,
    Faction,
    RoleType,
    SheriffRule,
    build_preset,
)
from app.engine.engine import StepResult
from app.engine.events import (
    ElectionStageChangedPayload,
    Event,
    EventType,
    Visibility,
    reduce,
)
from app.engine.phases import (
    ElectionStage,
    Phase,
    campaign_speaking,
    expected_actors,
    pk_speaking,
    speech_queue_pending,
)
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


def test_pk_speaking_and_speech_queue_pending() -> None:
    # 上警发言中：pending True，pk False
    campaigning = _state(election_stage="speech", speech_order=(1, 2), speech_idx=0)
    assert not pk_speaking(campaigning)
    assert speech_queue_pending(campaigning)

    # SHERIFF_PK / VOTE_PK 发言中：两者皆 True
    for ph in (Phase.SHERIFF_PK, Phase.VOTE_PK):
        pk = _state(phase=ph, speech_order=(1, 2), speech_idx=0)
        assert pk_speaking(pk)
        assert speech_queue_pending(pk)

    # 队列耗尽：皆 False
    exhausted = _state(phase=Phase.SHERIFF_PK, speech_order=(1, 2), speech_idx=2)
    assert not pk_speaking(exhausted)
    assert not speech_queue_pending(exhausted)

    # withdraw 子阶段：皆 False
    withdrawing = _state(election_stage="withdraw", speech_order=(1, 2), speech_idx=0)
    assert not pk_speaking(withdrawing)
    assert not speech_queue_pending(withdrawing)


# ---------- Task 2：内置驱动 ----------


def test_bot_speaks_in_campaign_speech() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    st = _state(
        election_stage="speech", sheriff_candidates=(2, 3), speech_order=(3, 2), speech_idx=0
    )
    a = RandomBot.choose_action(st, 3)  # 3 号是好人：不会触发狼自爆掷骰
    assert isinstance(a, Speak)
    assert a.actor_seat == 3 and a.content == "(bot-campaign)"


def test_bot_campaign_badge_flow_sometimes_and_always_wellformed() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    seen_claim = False
    for seed in range(1, 41):
        st = _state(
            seed=seed,
            election_stage="speech",
            sheriff_candidates=(2, 3),
            speech_order=(3, 2),
            speech_idx=0,
        )
        a = RandomBot.choose_action(st, 3)
        assert isinstance(a, Speak)
        bf = a.badge_flow
        assert len(bf) <= st.config.sheriff.badge_flow_max_length
        assert len(set(bf)) == len(bf) and 3 not in bf
        seen_claim = seen_claim or bool(bf)
    assert seen_claim  # 1/4 概率，40 个 seed 内必现


def test_bot_no_badge_flow_when_disabled() -> None:
    from app.cli.bot import RandomBot
    from app.engine.actions import Speak

    for seed in range(1, 41):
        st = _state(
            seed=seed,
            sheriff=SheriffRule(badge_flow_enabled=False),
            election_stage="speech",
            sheriff_candidates=(2, 3),
            speech_order=(3, 2),
            speech_idx=0,
        )
        a = RandomBot.choose_action(st, 3)
        assert isinstance(a, Speak) and a.badge_flow == ()


# ---------- Task 3：引擎 ----------


def _finish_candidacy(
    sheriff: SheriffRule | None = None,
    seed: int = 1,
    cands: tuple[int, ...] = (1, 2, 3),
    wolves: tuple[int, ...] = (0,),
) -> StepResult:
    """6 人局 candidacy 收尾：0-4 已声明，5 号最后声明不上警 -> 引擎推进子阶段。"""
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.engine import step

    st = _state(
        sheriff=sheriff,
        seed=seed,
        wolves=wolves,
        election_stage="candidacy",
        sheriff_declared=frozenset({0, 1, 2, 3, 4}),
        sheriff_candidates=cands,
    )
    res = step(st, SheriffAction(actor_seat=5, action_type=SheriffActionType.WITHDRAW))
    assert res.rejection is None
    return res


def _stage_events(events: list[Event]) -> list[ElectionStageChangedPayload]:
    out = []
    for e in events:
        if e.type == EventType.ELECTION_STAGE_CHANGED:
            assert isinstance(e.payload, ElectionStageChangedPayload)
            out.append(e.payload)
    return out


def test_candidacy_flows_into_speech_with_order_in_event() -> None:
    res = _finish_candidacy()
    st = res.state
    assert st.election_stage == "speech"
    assert sorted(st.speech_order) == [1, 2, 3] and st.speech_idx == 0
    assert expected_actors(st) == {st.speech_order[0]}
    stages = _stage_events(res.events)
    assert [p.stage.value for p in stages] == ["speech"]
    assert stages[0].speech_order == st.speech_order  # 顺序随事件入流，回放不重算 RNG


def test_seat_asc_order() -> None:
    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    for seed in range(1, 11):
        assert _finish_candidacy(sheriff=sr, seed=seed, cands=(3, 1, 2)).state.speech_order == (
            1,
            2,
            3,
        )


def test_judge_odd_even_both_directions_and_deterministic() -> None:
    orders = {seed: _finish_candidacy(seed=seed).state.speech_order for seed in range(1, 21)}
    assert set(orders.values()) == {(1, 2, 3), (3, 2, 1)}  # 单顺双逆：只有升序/降序两种
    again = {seed: _finish_candidacy(seed=seed).state.speech_order for seed in range(1, 21)}
    assert again == orders  # 同 seed 可复现


def test_speech_flow_then_withdraw_stage() -> None:
    from tests.factories import run_campaign_speeches

    st = _finish_candidacy().state
    order = st.speech_order
    st2, events = run_campaign_speeches(st)
    spoke = [e.actor_seat for e in events if e.type == EventType.PLAYER_SPOKE]
    assert tuple(spoke) == order
    assert st2.election_stage == "withdraw"
    assert st2.sheriff_confirmed == frozenset()
    assert expected_actors(st2) == {1, 2, 3}  # 既有退水确认照旧


def test_no_candidates_skips_speech() -> None:
    res = _finish_candidacy(cands=())
    assert res.state.election_stage == ""
    assert all(p.stage != ElectionStage.SPEECH for p in _stage_events(res.events))


def test_disabled_toggle_goes_straight_to_withdraw() -> None:
    res = _finish_candidacy(sheriff=SheriffRule(campaign_speech_enabled=False))
    assert res.state.election_stage == "withdraw"
    assert [p.stage.value for p in _stage_events(res.events)] == ["withdraw"]


def test_rejection_matrix() -> None:
    from app.engine.actions import RejectedReason, SheriffAction, SheriffActionType, Speak
    from app.engine.engine import step
    from tests.factories import run_campaign_speeches

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr).state  # 顺序 (1,2,3)，轮到 1

    # 非当前发言者 / 警下玩家发言
    assert step(st, Speak(actor_seat=2, content="x")).rejection == RejectedReason.NOT_YOUR_TURN
    assert step(st, Speak(actor_seat=4, content="x")).rejection == RejectedReason.NOT_YOUR_TURN
    # 当前发言者在发言期提交任何警长行动 -> WRONG_PHASE（含投票：堵住兜底分支）
    for at, tgt in (
        (SheriffActionType.RUN_FOR_SHERIFF, None),
        (SheriffActionType.WITHDRAW, None),
        (SheriffActionType.VOTE_SHERIFF, 2),
    ):
        r = step(st, SheriffAction(actor_seat=1, action_type=at, target_seat=tgt))
        assert r.rejection == RejectedReason.WRONG_PHASE, at
        assert r.state.sheriff_votes == {}
    # 其他人提交警长行动 -> NOT_YOUR_TURN
    r = step(
        st, SheriffAction(actor_seat=4, action_type=SheriffActionType.VOTE_SHERIFF, target_seat=1)
    )
    assert r.rejection == RejectedReason.NOT_YOUR_TURN

    # 发言结束后（withdraw 子阶段）候选人再 Speak -> WRONG_PHASE
    st_w, _ = run_campaign_speeches(st)
    assert step(st_w, Speak(actor_seat=1, content="x")).rejection == RejectedReason.WRONG_PHASE

    # withdraw 子阶段全员坚持竞选（RUN_FOR_SHERIFF 再确认）-> 进入 vote 子阶段；
    # 此时警下投票人再 Speak -> WRONG_PHASE（F6，规格 §7 点名但缺失的用例）
    st_v = st_w
    for seat in sorted(st_w.sheriff_candidates):
        r = step(
            st_v, SheriffAction(actor_seat=seat, action_type=SheriffActionType.RUN_FOR_SHERIFF)
        )
        assert r.rejection is None
        st_v = r.state
    assert st_v.election_stage == "vote"
    voter = next(p.seat for p in st_v.players if p.seat not in st_v.sheriff_candidates)
    assert step(st_v, Speak(actor_seat=voter, content="x")).rejection == RejectedReason.WRONG_PHASE


def test_badge_flow_in_campaign_speech() -> None:
    from app.engine.actions import RejectedReason, Speak
    from app.engine.engine import step

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr).state
    ok = step(st, Speak(actor_seat=1, content="我是预言家", badge_flow=(4, 5)))
    assert ok.rejection is None
    assert ok.state.badge_flow_claims == {1: (4, 5)}

    for bad in ((4, 5, 0), (4, 4)):  # 超长 / 重复
        r = step(st, Speak(actor_seat=1, content="x", badge_flow=bad))
        assert r.rejection == RejectedReason.BADGE_FLOW_INVALID, bad

    # 死目标：座位 4 非候选人，置为已死亡 -> badge_flow 引用死座位应被拒（F6）
    dead_players = tuple(
        p.model_copy(update={"alive": False}) if p.seat == 4 else p for p in st.players
    )
    st_dead = st.model_copy(update={"players": dead_players})
    r = step(st_dead, Speak(actor_seat=1, content="x", badge_flow=(4,)))
    assert r.rejection == RejectedReason.BADGE_FLOW_INVALID

    off = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC, badge_flow_enabled=False)
    st_off = _finish_candidacy(sheriff=off).state
    r = step(st_off, Speak(actor_seat=1, content="x", badge_flow=(4,)))
    assert r.rejection == RejectedReason.BADGE_FLOW_INVALID


def test_self_destruct_mid_speech_eats_badge_and_skips_day() -> None:
    from app.engine.actions import SelfDestruct, Speak
    from app.engine.engine import step
    from app.engine.events import PhaseChangedPayload, SheriffBadgeLostPayload

    sr = SheriffRule(campaign_speech_order=CampaignSpeechOrder.SEAT_ASC)
    st = _finish_candidacy(sheriff=sr, wolves=(0, 4)).state
    st = step(st, Speak(actor_seat=1, content="first")).state  # 发言进行到一半
    res = step(st, SelfDestruct(actor_seat=0))  # 警下狼自爆，不受发言轮次限制
    assert res.rejection is None
    assert res.state.sheriff_seat is None and res.state.election_stage == ""
    assert any(
        isinstance(e.payload, SheriffBadgeLostPayload) and e.payload.reason == "SELF_DESTRUCT"
        for e in res.events
    )
    assert not any(
        isinstance(e.payload, PhaseChangedPayload) and e.payload.to == Phase.DAY_SPEECH
        for e in res.events
    )  # 立即天黑：当天无发言


def test_stepwise_replay_equals_live_during_campaign_speech() -> None:
    # 回放保真（不给 issue #37 添新债）：发言中途任意前缀重放与 live 逐字段相等
    from app.cli.bot import RandomBot
    from app.engine.engine import create_game, step
    from app.engine.events import reduce_all

    mid_speech_points = 0
    for seed in (7, 8, 9):
        cfg = build_preset("std_12_yn_hunter_idiot").model_copy(update={"seed": seed})
        res = create_game(cfg, "g")
        state, events = res.state, list(res.events)
        blank = GameState(
            game_id=state.game_id,
            config=state.config,
            phase=Phase.LOBBY,
            round=0,
            players=tuple(
                Player(
                    seat=p.seat,
                    display_name=p.display_name,
                    role=RoleType.VILLAGER,
                    faction=Faction.GOOD,
                )
                for p in state.players
            ),
        )
        guard = 0
        while state.phase not in (Phase.GAME_OVER, Phase.DAY_SPEECH):
            for seat in sorted(expected_actors(state)):
                if seat not in expected_actors(state):
                    continue
                r = step(state, RandomBot.choose_action(state, seat))
                assert r.rejection is None
                state, events = r.state, [*events, *r.events]
                if state.phase == Phase.SHERIFF_ELECTION and state.election_stage == "speech":
                    replayed = reduce_all(blank, events)
                    assert replayed.election_stage == state.election_stage
                    assert replayed.speech_order == state.speech_order
                    assert replayed.speech_idx == state.speech_idx
                    assert replayed.badge_flow_claims == state.badge_flow_claims
                    mid_speech_points += 1
            guard += 1
            assert guard < 10_000
    assert mid_speech_points > 0  # 样本里确实走到了上警发言


def test_full_games_with_campaign_speech_terminate() -> None:
    from app.cli.bot import run_game

    saw_speech = False
    for preset in ("std_12_yn_hunter_idiot", "std_12_yn_hunter_guard", "std_9_kill_side"):
        for seed in (3, 42, 256):
            cfg = build_preset(preset).model_copy(update={"seed": seed})
            final, events = run_game(cfg, "g")
            assert final.phase == Phase.GAME_OVER
            saw_speech = saw_speech or any(
                p.stage == ElectionStage.SPEECH for p in _stage_events(events)
            )
    assert saw_speech
