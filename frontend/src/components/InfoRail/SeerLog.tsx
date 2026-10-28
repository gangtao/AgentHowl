// 验人记录（设计稿 7a 右栏）：state.seer_log 全部条目。零过滤：观众 / 非预言家的 state 没有 seer_log。

import type { GameState } from "../../engine/types";
import styles from "./InfoRail.module.css";

export function SeerLog({ state }: { state: GameState }): JSX.Element {
  const rows = Object.values(state.seer_log)
    .flat()
    .sort((a, b) => a.round - b.round);
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>验人记录</h3>
      </div>
      {rows.map((r, i) => (
        <div key={`${r.round}-${r.seat}-${i}`} className={styles.logRow}>
          第 {r.round} 夜 · {r.seat}号 →{" "}
          <span className={styles.result} data-result={r.result}>
            {r.result === "WOLF" ? "狼人" : "好人"}
          </span>
        </div>
      ))}
    </section>
  );
}
