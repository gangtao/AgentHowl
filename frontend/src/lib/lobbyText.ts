// 大厅文案 / 座位签选择器（规格 §5）：右栏「开局卷轴」汇总、第 3 步卷轴副标与座位签、圆桌座位显示字。
// 纯函数，零 React、零 IO；数据全部来自 /agents /presets 与本地分配表，不做任何可见性判断。

import type { StoredAgent } from "../api/agents";
import { ME, type AssignmentSummary, type SeatSlot } from "./seats";

export type SeatTagKind = "me" | "agent" | "fill" | "bot";

export interface SeatTag {
  seat: number;
  kind: SeatTagKind;
  text: string;
}

function nameOf(library: StoredAgent[], agentId: string): string | null {
  const stored = library.find((a) => a.agent_id === agentId);
  if (stored === undefined) return null;
  return stored.profile.name ?? "";
}

/** 名字首字；空名回退给调用方。 */
function initial(name: string): string | null {
  const t = name.trim();
  return t === "" ? null : (Array.from(t)[0] as string);
}

/**
 * 右栏卡汇总行一：`12 座位 · 3 个 Agent · 我在 0号 · 8 个随机 bot`；
 * 未选剧本写「未选剧本」；fill 生效时末段改「其余 N 座由「{fillName}」填满」。
 */
export function summaryMain(
  numPlayers: number | null,
  s: AssignmentSummary,
  fillName: string | null,
): string {
  const parts = [
    numPlayers === null ? "未选剧本" : `${numPlayers} 座位`,
    `${s.agentSeats} 个 Agent`,
  ];
  if (s.humanSeat !== null) parts.push(`我在 ${s.humanSeat}号`);
  parts.push(
    s.filled && fillName !== null
      ? `其余 ${s.restSeats} 座由「${fillName}」填满`
      : `${s.restSeats} 个随机 bot`,
  );
  return parts.join(" · ");
}

/** 汇总行二：`12 人预女猎白 · seed 随机`；没选剧本只剩 seed 段。 */
export function summarySub(presetZh: string | null, seed: string): string {
  const seedText = seed.trim() === "" ? "随机" : seed.trim();
  return presetZh === null ? `seed ${seedText}` : `${presetZh} · seed ${seedText}`;
}

/** 第 3 步卷轴副标：有真人座位 / 全 AI 两种。 */
export function scrollSubtitle(me: number | null): string {
  return me === null
    ? "全 AI 对局 · 创建后进入上帝视角"
    : `你将以 ${me}号 入座 · 创建后直接进入玩家页 · 对局结束前看不到上帝视角`;
}

/**
 * 圆桌座位显示字：我自己 → 「我」；库内档案 → 名字首字；fill 生效的空位 → fill 档案首字（kind "fill"）；
 * 其余（含库里查不到的 id）→ 「bot」。
 */
export function seatGlyph(
  agentId: string | null,
  library: StoredAgent[],
  fillName: string | null,
): { text: string; kind: SeatTagKind } {
  if (agentId === ME) return { text: "我", kind: "me" };
  if (agentId !== null) {
    const name = nameOf(library, agentId);
    const ch = name === null ? null : initial(name);
    if (ch !== null) return { text: ch, kind: "agent" };
    if (name !== null) return { text: "bot", kind: "agent" };
  }
  if (agentId === null && fillName !== null) {
    const ch = initial(fillName);
    if (ch !== null) return { text: ch, kind: "fill" };
  }
  return { text: "bot", kind: "bot" };
}

/** 第 3 步「座位」行：已分配座位（我自己 / 库内档案）按座号升序的签 + 其余座位数。 */
export function seatTags(
  assignment: SeatSlot[],
  library: StoredAgent[],
  fill: string | null,
): { tags: SeatTag[]; rest: number; fillName: string | null } {
  const tags: SeatTag[] = [];
  for (const slot of [...assignment].sort((a, b) => a.seat - b.seat)) {
    if (slot.agentId === ME) {
      tags.push({ seat: slot.seat, kind: "me", text: "我自己" });
      continue;
    }
    if (slot.agentId === null) continue;
    const name = nameOf(library, slot.agentId);
    if (name !== null) tags.push({ seat: slot.seat, kind: "agent", text: name });
  }
  const fillName = fill === null ? null : nameOf(library, fill);
  return { tags, rest: assignment.length - tags.length, fillName };
}

/** 剧本牌右上木签：`12 人 / 带警长`、`9 人`。 */
export function presetTag(numPlayers: number, sheriff: boolean): string {
  return sheriff ? `${numPlayers} 人 / 带警长` : `${numPlayers} 人`;
}
