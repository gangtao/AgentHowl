// 角色徽记（设计稿 2a「七枚徽记 · 单色剪影，阵营配色，24 网格」）。
// 路径逐字取自 docs/design/gamified-2026-10-27/AgentHowl-gamified.dc.html 末尾脚本的 ICON 表，
// viewBox 0 0 24 24，fill-rule evenodd。颜色只给 CSS 变量名，具体色值在 tokens.css。

import type { RoleType } from "../engine/types";

export type Camp = "wolf" | "god" | "villager";

export const ROLE_ICON_PATH: Record<RoleType, string> = {
  WEREWOLF: "M4 3l5 5h6l5-5-1 9-7 10L5 12z M9.5 11h2v2h-2z M12.5 11h2v2h-2z",
  SEER:
    "M12 5C6.5 5 2 12 2 12s4.5 7 10 7 10-7 10-7-4.5-7-10-7z M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z M12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z",
  WITCH:
    "M9 2h6v2h-1v5l5.5 9.5A2 2 0 0 1 17.8 21H6.2a2 2 0 0 1-1.7-2.5L10 9V4H9z M10.5 13.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z M14 16a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  HUNTER:
    "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13z M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z M11 0h2v4h-2z M11 20h2v4h-2z M0 11h4v2H0z M20 11h4v2h-4z",
  GUARD:
    "M12 1.5l8.5 3.2V11c0 5.2-3.6 9.6-8.5 11.5C7.1 20.6 3.5 16.2 3.5 11V4.7z M12 5.5L7 7.4V11c0 3.3 2 6.3 5 7.9 3-1.6 5-4.6 5-7.9V7.4z M11 8h2v3h3v2h-3v3h-2v-3H8v-2h3z",
  IDIOT: "M3 5l5 4 4-6 4 6 5-4-2.5 11h-13z M5.5 18h13v3h-13z M12 11.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z",
  VILLAGER: "M12 2.5l9.5 8.5H19v10H5V11H2.5z M10 14h4v7h-4z M7.5 12.5h3v3h-3z M13.5 12.5h3v3h-3z",
};

/** 阵营：狼 / 神（预女猎守痴）/ 民。 */
export function roleCamp(role: RoleType): Camp {
  if (role === "WEREWOLF") return "wolf";
  if (role === "VILLAGER") return "villager";
  return "god";
}

export interface CampVars {
  /** 环 / 描边 / 文字强调色。 */
  ring: string;
  /** 徽记径向渐变亮端。 */
  hi: string;
  /** 徽记径向渐变暗端。 */
  lo: string;
  /** 徽记前景。 */
  fg: string;
}

export const CAMP_VARS: Record<Camp, CampVars> = {
  wolf: { ring: "var(--ah-wolf)", hi: "var(--ah-wolf-hi)", lo: "var(--ah-wolf-lo)", fg: "var(--ah-wolf-fg)" },
  god: { ring: "var(--ah-god)", hi: "var(--ah-god-hi)", lo: "var(--ah-god-lo)", fg: "var(--ah-god-fg)" },
  villager: {
    ring: "var(--ah-villager)",
    hi: "var(--ah-villager-hi)",
    lo: "var(--ah-villager-lo)",
    fg: "var(--ah-villager-fg)",
  },
};
