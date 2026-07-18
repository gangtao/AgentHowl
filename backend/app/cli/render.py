"""CLI 叙述器（issue #44）：事件/观察/工具渲染成可读中文。纯函数、无 IO、不 import api。

专用于终端展示；不复用 agent 层私有 _render（其通用回退是 raw dict）。
"""

from __future__ import annotations

import os
import sys

from app.engine.config import Faction, RoleType
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    Event,
    EventType,
    GameOverPayload,
    GuardProtectedPayload,
    HunterShotPayload,
    LastWordsPayload,
    PhaseChangedPayload,
    PlayerExiledPayload,
    PlayerSpokePayload,
    RoundStartedPayload,
    SeerCheckedPayload,
    SheriffCandidacyPayload,
    SheriffElectedPayload,
    VoteCastPayload,
    VoteResultPayload,
    WolfKillDecidedPayload,
    WolfKillProposedPayload,
    WolfSelfDestructPayload,
)
from app.engine.observation import PlayerObservation

_ANSI = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "grey": "90",
    "bold": "1",
}

_ROLE_ZH = {
    RoleType.WEREWOLF: "狼人",
    RoleType.VILLAGER: "村民",
    RoleType.SEER: "预言家",
    RoleType.WITCH: "女巫",
    RoleType.HUNTER: "猎人",
    RoleType.GUARD: "守卫",
    RoleType.IDIOT: "白痴",
}


def color(text: str, style: str, *, enabled: bool | None = None) -> str:
    """ANSI 上色；enabled=None 时按 stdout 是否 TTY 且无 NO_COLOR 决定。"""
    if enabled is None:
        enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if not enabled or style not in _ANSI:
        return text
    return f"\033[{_ANSI[style]}m{text}\033[0m"


def _seats(xs: tuple[int, ...]) -> str:
    return "、".join(f"{s}号" for s in xs) if xs else "无"


def render_event(event: Event) -> str:  # noqa: PLR0911
    """单事件 → 一行可读中文。未特判类型回退简洁通用格式（非 raw dict）。"""
    p = event.payload
    t = event.type

    if t == EventType.ROUND_STARTED and isinstance(p, RoundStartedPayload):
        return f"———— 第 {p.round} 轮 ————"
    if t == EventType.PHASE_CHANGED and isinstance(p, PhaseChangedPayload):
        return f"【阶段】{p.to.value}"
    if t == EventType.PLAYER_SPOKE and isinstance(p, PlayerSpokePayload):
        claim = f"（自称{_ROLE_ZH.get(p.claim_role, p.claim_role)}）" if p.claim_role else ""
        badge = f"（警徽流{list(p.badge_flow)}）" if p.badge_flow else ""
        return f"{event.actor_seat}号发言{claim}{badge}：{p.content}"
    if t == EventType.LAST_WORDS and isinstance(p, LastWordsPayload):
        return f"{p.seat}号遗言：{p.content}"
    if t == EventType.DEATH_ANNOUNCED and isinstance(p, DeathAnnouncedPayload):
        return f"【天亮】昨夜出局：{_seats(p.seats)}" if p.seats else "【天亮】平安夜，无人出局"
    if t == EventType.PLAYER_EXILED and isinstance(p, PlayerExiledPayload):
        return f"【放逐】{p.seat}号被票出" if p.seat is not None else "【放逐】无人出局"
    if t == EventType.HUNTER_SHOT and isinstance(p, HunterShotPayload):
        return (
            f"{p.shooter}号猎人开枪带走 {p.victim}号"
            if p.victim is not None
            else f"{p.shooter}号猎人未开枪"
        )
    if t == EventType.WOLF_SELF_DESTRUCT and isinstance(p, WolfSelfDestructPayload):
        return f"💥 {p.seat}号狼人自爆！"
    if t == EventType.VOTE_STARTED:
        return "【投票开始】"
    if t == EventType.VOTE_CAST and isinstance(p, VoteCastPayload):
        return f"  {p.voter}号 → {p.target}号" if p.target is not None else f"  {p.voter}号 弃票"
    if t == EventType.VOTE_RESULT and isinstance(p, VoteResultPayload):
        if p.exiled is not None:
            return f"【计票】{p.exiled}号得票最高，出局"
        return f"【计票】平票：{_seats(p.tie_seats)}"
    if t == EventType.SHERIFF_CANDIDACY and isinstance(p, SheriffCandidacyPayload):
        return f"{p.seat}号{'上警竞选' if p.running else '不上警'}"
    if t == EventType.SHERIFF_ELECTED and isinstance(p, SheriffElectedPayload):
        return f"【警长】{p.seat}号当选警长"
    if t == EventType.BADGE_PASSED and isinstance(p, BadgePassedPayload):
        return (
            f"{p.from_seat}号移交警徽给 {p.to_seat}号"
            if p.to_seat is not None
            else f"{p.from_seat}号撕毁警徽"
        )
    if t == EventType.GAME_OVER and isinstance(p, GameOverPayload):
        who = {"GOOD": "好人阵营", "WOLF": "狼人阵营"}.get(p.winner or "", "平局")
        return f"═══════ 游戏结束：{who}胜（{p.winner or '平局'}）═══════"
    # GM 视角夜间事件
    if t == EventType.SEER_CHECKED and isinstance(p, SeerCheckedPayload):
        res = "狼人" if p.result == Faction.WOLF else "好人"
        return f"[GM] 预言家查验 {p.target}号：{res}"
    if t == EventType.GUARD_PROTECTED and isinstance(p, GuardProtectedPayload):
        return f"[GM] 守卫守护 {p.target}号" if p.target is not None else "[GM] 守卫空守"
    if t == EventType.WOLF_KILL_PROPOSED and isinstance(p, WolfKillProposedPayload):
        return f"[GM] {p.wolf_seat}号狼提议刀 {p.target}号"
    if t == EventType.WOLF_KILL_DECIDED and isinstance(p, WolfKillDecidedPayload):
        return f"[GM] 狼队决定刀 {p.target}号" if p.target is not None else "[GM] 狼队空刀"

    # 通用回退：可读、非 raw dict
    fields = p.model_dump(mode="json")
    actor = f"{event.actor_seat}号 " if event.actor_seat is not None else ""
    body = "，".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
    return f"[{t.value}] {actor}{body}".rstrip()


def render_observation(obs: PlayerObservation) -> str:
    """本座局势摘要（多行）。排除内部键 wolf_chat。"""
    alive = [s["seat"] for s in obs.seats if s.get("alive")]
    role = _ROLE_ZH.get(obs.my_role, obs.my_role)
    lines = [
        f"你是 {obs.my_seat}号 · {role} · {'存活' if obs.my_status == 'ALIVE' else '出局'}",
        f"第 {obs.round} 轮 · 阶段 {obs.phase} · 存活 {alive}",
        f"警长：{obs.sheriff_seat if obs.sheriff_seat is not None else '无'}",
    ]
    if obs.election_stage:
        lines.append(f"竞选子阶段：{obs.election_stage} · 候选 {obs.sheriff_candidates}")
    if obs.badge_flow_claims:
        lines.append(f"公开警徽流：{obs.badge_flow_claims}")
    priv = {k: v for k, v in obs.private.items() if k != "wolf_chat"}
    if priv:
        lines.append(f"你的私有信息：{priv}")
    return "\n".join(lines)


def render_tools(tools: tuple[str, ...]) -> str:
    """可用工具一行摘要。"""
    return "可用工具：" + "、".join(tools)
