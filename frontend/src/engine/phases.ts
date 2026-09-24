// 中文文案表：对齐 backend/app/cli/render.py（_ROLE_ZH、_ELECTION_STAGE_ZH、render_event）
// 与 backend/app/engine/events.py（BadgeLostReason 注释）。纯常量 + 纯函数，零 IO。

import type { ElectionStage, Phase, RoleType } from "./types";

export const PHASE_ZH: Record<Phase, string> = {
  LOBBY: "大厅",
  ROLE_ASSIGN: "发牌",
  NIGHT_GUARD: "夜晚 · 守卫行动",
  NIGHT_WEREWOLF: "夜晚 · 狼人行动",
  NIGHT_WITCH: "夜晚 · 女巫行动",
  NIGHT_SEER: "夜晚 · 预言家行动",
  NIGHT_HUNTER_CONFIRM: "夜晚 · 猎人确认",
  WIN_CHECK: "胜负判定",
  SHERIFF_ELECTION: "白天 · 警长竞选",
  SHERIFF_PK: "白天 · 警长 PK",
  DEATH_ANNOUNCE: "白天 · 公布死讯",
  LAST_WORDS: "白天 · 遗言",
  DAY_SPEECH: "白天 · 发言",
  VOTE: "白天 · 投票",
  VOTE_PK: "白天 · PK 投票",
  EXILE: "白天 · 放逐",
  HUNTER_SHOOT: "猎人开枪",
  IDIOT_FLIP: "白痴翻牌",
  GAME_OVER: "游戏结束",
};

export const ELECTION_STAGE_ZH: Record<ElectionStage, string> = {
  "": "竞选环节结束",
  candidacy: "上警报名",
  speech: "上警发言",
  withdraw: "退水确认",
  vote: "警下投票",
  direction: "警长决定发言方向",
  announce: "公布结果",
};

export const ROLE_ZH: Record<RoleType, string> = {
  WEREWOLF: "狼人",
  VILLAGER: "村民",
  SEER: "预言家",
  WITCH: "女巫",
  HUNTER: "猎人",
  GUARD: "守卫",
  IDIOT: "白痴",
};

export const ROLE_ABBR: Record<RoleType, string> = {
  WEREWOLF: "狼",
  SEER: "预",
  WITCH: "巫",
  HUNTER: "猎",
  GUARD: "守",
  IDIOT: "痴",
  VILLAGER: "民",
};

// 与 events.py::BadgeLostReason 的中文注释一致。
export const BADGE_LOST_ZH: Record<string, string> = {
  NO_CANDIDATES: "无人上警",
  ALL_WITHDREW: "候选人全员退水",
  NO_VOTERS: "全员上警，无警下投票人",
  TIE_AGAIN: "PK 再平票",
  SELF_DESTRUCT: "竞选期狼人自爆吞警徽",
};

// 与 render.py::render_event 的 GAME_OVER 分支一致（winner 为 null 时另行显示「平局」）。
export const WINNER_ZH: Record<string, string> = {
  GOOD: "好人阵营",
  WOLF: "狼人阵营",
};

const NIGHT_PHASES: ReadonlySet<Phase> = new Set([
  "NIGHT_GUARD",
  "NIGHT_WEREWOLF",
  "NIGHT_WITCH",
  "NIGHT_SEER",
  "NIGHT_HUNTER_CONFIRM",
]);

export function isNight(phase: Phase): boolean {
  return NIGHT_PHASES.has(phase);
}

/** 角色所属阵营配色变量名（Nocturne tokens）：狼/神职/民。 */
export function factionColorVar(role: RoleType): string {
  if (role === "WEREWOLF") return "--ah-wolf";
  if (role === "VILLAGER" || role === "IDIOT") return "--ah-villager";
  return "--ah-god"; // SEER / WITCH / HUNTER / GUARD
}
