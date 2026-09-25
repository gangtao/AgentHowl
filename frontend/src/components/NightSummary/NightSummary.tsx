// 右栏 · 本夜行动（设计稿 1c GM / 1h 观众）。
// 零过滤：rows 就是 nightSummary(events, round) 的结果——观众收不到夜间事件，自然为空，
// 空态即「夜晚进行中…」占位。

import { ROLE_ZH } from "../../engine/phases";
import type { NightSummaryRow } from "../../engine/select";
import type { Viewer } from "../../store/game";
import styles from "./NightSummary.module.css";

export interface NightSummaryProps {
  rows: NightSummaryRow[];
  round: number;
  viewer: Viewer;
}

export default function NightSummary({ rows, round, viewer }: NightSummaryProps): JSX.Element {
  return (
    <section className={styles.root}>
      <div className={styles.head}>
        <span className={styles.title}>{rows.length > 0 ? "本夜行动" : "夜晚"}</span>
        <span className={styles.sub}>
          第 {round} 夜{viewer === "GM" ? " · GM" : ""}
        </span>
      </div>

      {rows.length > 0 ? (
        <>
          <div className={styles.rows}>
            {rows.map((r, i) => (
              <div className={styles.row} key={`${r.role ?? "sys"}-${i}`}>
                <span className={styles.dot} style={{ background: `var(${r.color})` }} />
                <div className={styles.rowBody}>
                  <span className={styles.rowRole}>
                    {r.role !== null ? ROLE_ZH[r.role] : "结算"}
                    {r.seat !== null ? ` · ${r.seat}号` : ""}
                  </span>
                  <span className={styles.rowText}>{r.text}</span>
                </div>
              </div>
            ))}
          </div>
          <div className={styles.footer}>结算于天亮 · 按 night_order 依次结算</div>
        </>
      ) : (
        <div className={styles.empty}>
          <div>
            <div className={styles.spinner} />
            夜晚进行中…
            {viewer === "SPECTATOR" && (
              <>
                <br />
                <span className={styles.emptySub}>夜间行动仅上帝视角可见</span>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
