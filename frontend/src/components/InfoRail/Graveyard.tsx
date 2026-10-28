// 墓地（设计稿 3a 右栏）：按出局顺序，已知角色显示徽记，未知显示 ✕。

import { ROLE_ZH } from "../../engine/phases";
import type { Event, GameState, RoleType } from "../../engine/types";
import { graveyard } from "../../lib/village";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./InfoRail.module.css";

export function Graveyard({
  state,
  events,
  knownRoles,
}: {
  state: GameState;
  events: readonly Event[];
  knownRoles: Record<number, RoleType>;
}): JSX.Element {
  const rows = graveyard(events, state, knownRoles);
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>墓地 · 按出局顺序</h3>
      </div>
      {rows.length === 0 && <div className={styles.muted}>还没有人出局</div>}
      {rows.map((r, i) => (
        <div key={`${r.seat}-${i}`} className={styles.grave}>
          <RoleToken
            role={r.role}
            state={r.role === null ? "dead" : "known"}
            variant="outline"
            size={26}
          />
          <div className={styles.graveBody}>
            <div>
              {r.seat} {r.name}
              {r.role !== null && (
                <span className={styles.graveRole} data-role={r.role}>
                  {ROLE_ZH[r.role]}
                </span>
              )}
            </div>
            <div className={styles.muted}>{r.when}</div>
          </div>
        </div>
      ))}
    </section>
  );
}
