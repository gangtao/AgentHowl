// 身份牌说明行（规格 §4.7 HUD 左栏）：按角色与服务端观察生成一两行说明。纯函数。
// 零过滤：队友 / 药瓶 / 可开枪都来自 PlayerObservation.private（服务端给的），缺失就省略那一行。

import type { PlayerObservation } from "../api/player";
import type { GameState, RoleType } from "../engine/types";

function seatsZh(xs: readonly number[]): string {
  return xs.map((s) => `${s}号`).join(" · ");
}

export function identityLines(
  role: RoleType | null,
  obs: PlayerObservation | null,
  state: GameState,
): string[] {
  const priv = obs?.private ?? {};
  const lines: string[] = [];
  const cfg = state.config as Record<string, unknown>;

  switch (role) {
    case "WEREWOLF": {
      const mates = Array.isArray(priv.teammates) ? (priv.teammates as number[]) : null;
      if (mates !== null && mates.length > 0) lines.push(`队友 ${seatsZh(mates)}`);
      if (cfg.win_condition === "kill_side") lines.push("目标：屠边");
      else if (cfg.win_condition === "kill_all") lines.push("目标：屠城");
      break;
    }
    case "SEER": {
      const me = obs?.my_seat;
      const log =
        me !== undefined
          ? (state.seer_log[String(me)] ?? [])
          : Object.values(state.seer_log).flat();
      const wolves = log.filter((e) => e.result === "WOLF").length;
      lines.push(`已验 ${log.length} 人 · ${wolves} 狼`);
      const flow = me !== undefined ? state.badge_flow_claims[String(me)] : undefined;
      if (flow && flow.length > 0) lines.push(`警徽流 ${flow.join(" → ")}`);
      break;
    }
    case "WITCH": {
      const a = priv.antidote_available;
      const p = priv.poison_available;
      if (typeof a === "boolean" && typeof p === "boolean") {
        lines.push(`解药 ${a ? 1 : 0} · 毒药 ${p ? 1 : 0}`);
      }
      if (cfg.witch_self_save === false) lines.push("不能自救");
      break;
    }
    case "HUNTER":
      if (priv.can_shoot !== false) lines.push("可开枪");
      break;
    default:
      break;
  }

  const me = obs?.my_seat;
  if (
    me !== undefined &&
    (state.phase === "SHERIFF_ELECTION" || state.phase === "SHERIFF_PK") &&
    state.sheriff_candidates.includes(me) &&
    !state.sheriff_withdrawn.includes(me)
  ) {
    lines.push("已上警 · 可退水");
  }
  return lines;
}
