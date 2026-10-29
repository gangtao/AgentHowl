// 回放阅读停留（规格 R9 / §7，issue #189）：静音回放时发言 / 遗言按字数折算停留时长，其它事件不额外停留。
// 150 ms/字 ≈ 每秒 6–7 个汉字，最短 1.5 s、最长 30 s，再除以倍速。纯函数。

import type { Event, LastWordsPayload, PlayerSpokePayload } from "../engine/types";

const BASE_MS = 1500;
const PER_CHAR_MS = 150;
const MAX_MS = 30000;

function contentOf(event: Event): string | null {
  if (event.type === "PLAYER_SPOKE") return (event.payload as PlayerSpokePayload).content;
  if (event.type === "LAST_WORDS") return (event.payload as LastWordsPayload).content;
  return null;
}

export function readingDwellMs(event: Event | undefined, speed: number): number {
  if (event === undefined) return 0;
  const content = contentOf(event);
  if (content === null) return 0;
  const raw = Math.min(MAX_MS, Math.max(BASE_MS, BASE_MS + content.length * PER_CHAR_MS));
  return raw / (speed > 0 ? speed : 1);
}
