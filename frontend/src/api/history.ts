// 历史对局列表（issue #98 设计 §2.1）：GET /api/v1/games → GameSummary[]。
// 开关 AGENTHOWL_PUBLIC_HISTORY 开启（默认）时无需 token；关闭时后端要求任意有效 token（401）。

import { req } from "./rest";

export type GameStatus = "finished" | "live" | "aborted";

export interface SeatSummary {
  seat: number;
  display_name: string;
  agent: boolean;
}

export interface GameSummary {
  game_id: string;
  preset: string;
  num_players: number;
  status: GameStatus;
  started_at: string | null;
  ended_at: string | null;
  winner: string | null;
  rounds: number;
  seats: SeatSummary[];
  seq: number;
}

/** 后端已按 started_at 倒序返回，前端不再排序（零裁决：只渲染服务端给的顺序与字段）。 */
export function listGames(): Promise<GameSummary[]> {
  return req<GameSummary[]>("GET", "/games");
}
