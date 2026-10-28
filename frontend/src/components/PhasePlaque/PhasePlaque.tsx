// 阶段木牌（规格 §4.1，设计稿 3a 左上）：第一行「第 N 轮 / 夜 · 阶段」，第二行按阶段的副标。
// 文案由 src/lib/phaseText.ts 的 plaqueLines 生成（纯函数，不收 viewer）；这里只管渲染。

import type { Event, GameState } from "../../engine/types";
import { plaqueLines } from "../../lib/phaseText";
import styles from "./PhasePlaque.module.css";

export interface PhasePlaqueProps {
  state: GameState;
  events: readonly Event[];
  cursor: number | null;
  total: number;
}

export default function PhasePlaque({
  state,
  events,
  cursor,
  total,
}: PhasePlaqueProps): JSX.Element {
  const { title, sub } = plaqueLines(state, events, cursor, total);
  return (
    <div className={`ah-plaque ${styles.root}`} role="status" aria-label={`${title}，${sub}`}>
      <div className={styles.title}>{title}</div>
      <div className={`ah-plaque-sub ${styles.sub}`}>{sub}</div>
    </div>
  );
}
