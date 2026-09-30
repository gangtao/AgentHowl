"""死亡玩家仍需要的私有信息：预言家交徽 / 遗言时要看到自己的查验结果，猎人开枪窗口本就已出局。
（曾整段挂在 alive 之下，真机一局预言家交徽时不知道验过谁，把警徽交给了狼。）"""

from app.engine.config import Faction, RoleType, build_preset
from app.engine.observation import build_observation
from app.engine.phases import Phase
from app.engine.state import GameState, Player


def _state(role: RoleType, alive: bool, **kw: object) -> GameState:
    roles = [role, RoleType.VILLAGER, RoleType.WEREWOLF]
    players = tuple(
        Player(
            seat=i,
            display_name=f"P{i}",
            role=r,
            faction=Faction.WOLF if r == RoleType.WEREWOLF else Faction.GOOD,
            alive=(i != 0) or alive,
            hunter_can_shoot=True,
        )
        for i, r in enumerate(roles)
    )
    cfg = build_preset("std_9_kill_side").model_copy(update={"num_players": 3, "seed": 1})
    return GameState(game_id="g", config=cfg, round=2, players=players, **kw)  # type: ignore[arg-type]


def test_dead_seer_still_sees_check_results() -> None:
    st = _state(
        RoleType.SEER,
        alive=False,
        phase=Phase.LAST_WORDS,
        speech_order=(0,),
        speech_idx=0,
        sheriff_seat=0,
        resume_token="badge_only:after_day",
        seer_log={0: ({"round": 1, "seat": 2, "result": "WOLF"},)},
    )
    obs = build_observation(st, 0)
    assert obs.my_status == "DEAD" and obs.badge_only
    assert obs.private.get("check_results"), "死亡预言家丢失了查验结果"
    assert obs.private["check_results"][0]["seat"] == 2


def test_dead_hunter_still_sees_can_shoot() -> None:
    st = _state(RoleType.HUNTER, alive=False, phase=Phase.HUNTER_SHOOT, pending_hunter=0)
    obs = build_observation(st, 0)
    assert obs.private.get("can_shoot") is True


def test_dead_wolf_gets_no_night_ledger() -> None:
    # 狼队私有账本仍只给存活狼（公私分离不放宽）
    st = _state(RoleType.WEREWOLF, alive=False, phase=Phase.LAST_WORDS, speech_order=(0,))
    assert "teammates" not in build_observation(st, 0).private
