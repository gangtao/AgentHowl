// 日夜扫描（规格 R12 / §6.1）：给事件流里的每条事件打上「开局 / 第 N 夜 / 第 N 天」。
//
// 只从事件流里可复现的信号推导，不读 state.round：直播时玩家 / 观众收不到 GM_ONLY 的
// ROUND_STARTED 与夜间 PHASE_CHANGED（engine.py::_begin_night），前端靠 phase_change 帧改 head，
// 事件流里没有这两条。上帝 / 回放有 ROUND_STARTED 就以它为准；没有则靠夜间组事件（预言家 / 狼 / 女巫
// 只收到自己的夜间事件，含被跳过的 ROLE_SKIPPED）开夜、靠 DEATH_ANNOUNCED 或白天 PHASE_CHANGED 开天。
//
// 观众（只有 PUBLIC 事件）一整夜什么都收不到：夜没有被「开」过，下一次 DEATH_ANNOUNCED 到来时仍在白天。
// 所以用 dawned 记住「这一天是否已经天亮过」：已天亮的白天再遇到天亮 → 直接进入下一天（评审 C1）。
// 第 1 轮上帝流里 PHASE_CHANGED→SHERIFF_ELECTION 先于 DEATH_ANNOUNCED 开了白天，此时 dawned=false，
// 天亮不加天。同一条公开事件在上帝流与任何玩家流下得到同样的标签。

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
  "ROLE_SKIPPED",
]);

export function dayLabel(m: DayMark): string {
  if (m.kind === "start") return "开局";
  return m.kind === "night" ? `第 ${m.n} 夜` : `第 ${m.n} 天`;
}

interface Scan {
  mark: DayMark;
  /** 当前这一天是否已经出现过 DEATH_ANNOUNCED。 */
  dawned: boolean;
}

function night(n: number): Scan {
  return { mark: { kind: "night", n }, dawned: false };
}

/** 白天 PHASE_CHANGED：夜 N → 天 N；开局 → 第 1 天；已是白天不变（从不加天）。 */
function daybreak(cur: Scan): Scan {
  if (cur.mark.kind === "night") return { mark: { kind: "day", n: cur.mark.n }, dawned: false };
  if (cur.mark.kind === "start") return { mark: { kind: "day", n: 1 }, dawned: false };
  return cur;
}

/** DEATH_ANNOUNCED：同 daybreak，但「已天亮过的白天」再天亮就是下一天。 */
function dawn(cur: Scan): Scan {
  if (cur.mark.kind === "day" && cur.dawned) {
    return { mark: { kind: "day", n: cur.mark.n + 1 }, dawned: true };
  }
  return { ...daybreak(cur), dawned: true };
}

function next(cur: Scan, e: Event): Scan {
  if (e.type === "ROUND_STARTED") return night((e.payload as RoundStartedPayload).round);
  if (e.type === "PHASE_CHANGED") {
    const to = (e.payload as PhaseChangedPayload).to;
    if (isNight(to)) return cur.mark.kind === "night" ? cur : night(cur.mark.n + 1);
    return daybreak(cur);
  }
  if (NIGHT_EVENT_TYPES.has(e.type)) {
    return cur.mark.kind === "night" ? cur : night(cur.mark.n + 1);
  }
  if (e.type === "DEATH_ANNOUNCED") return dawn(cur);
  return cur;
}

/** 与 events 等长：第 i 项是「应用了 events[i] 之后」生效的日夜。 */
export function dayMarks(events: readonly Event[]): DayMark[] {
  const out: DayMark[] = [];
  let cur: Scan = { mark: { kind: "start", n: 0 }, dawned: false };
  for (const e of events) {
    cur = next(cur, e);
    out.push(cur.mark);
  }
  return out;
}
