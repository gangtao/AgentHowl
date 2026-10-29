// 右栏卡片选择（规格 §4.5）：按阶段决定 InfoRail 显示哪几张卡，最多 2 张。纯函数，不收 viewer——
// nightActs 只看 nightSummary 是否有行（观众收不到夜间事件自然没有），potions 只看观察里有没有药瓶。

import { isNight } from "../engine/phases";
import { nightSummary } from "../engine/select";
import type { Event, GameState } from "../engine/types";

export type RailCardId =
  | "news"
  | "graveyard"
  | "election"
  | "votes"
  | "nightFlow"
  | "seerLog"
  | "potions"
  | "nightActs"
  | "pkRecap";

export interface RailInput {
  state: GameState;
  /** 已按回放游标截断的事件流。 */
  events: readonly Event[];
  mode: "live" | "replay";
  /** 本人观察里带药瓶字段（女巫）。 */
  hasPotions: boolean;
  /** 墓地非空。 */
  hasDeaths: boolean;
}

/** 右栏上半最多 2 张（下半是对局记录，规格 2026-10-28-speech-stage R2）；发言顺序卡已由座位状态行取代。 */
const MAX_CARDS = 2;

export function railCards(input: RailInput): RailCardId[] {
  const { state, events, hasPotions, hasDeaths } = input;
  const phase = state.phase;
  const seerLog = Object.values(state.seer_log).some((xs) => xs.length > 0);

  let order: RailCardId[];
  if (isNight(phase)) {
    const acts = nightSummary(events, state.round).length > 0;
    order = [
      ...(acts ? (["nightActs"] as const) : []),
      ...(hasPotions && phase === "NIGHT_WITCH" ? (["potions"] as const) : []),
      ...(seerLog ? (["seerLog"] as const) : []),
      "nightFlow",
      "news",
      "graveyard",
    ];
  } else if (phase === "SHERIFF_ELECTION" || phase === "SHERIFF_PK") {
    order = [
      "election",
      ...(phase === "SHERIFF_PK" ? (["pkRecap"] as const) : []),
      ...(seerLog ? (["seerLog"] as const) : []),
      "news",
      "graveyard",
    ];
  } else if (
    phase === "VOTE" ||
    phase === "VOTE_PK" ||
    phase === "EXILE" ||
    phase === "LAST_WORDS"
  ) {
    order = [
      "votes",
      ...(phase === "VOTE_PK" ? (["pkRecap"] as const) : []),
      ...(seerLog ? (["seerLog"] as const) : []),
      "news",
      "graveyard",
    ];
  } else {
    order = [...(seerLog ? (["seerLog"] as const) : []), "news", "graveyard"];
  }

  return order.filter((id) => id !== "graveyard" || hasDeaths).slice(0, MAX_CARDS);
}
