// PK 发言回顾（设计稿 4c 右栏）：PK 双方各自最近一条发言的前 60 字。

import { speechItems } from "../../engine/select";
import type { Event, GameState } from "../../engine/types";
import styles from "./InfoRail.module.css";

const MAX = 60;

export function PkRecap({
  state,
  events,
}: {
  state: GameState;
  events: readonly Event[];
}): JSX.Element {
  const pair =
    state.phase === "SHERIFF_PK" || state.phase === "SHERIFF_ELECTION"
      ? state.sheriff_candidates
      : state.vote_candidates;
  const items = speechItems(events);
  const lastOf = (seat: number): string | null => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const it = items[i];
      if (it && it.kind === "speech" && it.actor_seat === seat) {
        const t = it.content ?? it.text;
        return t.length > MAX ? `${t.slice(0, MAX)}…` : t;
      }
    }
    return null;
  };
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>PK 发言回顾</h3>
      </div>
      {pair.map((seat) => (
        <div key={seat} className={styles.recap}>
          {seat}号：{lastOf(seat) ?? "（尚未发言）"}
        </div>
      ))}
    </section>
  );
}
