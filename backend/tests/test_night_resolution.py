from app.engine.config import GuardRule
from app.engine.resolver import resolve_night
from app.engine.state import NightActions
from tests.factories import stage1_config


def _cfg(**guard_kw: object):
    cfg = stage1_config(seed=1)
    if guard_kw:
        return cfg.model_copy(update={"guard": GuardRule(**guard_kw)})  # type: ignore[arg-type]
    return cfg


def test_plain_kill_dies() -> None:
    na = NightActions(wolf_target=4)
    assert resolve_night(_cfg(), na) == frozenset({4})


def test_guard_blocks_kill() -> None:
    na = NightActions(wolf_target=4, guard_target=4)
    assert resolve_night(_cfg(), na) == frozenset()


def test_witch_save_blocks_kill() -> None:
    na = NightActions(wolf_target=4, witch_save=True)
    assert resolve_night(_cfg(), na) == frozenset()


def test_guard_plus_antidote_cancels_target_dies() -> None:
    # 同守同救：默认 guard_plus_antidote_cancels=True -> 奶死
    na = NightActions(wolf_target=4, guard_target=4, witch_save=True)
    assert resolve_night(_cfg(guard_plus_antidote_cancels=True), na) == frozenset({4})


def test_guard_plus_antidote_no_cancel_target_lives() -> None:
    na = NightActions(wolf_target=4, guard_target=4, witch_save=True)
    assert resolve_night(_cfg(guard_plus_antidote_cancels=False), na) == frozenset()


def test_poison_kills_through_guard() -> None:
    # 守卫挡不住毒
    na = NightActions(guard_target=5, witch_poison_target=5)
    assert resolve_night(_cfg(), na) == frozenset({5})


def test_empty_knife_no_death() -> None:
    na = NightActions(wolf_target=None)
    assert resolve_night(_cfg(), na) == frozenset()


def test_kill_and_poison_two_deaths() -> None:
    na = NightActions(wolf_target=4, witch_poison_target=6)
    assert resolve_night(_cfg(), na) == frozenset({4, 6})
