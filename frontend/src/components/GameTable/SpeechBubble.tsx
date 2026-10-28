// 发言气泡（规格 §4.3，设计稿 3a / 3d / 4b / 4d）：羊皮纸卡锚在发言者座位朝桌心一侧。
// 零过滤：正文来自 SpeechItem（服务端事件），有没有正文只看 item 是否为空。

import { useEffect, useState } from "react";
import type { SpeechItem } from "../../engine/select";
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
  /** 座位百分比坐标，决定气泡在座位的上方还是下方。 */
  anchor: { x: number; y: number };
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

  return (
    <div
      className={styles.bubble}
      data-side={side}
      data-kind={kind}
      role="status"
      aria-label={`${seat}号 ${name} ${HEAD[kind]}`}
      style={{
        left: `${x}%`,
        top: side === "below" ? `${anchor.y + 7}%` : undefined,
        bottom: side === "above" ? `${100 - anchor.y + 7}%` : undefined,
      }}
    >
      <span className={styles.bubbleArrow} aria-hidden="true" />
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
          <span className={styles.placeholder}>{PLACEHOLDER[kind]}</span>
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
    </div>
  );
}
