"""离线指标分析器（issue #60）：随机 bot 局的一致性 + 手工事件序列的口径——零 IO。"""

from app.agent.profile import AgentProfile
from app.cli.bot import run_game
from app.engine.config import RoleType, build_preset
from app.engine.engine import create_game
from app.engine.events import (
    Event,
    EventType,
    GameOverPayload,
    NightResolvedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SheriffCandidacyPayload,
    SheriffElectedPayload,
    SheriffWithdrewPayload,
    Visibility,
    VoteCastPayload,
    VoteStartedPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfKillRevotePayload,
)
from app.eval.fingerprint import profile_fingerprint
from app.eval.metrics import (
    RANDOM_BOT_LABEL,
    ProfileStats,
    aggregate,
    analyze_game,
    collect_profiles,
    diff,
)
from app.store.event_store import GameMeta, SeatName


def _meta(final, game_id: str = "g1", agents: dict[str, AgentProfile] | None = None) -> GameMeta:
    roster = tuple(SeatName(seat=p.seat, display_name=p.display_name) for p in final.players)
    return GameMeta(game_id=game_id, config=final.config, roster=roster, agents=agents or {})


def test_random_bot_game_consistency() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, "g1")
    a = analyze_game(_meta(final), events)
    assert a.winner == final.winner and a.rounds == final.round and a.sheriff_enabled
    assert set(a.roles) == set(range(9)) and all(fp is None for fp in a.fingerprints.values())
    for p in final.players:
        st = a.seats[p.seat]
        assert st.wins == (1 if final.winner is not None and p.faction == final.winner else 0)
        assert st.alive_at_end == (1 if p.alive else 0)
        assert 0 <= st.rounds_alive <= final.round
        assert st.exiled + st.night_killed <= 1  # 一人至多死一次于这两种原因
        if p.alive:
            assert st.exiled == st.night_killed == 0 and st.rounds_alive == final.round
    assert sum(st.speeches for st in a.seats.values()) == sum(
        1 for e in events if e.type is EventType.PLAYER_SPOKE
    )
    wolves = [s for s, r in a.roles.items() if r == RoleType.WEREWOLF]
    assert all(a.seats[w].wolf_nights >= 1 for w in wolves)
    assert all(a.seats[s].wolf_nights == 0 for s in a.seats if s not in wolves)


def test_unfinished_game_not_finished_and_excluded_from_aggregate() -> None:
    """F1（终审）：没见到 GAME_OVER 的事件流（中断 / 仍在进行）不应计入分母。"""
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, "g1")
    game_over_idx = next(i for i, e in enumerate(events) if e.type is EventType.GAME_OVER)
    truncated = events[:game_over_idx]  # 截到 GAME_OVER 之前

    unfinished = analyze_game(_meta(final), truncated)
    assert unfinished.finished is False
    finished = analyze_game(_meta(final), events)
    assert finished.finished is True

    stats = aggregate([unfinished, finished])
    assert stats[None].games == 9  # 只有终局的一局（9 座位）计入


def test_manual_sequence_votes_wolves_speech_sheriff_skills() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, _ = run_game(cfg, "g1")
    roles = {s: (RoleType.WEREWOLF if s in (0, 1, 2) else RoleType.VILLAGER) for s in range(9)}
    head = create_game(cfg, "g1")
    # 用 ROLES_ASSIGNED 之后的真实 head 无法改角色，这里直接把角色事件替换掉
    events = [e for e in head.events if e.type is not EventType.ROLES_ASSIGNED]
    from app.engine.events import RolesAssignedPayload

    events.append(
        Event(
            seq=len(events) + 1,
            game_id="g1",
            ts=0.0,
            type=EventType.ROLES_ASSIGNED,
            actor_seat=None,
            payload=RolesAssignedPayload(assignments=tuple(roles.items())),
            visibility=Visibility.GM_ONLY,
        )
    )
    wolf_propose_05 = WolfKillProposedPayload(wolf_seat=0, target=5)
    seer_speak = PlayerSpokePayload(
        content="我是预言家", claim_role=RoleType.SEER, badge_flow=(3, 4)
    )
    tail: list[tuple[EventType, object, int | None, dict[str, str]]] = [
        (EventType.ROUND_STARTED, RoundStartedPayload(round=1), None, {}),
        (EventType.WOLF_KILL_PROPOSED, wolf_propose_05, 0, {"skills": "wolf-team-kill"}),
        (EventType.WOLF_KILL_PROPOSED, WolfKillProposedPayload(wolf_seat=1, target=None), 1, {}),
        (
            EventType.WOLF_KILL_REVOTE,
            WolfKillRevotePayload(round_no=1, proposals=((0, 5), (1, None), (2, 5))),
            None,
            {},
        ),
        (EventType.WOLF_KILL_PROPOSED, wolf_propose_05, 0, {}),
        (EventType.WOLF_KILL_DECIDED, WolfKillDecidedPayload(target=None), None, {}),
        (
            EventType.PLAYER_SPOKE,
            seer_speak,
            4,
            {"skills": "seer-badge-flow,logic-chain"},
        ),
        (EventType.PLAYER_SPOKE, PlayerSpokePayload(content="过"), 4, {}),
        (EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=4, running=True), 4, {}),
        (EventType.SHERIFF_CANDIDACY, SheriffCandidacyPayload(seat=5, running=False), 5, {}),
        (EventType.SHERIFF_WITHDREW, SheriffWithdrewPayload(seat=4), 4, {}),
        (EventType.SHERIFF_ELECTED, SheriffElectedPayload(seat=6), None, {}),
        (
            EventType.VOTE_STARTED,
            VoteStartedPayload(candidates=tuple(range(9)), tie_round=0),
            None,
            {},
        ),
        (EventType.VOTE_CAST, VoteCastPayload(voter=3, target=7), 3, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=4, target=8), 4, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=5, target=None), 5, {}),
        (EventType.VOTE_CAST, VoteCastPayload(voter=6, target=2), 6, {}),
        (EventType.VOTE_STARTED, VoteStartedPayload(candidates=(7, 8), tie_round=1), None, {}),
        # 首轮 7∈PK 候选，改投 8 → 改票
        (EventType.VOTE_CAST, VoteCastPayload(voter=3, target=8), 3, {}),
        # 首轮 8，坚持 → 不改
        (EventType.VOTE_CAST, VoteCastPayload(voter=4, target=8), 4, {}),
        # 首轮 2∉PK 候选 → 不计入分母
        (EventType.VOTE_CAST, VoteCastPayload(voter=6, target=7), 6, {}),
        # m7（终审）：夜死具体断言——8 号本轮被刀
        (EventType.NIGHT_RESOLVED, NightResolvedPayload(deaths=(8,)), None, {}),
        (EventType.PLAYER_EXILED, PlayerExiledPayload(seat=7), None, {}),
        (EventType.GAME_OVER, GameOverPayload(winner="WOLF"), None, {}),
    ]
    base = len(events)
    for i, (etype, payload, actor, meta) in enumerate(tail, start=base + 1):
        events.append(
            Event(
                seq=i,
                game_id="g1",
                ts=0.0,
                type=etype,
                actor_seat=actor,
                payload=payload,
                visibility=Visibility.PUBLIC,
                meta=meta,
            )
        )
    a = analyze_game(_meta(final, agents={"0": AgentProfile(model="m")}), events)

    s0, s1, s2, s3, s4, s5, s6, s7, s8 = (a.seats[i] for i in range(9))
    # 狼队：三狼各 1 狼夜；0 号提案 2 次、无空刀；1 号 1 次空刀提案；重提与决定空刀记到三狼
    assert (s0.wolf_nights, s1.wolf_nights, s2.wolf_nights) == (1, 1, 1)
    assert (s0.proposals, s0.no_kill_proposals, s1.proposals, s1.no_kill_proposals) == (2, 0, 1, 1)
    assert all(st.revote_nights == 1 and st.decided_no_kill == 1 for st in (s0, s1, s2))
    assert s3.wolf_nights == 0 and s3.proposals == 0
    # 发言 / 警长
    assert (s4.speeches, s4.speech_chars, s4.claims, s4.badge_flows) == (2, 6, 1, 1)
    assert (s4.candidacies, s4.withdrew, s5.candidacies, s6.elected) == (1, 1, 0, 1)
    # 投票
    assert (s3.votes, s3.pk_votes_eligible, s3.vote_changes) == (2, 1, 1)
    assert (s4.votes, s4.pk_votes_eligible, s4.vote_changes) == (2, 1, 0)
    assert (s5.votes, s5.abstains) == (1, 1)
    assert (s6.votes, s6.pk_votes_eligible, s6.vote_changes) == (2, 0, 0)
    # 放逐与胜负
    assert s7.exiled == 1 and s7.rounds_alive == 1 and s7.alive_at_end == 0
    # 夜死（m7 终审）：8 号被刀，死于本轮，终局不在世
    assert s8.night_killed == 1 and s8.rounds_alive == 1 and s8.alive_at_end == 0
    assert s0.wins == 1 and s3.wins == 0
    # 技能：按事件计次、逐名计数
    assert s0.skills_assembled == 1 and s0.skill_counts == {"wolf-team-kill": 1}
    assert s4.skills_assembled == 1 and s4.skill_counts == {"seer-badge-flow": 1, "logic-chain": 1}
    # 指纹：只有 0 号有档案
    assert a.fingerprints[0] == profile_fingerprint(AgentProfile(model="m"))
    assert a.fingerprints[1] is None


def test_aggregate_by_fingerprint_role_and_diff() -> None:
    cfg = build_preset("std_9_kill_side").model_copy(update={"seed": 3})
    final, events = run_game(cfg, "g1")
    pa, pb = AgentProfile(model="a"), AgentProfile(model="b", temperature=0.9)
    agents1 = {str(s): (pa if s % 2 == 0 else pb) for s in range(9)}
    agents2 = {str(s): (pb if s % 2 == 0 else pa) for s in range(9)}
    m1, m2 = _meta(final, "g1", agents1), _meta(final, "g2", agents2)
    profiles = collect_profiles([m1, m2])
    assert set(profiles) == {profile_fingerprint(pa), profile_fingerprint(pb)}
    stats = aggregate([analyze_game(m1, events), analyze_game(m2, events)], profiles)
    sa, sb = stats[profile_fingerprint(pa)], stats[profile_fingerprint(pb)]
    assert sa.games == 9 and sb.games == 9 and sa.summary == "a"
    assert sa.games == sa.wolf_games + sa.good_games
    assert sum(r.games for r in sa.by_role.values()) == 9
    assert sa.sheriff_games == 9 and sa.win_rate is not None
    assert None not in stats  # 全部座位都有档案 → 无随机 bot 组
    d = diff(sa, sb)
    assert set(d) == set(ProfileStats.RATE_FIELDS)
    assert d["win_rate"] is not None
    # 分母为 0 → None 传播
    empty = ProfileStats(summary="x")
    assert empty.win_rate is None and diff(empty, sa)["win_rate"] is None
    # 随机 bot 组
    bare = aggregate([analyze_game(_meta(final), events)])
    assert set(bare) == {None} and bare[None].summary == RANDOM_BOT_LABEL and bare[None].games == 9
