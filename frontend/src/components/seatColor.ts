// 座位配色的共用小工具（呈现层）：按 state 里的角色取阵营色。
// 零过滤（spec §1）：不看 viewer——未发牌 / 服务端未下发角色时，全员是 initialState 的
// VILLAGER 默认值，取到的本就是村民灰，与「隐藏数据」无关。

import { factionColorVar } from "../engine/phases";
import type { GameState } from "../engine/types";

export function seatColor(state: GameState, seat: number | null): string {
  if (seat === null) return "var(--color-neutral-300)";
  const p = state.players.find((x) => x.seat === seat);
  return p ? `var(${factionColorVar(p.role)})` : "var(--color-neutral-300)";
}

export function seatName(state: GameState, seat: number): string {
  return state.players.find((p) => p.seat === seat)?.display_name ?? "";
}
