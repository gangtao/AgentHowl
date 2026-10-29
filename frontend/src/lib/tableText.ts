// 桌面共用的文本选择器（规格 §4.2 / §7）：座位按钮的无障碍名、当前发言者这一轮的发言。
// 圆桌（GameTable）与卡牌（CardBoard）共用，纯函数。

import type { SpeechItem } from "../engine/select";
import type { SeatModel } from "./seatModel";

/** `{seat}号 {name} 存活|出局 [警长] [状态行文案]`（状态行见 lib/seatStatus；出局时状态行就是「出局」，不重复）。 */
export function seatLabel(s: SeatModel): string {
  const parts = [`${s.seat}号`, s.name, s.alive ? "存活" : "出局"];
  if (s.badges.sheriff) parts.push("警长");
  if (s.alive && s.status.text !== "") parts.push(s.status.text);
  return parts.join(" ");
}

/** 当前发言者「这一轮」的发言：取 feed 里最后一条发言 / 遗言，且得是这个座位说的；否则还没说。 */
export function currentSpeechItem(items: SpeechItem[], speaker: number): SpeechItem | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i] as SpeechItem;
    if (it.kind === "speech" || it.kind === "last_words") {
      return it.actor_seat === speaker ? it : null;
    }
  }
  return null;
}
