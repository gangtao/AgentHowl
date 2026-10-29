// 卡牌皮肤牌阵（规格 §7，设计稿 6a / 6b / 7e）：与 GameTable 同一份 props 与座位契约
// （button[data-seat] / data-selectable / data-selected / aria-label），只是把座位画成 116×140 的牌：
// 已知身份正面（阵营渐变 + 徽记 + 角色名）、未知牌背（木纹 + 首字圆 + 「身份未翻」）、出局灰牌。
// 零过滤：role 为 null 就画牌背，非 null 就翻面——谁能看到由 seatModel（服务端数据）决定，这里不判断。

import type { RoleType } from "../../engine/types";
import { ROLE_ZH } from "../../engine/phases";
import type { SeatModel } from "../../lib/seatModel";
import { CAMP_VARS, ROLE_ICON_PATH, roleCamp } from "../../lib/roleIcons";
import { currentSpeechItem, seatLabel } from "../../lib/tableText";
import Avatar from "../Avatar/Avatar";
import type { GameTableProps } from "./GameTable";
import { SpeechBubble } from "./SpeechBubble";
import { TableCenter } from "./TableCenter";
import styles from "./CardBoard.module.css";

type Face = "front" | "back" | "dead";

function faceOf(s: SeatModel): Face {
  if (!s.alive) return "dead";
  return s.role === null ? "back" : "front";
}

function campStyle(role: RoleType | null): Record<string, string> {
  if (role === null) return {};
  const v = CAMP_VARS[roleCamp(role)];
  return { "--cb-ring": v.ring, "--cb-hi": v.hi, "--cb-lo": v.lo, "--cb-fg": v.fg };
}

export default function CardBoard({
  seats,
  night,
  center,
  speech,
  avatars,
  onSelectSeat,
}: GameTableProps): JSX.Element {
  const maxVotes = Math.max(0, ...seats.map((s) => s.badges.votes ?? 0));
  const speaker = speech === null ? null : (seats.find((s) => s.seat === speech.speaker) ?? null);
  // 桌心内容：只有 TableCenter 真会画东西时才挂容器——空盒子会把下方内容挤出视口（评审 PR ⑤）；
  // speechProgress（发言进度一行，设计稿 8c）永远有内容。
  const showCenter = center.kind !== "none" && center.kind !== "campfire";

  return (
    <div className={styles.root} data-night={night ? "true" : undefined} data-testid="card-board">
      <div className={styles.grid}>
        {seats.map((s) => {
          const face = faceOf(s);
          const leader =
            s.badges.votes !== null && s.badges.votes > 0 && s.badges.votes === maxVotes;
          return (
            <button
              key={s.seat}
              type="button"
              className={styles.piece}
              style={campStyle(s.role)}
              aria-label={seatLabel(s)}
              aria-pressed={s.selected}
              disabled={!s.selectable}
              tabIndex={s.selectable ? 0 : -1}
              data-seat={s.seat}
              data-face={face}
              data-dim={s.dim ? "true" : undefined}
              data-me={s.me ? "true" : undefined}
              data-speaking={s.speaking ? "true" : undefined}
              data-selectable={s.selectable ? "true" : undefined}
              data-selected={s.selected ? "true" : undefined}
              data-leader={leader ? "true" : undefined}
              data-target={s.badges.tag !== null ? "true" : undefined}
              onClick={() => {
                if (s.selectable) onSelectSeat?.(s.seat);
              }}
            >
              <span className={styles.inner} aria-hidden="true" />
              <span className={styles.no}>{s.seat}</span>

              {s.role !== null ? (
                <>
                  <svg
                    viewBox="0 0 24 24"
                    width={46}
                    height={46}
                    aria-hidden="true"
                    className={styles.icon}
                  >
                    <path d={ROLE_ICON_PATH[s.role]} fill="currentColor" fillRule="evenodd" />
                  </svg>
                  <span className={styles.roleName}>{ROLE_ZH[s.role]}</span>
                </>
              ) : face === "dead" ? (
                <>
                  <span className={styles.cross} aria-hidden="true">
                    ✕
                  </span>
                  <span className={styles.deadText}>出局</span>
                </>
              ) : (
                <>
                  <span className={styles.initial}>
                    <Avatar
                      avatar={avatars[s.seat] ?? null}
                      name={s.name}
                      seat={s.seat}
                      size={44}
                      color="transparent"
                    />
                  </span>
                  <span className={styles.backText}>身份未翻</span>
                </>
              )}

              {face === "dead" && s.role !== null && (
                <span className={styles.stamp} data-stamp="true" aria-hidden="true">
                  ✕
                </span>
              )}
              {s.badges.candidate && <span className={styles.candidate}>警</span>}
              {s.badges.sheriff && (
                <span className={styles.sheriff} title="警长">
                  ★
                </span>
              )}
              {s.badges.votes !== null && <span className={styles.votes}>{s.badges.votes}</span>}
              {s.badges.tag !== null ? (
                <span className={styles.redTag}>{s.badges.tag}</span>
              ) : s.badges.mark !== null ? (
                <span className={styles.mark} data-mark={s.badges.mark}>
                  {s.badges.mark}
                </span>
              ) : null}
              <span className={styles.name}>{s.name}</span>
            </button>
          );
        })}
      </div>

      {showCenter && (
        <div className={styles.center} data-testid="card-center">
          <TableCenter content={center} seats={seats} />
        </div>
      )}

      {speech !== null && speaker !== null && (
        <SpeechBubble
          layout="strip"
          item={currentSpeechItem(speech.items, speech.speaker)}
          seat={speaker.seat}
          name={speaker.name}
          role={speaker.role}
          avatar={avatars[speaker.seat] ?? null}
          kind={speech.kind}
          deadline={speech.deadline}
          limit={speech.limit ?? null}
          {...(speech.now ? { now: speech.now } : {})}
          voicing={speech.voicing}
          mine={speech.mine}
          anchor={{ x: speaker.x, y: speaker.y }}
        />
      )}
    </div>
  );
}
