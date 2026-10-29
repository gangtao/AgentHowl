// 发言台（规格 §5，设计稿 8a / 8b / 8c 右上）：右栏上半的木牌面板——当前发言人的大头像 + 计时环 + 正文、
// 自称 / 警徽流签、配音音柱、之后的发言队列；本人未开口时切紧凑版「轮到你」+ 本轮自称提示（输入框仍在 HUD）。
// 零过滤：props 里没有视角参数。mine 由 GamePage 推出；agent 行只在 meta.agents 有这个座位时由调用方传入。

import type { CSSProperties } from "react";
import type { SpeechItem } from "../../engine/select";
import { ROLE_ZH } from "../../engine/phases";
import type { RoleType } from "../../engine/types";
import { claimsZh } from "../../lib/gameLog";
import { defaultNow, useCountdown } from "../../lib/useCountdown";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./SpeakerStand.module.css";

export type StandKind = "speech" | "campaign" | "last_words";

export interface SpeakerStandProps {
  seat: number;
  name: string;
  role: RoleType | null;
  avatar: string | null;
  kind: StandKind;
  /** 该座位这一轮的发言（currentSpeechItem），还没说为 null。 */
  item: SpeechItem | null;
  /** 本人回合（GamePage 由视角推出）。 */
  mine: boolean;
  deadline: number | null;
  limit: number | null;
  now?: () => number;
  voicing: boolean;
  /** meta.agents[seat] 有则传（规格 R7）。 */
  agent?: { model: string; voice: string } | null;
  /** 发言顺序里当前位之后的座位。 */
  queue: number[];
  /** 本轮已声明的身份（规格 R6）。 */
  claims: [number, RoleType][];
}

const HEAD: Record<StandKind, string> = {
  speech: "发言中",
  campaign: "竞选发言",
  last_words: "遗言",
};

const PLACEHOLDER: Record<StandKind, string> = {
  speech: "轮到你发言…",
  campaign: "轮到你时在此陈述竞选理由…（草稿会保留）",
  last_words: "写下遗言…",
};

function queueText(kind: StandKind, queue: readonly number[]): string {
  if (queue.length > 0) return `之后 ${queue.map((s) => `${s}号`).join(" → ")}`;
  return kind === "speech" ? "最后一位 · 发完即进入投票" : "最后一位 · 发完即进入下一阶段";
}

export default function SpeakerStand({
  seat,
  name,
  role,
  avatar,
  kind,
  item,
  mine,
  deadline,
  limit,
  now = defaultNow,
  voicing,
  agent = null,
  queue,
  claims,
}: SpeakerStandProps): JSX.Element {
  const left = useCountdown(deadline, now);
  const pct =
    left !== null && limit !== null && limit > 0
      ? Math.round(Math.min(100, Math.max(0, (left / limit) * 100)))
      : 100;
  const compact = mine && item === null;
  const head = compact ? "轮到你" : HEAD[kind];
  const text = item === null ? null : (item.content ?? item.text);
  const ringStyle = { "--ring": `${pct}%` } as CSSProperties;
  const hint = claims.length > 0 ? `本轮自称：${claimsZh(claims)}` : "本轮尚无人声明身份";

  if (compact) {
    return (
      <section
        className={`ah-wood ${styles.root} ${styles.compact}`}
        role="status"
        aria-label={`${seat}号 ${name} ${head}`}
        data-layout="compact"
        data-kind={kind}
      >
        <div className={`${styles.ring} ${styles.ringSmall}`} style={ringStyle} data-testid="stand-ring">
          <RoleToken role={role} variant="seat" size={76} initial={name.slice(0, 1)} avatar={avatar} />
        </div>
        <div className={styles.compactMain}>
          <div className={styles.row}>
            <span className={styles.nameBig}>
              {seat}号 · {name}
            </span>
            <span className={styles.pill}>{head}</span>
            <span className={styles.muted} data-testid="stand-queue">
              {queueText(kind, queue)}
            </span>
          </div>
          <div className={styles.hint} data-testid="stand-hint">
            {hint}
          </div>
        </div>
        {left !== null && (
          <div className={styles.bigTimer}>
            <div className={styles.bigTimerNum} data-testid="stand-timer">
              {left}s
            </div>
            <div className={styles.muted}>剩余</div>
          </div>
        )}
      </section>
    );
  }

  return (
    <section
      className={`ah-wood ${styles.root}`}
      role="status"
      aria-label={`${seat}号 ${name} ${head}`}
      data-layout="full"
      data-kind={kind}
    >
      <div className={styles.side}>
        <div className={styles.ring} style={ringStyle} data-testid="stand-ring">
          <RoleToken role={role} variant="seat" size={94} initial={name.slice(0, 1)} avatar={avatar} />
        </div>
        <div className={styles.name}>
          {seat}号 · {name}
        </div>
        {left !== null && (
          <div className={styles.timer} data-testid="stand-timer">
            {left}s
          </div>
        )}
      </div>
      <div className={styles.main}>
        <div className={styles.row}>
          <span className={styles.pill}>{head}</span>
          {item?.claim && <span className={styles.claim}>自称 {ROLE_ZH[item.claim]}</span>}
          {item?.badgeFlow && item.badgeFlow.length > 0 && (
            <span className="tag tag-neutral">警徽流 {item.badgeFlow.join(" → ")}</span>
          )}
          {agent !== null && (
            <span className={styles.muted} data-testid="stand-agent">
              {agent.model} · 声线：{agent.voice}
            </span>
          )}
          <span className={styles.spacer} />
          {voicing && (
            <span className={styles.bars} aria-hidden="true" data-testid="stand-bars">
              <i />
              <i />
              <i />
              <i />
              <i />
              <i />
            </span>
          )}
        </div>
        <p className={styles.text} data-testid="stand-text">
          {text !== null ? (
            <>
              {text}
              {voicing && <span className={styles.caret}>▍</span>}
            </>
          ) : (
            <span className={styles.placeholder}>{mine ? PLACEHOLDER[kind] : "正在组织语言…"}</span>
          )}
        </p>
        <div className={styles.queue} data-testid="stand-queue">
          {queueText(kind, queue)}
        </div>
      </div>
    </section>
  );
}
