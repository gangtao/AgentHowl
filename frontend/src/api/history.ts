// 历史对局列表（issue #98 设计 §2.1）：GET /api/v1/games → GameSummary[]。
// 登录态 cookie：普通用户只看到自己的对局，管理员看到全部（issue #114）。

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
  /** 建局者（issue #114）；旧对局可能无主。 */
  owner_id: string | null;
  owner_name: string | null;
  /** 分享 token；null = 未开放观众。 */
  share_token: string | null;
}

/** 后端已按 started_at 倒序返回，前端不再排序（零裁决：只渲染服务端给的顺序与字段）。 */
export function listGames(): Promise<GameSummary[]> {
  return req<GameSummary[]>("GET", "/games");
}

/** 删除历史对局（issue #100）：进行中 409；开关关 404。 */
export function deleteGame(gameId: string): Promise<void> {
  return req<void>("DELETE", `/games/${gameId}`);
}
