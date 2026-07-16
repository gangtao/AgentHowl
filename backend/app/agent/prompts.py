"""三段式 prompt 装配（issue #31，PRD §4.4.1）：静态段 + 动态段 + 指令段。

公私分离的类型落点：build_prompt（全部昼间与非狼夜间决策）签名上没有私有分区
参数；唯一能接收 night_private 的是 build_wolf_night_prompt。
候选列表经确定性洗牌（抗位置偏置，PRD §4.4.4）。
"""

from __future__ import annotations

import random
from typing import Any

from app.agent.decisions import DecisionKind
from app.engine.config import GameConfig, RoleType, WinCondition
from app.engine.observation import PlayerObservation

ROLE_BRIEFS: dict[RoleType, str] = {
    RoleType.WEREWOLF: "狼人：夜间与队友共同袭击一名玩家；白天隐藏身份、误导好人；可自爆结束白天。",
    RoleType.VILLAGER: "村民：无夜间能力；靠发言与投票找出狼人。",
    RoleType.SEER: "预言家：每夜查验一名玩家的阵营（好人/狼人）。",
    RoleType.WITCH: "女巫：一瓶解药一瓶毒药，全局各一次；通常同夜不能双用。",
    RoleType.HUNTER: "猎人：被狼杀或被放逐时可开枪带走一名玩家（被毒死不能开枪）。",
    RoleType.GUARD: "守卫：每夜守护一名玩家免受狼刀；通常不能连守同一人。",
    RoleType.IDIOT: "白痴：被投票放逐时翻牌免死，但失去投票权。",
}

_WIN_TEXT = {
    WinCondition.KILL_SIDE: "屠边：狼人杀光全部村民或全部神职即胜",
    WinCondition.KILL_ALL: "屠城：狼人杀光所有好人即胜",
}

_SELF_CHECK = "回答前自检：当前是什么阶段？你的座位号和角色是什么？不要臆造未发生的事件。"

# 评审修正（Task 2 review 摘要）：badge_flow 仅在 SHERIFF_PK 发言引擎合法，
# self_destruct 仅在 DAY_SPEECH/SHERIFF_ELECTION/SHERIFF_PK 引擎合法，
# 其它阶段提交会被引擎拒绝（BADGE_FLOW_INVALID 等）——指令段按阶段裁剪提示，
# 避免诱导 agent 提交必然非法的字段。
_BADGE_FLOW_PHASES = frozenset({"SHERIFF_PK"})
_SELF_DESTRUCT_PHASES = frozenset({"DAY_SPEECH", "SHERIFF_ELECTION", "SHERIFF_PK"})


def shuffle_candidates(
    candidates: list[int], *, agent_seed: int, seat: int, state_version: int
) -> list[int]:
    out = list(candidates)
    random.Random(hash((agent_seed, seat, state_version))).shuffle(out)
    return out


def static_system_prompt(config: GameConfig, seat: int, role: RoleType) -> str:
    roles_desc = "、".join(f"{slot.role.value}x{slot.count}" for slot in config.roles)
    win = _WIN_TEXT.get(config.win_condition, str(config.win_condition))
    sheriff = "启用警长（1.5 票与发言顺序权）" if config.sheriff.enabled else "无警长"
    return (
        "你在玩狼人杀。服务器是唯一裁决者，你只提交意图。\n"
        f"本局配置：{config.num_players} 人（{roles_desc}）；胜利条件：{win}；{sheriff}。\n"
        f"你是 {seat} 号，角色：{role.value}。{ROLE_BRIEFS[role]}\n"
        "发言用中文，符合角色立场；狼人白天绝不能泄露夜间的私下谋划。"
    )


def _alive_others(obs: PlayerObservation) -> list[int]:
    return [s["seat"] for s in obs.seats if s.get("alive") and s.get("seat") != obs.my_seat]


def candidates_for(kind: DecisionKind, obs: PlayerObservation) -> list[int]:
    if kind is DecisionKind.VOTE and obs.vote_candidates:
        return list(obs.vote_candidates)
    if kind is DecisionKind.SHERIFF and obs.sheriff_candidates:
        return list(obs.sheriff_candidates)
    if kind is DecisionKind.SPEECH:
        return []
    return _alive_others(obs)


def _render_observation(obs: PlayerObservation) -> str:
    alive = [s["seat"] for s in obs.seats if s.get("alive")]
    lines = [
        f"第 {obs.round} 轮，阶段 {obs.phase}。存活座位：{alive}。",
        f"警长：{obs.sheriff_seat if obs.sheriff_seat is not None else '无'}。",
    ]
    if obs.election_stage:
        lines.append(f"竞选子阶段：{obs.election_stage}；候选人：{obs.sheriff_candidates}。")
    if obs.badge_flow_claims:
        lines.append(f"公开警徽流声明：{obs.badge_flow_claims}。")
    priv = {k: v for k, v in obs.private.items() if k != "wolf_chat"}
    if priv:
        lines.append(f"你的私有信息：{priv}。")
    return "\n".join(lines)


def _speech_instruction(obs: PlayerObservation) -> str:
    parts = ["给出你的发言 content；可选声称身份 claim_role"]
    if obs.phase in _BADGE_FLOW_PHASES:
        parts.append("可报警徽流 badge_flow")
    if obs.phase in _SELF_DESTRUCT_PHASES:
        parts.append("狼人可选 self_destruct 自爆")
    return "；".join(parts) + "。"


def _sheriff_instruction(obs: PlayerObservation) -> str:
    text = (
        "警长相关决策：按当前子阶段给出 action_type"
        "（run_for_sheriff/withdraw/vote_sheriff/pass_badge/tear_badge/set_speech_direction）"
        "及必要的 target_seat 或 direction。"
    )
    if obs.phase in _SELF_DESTRUCT_PHASES:
        text += "狼人可选 self_destruct 自爆代替常规行动。"
    return text


def _instruction_for(kind: DecisionKind, obs: PlayerObservation, cands: list[int]) -> str:
    cand_text = f"候选座位（顺序无含义）：{cands}。" if cands else ""
    body: dict[DecisionKind, str] = {
        DecisionKind.NIGHT: "给出夜间/开枪行动：action_type 与 target_seat（可 skip）。",
        DecisionKind.SPEECH: _speech_instruction(obs),
        DecisionKind.VOTE: "投票放逐一人（target_seat）或弃票（abstain=true）。",
        DecisionKind.SHERIFF: _sheriff_instruction(obs),
    }
    return f"{body[kind]}\n{cand_text}\n先在 reasoning 中简短推理。{_SELF_CHECK}"


def build_prompt(
    kind: DecisionKind,
    obs: PlayerObservation,
    memory_context: str,
    *,
    agent_seed: int,
) -> str:
    """昼间与非狼夜间决策的 user prompt。注意：本函数拿不到 night_private 分区。"""
    cands = shuffle_candidates(
        candidates_for(kind, obs),
        agent_seed=agent_seed,
        seat=obs.my_seat,
        state_version=obs.state_version,
    )
    return (
        f"== 局势 ==\n{_render_observation(obs)}\n\n"
        f"== 你的记忆 ==\n{memory_context or '（暂无）'}\n\n"
        f"== 本次决策 ==\n{_instruction_for(kind, obs, cands)}"
    )


def build_wolf_night_prompt(
    obs: PlayerObservation,
    memory_context: str,
    night_private_context: str,
    *,
    agent_seed: int,
) -> str:
    """狼人夜间私有推理调用的 user prompt —— 唯一能接收私有分区的装配函数。"""
    teammates: Any = obs.private.get("teammates", [])
    cands = shuffle_candidates(
        candidates_for(DecisionKind.WOLF_NIGHT, obs),
        agent_seed=agent_seed,
        seat=obs.my_seat,
        state_version=obs.state_version,
    )
    proposal = obs.private.get("tonight_kill_proposal")
    proposal_line = f"队友已提议刀 {proposal} 号。\n" if proposal is not None else ""
    return (
        f"== 局势 ==\n{_render_observation(obs)}\n\n"
        f"== 你的记忆 ==\n{memory_context or '（暂无）'}\n\n"
        f"== 狼队私有 ==\n你的队友座位：{teammates}。\n{proposal_line}"
        f"{night_private_context or '（无历史私谋）'}\n\n"
        f"== 本次决策 ==\n分析局势（analysis）并提议今晚击杀目标 proposed_target。"
        f"候选座位（顺序无含义）：{cands}。{_SELF_CHECK}"
    )
