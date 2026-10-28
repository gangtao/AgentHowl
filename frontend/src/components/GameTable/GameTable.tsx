// 全景圆桌（规格 §4.2，设计稿 3a）：正方形桌面，座位沿 41% 半径分布，桌心由 TableCenter 画，
// 发言气泡锚在发言者座位上。只收 seatModel / stageContent 的结果与头像表——不收 viewer。

import type { SpeechItem } from "../../engine/select";
import type { SeatModel } from "../../lib/seatModel";
import type { StageContent } from "../../lib/stageContent";
import RoleToken from "../RoleToken/RoleToken";
import { SpeechBubble, type BubbleKind } from "./SpeechBubble";
import styles from "./GameTable.module.css";
import { TableCenter } from "./TableCenter";

export interface TableSpeech {
  items: SpeechItem[];
  speaker: number;
  kind: BubbleKind;
  deadline: number | null;
  limit?: number | null;
  now?: () => number;
  voicing: boolean;
  /** 发言者是本人。 */
  mine: boolean;
}

export interface GameTableProps {
  seats: SeatModel[];
  /** 夜间：月光调色板。 */
  night: boolean;
  center: StageContent;
  /** 发言气泡；null 不渲染。 */
  speech: TableSpeech | null;
  avatars: Record<number, string>;
  /** 只对 selectable 的座位触发。 */
  onSelectSeat?(seat: number): void;
}

/** 当前发言者「这一轮」的发言：取 feed 里最后一条发言 / 遗言，且得是这个座位说的；否则还没说。 */
function currentItem(items: SpeechItem[], speaker: number): SpeechItem | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i] as SpeechItem;
    if (it.kind === "speech" || it.kind === "last_words") {
      return it.actor_seat === speaker ? it : null;
    }
  }
  return null;
}

function seatLabel(s: SeatModel): string {
  const parts = [`${s.seat}号`, s.name, s.alive ? "存活" : "出局"];
  if (s.badges.sheriff) parts.push("警长");
  if (s.speaking) parts.push("发言中");
  return parts.join(" ");
}

export default function GameTable({
  seats,
  night,
  center,
  speech,
  avatars,
  onSelectSeat,
}: GameTableProps): JSX.Element {
  const speakerSeat =
    speech === null ? null : (seats.find((s) => s.seat === speech.speaker) ?? null);
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
          </button>
        ))}

        {speech !== null && speakerSeat !== null && (
          <SpeechBubble
            item={currentItem(speech.items, speech.speaker)}
            seat={speakerSeat.seat}
            name={speakerSeat.name}
            kind={speech.kind}
            deadline={speech.deadline}
            limit={speech.limit ?? null}
            {...(speech.now ? { now: speech.now } : {})}
            voicing={speech.voicing}
            mine={speech.mine}
            anchor={{ x: speakerSeat.x, y: speakerSeat.y }}
          />
        )}
      </div>
    </div>
  );
}
