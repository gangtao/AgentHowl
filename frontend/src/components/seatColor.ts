// 座位配色的共用小工具（呈现层）：上帝视角按阵营色，观众视角统一中性色——
// 观众的 state 里本就没有角色（服务端没发 ROLES_ASSIGNED），不是前端在过滤。

import { factionColorVar } from "../engine/phases";
import type { GameState } from "../engine/types";
import type { Viewer } from "../store/game";

export function seatColor(state: GameState, seat: number | null, viewer: Viewer): string {
  if (seat === null || viewer !== "GM") return "var(--color-neutral-300)";
  const p = state.players.find((x) => x.seat === seat);
  return p ? `var(${factionColorVar(p.role)})` : "var(--color-neutral-300)";
}

export function seatName(state: GameState, seat: number): string {
  return state.players.find((p) => p.seat === seat)?.display_name ?? "";
}
