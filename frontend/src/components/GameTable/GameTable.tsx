// 全景圆桌（规格 §4.2，设计稿 3a / 8a）：正方形桌面，座位沿 41% 半径分布，桌心由 TableCenter 画；
// 座位只留状态行，发言正文在右栏发言台。只收 seatModel / stageContent 的结果与头像表——不收 viewer。

import type { SeatModel } from "../../lib/seatModel";
import type { StageContent } from "../../lib/stageContent";
import { seatLabel } from "../../lib/tableText";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./GameTable.module.css";
import { TableCenter } from "./TableCenter";

export interface GameTableProps {
  seats: SeatModel[];
  /** 夜间：月光调色板。 */
  night: boolean;
  center: StageContent;
  avatars: Record<number, string>;
  /** 只对 selectable 的座位触发。 */
  onSelectSeat?(seat: number): void;
}

export default function GameTable({
  seats,
  night,
  center,
  avatars,
  onSelectSeat,
}: GameTableProps): JSX.Element {
  return (
    <div className={styles.root} data-night={night ? "true" : undefined}>
      <div className={styles.table}>
        <div className={styles.disc} aria-hidden="true" />
        <div className={night ? styles.moon : styles.fire} aria-hidden="true" />

        <TableCenter content={center} seats={seats} />

        {seats.map((s) => (
          <button
            key={s.seat}
            type="button"
            className={styles.seat}
            style={{ left: `${s.x}%`, top: `${s.y}%` }}
            aria-label={seatLabel(s)}
            aria-pressed={s.selected}
            disabled={!s.selectable}
            tabIndex={s.selectable ? 0 : -1}
            data-seat={s.seat}
            data-dim={s.dim ? "true" : undefined}
            data-me={s.me ? "true" : undefined}
            data-speaking={s.speaking ? "true" : undefined}
            data-selectable={s.selectable ? "true" : undefined}
            data-selected={s.selected ? "true" : undefined}
            onClick={() => {
              if (s.selectable) onSelectSeat?.(s.seat);
            }}
          >
            <span className={styles.token}>
              <RoleToken
                role={s.role}
                state={s.alive ? undefined : "dead"}
                size={64}
                initial={s.name.slice(0, 1)}
                avatar={avatars[s.seat] ?? null}
              />
              <span className={styles.no}>{s.seat}</span>
              {s.badges.candidate && <span className={styles.candidate}>警</span>}
              {s.badges.sheriff && (
                <span className={styles.sheriff} title="警长">
                  ★
                </span>
              )}
              {s.badges.votes !== null && <span className={styles.votes}>{s.badges.votes}</span>}
              {s.badges.mark !== null && (
                <span className={styles.mark} data-mark={s.badges.mark}>
                  {s.badges.mark}
                </span>
              )}
              {s.badges.tag !== null && <span className={styles.tag}>{s.badges.tag}</span>}
            </span>
            <span className={styles.name}>{s.name}</span>
            <span className={styles.status} data-tone={s.status.tone}>
              {s.status.text}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
