"""CLI 叙述器（issue #44）：事件/观察/工具渲染成可读中文。纯函数、无 IO、不 import api。

专用于终端展示；不复用 agent 层私有 _render（其通用回退是 raw dict）。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from app.agent.experience import AgentExperience
from app.agent.personality import personality_summary
from app.agent.profile import AgentProfiles, profile_for
from app.engine.config import Faction, RoleType
from app.engine.events import (
    BadgePassedPayload,
    DeathAnnouncedPayload,
    ElectionStageChangedPayload,
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
    WolfKillRevotePayload,
    WolfSelfDestructPayload,
)
from app.engine.observation import PlayerObservation
from app.engine.phases import ElectionStage

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


_ELECTION_STAGE_ZH = {
    ElectionStage.CANDIDACY: "上警报名",
    ElectionStage.SPEECH: "上警发言",
    ElectionStage.WITHDRAW: "退水确认",
    ElectionStage.VOTE: "警下投票",
    ElectionStage.DIRECTION: "警长决定发言方向",
    ElectionStage.ANNOUNCE: "公布结果",
    ElectionStage.NONE: "竞选环节结束",
}


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
    if t == EventType.ELECTION_STAGE_CHANGED and isinstance(p, ElectionStageChangedPayload):
        order = f"，顺序：{_seats(p.speech_order)}" if p.speech_order is not None else ""
        return f"【竞选】{_ELECTION_STAGE_ZH[p.stage]}{order}"
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
    if t == EventType.WOLF_KILL_REVOTE and isinstance(p, WolfKillRevotePayload):
        body = "、".join(f"{s}号→{'空刀' if tgt is None else f'{tgt}号'}" for s, tgt in p.proposals)
        return f"[GM] 狼队第 {p.round_no} 轮意见不一致（{body}），重新提案"

    # 通用回退：可读、非 raw dict
    fields = p.model_dump(mode="json")
    actor = f"{event.actor_seat}号 " if event.actor_seat is not None else ""
    body = "，".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
    return f"[{t.value}] {actor}{body}".rstrip()


def _format_proposal_pair(wolf_seat: int, target: int | None) -> str:
    """格式化狼提案对：座号→目标。"""
    return f"{wolf_seat}号→{'空刀' if target is None else f'{target}号'}"


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
    proposals = priv.pop("tonight_kill_proposals", None)
    history = priv.pop("kill_proposal_history", None)
    rnd = priv.pop("kill_vote_round", None)
    rnd_max = priv.pop("kill_vote_rounds_max", None)
    if proposals is not None:
        pairs = [_format_proposal_pair(s, t) for s, t in sorted(proposals.items())]
        body = "、".join(pairs) or "暂无"
        lines.append(f"狼队第 {rnd}/{rnd_max} 轮 · 队友提案：{body}")
        if history:
            prev_pairs = [_format_proposal_pair(s, t) for s, t in sorted(history[-1].items())]
            prev = "、".join(prev_pairs)
            lines.append(f"上一轮分歧：{prev}")
    if priv:
        lines.append(f"你的私有信息：{priv}")
    return "\n".join(lines)


def render_tools(tools: tuple[str, ...]) -> str:
    """可用工具一行摘要。"""
    return "可用工具：" + "、".join(tools)


def render_agent_roster(
    agents: AgentProfiles,
    num_players: int,
    human_seat: int | None,
    *,
    experiences: Mapping[str, AgentExperience] | None = None,
) -> str:
    """开局座位档案表（GM 视角，仅本地终端）：一行一座位。"""
    lines: list[str] = []
    for seat in range(num_players):
        if seat == human_seat:
            lines.append(f"{seat}号 你（真人）")
            continue
        p = profile_for(agents, seat)
        if p is None:
            lines.append(f"{seat}号 Bot（随机）")
            continue
        parts = [p.name or f"Bot{seat}", p.model]
        if p.model_speech:
            parts.append(f"发言 {p.model_speech}")
        if p.reflection_model:
            parts.append(f"反思 {p.reflection_model}")
        if p.thinking:
            parts.append("thinking")
        parts.append(f"T={p.temperature}")
        if p.skills:
            parts.append("技能 " + ",".join(p.skills))
        if p.personality is not None:
            parts.append(f"性格 {personality_summary(p.personality)}")
        if p.memory_id is not None:
            exp = (experiences or {}).get(p.memory_id)
            games = f"（{exp.games_played} 局）" if exp is not None else ""
            parts.append(f"记忆 {p.memory_id}{games}")
        lines.append(f"{seat}号 " + " · ".join(parts))
    return "\n".join(lines)
