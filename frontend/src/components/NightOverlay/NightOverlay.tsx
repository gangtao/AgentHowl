// 夜间遮罩（设计稿 1c / 1h）：仅夜间阶段渲染；上帝视角遮罩更浅以便看连线，观众只有文字。

import { isNight } from "../../engine/phases";
import type { Phase } from "../../engine/types";
import type { Viewer } from "../../store/game";
import styles from "./NightOverlay.module.css";

export interface NightOverlayProps {
  phase: Phase;
  viewer: Viewer;
}

/** 夜间各阶段的「请睁眼」文案与配色（色值用 tokens 变量名）。 */
const NIGHT_ROLE: Partial<Record<Phase, { text: string; color: string }>> = {
  NIGHT_GUARD: { text: "守卫请睁眼", color: "--ah-line-guard" },
  NIGHT_WEREWOLF: { text: "狼人请睁眼", color: "--ah-wolf" },
  NIGHT_WITCH: { text: "女巫请睁眼", color: "--ah-line-poison" },
  NIGHT_SEER: { text: "预言家请睁眼", color: "--ah-line-seer" },
  NIGHT_HUNTER_CONFIRM: { text: "猎人请确认", color: "--ah-god" },
};

export default function NightOverlay({ phase, viewer }: NightOverlayProps): JSX.Element | null {
  if (!isNight(phase)) return null;
  const role = NIGHT_ROLE[phase];
  const gm = viewer === "GM";
  return (
    <div className={gm ? styles.rootGm : styles.rootSpectator} aria-hidden="true">
      <div className={gm ? styles.cardGm : styles.cardSpectator}>
        <span className={styles.title}>天黑请闭眼</span>
        {role && (
          <span
            className={styles.role}
            style={{ color: gm ? `var(${role.color})` : "var(--color-neutral-400)" }}
          >
            {role.text}
          </span>
        )}
      </div>
    </div>
  );
}
