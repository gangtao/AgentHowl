from app.cli.bot import run_game
from app.engine.config import build_preset
from app.engine.engine import step
from app.engine.phases import Phase
from app.engine.state import GameState


def _preset_with_sheriff(seed: int):
    return build_preset("std_12_yn_hunter_guard").model_copy(update={"seed": seed})


def test_full_game_with_sheriff_terminates() -> None:
    final, events = run_game(_preset_with_sheriff(2024), game_id="g")
    assert final.phase == Phase.GAME_OVER
    # 竞选发生过：存在 SHERIFF_ELECTED 或 SHERIFF_BADGE_LOST 事件（当选或流失，竞选必有其一）
    from app.engine.events import EventType

    assert any(e.type in (EventType.SHERIFF_ELECTED, EventType.SHERIFF_BADGE_LOST) for e in events)


def test_sheriff_vote_weight_is_1_5() -> None:
    # 单元层已由 resolver.test_count_votes_sheriff_weight_breaks_tie 覆盖；
    # 此处断言 engine 用了 is_sheriff 权重
    from app.engine.config import Faction, RoleType
    from app.engine.engine import _tally_and_continue
    from app.engine.state import GameState, Player

    roles = [RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    # seat0(警长,1.5票)投1；seat2投2 -> 1 以 1.5 vs 1.0 胜
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE,
        round=2,
        players=players,
        votes={0: 1, 2: 2},
    )
    new, _ = _tally_and_continue(st)
    assert new.day_exiled == 1


def test_sheriff_vote_weight_reads_config() -> None:
    from app.engine.config import Faction, RoleType, SheriffRule
    from app.engine.engine import _tally_and_continue
    from app.engine.state import GameState, Player

    roles = [RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    # vote_weight=2.5：警长(座0)投1 -> 座1 得 2.5；座1、2 投 2 -> 座2 得 2.0；座1 应出局
    cfg = build_preset("std_9_kill_side").model_copy(
        update={
            "num_players": 3,
            "seed": 1,
            "sheriff": SheriffRule(vote_weight=2.5),
        }
    )
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.VOTE,
        round=2,
        players=players,
        votes={0: 1, 1: 2, 2: 2},
    )
    new, _ = _tally_and_continue(st)
    assert new.day_exiled == 1  # 若硬编码 1.5，座2(2.0) 会胜、结果不同


def test_self_destruct_in_day_skips_to_night() -> None:
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player

    roles = [
        RoleType.WEREWOLF,
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.VILLAGER,
    ]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
        speech_order=(0, 1, 2, 3, 4),
        speech_idx=0,
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    from app.engine.state import player_at

    assert player_at(res.state, 0).alive is False
    # 跳过当天发言/投票直接入夜（回到夜间阶段或终局）
    assert res.state.phase in (Phase.NIGHT_GUARD, Phase.NIGHT_WEREWOLF, Phase.GAME_OVER)


def test_self_destruct_in_election_eats_badge() -> None:
    # 覆盖 self-review 要求：竞选期自爆吞警徽
    # （sheriff_seat 变 None，且显式广播 SHERIFF_BADGE_LOST(SELF_DESTRUCT)）
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.events import EventType, SheriffBadgeLostPayload
    from app.engine.state import Player, player_at

    roles = [
        RoleType.WEREWOLF,
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.SEER,
    ]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 5, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.SHERIFF_ELECTION,
        round=1,
        players=players,
        election_stage="vote",
        sheriff_candidates=(2, 3),
        sheriff_votes={2: 3},
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    assert player_at(res.state, 0).alive is False
    assert res.state.sheriff_seat is None
    assert any(
        e.type == EventType.SHERIFF_BADGE_LOST
        and isinstance(e.payload, SheriffBadgeLostPayload)
        and e.payload.reason == "SELF_DESTRUCT"
        for e in res.events
    )


def test_non_wolf_cannot_self_destruct() -> None:
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player

    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(4)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 4, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
        speech_order=(0, 1, 2, 3),
        speech_idx=0,
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is not None


def test_bidding_speech_is_rejected() -> None:
    from app.engine.actions import RejectedReason, Speak
    from app.engine.config import Faction, RoleType, SpeechOrderRule
    from app.engine.state import Player

    players = tuple(
        Player(seat=i, display_name=f"P{i}", role=RoleType.VILLAGER, faction=Faction.GOOD)
        for i in range(4)
    )
    cfg = build_preset("std_9_kill_side").model_copy(
        update={"num_players": 4, "seed": 1, "speech_order_rule": SpeechOrderRule.BIDDING}
    )
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
        speech_order=(0, 1, 2, 3),
        speech_idx=0,
    )
    res = step(st, Speak(actor_seat=0, content="x"))
    assert res.rejection == RejectedReason.BIDDING_NOT_IMPLEMENTED


def test_dying_sheriff_can_pass_badge() -> None:
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player, player_at

    roles = [RoleType.VILLAGER, RoleType.SEER, RoleType.WEREWOLF]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0),
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.LAST_WORDS,
        round=1,
        players=players,
        speech_order=(0,),
        speech_idx=0,
        sheriff_seat=0,
        resume_token="after_day",
    )
    res = step(
        st, SheriffAction(actor_seat=0, action_type=SheriffActionType.PASS_BADGE, target_seat=1)
    )
    assert res.rejection is None
    assert res.state.sheriff_seat == 1
    assert player_at(res.state, 1).is_sheriff is True


def test_self_destructing_sheriff_loses_badge() -> None:
    from app.engine.actions import SelfDestruct
    from app.engine.config import Faction, RoleType
    from app.engine.state import Player, player_at

    roles = [RoleType.WEREWOLF, RoleType.VILLAGER, RoleType.SEER, RoleType.VILLAGER]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 4, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.DAY_SPEECH,
        round=1,
        players=players,
        speech_order=(0, 1, 2, 3),
        speech_idx=0,
        sheriff_seat=0,
    )
    res = step(st, SelfDestruct(actor_seat=0))
    assert res.rejection is None
    # 自爆的警长：警徽应流失，dead 玩家不再持徽
    assert res.state.sheriff_seat is None
    assert player_at(res.state, 0).is_sheriff is False


def test_badge_pass_reduce_matches_live() -> None:
    # reduce(events) == live 对于遗言回合主动移交警徽
    from app.engine.actions import SheriffAction, SheriffActionType
    from app.engine.config import Faction, RoleType
    from app.engine.events import reduce
    from app.engine.state import Player

    roles = [RoleType.VILLAGER, RoleType.SEER, RoleType.WEREWOLF]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0),
            is_sheriff=(i == 0),
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    st = GameState(
        game_id="g",
        config=cfg,
        phase=Phase.LAST_WORDS,
        round=1,
        players=players,
        speech_order=(0,),
        speech_idx=0,
        sheriff_seat=0,
        resume_token="after_day",
    )
    res = step(
        st, SheriffAction(actor_seat=0, action_type=SheriffActionType.PASS_BADGE, target_seat=1)
    )
    assert res.rejection is None
    # 用引擎产出的事件从 st 重放，speech_idx 等关键字段应与 live 一致
    replayed = st
    for ev in res.events:
        replayed = reduce(replayed, ev)
    assert replayed.speech_idx == res.state.speech_idx
    assert replayed.sheriff_seat == res.state.sheriff_seat
    assert [p.is_sheriff for p in replayed.players] == [p.is_sheriff for p in res.state.players]


def test_speech_order_rules_return_living_only() -> None:
    from app.engine.config import Faction, RoleType, SpeechOrderRule
    from app.engine.engine import _speech_order
    from app.engine.state import Player

    roles = [
        RoleType.WEREWOLF,
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.VILLAGER,
        RoleType.WITCH,
    ]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 2),  # 座2 已死
        )
        for i, r in enumerate(roles)
    )
    rules = (
        SpeechOrderRule.FIXED_CLOCKWISE,
        SpeechOrderRule.DEATH_NEXT,
        SpeechOrderRule.ODD_EVEN_CLOCK,
        SpeechOrderRule.SHERIFF_DECIDES,
    )
    for rule in rules:
        cfg = build_preset("std_9_kill_side").model_copy(
            update={"num_players": 5, "seed": 1, "speech_order_rule": rule}
        )
        st = GameState(
            game_id="g",
            config=cfg,
            phase=Phase.DAY_SPEECH,
            round=1,
            players=players,
            night_deaths=(2,),
        )
        order = _speech_order(st)
        assert 2 not in order  # 死者不在发言顺序
        assert set(order) == {0, 1, 3, 4}  # 覆盖所有存活者一次
