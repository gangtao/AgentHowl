"""GameConfig、内置 preset 与校验。

严格按规格 §3.2 实现；所有规则默认值都暴露为可配置项，不硬编码。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RoleType(StrEnum):
    WEREWOLF = "WEREWOLF"
    VILLAGER = "VILLAGER"
    SEER = "SEER"
    WITCH = "WITCH"
    HUNTER = "HUNTER"
    GUARD = "GUARD"
    IDIOT = "IDIOT"


class Faction(StrEnum):
    GOOD = "GOOD"
    WOLF = "WOLF"


def faction_of(role: RoleType) -> Faction:
    return Faction.WOLF if role == RoleType.WEREWOLF else Faction.GOOD


class WinCondition(StrEnum):
    KILL_SIDE = "KILL_SIDE"  # 屠边：杀光村民或杀光神职
    KILL_ALL = "KILL_ALL"  # 屠城：杀光所有好人


class SpeechOrderRule(StrEnum):
    SHERIFF_DECIDES = "SHERIFF_DECIDES"
    DEATH_NEXT = "DEATH_NEXT"
    FIXED_CLOCKWISE = "FIXED_CLOCKWISE"
    ODD_EVEN_CLOCK = "ODD_EVEN_CLOCK"
    BIDDING = "BIDDING"


class TieRule(StrEnum):
    PK_THEN_NO_EXILE = "PK_THEN_NO_EXILE"
    PK_THEN_RANDOM = "PK_THEN_RANDOM"
    NO_EXILE = "NO_EXILE"


class LastWordsRule(StrEnum):
    FIRST_NIGHT_ONLY = "FIRST_NIGHT_ONLY"
    ALWAYS_NIGHT = "ALWAYS_NIGHT"
    N_EQUALS_WOLVES = "N_EQUALS_WOLVES"


class WitchRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    self_rescue_first_night: bool = False
    self_rescue_always: bool = False
    two_potions_same_night: bool = False
    knows_kill_after_antidote_used: bool = False


class GuardRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    can_guard_self: bool = True
    can_guard_same_target_consecutively: bool = False
    guard_plus_antidote_cancels: bool = True


class SheriffRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool = True
    vote_weight: float = 1.5
    election_before_first_death_announce: bool = True
    badge_flow_enabled: bool = True
    wolf_selfdestruct_eats_badge: bool = True


class RoleSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: RoleType
    count: int


def _default_roles() -> list[RoleSlot]:
    return [
        RoleSlot(role=RoleType.WEREWOLF, count=4),
        RoleSlot(role=RoleType.VILLAGER, count=4),
        RoleSlot(role=RoleType.SEER, count=1),
        RoleSlot(role=RoleType.WITCH, count=1),
        RoleSlot(role=RoleType.HUNTER, count=1),
        RoleSlot(role=RoleType.IDIOT, count=1),
    ]


def _default_night_order() -> list[RoleType]:
    return [
        RoleType.WEREWOLF,
        RoleType.WITCH,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.IDIOT,
    ]


class GameConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str
    name: str = "标准12人预女猎白"
    num_players: int = 12
    roles: list[RoleSlot] = Field(default_factory=_default_roles)
    win_condition: WinCondition = WinCondition.KILL_SIDE
    night_order: list[RoleType] = Field(default_factory=_default_night_order)
    speech_order_rule: SpeechOrderRule = SpeechOrderRule.SHERIFF_DECIDES
    tie_rule: TieRule = TieRule.PK_THEN_NO_EXILE
    witch: WitchRule = Field(default_factory=WitchRule)
    guard: GuardRule = Field(default_factory=GuardRule)
    sheriff: SheriffRule = Field(default_factory=SheriffRule)
    last_words: LastWordsRule = LastWordsRule.FIRST_NIGHT_ONLY
    allow_wolf_self_knife: bool = True
    allow_wolf_empty_knife: bool = True
    wolf_first_kill_priority: bool = True
    speech_timeout_sec: int = 90
    action_timeout_sec: int = 45
    max_rounds: int = 20
    seed: int | None = None


class ConfigError(ValueError):
    """GameConfig 校验失败。"""


def _preset_12_yn_hunter_idiot() -> GameConfig:
    return GameConfig(
        config_id="std_12_yn_hunter_idiot",
        name="标准12人预女猎白",
    )


def _preset_12_yn_hunter_guard() -> GameConfig:
    return GameConfig(
        config_id="std_12_yn_hunter_guard",
        name="标准12人预女猎守",
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=4),
            RoleSlot(role=RoleType.VILLAGER, count=4),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.HUNTER, count=1),
            RoleSlot(role=RoleType.GUARD, count=1),
        ],
        night_order=[
            RoleType.GUARD,
            RoleType.WEREWOLF,
            RoleType.WITCH,
            RoleType.SEER,
            RoleType.HUNTER,
        ],
    )


def _preset_9_kill_side() -> GameConfig:
    return GameConfig(
        config_id="std_9_kill_side",
        name="9人屠边预女猎",
        num_players=9,
        roles=[
            RoleSlot(role=RoleType.WEREWOLF, count=3),
            RoleSlot(role=RoleType.VILLAGER, count=3),
            RoleSlot(role=RoleType.SEER, count=1),
            RoleSlot(role=RoleType.WITCH, count=1),
            RoleSlot(role=RoleType.HUNTER, count=1),
        ],
        win_condition=WinCondition.KILL_SIDE,
        night_order=[
            RoleType.WEREWOLF,
            RoleType.WITCH,
            RoleType.SEER,
            RoleType.HUNTER,
        ],
        witch=WitchRule(self_rescue_first_night=True),
    )


def _preset_9_kill_all() -> GameConfig:
    return _preset_9_kill_side().model_copy(
        update={
            "config_id": "std_9_kill_all",
            "name": "9人屠城预女猎",
            "win_condition": WinCondition.KILL_ALL,
        }
    )


_PRESETS = {
    "std_12_yn_hunter_idiot": _preset_12_yn_hunter_idiot,
    "std_12_yn_hunter_guard": _preset_12_yn_hunter_guard,
    "std_9_kill_side": _preset_9_kill_side,
    "std_9_kill_all": _preset_9_kill_all,
}


def build_preset(name: str) -> GameConfig:
    if name not in _PRESETS:
        raise ConfigError(f"未知 preset：{name}；可用：{sorted(_PRESETS)}")
    return _PRESETS[name]()


def validate_config(config: GameConfig) -> None:
    """校验人数、night_order 角色归属、胜利条件相容性。失败抛 ConfigError。"""
    total = sum(slot.count for slot in config.roles)
    if total != config.num_players:
        raise ConfigError(
            f"角色总数 {total} 与 num_players {config.num_players} 不一致"
        )
    if any(slot.count < 0 for slot in config.roles):
        raise ConfigError("角色 count 不能为负")

    setup_roles = {slot.role for slot in config.roles if slot.count > 0}
    for role in config.night_order:
        if role not in setup_roles:
            raise ConfigError(f"night_order 含板子中不存在的角色：{role}")

    if RoleType.WEREWOLF not in setup_roles:
        raise ConfigError("板子必须至少有 1 名狼人")
    if not any(faction_of(slot.role) == Faction.GOOD for slot in config.roles):
        raise ConfigError("板子必须至少有 1 名好人")
