// 桌心（规格 §4.4）：按 stageContent 的判别联合渲染。bubble 的正文由 SpeechBubble 单独画（它锚在座位上），
// 这里只画 bubble 附带的「本轮票型（上轮）」；none 什么都不画。

import type { StageContent } from "../../lib/stageContent";
import type { SeatModel } from "../../lib/seatModel";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./GameTable.module.css";

export interface TableCenterProps {
  content: StageContent;
  seats: SeatModel[];
}

function potionZh(v: boolean | null, name: string): string | null {
  if (v === null) return null;
  return v ? `${name}尚在` : `${name}已用`;
}

export function TableCenter({ content, seats }: TableCenterProps): JSX.Element | null {
  const seatOf = (n: number): SeatModel | undefined => seats.find((s) => s.seat === n);

  switch (content.kind) {
    case "none":
      return null;

    case "bubble":
      if (content.lastTally === null) return null;
      return (
        <div className={`${styles.center} ${styles.centerLow}`}>
          <div className={styles.lastTallyLabel}>本轮票型（上轮）</div>
          <div className={styles.lastTally}>{content.lastTally}</div>
        </div>
      );

    case "campfire":
      return (
        <div className={`${styles.center} ${styles.centerLow}`}>
          <div className={styles.lastTallyLabel}>{content.note}</div>
        </div>
      );

    case "moon":
      return (
        <div className={`${styles.center} ${styles.moonCard}`}>
          <div className={styles.moonTitle}>天黑请闭眼</div>
          <div className={styles.moonSub}>{content.sub}</div>
        </div>
      );

    case "wolfCouncil": {
      const tallies = new Map<number, number>();
      for (const p of content.proposals) {
        if (p.target !== null) tallies.set(p.target, (tallies.get(p.target) ?? 0) + 1);
      }
      return (
        <div className={`${styles.center} ${styles.council}`}>
          <div className={styles.councilKicker}>狼 队 密 议 · 仅狼可见</div>
          <div>
            {content.proposals.map((p) => (
              <span key={p.seat} className={styles.proposal}>
                <b className={styles.wolfText}>{p.seat}号</b> 提议
                {p.target === null ? (
                  "空刀"
                ) : (
                  <>
                    刀 <b>{p.target}号</b>
                  </>
                )}
              </span>
            ))}
          </div>
          {tallies.size > 0 && (
            <div className={styles.councilTally}>
              {[...tallies.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([t, n]) => `${t}号 ${n} 票`)
                .join(" : ")}
              {content.round > 0 ? ` · 第 ${content.round + 1} 轮提案` : ""}
            </div>
          )}
          <div className={styles.councilHint}>{content.hint}</div>
        </div>
      );
    }

    case "witchTarget": {
      const potions = [potionZh(content.antidote, "解药"), potionZh(content.poison, "毒药")].filter(
        (x): x is string => x !== null,
      );
      return (
        <div className={`${styles.center} ${styles.council} ${styles.witch}`}>
          <div className={styles.councilKicker}>今 夜 被 刀</div>
          <div className={styles.bigName}>
            {content.seat}号 {content.name}
          </div>
          {potions.length > 0 && (
            <div className={styles.councilHint}>
              {potions.join(" · ")}
              <br />
              救人后不可同夜用毒
            </div>
          )}
        </div>
      );
    }

    case "crystal":
      return (
        <div className={`${styles.center} ${styles.crystal}`}>
          <div className={styles.orbKicker}>查 验</div>
          <div className={styles.orbSeat}>{content.seat}号</div>
          <div className={styles.orbSub}>确认后天亮前揭晓</div>
        </div>
      );

    case "crosshair":
      return (
        <div className={`${styles.center} ${styles.crosshair}`}>
          <div className={styles.orbKicker}>准 星</div>
          <div className={styles.orbSeat}>{content.seat}号</div>
          <div className={styles.orbSub}>{seatOf(content.seat)?.name ?? ""}</div>
        </div>
      );

    case "tally":
      return (
        <div className={`${styles.center} ${styles.parch}`}>
          <div className={styles.parchHead}>
            <span>实时票型 · 按被投者分组</span>
            <span>
              {content.cast}/{content.voters}
            </span>
          </div>
          {content.rows.map((r) => (
            <div key={r.target}>
              <b
                className={
                  r.votes === Math.max(...content.rows.map((x) => x.votes)) ? styles.leading : ""
                }
              >
                {r.target}号
              </b>{" "}
              · {r.votes} 票 <span className={styles.parchMuted}>← {r.from.join(" ")}</span>
            </div>
          ))}
          {content.waiting.length > 0 && (
            <div className={styles.parchMuted}>
              等待 {content.waiting.join(" ")}
              {content.election ? "" : " · 平票进入 PK"}
            </div>
          )}
        </div>
      );

    case "pkStage": {
      const total = content.a.votes + content.b.votes;
      const pctA = total > 0 ? (content.a.votes / total) * 100 : 50;
      const side = (s: { seat: number; name: string; votes: number }): JSX.Element => {
        const m = seatOf(s.seat);
        return (
          <div className={styles.pkSide}>
            <RoleToken
              role={m?.role ?? null}
              size={72}
              initial={s.name.slice(0, 1)}
              className={styles.pkToken}
            />
            <div className={styles.pkName}>
              {s.seat}号 {s.name}
            </div>
            <div className={styles.pkVotes}>{s.votes}</div>
          </div>
        );
      };
      return (
        <div className={`${styles.center} ${styles.pk}`}>
          <div className={styles.orbKicker}>PK 台</div>
          <div className={styles.pkRow}>
            {side(content.a)}
            <div className={styles.vs}>VS</div>
            {side(content.b)}
          </div>
          <div className={styles.pkBar}>
            <span style={{ width: `${pctA}%` }} />
          </div>
          <div className={styles.parchMuted}>
            已投 {content.cast}/{content.voters}
          </div>
        </div>
      );
    }

    case "gmNotes":
      return (
        <div className={`${styles.center} ${styles.parch} ${styles.notes}`}>
          <div className={styles.notesTitle}>GM 手记 · 第 {content.round} 夜</div>
          {content.rows.map((r, i) => (
            <div key={i} className={styles.noteRow}>
              <span className={styles.noteDot} style={{ background: `var(${r.color})` }} />
              <span>{r.text}</span>
            </div>
          ))}
        </div>
      );
  }
}
