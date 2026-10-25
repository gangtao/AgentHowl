// ToolCall 构造（issue #115）：ActionBar 的输入 → PRD §4.1 工具调用 body。
// 零 IO、零 React；只做形态转换，不判断合法性（引擎裁决，拒因经 action_result 回传）。
// 字段名对应 backend/app/schemas/actions.py::parse_tool_call。

import type { PlayerObservation, ToolCall } from "../api/player";
import type { RoleType } from "../engine/types";

export type NightActionType = "kill" | "check" | "save" | "poison" | "guard" | "shoot" | "skip";
export type SheriffActionType =
  | "run_for_sheriff"
  | "withdraw"
  | "vote_sheriff"
  | "pass_badge"
  | "tear_badge"
  | "set_speech_direction";

/** 需要 ActionBar 渲染输入的主动行动工具；其余（get_state 等只读）不渲染。 */
export const ACTION_TOOLS: ReadonlySet<string> = new Set([
  "speak",
  "vote",
  "night_action",
  "sheriff_action",
  "self_destruct",
]);

export function speakCall(content: string, claimRole?: RoleType | null, badgeFlow?: number[]): ToolCall {
  const args: Record<string, unknown> = { content };
  if (claimRole) args.claim_role = claimRole;
  if (badgeFlow && badgeFlow.length > 0) args.badge_flow = badgeFlow;
  return { tool: "speak", arguments: args };
}

/** null → 弃票（后端要求显式 target_seat 或 abstain=true）。 */
export function voteCall(target: number | null): ToolCall {
  return target === null
    ? { tool: "vote", arguments: { abstain: true } }
    : { tool: "vote", arguments: { target_seat: target } };
}

export function nightActionCall(actionType: NightActionType, target: number | null): ToolCall {
  const args: Record<string, unknown> = { action_type: actionType };
  if (target !== null) args.target_seat = target;
  return { tool: "night_action", arguments: args };
}

export function sheriffCall(
  actionType: SheriffActionType,
  opts: { target?: number; direction?: "LEFT" | "RIGHT" } = {},
): ToolCall {
  const args: Record<string, unknown> = { action_type: actionType };
  if (opts.target !== undefined) args.target_seat = opts.target;
  if (opts.direction !== undefined) args.direction = opts.direction;
  return { tool: "sheriff_action", arguments: args };
}

export function selfDestructCall(): ToolCall {
  return { tool: "self_destruct", arguments: {} };
}

/** 角色在当前阶段可选的夜间动作（UI 提示用；引擎仍会校验）。 */
export function nightOptions(obs: PlayerObservation): NightActionType[] {
  if (obs.phase === "HUNTER_SHOOT") return obs.my_role === "HUNTER" ? ["shoot", "skip"] : [];
  switch (obs.my_role) {
    case "WEREWOLF":
      return obs.phase === "NIGHT_WEREWOLF" ? ["kill", "skip"] : [];
    case "SEER":
      return obs.phase === "NIGHT_SEER" ? ["check"] : [];
    case "WITCH":
      return obs.phase === "NIGHT_WITCH" ? ["save", "poison", "skip"] : [];
    case "GUARD":
      return obs.phase === "NIGHT_GUARD" ? ["guard", "skip"] : [];
    default:
      return [];
  }
}

/** save 的目标固定是今晚刀口（服务端 private.tonight_killed_seat），skip 无目标；其余要选人。 */
export function needsTarget(actionType: NightActionType): boolean {
  return actionType !== "skip" && actionType !== "save";
}

export function aliveTargets(obs: PlayerObservation, includeSelf: boolean): number[] {
  return obs.seats
    .filter((s) => s.alive && (includeSelf || s.seat !== obs.my_seat))
    .map((s) => s.seat)
    .sort((a, b) => a - b);
}
