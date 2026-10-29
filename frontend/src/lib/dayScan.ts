// 日夜扫描（规格 R12 / §6.1）：给事件流里的每条事件打上「开局 / 第 N 夜 / 第 N 天」。
//
// 只从事件流里可复现的信号推导，不读 state.round：直播时玩家 / 观众收不到 GM_ONLY 的
// ROUND_STARTED 与夜间 PHASE_CHANGED（engine.py::_begin_night），前端靠 phase_change 帧改 head，
// 事件流里没有这两条。上帝 / 回放有 ROUND_STARTED 就以它为准；没有则靠夜间组事件（预言家 / 狼只收
// 到自己的夜间事件）开夜、靠 DEATH_ANNOUNCED 或白天 PHASE_CHANGED 开天。同一份事件流、同样的标签。

import { isNight } from "../engine/phases";
import type { Event, EventType, PhaseChangedPayload, RoundStartedPayload } from "../engine/types";

export type DayKind = "start" | "night" | "day";

export interface DayMark {
  kind: DayKind;
  n: number;
}

/** 夜间组事件类型（也是 gameLog 的 night 分组）。 */
export const NIGHT_EVENT_TYPES: ReadonlySet<EventType> = new Set<EventType>([
  "GUARD_PROTECTED",
  "WOLF_KILL_PROPOSED",
  "WOLF_KILL_DECIDED",
  "WOLF_KILL_REVOTE",
  "WITCH_SAVED",
  "WITCH_POISONED",
  "WITCH_POTION_CONSUMED",
  "NIGHT_RESOLVED",
  "SEER_CHECKED",
]);

export function dayLabel(m: DayMark): string {
  if (m.kind === "start") return "开局";
  return m.kind === "night" ? `第 ${m.n} 夜` : `第 ${m.n} 天`;
}

function next(cur: DayMark, e: Event): DayMark {
  if (e.type === "ROUND_STARTED") {
    return { kind: "night", n: (e.payload as RoundStartedPayload).round };
  }
  if (e.type === "PHASE_CHANGED") {
    const to = (e.payload as PhaseChangedPayload).to;
    if (isNight(to)) return cur.kind === "night" ? cur : { kind: "night", n: cur.n + 1 };
    return dawn(cur);
  }
  if (NIGHT_EVENT_TYPES.has(e.type)) {
    return cur.kind === "night" ? cur : { kind: "night", n: cur.n + 1 };
  }
  if (e.type === "DEATH_ANNOUNCED") return dawn(cur);
  return cur;
}

/** 天亮：夜 N → 天 N；开局（一夜没有任何可见事件）→ 第 1 天；已是白天不变。 */
function dawn(cur: DayMark): DayMark {
  if (cur.kind === "night") return { kind: "day", n: cur.n };
  if (cur.kind === "start") return { kind: "day", n: 1 };
  return cur;
}

/** 与 events 等长：第 i 项是「应用了 events[i] 之后」生效的日夜。 */
export function dayMarks(events: readonly Event[]): DayMark[] {
  const out: DayMark[] = [];
  let cur: DayMark = { kind: "start", n: 0 };
  for (const e of events) {
    cur = next(cur, e);
    out.push(cur);
  }
  return out;
}
