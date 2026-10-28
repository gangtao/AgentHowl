// 村镇公告（设计稿 3a 右栏）：townNews 选择器的键值行。

import type { Event, GameState } from "../../engine/types";
import { townNews } from "../../lib/village";
import styles from "./InfoRail.module.css";

export function TownNews({
  state,
  events,
}: {
  state: GameState;
  events: readonly Event[];
}): JSX.Element {
  const rows = townNews(events, state);
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>村镇公告</h3>
        <span>第 {state.round} 天</span>
      </div>
      {rows.map((r) => (
        <div key={r.k} className={styles.kv}>
          <span className={styles.k}>{r.k}</span>
          <span className={styles.v} data-tone={r.tone}>
            {r.v}
          </span>
        </div>
      ))}
    </section>
  );
}
