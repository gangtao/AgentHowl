/** 由 /state 快照补出 GameMeta（观众 / 玩家视角没有 /meta；见 GamePage 文件头注释）。 */
import type { GameMeta } from "../engine/types";

interface SeatRow {
  seat: number;
  display_name: string;
}

/** 由 /state 快照补出 GameMeta（见文件头注释）。 */
export function metaFromState(gameId: string, raw: Record<string, unknown>): GameMeta {
  const players = raw.players as SeatRow[] | undefined;
  const seats = raw.seats as SeatRow[] | undefined;
  const roster = (players ?? seats ?? []).map((p) => ({
    seat: p.seat,
    display_name: p.display_name,
  }));
  // GM 视角拿到完整 config；观众 / 玩家视角服务端只发公开子集（num_players、sheriff，issue #80）。
  // 缺的字段用名单人数兜底，只用于渲染，不参与裁决；警长票权一律以服务端给的为准。
  const partial = (raw.config as Partial<GameMeta["config"]> | undefined) ?? {};
  const config: GameMeta["config"] = {
    num_players: roster.length,
    sheriff: { enabled: true, vote_weight: 1.5 },
    roles: [],
    win_condition: "",
    ...partial,
  };
  return { game_id: gameId, config, roster, agents: {} };
}
