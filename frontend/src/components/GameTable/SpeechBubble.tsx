// 发言气泡（规格 §4.3，设计稿 3a / 3d / 4b / 4d）：羊皮纸卡锚在发言者座位朝桌心一侧；
// layout="strip"（规格 §7，设计稿 6b）是卡牌皮肤用的横向发言条：不定位，左侧 44px 徽记。
// 零过滤：正文来自 SpeechItem（服务端事件），有没有正文只看 item 是否为空；徽记按传入的 role 画。

import { useEffect, useState } from "react";
import type { SpeechItem } from "../../engine/select";
import type { RoleType } from "../../engine/types";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./GameTable.module.css";

export type BubbleKind = "speech" | "last_words" | "campaign";

export interface SpeechBubbleProps {
  item: SpeechItem | null;
  seat: number;
  name: string;
  kind: BubbleKind;
  /** 服务端截止时间（秒）；无则不显示倒计时。 */
  deadline: number | null;
  /** 时限总秒数（config.speech_time_limit）；与 deadline 一起决定进度条。 */
  limit?: number | null;
  /** 当前时间（秒）；测试注入。 */
  now?: () => number;
  /** 这句正在配音播放。 */
  voicing: boolean;
  /** 发言者是本人（占位文案「轮到你发言…」只对本人说）。 */
  mine?: boolean;
  /** 座位百分比坐标，决定气泡在座位的上方还是下方（strip 不用）。 */
  anchor: { x: number; y: number };
  /** 缺省气泡；"strip" = 牌阵下方的横向发言条。 */
  layout?: "bubble" | "strip";
  /** strip 左侧徽记用：发言者的已知角色（null = 首字）。 */
  role?: RoleType | null;
  /** strip 左侧徽记用：头像 id。 */
  avatar?: string | null;
}

const PLACEHOLDER: Record<BubbleKind, string> = {
  speech: "轮到你发言…",
  campaign: "轮到你时在此陈述竞选理由…（草稿会保留）",
  last_words: "写下遗言…",
};

const HEAD: Record<BubbleKind, string> = {
  speech: "发言中",
  campaign: "竞选发言",
  last_words: "遗言",
};

const defaultNow = (): number => Date.now() / 1000;

function useLeft(deadline: number | null, now: () => number): number | null {
  const [left, setLeft] = useState<number | null>(() =>
    deadline === null ? null : Math.max(0, Math.ceil(deadline - now())),
  );
  useEffect(() => {
    if (deadline === null) {
      setLeft(null);
      return;
    }
    const tick = (): void => setLeft(Math.max(0, Math.ceil(deadline - now())));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline, now]);
  return left;
}

export function SpeechBubble({
  item,
  seat,
  name,
  kind,
  deadline,
  limit = null,
  now = defaultNow,
  voicing,
  anchor,
  mine = false,
  layout = "bubble",
  role = null,
  avatar = null,
}: SpeechBubbleProps): JSX.Element {
  const left = useLeft(deadline, now);
  const side = anchor.y < 50 ? "below" : "above";
  // 气泡水平位置跟着座位走，但夹在桌面 8%–92% 之间，免得贴边被裁。
  const x = Math.min(92, Math.max(8, anchor.x));
  const progress =
    left !== null && limit !== null && limit > 0
      ? Math.round(Math.min(100, Math.max(0, (left / limit) * 100)))
      : null;
  const text = item === null ? null : (item.content ?? item.text);

  const body = (
    <>
      <div className={styles.bubbleHead}>
        <span>
          {seat}号 {name} · {HEAD[kind]}
        </span>
        {left !== null && <span className={styles.bubbleTimer}>{left}s</span>}
      </div>
      <div className={styles.bubbleText}>
        {text !== null ? (
          <>
            {text}
            {voicing && <span className={styles.caret}>▍</span>}
          </>
        ) : (
          <span className={styles.placeholder}>{mine ? PLACEHOLDER[kind] : "正在组织语言…"}</span>
        )}
      </div>
      {voicing && (
        <div className={styles.voicing}>
          <span>语音播报 · 正在朗读</span>
          <span className={styles.bars} aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
        </div>
      )}
      {progress !== null && (
        <div className={styles.progress} data-progress={progress}>
          <span style={{ width: `${progress}%` }} />
        </div>
      )}
    </>
  );

  if (layout === "strip") {
    return (
      <div
        className={styles.strip}
        data-kind={kind}
        role="status"
        aria-label={`${seat}号 ${name} ${HEAD[kind]}`}
      >
        <span className={styles.stripToken}>
          <RoleToken
            role={role}
            variant="seat"
            size={44}
            initial={name.slice(0, 1)}
            avatar={avatar}
          />
        </span>
        <div className={styles.stripMain}>{body}</div>
      </div>
    );
  }

  return (
    <div
      className={styles.bubble}
      data-side={side}
      data-kind={kind}
      role="status"
      aria-label={`${seat}号 ${name} ${HEAD[kind]}`}
      style={{
        left: `${x}%`,
        top: side === "below" ? `${anchor.y + 9}%` : undefined,
        bottom: side === "above" ? `${100 - anchor.y + 9}%` : undefined,
      }}
    >
      <span className={styles.bubbleArrow} aria-hidden="true" />
      {body}
    </div>
  );
}
