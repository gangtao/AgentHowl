import pytest
from pydantic import ValidationError

from app.engine.config import (
    ConfigError,
    Faction,
    GameConfig,
    RoleSlot,
    RoleType,
    build_preset,
    faction_of,
    validate_config,
)

ALL_PRESETS = [
    "std_12_yn_hunter_idiot",
    "std_12_yn_hunter_guard",
    "std_9_kill_side",
    "std_9_kill_all",
]


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_presets_are_valid(name: str) -> None:
    config = build_preset(name)
    validate_config(config)  # 不抛异常即通过
    assert sum(slot.count for slot in config.roles) == config.num_players


def test_preset_12_yn_hunter_idiot_composition() -> None:
    config = build_preset("std_12_yn_hunter_idiot")
    counts = {slot.role: slot.count for slot in config.roles}
    assert counts[RoleType.WEREWOLF] == 4
    assert counts[RoleType.VILLAGER] == 4
    assert counts[RoleType.SEER] == 1
    assert counts[RoleType.WITCH] == 1
    assert counts[RoleType.HUNTER] == 1
    assert counts[RoleType.IDIOT] == 1


def test_preset_9_kill_side_witch_self_rescue_first_night() -> None:
    config = build_preset("std_9_kill_side")
    assert config.num_players == 9
    assert config.witch.self_rescue_first_night is True


def test_build_preset_unknown_name_raises() -> None:
    with pytest.raises(ConfigError):
        build_preset("does_not_exist")


def test_faction_of() -> None:
    assert faction_of(RoleType.WEREWOLF) == Faction.WOLF
    for role in (
        RoleType.VILLAGER,
        RoleType.SEER,
        RoleType.WITCH,
        RoleType.HUNTER,
        RoleType.GUARD,
        RoleType.IDIOT,
    ):
        assert faction_of(role) == Faction.GOOD


def test_validate_config_rejects_count_mismatch() -> None:
    config = GameConfig(
        config_id="bad",
        num_players=12,
        roles=[RoleSlot(role=RoleType.WEREWOLF, count=3)],
    )
    with pytest.raises(ConfigError, match="num_players"):
        validate_config(config)


def test_validate_config_rejects_night_order_role_not_in_setup() -> None:
    config = GameConfig(
        config_id="bad2",
        num_players=4,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=1),
            RoleSlot(role=RoleType.VILLAGER, count=3),
        ],
        night_order=[RoleType.WEREWOLF, RoleType.SEER],  # SEER 不在板子里
    )
    with pytest.raises(ConfigError, match="night_order"):
        validate_config(config)


def test_validate_config_rejects_no_wolves() -> None:
    config = GameConfig(
        config_id="bad3",
        num_players=3,
        roles=[RoleSlot(role=RoleType.VILLAGER, count=3)],
        night_order=[],
    )
    with pytest.raises(ConfigError, match="狼"):
        validate_config(config)


def test_default_config_is_valid() -> None:
    # 默认 GameConfig（默认 idiot 板 + 默认夜序）必须自洽
    validate_config(GameConfig(config_id="default_check"))


def test_validate_config_rejects_no_good_faction() -> None:
    config = GameConfig(
        config_id="bad_all_wolf",
        num_players=2,
        roles=[RoleSlot(role=RoleType.WEREWOLF, count=2)],
        night_order=[RoleType.WEREWOLF],
    )
    with pytest.raises(ConfigError, match="好人"):
        validate_config(config)


def test_gameconfig_is_frozen() -> None:
    config = build_preset("std_9_kill_all")
    with pytest.raises(ValidationError):
        config.num_players = 8  # type: ignore[misc]
