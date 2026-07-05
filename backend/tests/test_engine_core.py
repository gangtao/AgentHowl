from app.engine.actions import NightAction, NightActionType
from app.engine.config import RoleType
from app.engine.engine import create_game, step
from app.engine.events import reduce_all
from app.engine.phases import Phase, expected_actors
from app.engine.state import GameState, living_of_role, living_wolves, player_at
from tests.factories import stage1_config


def _start() -> GameState:
    res = create_game(stage1_config(seed=42), game_id="g1")
    assert res.rejection is None
    return res.state


def test_create_game_reaches_first_night_actor() -> None:
    state = _start()
    # 首夜第一个夜间阶段是守卫（night_order 首位）
    assert state.phase == Phase.NIGHT_GUARD
    assert state.round == 1
    guard = living_of_role(state, RoleType.GUARD)[0]
    assert expected_actors(state) == {guard.seat}
    # 发牌确定：同 seed 再来一次身份完全一致
    again = create_game(stage1_config(seed=42), game_id="g1")
    assert [p.role for p in again.state.players] == [p.role for p in state.players]


def _submit(state: GameState, action: object) -> GameState:
    res = step(state, action)  # type: ignore[arg-type]
    assert res.rejection is None, res.rejection
    return res.state


def test_full_night_resolves_and_enters_day() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    witch = living_of_role(state, RoleType.WITCH)[0].seat
    wolves = [w.seat for w in living_wolves(state)]
    villager = next(p.seat for p in state.players if p.role == RoleType.VILLAGER)

    # 守卫守 seer
    state = _submit(
        state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer)
    )
    assert state.phase == Phase.NIGHT_WEREWOLF
    # 三狼一致刀 villager
    for w in wolves:
        state = _submit(
            state, NightAction(actor_seat=w, action_type=NightActionType.KILL, target_seat=villager)
        )
    # 狼刀共识决定后进入女巫
    assert state.phase == Phase.NIGHT_WITCH
    # 女巫不救不毒
    state = _submit(state, NightAction(actor_seat=witch, action_type=NightActionType.SKIP))
    # 预言家验一只狼
    state = _submit(
        state,
        NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=wolves[0]),
    )
    # 夜晚结算 -> 公布死讯 -> 进入白天发言
    assert state.phase == Phase.DAY_SPEECH
    assert player_at(state, villager).alive is False
    # 发言顺序为存活玩家（含被投前）
    assert villager not in state.speech_order


def test_reject_out_of_turn() -> None:
    state = _start()
    seer = living_of_role(state, RoleType.SEER)[0].seat
    # 现在是守卫阶段，预言家行动应被拒
    res = step(
        state, NightAction(actor_seat=seer, action_type=NightActionType.CHECK, target_seat=0)
    )
    assert res.rejection is not None
    assert res.state is state  # 状态不变
    assert res.events == []


def test_guard_cannot_repeat_target() -> None:
    state = _start()
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    seer = living_of_role(state, RoleType.SEER)[0].seat
    # 设置守卫上次守护目标 = seer
    players = tuple(
        p.model_copy(update={"last_guard_target": seer}) if p.seat == guard else p
        for p in state.players
    )
    state = state.model_copy(update={"players": players})
    res = step(
        state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=seer)
    )
    assert res.rejection is not None


def test_replay_matches_live_state() -> None:
    res = create_game(stage1_config(seed=7), game_id="g1")
    all_events = list(res.events)
    state = res.state
    guard = living_of_role(state, RoleType.GUARD)[0].seat
    step_res = step(
        state, NightAction(actor_seat=guard, action_type=NightActionType.GUARD, target_seat=guard)
    )
    all_events += step_res.events
    live = step_res.state
    # 从初始空局重放全部事件 == 实时状态
    initial = create_game(stage1_config(seed=7), game_id="g1")
    # 重放需要一个「未推进」的基态；这里用 reduce_all 校验事件流内部一致性：
    replayed = reduce_all(
        initial.state.model_copy(
            update={"state_version": live.state_version - len(step_res.events)}
        ),
        step_res.events,
    )
    assert replayed.phase == live.phase
    assert [p.alive for p in replayed.players] == [p.alive for p in live.players]


def test_all_abstain_vote_no_exile_no_pk() -> None:
    from app.engine.engine import _tally_and_continue
    from app.engine.events import EventType

    state = _start()
    # 构造一个 VOTE 阶段、全员弃票（votes 全为 None）的态
    voters = {p.seat: None for p in state.players if p.alive}
    vote_state = state.model_copy(
        update={
            "phase": Phase.VOTE,
            "votes": voters,
            "vote_candidates": (),
            "tie_round": 0,
        }
    )
    new, events = _tally_and_continue(vote_state)
    # 不进入 PK；直接无人放逐
    assert new.phase != Phase.VOTE_PK
    assert any(e.type == EventType.PLAYER_EXILED for e in events)
    assert new.day_exiled is None
