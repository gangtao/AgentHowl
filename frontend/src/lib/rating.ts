// Agent 积分展示的纯函数（issue #123）。零 IO、零 React；只排版服务端给的数字，不在前端算 Elo。

import type { RatingSummary } from "../api/agents";

/** 卡片战绩行：`1024 分 · 12 局 · 胜率 58%`；没打过 → `尚无战绩`。积分取整，胜率四舍五入。 */
export function ratingLine(r: RatingSummary): string {
  if (r.games === 0) return "尚无战绩";
  const winRate = Math.round((r.wins / r.games) * 100);
  return `${Math.round(r.rating)} 分 · ${r.games} 局 · 胜率 ${winRate}%`;
}
