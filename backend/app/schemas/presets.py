"""内置板子的展示信息（issue #26 Lobby 步骤 1）。"""

from __future__ import annotations

from pydantic import BaseModel

from app.engine.config import GameConfig

PRESET_DESCRIPTION_ZH: dict[str, str] = {
    "std_9_kill_side": "9 人屠边 · 预女猎 + 3 狼 + 3 民",
    "std_9_kill_all": "9 人屠城 · 预女猎 + 3 狼 + 3 民",
    "std_12_yn_hunter_idiot": "12 人预女猎白 · 4 狼 + 4 民",
    "std_12_yn_hunter_guard": "12 人预女猎守 · 4 狼 + 4 民",
}


class PresetRole(BaseModel):
    role: str
    count: int


class PresetInfo(BaseModel):
    name: str
    num_players: int
    roles: list[PresetRole]
    sheriff: bool
    win_condition: str
    description_zh: str


def preset_info(name: str, config: GameConfig) -> PresetInfo:
    return PresetInfo(
        name=name,
        num_players=config.num_players,
        roles=[PresetRole(role=s.role.value, count=s.count) for s in config.roles],
        sheriff=config.sheriff.enabled,
        win_condition=config.win_condition.value,
        description_zh=PRESET_DESCRIPTION_ZH.get(name, name),
    )
